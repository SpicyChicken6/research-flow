#!/usr/bin/env python3
"""Free Layers positioning through pointer/keyboard input and public exports."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import shutil
import sys
import time

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.build_preview import build
from server import parse_project

OUT = ROOT / 'test-results'
CHECKS = []
ERRORS = []
LAST_DOWNLOAD = 0.0


def check(value, label):
    if not value:
        raise AssertionError(label)
    CHECKS.append(label)
    print('PASS', label, flush=True)


def opened(browser, path, width=1600, height=1000, mobile=False):
    page = browser.new_page(viewport={'width': width, 'height': height},
                            accept_downloads=True, reduced_motion='reduce',
                            is_mobile=mobile, has_touch=mobile)
    page.set_default_timeout(7000)
    page.on('pageerror', lambda error: ERRORS.append(str(error)))
    page.goto(path.resolve().as_uri(), wait_until='load')
    expect(page.locator('#save-button')).to_be_enabled()
    expect(page.locator('#layer-canvas')).to_be_visible()
    return page


def downloaded(page, action):
    global LAST_DOWNLOAD
    pause = 1 - (time.monotonic() - LAST_DOWNLOAD)
    if pause > 0:
        page.wait_for_timeout(pause * 1000)
    if action.startswith('export-'):
        page.locator('#more-menu summary').click()
    selector = (f'#more-menu [data-action="{action}"]' if action.startswith('export-')
                else f'[data-action="{action}"]')
    with page.expect_download() as download:
        page.locator(selector).click()
    LAST_DOWNLOAD = time.monotonic()
    return Path(download.value.path()).read_text(encoding='utf-8')


def snapshot(page):
    return json.loads(downloaded(page, 'export-json'))


def without_layer_positions(document):
    document = deepcopy(document)
    document['layout'].pop('layer_positions', None)
    return document


def card(page, task_id):
    return page.locator(f'.flow-node[data-id="{task_id}"]')


def positions(page):
    return page.locator('.flow-node').evaluate_all('''nodes => Object.fromEntries(nodes.map(node =>
      [node.dataset.id, {x:parseFloat(node.style.left), y:parseFloat(node.style.top)}]))''')


def scale(page):
    return page.locator('#layer-world').evaluate('node => new DOMMatrix(getComputedStyle(node).transform).a')


def start_drag(page, task_id, dx, dy):
    box = card(page, task_id).bounding_box()
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=8)


def move_to(page, task_id, x, y):
    origin = positions(page)[task_id]
    zoom = scale(page)
    start_drag(page, task_id, (x - origin['x']) * zoom, (y - origin['y']) * zoom)
    page.mouse.up()


def select(page, task_id):
    card(page, task_id).focus()
    page.keyboard.press('Enter')
    expect(page.locator('#inspector')).to_be_visible()


def close_details(page):
    if page.locator('#inspector').is_visible():
        page.locator('[data-action=close-inspector]').click()


def undo(page):
    page.locator('#layers-view [data-action=undo]').click()


def redo(page):
    page.locator('#layers-view [data-action=redo]').click()


def all_visible(page):
    return page.locator('.flow-node').evaluate_all('''nodes => {
      const canvas=document.querySelector('#layer-canvas').getBoundingClientRect();
      return nodes.every(node => {const box=node.getBoundingClientRect();
        return box.left>=canvas.left-1 && box.right<=canvas.right+1
          && box.top>=canvas.top-1 && box.bottom<=canvas.bottom+1;});
    }''')


def endpoints_touch_cards(page):
    return page.locator('.layer-dependency-path,.layer-membership-path').evaluate_all('''paths => {
      const onEdge=(point,box) => {
        const inside=point.x>=box.left-1 && point.x<=box.right+1 && point.y>=box.top-1 && point.y<=box.bottom+1;
        const distance=Math.min(Math.abs(point.x-box.left),Math.abs(point.x-box.right),Math.abs(point.y-box.top),Math.abs(point.y-box.bottom));
        return inside && distance<=1;
      };
      return paths.every(path => {
        const source=document.querySelector(`.flow-node[data-id="${path.dataset.source}"]`).getBoundingClientRect();
        const target=document.querySelector(`.flow-node[data-id="${path.dataset.target}"]`).getBoundingClientRect();
        const matrix=path.getScreenCTM(),start=path.getPointAtLength(0).matrixTransform(matrix),end=path.getPointAtLength(path.getTotalLength()).matrixTransform(matrix);
        return onEdge(start,source) && onEdge(end,target);
      });
    }''')


def run():
    OUT.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='research-flow-layer-positions-') as temporary:
        folder = Path(temporary)
        fixture = parse_project((ROOT / 'examples/three-layers.yaml').read_text(encoding='utf-8'))
        fixture.get('layout', {}).pop('layer_positions', None)
        source = folder / 'initially-arranged.json'
        source.write_text(json.dumps(fixture), encoding='utf-8')
        preview = build(source, ROOT / 'dist/layer-positions-checks.html')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])
            page = opened(browser, preview)
            base = snapshot(page)
            default_positions = positions(page)
            membership = page.locator('.layer-membership-path[data-source=preparation][data-target=normalization]')
            previous_path = membership.get_attribute('d')

            # First move deliberately crosses a layer boundary and the origin.
            target = {'x': default_positions['preparation']['x'], 'y': -104}
            move_to(page, 'normalization', **target)
            page.locator('[data-action=layer-fit]').click()
            check(all_visible(page), 'a toolbar Fit click immediately after dragging is not swallowed')
            moved = snapshot(page)
            saved_positions = moved['layout']['layer_positions']
            check(all(abs(saved_positions['normalization'][axis] - target[axis]) <= 1 for axis in ['x', 'y'])
                  and positions(page)['normalization']['y'] < positions(page)['preparation']['y'],
                  'an operation can be dragged above its overview into negative canvas coordinates')
            check(set(saved_positions) >= set(default_positions)
                  and all(saved_positions[task_id] == position for task_id, position in default_positions.items()
                          if task_id != 'normalization'),
                  'the first move freezes visible card positions without displacing untouched cards')
            check(without_layer_positions(moved) == without_layer_positions(base),
                  'dragging changes only Layers positions, preserving Graph coordinates, tasks, ideas and run history')
            check(not page.locator('#inspector').is_visible(),
                  'a completed card drag does not also trigger the details click')
            check(membership.get_attribute('d') != previous_path and endpoints_touch_cards(page),
                  'membership and dependency connectors follow moved card edges')

            undo(page)
            check(snapshot(page) == base and positions(page) == default_positions,
                  'undo reverses the complete drag including the initial position snapshot')
            redo(page)
            check(snapshot(page) == moved, 'redo restores the complete free card arrangement')
            page.locator('[data-action=layer-fit]').click()
            check(all_visible(page) and snapshot(page) == moved,
                  'Fit includes negative coordinates without modifying the workflow')

            # Both cancellation paths must restore data and avoid a spurious click.
            start_drag(page, 'normalization', 70, 50)
            page.keyboard.press('Escape')
            page.mouse.up()
            check(snapshot(page) == moved and not page.locator('#inspector').is_visible(),
                  'Escape cancels an in-progress drag without saving or opening details')
            start_drag(page, 'normalization', -65, 45)
            page.locator('#layers-view').dispatch_event('pointercancel',
                {'pointerId': 1, 'pointerType': 'mouse', 'bubbles': True})
            page.mouse.up()
            check(snapshot(page) == moved, 'pointer cancellation restores the pre-drag positions')

            move_to(page, 'scale-cpm', -140, 420)
            leftward = snapshot(page)
            check(leftward['layout']['layer_positions']['scale-cpm']['x'] < 0
                  and without_layer_positions(leftward) == without_layer_positions(base),
                  'a processing card can also move left of the canvas origin without changing its method')
            page.locator('[data-action=layer-fit]').click()
            check(all_visible(page) and endpoints_touch_cards(page),
                  'Fit and connector routing handle negative coordinates on both axes')
            undo(page)
            check(snapshot(page) == moved, 'undoing the processing drag preserves the earlier operation move')

            card(page, 'normalization').focus()
            page.keyboard.press('ArrowRight')
            nudged = snapshot(page)
            check(nudged['layout']['layer_positions']['normalization']['x'] == saved_positions['normalization']['x'] + 10
                  and without_layer_positions(nudged) == without_layer_positions(base),
                  'keyboard arrows nudge the focused card by ten canvas units')
            card(page, 'normalization').focus()
            page.keyboard.press('Shift+ArrowUp')
            nudged = snapshot(page)
            check(nudged['layout']['layer_positions']['normalization']['y'] == saved_positions['normalization']['y'] - 40,
                  'Shift plus an arrow nudges by forty canvas units without a layer boundary')
            # Consecutive keyboard moves may intentionally form one undo group.
            undo(page)
            after_undo = snapshot(page)
            if after_undo != moved:
                undo(page)
            check(snapshot(page) == moved, 'keyboard movement is undoable without changing research content')

            # A normal click still opens methods, even for a freely moved card.
            card(page, 'normalization').click()
            expect(page.locator('#methods-panel')).to_be_visible()
            expect(page.locator('#methods-panel .record-entry')).to_have_count(2)
            check(snapshot(page) == moved, 'clicking a moved operation still opens its unchanged method history')
            close_details(page)
            select(page, 'evidence')
            close_details(page)
            expect(card(page, 'literature')).to_have_count(1)
            select(page, 'preparation')
            close_details(page)
            check(positions(page)['normalization'] == saved_positions['normalization'] and snapshot(page) == moved,
                  'overview context switches preserve custom positions and all project data')

            saved = folder / 'free-position-copy.html'
            saved.write_text(downloaded(page, 'save'), encoding='utf-8')
            reopened = opened(browser, saved)
            check(snapshot(reopened) == moved and positions(reopened)['normalization'] == saved_positions['normalization'],
                  'Save copy and reopen retain exact free positions and historical research records')
            reopened.locator('[data-action=layer-fit]').click()
            check(all_visible(reopened) and endpoints_touch_cards(reopened),
                  'reopened negative-coordinate cards fit with connectors attached')
            reopened.close()

            # Changing an input and immediately dragging another card commits both.
            select(page, 'normalization')
            page.locator('#plan-tab').click()
            page.locator('.layer-position-editor summary').click()
            page.locator('[data-action=layer-fit]').click()
            coordinate_x = saved_positions['normalization']['x'] + 23
            page.locator('[data-layer-coordinate=x]').fill(str(coordinate_x))
            start_drag(page, 'scale-cpm', 35, 25)
            page.mouse.up()
            immediate_drag = snapshot(page)
            check(immediate_drag['layout']['layer_positions']['normalization']['x'] == coordinate_x
                  and immediate_drag['layout']['layer_positions']['scale-cpm'] != saved_positions['scale-cpm']
                  and without_layer_positions(immediate_drag) == without_layer_positions(base),
                  'an unblurred coordinate edit survives immediately dragging a different card')
            undo(page)
            undo(page)
            check(snapshot(page) == moved, 'coordinate input and subsequent drag undo as separate edits')
            close_details(page)

            # Arrange is scoped: custom work in another overview must survive.
            select(page, 'evidence')
            close_details(page)
            card(page, 'literature').focus()
            page.keyboard.press('ArrowLeft')
            other_scope = snapshot(page)
            hidden_position = other_scope['layout']['layer_positions']['literature']
            select(page, 'preparation')
            close_details(page)
            page.locator('[data-action=layer-arrange]').click()
            arranged = snapshot(page)
            check(positions(page) == default_positions
                  and arranged['layout']['layer_positions']['literature'] == hidden_position
                  and without_layer_positions(arranged) == without_layer_positions(base),
                  'Arrange resets visible cards and preserves custom positions in another overview')
            undo(page)
            check(snapshot(page) == other_scope, 'Arrange is one undoable layout change')
            redo(page)
            check(snapshot(page) == arranged, 'redo reapplies only the visible arrangement reset')

            select(page, 'normalization')
            page.locator('#plan-tab').click()
            page.locator('[data-field=method]').fill('Fictional layout regression method edit.')
            page.locator('[data-field=method]').press('Tab')
            edited = snapshot(page)
            expected = deepcopy(arranged)
            next(task for task in expected['tasks'] if task['id'] == 'normalization')['method'] = 'Fictional layout regression method edit.'
            check(edited == expected, 'editing planned methods preserves custom layout and earlier execution records')
            undo(page)
            close_details(page)
            page.locator('#ideas-button').click()
            page.locator('#ideas-panel [data-action=idea-edit][data-id=batch-question]').first.click()
            page.locator('#idea-form [name=notes]').fill('Fictional layout regression question edit.')
            page.locator('#idea-form button[type=submit]').click()
            edited = snapshot(page)
            edited_idea = next(idea for idea in edited['ideas'] if idea['id'] == 'batch-question')
            expected = deepcopy(arranged)
            expected['ideas'] = edited['ideas']
            check(edited == expected and edited_idea['notes'] == 'Fictional layout regression question edit.'
                  and edited_idea.get('updated_at')
                  and [idea for idea in edited['ideas'] if idea['id'] != 'batch-question']
                      == [idea for idea in arranged['ideas'] if idea['id'] != 'batch-question'],
                  'editing an idea preserves freely positioned cards and workflow records')
            undo(page)
            check(snapshot(page) == arranged, 'method and idea edits undo independently of card arrangements')
            page.locator('#ideas-button').click()
            for task_id, x in [('normalization', -6000), ('log-transform', 6000)]:
                select(page, task_id)
                page.locator('#plan-tab').click()
                page.locator('.layer-position-editor summary').click()
                page.locator('[data-layer-coordinate=x]').fill(str(x))
                page.locator('[data-layer-coordinate=x]').press('Tab')
            close_details(page)
            widely_spaced = snapshot(page)
            page.locator('[data-action=layer-fit]').click()
            check(all_visible(page) and scale(page) < .15 and snapshot(page) == widely_spaced,
                  'explicit Fit includes widely separated valid coordinates below the normal reading scale')
            undo(page)
            undo(page)
            check(snapshot(page) == arranged, 'large coordinate edits undo without disturbing existing arrangements')
            page.close()

            # Touch-sized views must display the saved custom layout without overflow.
            for width, height in [(390, 844), (700, 900)]:
                mobile = opened(browser, saved, width=width, height=height, mobile=True)
                check(positions(mobile)['normalization'] == saved_positions['normalization']
                      and mobile.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                      f'saved custom positions reopen without document overflow at {width}px')
                mobile.locator('[data-action=layer-fit]').click()
                check(all_visible(mobile) and endpoints_touch_cards(mobile) and snapshot(mobile) == moved,
                      f'mobile Fit includes every moved card without data changes at {width}px')
                mobile.close()
            check(not ERRORS, 'free-position interactions produce no uncaught JavaScript errors')
            browser.close()
    (OUT / 'layer-positions-checks.json').write_text(json.dumps(
        {'count': len(CHECKS), 'checks': CHECKS, 'errors': ERRORS}, indent=2), encoding='utf-8')
    print('ALL', len(CHECKS), 'CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run()
