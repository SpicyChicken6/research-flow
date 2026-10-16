#!/usr/bin/env python3
"""Parent-centered Arrange, styling and view icons through public browser controls."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import math
import os
import shutil

from playwright.sync_api import expect, sync_playwright

import layer_positions_checks as helpers
from layer_positions_checks import (
    ROOT, OUT, check, opened, snapshot, downloaded, positions, card,
    move_to, select, close_details, undo, redo, all_visible,
    without_layer_positions, endpoints_touch_cards,
)
from scripts.build_preview import build
from server import parse_project


def rectangles(page):
    return page.locator('.flow-node').evaluate_all('''nodes => Object.fromEntries(nodes.map(node =>
      [node.dataset.id, {x:parseFloat(node.style.left), y:parseFloat(node.style.top),
        width:parseFloat(node.style.width), height:parseFloat(node.style.height)}]))''')


def collision_free(page):
    boxes = list(rectangles(page).values())
    return all(a['x'] + a['width'] <= b['x'] or b['x'] + b['width'] <= a['x']
               or a['y'] + a['height'] <= b['y'] or b['y'] + b['height'] <= a['y']
               for index, a in enumerate(boxes) for b in boxes[index + 1:])


def surrounds_parent(page, parent_id, child_ids):
    boxes = rectangles(page)
    parent = boxes[parent_id]
    py = parent['y'] + parent['height'] / 2
    ys = [boxes[task_id]['y'] + boxes[task_id]['height'] / 2 for task_id in child_ids]
    return min(ys) < py < max(ys)


def close_to_parent(page, task_id, parent_id):
    boxes = rectangles(page)
    child, parent = boxes[task_id], boxes[parent_id]
    distance = math.hypot(child['x'] - parent['x'], child['y'] - parent['y'])
    return distance <= 6 * max(parent['width'], parent['height'])


def uniform_border(locator):
    return locator.evaluate_all('''nodes => nodes.every(node => {
      const style=getComputedStyle(node);
      const widths=['Top','Right','Bottom','Left'].map(side=>parseFloat(style[`border${side}Width`]));
      return Math.max(...widths)<=1 && widths.every(width=>width===widths[0]);
    })''')


def fixture(path):
    document = parse_project((ROOT / 'examples/three-layers.yaml').read_text(encoding='utf-8'))
    document.setdefault('layout', {})['layer_positions'] = {
        'normalization': {'x': 90, 'y': -900},
        'literature': {'x': -875, 'y': -575},
    }
    path.write_text(json.dumps(document), encoding='utf-8')
    return document


def run():
    OUT.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='research-flow-organic-') as temporary:
        folder = Path(temporary)
        source = folder / 'custom-start.json'
        fixture(source)
        preview = build(source, ROOT / 'dist/organic-arrangement-checks.html')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])
            page = opened(browser, preview)
            base = snapshot(page)
            icons = [page.locator(f'#{button} svg').inner_html()
                     for button in ['layers-button', 'overview-button', 'list-button']]
            check(len(set(icons)) == 3 and all(icons),
                  'Layers, Graph and Step list use three distinct visible SVG shapes')

            page.locator('[data-action=layer-arrange]').click()
            arranged = snapshot(page)
            arranged_positions = positions(page)
            operation_ids = [task['id'] for task in base['tasks'] if task.get('overview_id') == 'preparation']
            processing_ids = [task['id'] for task in base['tasks'] if task.get('operation_id') == 'normalization']
            check(surrounds_parent(page, 'preparation', operation_ids),
                  'Arrange places preparation operations both above and below their overview')
            processing_members = set(page.locator('.layer-membership-path[data-source=normalization]').evaluate_all(
                'paths => paths.map(path => path.dataset.target)'))
            check(len({arranged_positions[task_id]['x'] for task_id in processing_ids}) > 1
                  and processing_members == set(processing_ids),
                  'processing steps fan around their operation with the correct membership connectors')
            check(all(close_to_parent(page, task_id, 'preparation') for task_id in operation_ids)
                  and all(close_to_parent(page, task_id, 'normalization') for task_id in processing_ids),
                  'operations and processing remain spatially grouped around their actual parents')
            check(collision_free(page), 'automatic parent-centered placement has no overlapping cards')
            check(endpoints_touch_cards(page), 'arranged membership and dependency paths meet their card edges')
            check(without_layer_positions(arranged) == without_layer_positions(base)
                  and arranged['layout']['layer_positions']['literature'] == base['layout']['layer_positions']['literature'],
                  'Arrange preserves task history, ideas, Graph positions and another overview’s manual placement')

            page.locator('[data-action=layer-arrange]').click()
            page.locator('[data-action=layer-arrange]').click()
            check(positions(page) == arranged_positions and snapshot(page) == arranged,
                  'repeated Arrange is deterministic and does not add data changes')
            undo(page)
            check(snapshot(page) == base,
                  'one undo restores the manual arrangement even after repeated no-op Arrange clicks')
            redo(page)
            check(snapshot(page) == arranged and positions(page) == arranged_positions,
                  'redo restores the same automatic parent-centered arrangement')

            check(uniform_border(page.locator('.flow-node')),
                  'all card types have a uniform thin border without a left accent bar')
            for task_id in ['preparation', 'normalization', 'scale-cpm']:
                select(page, task_id)
                close_details(page)
                page.locator('[data-action=layer-fit]').click()
                card(page, task_id).hover()
                check(uniform_border(card(page, task_id)),
                      f'{task_id} keeps a uniform thin border when selected and hovered')
            check(snapshot(page) == arranged, 'inspecting and hovering card styles does not mutate project content')

            # Moving after Arrange must still be persistent and must freeze other cards.
            page.locator('[data-action=layer-fit]').click()
            before_drag = positions(page)
            origin = before_drag['normalization']
            move_to(page, 'normalization', origin['x'] + 12, origin['y'] + 8)
            manual = snapshot(page)
            manual_positions = positions(page)
            check(manual_positions['normalization'] != origin
                  and all(manual_positions[task_id] == position for task_id, position in before_drag.items()
                          if task_id != 'normalization')
                  and without_layer_positions(manual) == without_layer_positions(arranged),
                  'manual dragging after Arrange persists without moving other cards or changing research data')
            select(page, 'evidence')
            close_details(page)
            check(positions(page)['literature'] == base['layout']['layer_positions']['literature'],
                  'switching overview reveals its preserved manual child position')
            select(page, 'preparation')
            close_details(page)
            check(positions(page) == manual_positions and snapshot(page) == manual,
                  'returning to the overview preserves the manual edit made after Arrange')

            saved = folder / 'manual-after-arrange.html'
            saved.write_text(downloaded(page, 'save'), encoding='utf-8')
            reopened = opened(browser, saved)
            check(snapshot(reopened) == manual and positions(reopened) == manual_positions,
                  'Save copy retains the post-Arrange manual placement on reopen')
            reopened.close()

            # New children use nearby unoccupied space without changing pinned cards.
            for layer, parent_id, association in [('processing', 'normalization', 'operation_id'),
                                                  ('operation', 'preparation', 'overview_id')]:
                select(page, parent_id)
                page.locator(f'[data-action=layer-add-{layer}]').click()
                added = snapshot(page)
                added_task = next(task for task in added['tasks']
                                  if task['id'] not in {existing['id'] for existing in manual['tasks']})
                new_positions = positions(page)
                check(added_task.get(association) == parent_id
                      and close_to_parent(page, added_task['id'], parent_id) and collision_free(page)
                      and all(new_positions[task_id] == position for task_id, position in manual_positions.items()),
                      f'a new {layer} appears near its parent without overlapping or shifting pinned cards')
                undo(page)
                close_details(page)
                check(snapshot(page) == manual,
                      f'undoing a new {layer} preserves earlier manual and automatic arrangements')
            page.close()

            for width, height in [(390, 844), (700, 900)]:
                mobile = opened(browser, preview, width=width, height=height, mobile=True)
                mobile_base = snapshot(mobile)
                mobile.locator('[data-action=layer-arrange]').click()
                check(collision_free(mobile) and all_visible(mobile)
                      and mobile.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                      f'Arrange fits the parent-centered layout without card collisions or document overflow at {width}px')
                check(without_layer_positions(snapshot(mobile)) == without_layer_positions(mobile_base),
                      f'mobile Arrange preserves research content and Graph coordinates at {width}px')
                mobile.close()
            check(not helpers.ERRORS, 'organic arrangement interactions produce no uncaught browser errors')
            browser.close()
    (OUT / 'organic-arrangement-checks.json').write_text(json.dumps(
        {'count': len(helpers.CHECKS), 'checks': helpers.CHECKS, 'errors': helpers.ERRORS}, indent=2), encoding='utf-8')
    print('ALL', len(helpers.CHECKS), 'CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run()
