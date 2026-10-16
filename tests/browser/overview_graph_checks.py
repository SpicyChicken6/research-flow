#!/usr/bin/env python3
"""Overview-only Graph regressions through public controls and full exports."""
from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
import json
import os
import re
import shutil
import sys
import time

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.build_preview import build

OUT = ROOT / 'test-results'
CHECKS = []
ERRORS = []
LAST_DOWNLOAD = 0.0


def check(value, label):
    if not value:
        raise AssertionError(label)
    CHECKS.append(label)
    print('PASS', label, flush=True)


def opened(browser, path, width=1600, height=1000):
    page = browser.new_page(viewport={'width': width, 'height': height},
                            accept_downloads=True, reduced_motion='reduce')
    page.set_default_timeout(7000)
    page.on('pageerror', lambda error: ERRORS.append(str(error)))
    page.goto(path.resolve().as_uri(), wait_until='load')
    expect(page.locator('#save-button')).to_be_enabled()
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


def graph(page):
    page.locator('#overview-button').click()
    expect(page.locator('#canvas')).to_be_visible()
    expect(page.locator('#overview-button')).to_have_attribute('aria-pressed', 'true')


def graph_ids(page):
    return set(page.locator('#canvas .task-node').evaluate_all('nodes => nodes.map(node => node.dataset.id)'))


def minimap_ids(page):
    return set(page.locator('.mini-node').evaluate_all('nodes => nodes.map(node => node.dataset.miniTask)'))


def edge_ids(page):
    return set(page.locator('#canvas .edge-hit').evaluate_all('edges => edges.map(edge => edge.dataset.edge)'))


def graph_positions(page):
    return page.locator('#canvas .task-node').evaluate_all('''nodes => Object.fromEntries(nodes.map(node =>
      [node.dataset.id,{x:parseFloat(node.style.left),y:parseFloat(node.style.top)}]))''')


def drag_graph_card(page, task_id):
    box = page.locator(f'.task-node[data-id="{task_id}"]').bounding_box()
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 80, y - 45, steps=8)
    page.mouse.up()


def choose_layer_node(page, task_id):
    page.locator('#layers-button').click()
    node = page.locator(f'.flow-node[data-id="{task_id}"]')
    node.focus()
    page.keyboard.press('Enter')
    expect(page.locator('#methods-panel')).to_be_visible()


def fixture_preview(folder, name, document):
    source = folder / f'{name}.json'
    source.write_text(json.dumps(document), encoding='utf-8')
    return build(source, folder / f'{name}.html')


def run():
    OUT.mkdir(exist_ok=True)
    preview = build(ROOT / 'examples/three-layers.yaml', ROOT / 'dist/overview-graph-checks.html')
    overview_ids = {'question', 'evidence', 'preparation', 'analysis', 'communication'}
    direct_edges = {'question|evidence', 'evidence|preparation', 'preparation|analysis', 'analysis|communication'}
    with TemporaryDirectory(prefix='research-flow-overview-graph-') as temporary:
        folder = Path(temporary)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])
            page = opened(browser, preview)
            base = snapshot(page)
            graph(page)
            check(graph_ids(page) == overview_ids,
                  'Graph renders only the five high-level overview steps')
            check(minimap_ids(page) == overview_ids,
                  'the Graph minimap contains only overview steps')
            check(edge_ids(page) == direct_edges and page.locator('.mini-dependency').count() == 4,
                  'Graph and minimap preserve exactly the direct overview dependencies')
            check(page.locator('.stage-column').count() == 5
                  and len(set(page.locator('.task-node').evaluate_all(
                      'nodes => nodes.map(node => parseFloat(node.style.left))'))) == 5,
                  'Graph gives the five numbered overview steps separate ordered columns')
            staged_positions = graph_positions(page)
            check(page.locator('#layout-freeform').count() == 0,
                  'Graph exposes only the organized step layout, without a Freeform option')
            page.locator('#list-button').click()
            graph(page)
            page.locator('#arrange-button').click()
            check(graph_positions(page) == staged_positions and snapshot(page) == base,
                  'view switching and Graph Arrange preserve the organized positions and complete project')
            page.screenshot(path=str(OUT / 'overview-graph-desktop.png'))

            edge = page.locator('.edge-hit[data-edge="question|evidence"]')
            edge.focus()
            page.keyboard.press('Enter')
            for selector in ['#connection-source', '#connection-target']:
                check(set(page.locator(f'{selector} option').evaluate_all(
                    'options => options.map(option => option.value)')) == overview_ids,
                    f'{selector} edits only overview endpoints in Graph')
            page.locator('[data-action=close-inspector]').click()
            page.locator('#fit-button').click()
            drag_graph_card(page, 'preparation')
            check(graph_positions(page) == staged_positions and snapshot(page) == base,
                  'dragging a Graph card cannot turn the organized overview into a free layout')
            page.locator('.task-node[data-id=preparation]').focus()
            page.keyboard.press('ArrowRight')
            page.keyboard.press('Shift+ArrowDown')
            check(graph_positions(page) == staged_positions and snapshot(page) == base,
                  'arrow keys do not edit Graph coordinates or any Layers positions')
            before_camera = page.locator('#world').get_attribute('style')
            page.locator('#canvas [data-action=zoom-in]').click()
            check(page.locator('#world').get_attribute('style') != before_camera,
                  'Graph zoom remains available without changing its stage organization')
            point = page.locator('#canvas').evaluate('''canvas => {
              const box=canvas.getBoundingClientRect();
              for(const [rx,ry] of [[.12,.18],[.75,.12],[.85,.85]]){
                const x=box.left+box.width*rx,y=box.top+box.height*ry,target=document.elementFromPoint(x,y);
                if(target&&canvas.contains(target)&&!target.closest('.task-node,button,[data-edge],.minimap-wrap'))return {x,y};
              }
              return null;
            }''')
            assert point, 'Graph has a visible background area for panning'
            before_camera = page.locator('#world').get_attribute('style')
            page.mouse.move(point['x'], point['y'])
            page.mouse.down()
            page.mouse.move(point['x'] + 65, point['y'] + 35, steps=5)
            page.mouse.up()
            check(page.locator('#world').get_attribute('style') != before_camera,
                  'dragging empty Graph space still pans the view')
            page.locator('#arrange-button').click()
            check(graph_positions(page) == staged_positions and snapshot(page) == base,
                  'Graph pan, zoom and Arrange never rewrite stored coordinates, tasks or records')

            source = page.locator('.task-node[data-id=question] [data-port=out]').bounding_box()
            target = page.locator('.task-node[data-id=analysis] [data-port=in]').bounding_box()
            page.mouse.move(source['x'] + source['width']/2, source['y'] + source['height']/2)
            page.mouse.down()
            page.mouse.move(target['x'] + target['width']/2, target['y'] + target['height']/2, steps=10)
            page.mouse.up()
            connected = snapshot(page)
            expected = deepcopy(base)
            next(task for task in expected['tasks'] if task['id'] == 'analysis')['depends_on'].append('question')
            check(connected == expected and 'question|analysis' in edge_ids(page),
                  'dragging a Graph output to an input still creates a real dependency')
            page.locator('#undo-button').click()
            check(snapshot(page) == base and graph_positions(page) == staged_positions,
                  'undoing a connection restores the original organized overview')

            choose_layer_node(page, 'normalization')
            graph(page)
            expect(page.locator('.task-node[data-id=preparation]')).to_have_class(
                re.compile(r'\bselected\b'))
            expect(page.locator('[data-field=title]')).to_have_value('Prepare data')
            check(snapshot(page) == base,
                  'switching from a selected operation to Graph selects its owning overview without edits')
            choose_layer_node(page, 'log-transform')
            graph(page)
            expect(page.locator('.task-node[data-id=preparation]')).to_have_class(
                re.compile(r'\bselected\b'))
            check(snapshot(page) == base,
                  'switching from processing details to Graph follows its operation to the overview')

            page.locator('#list-button').click()
            page.locator('.table-task[data-id=log-transform]').click()
            expect(page.locator('#inspector')).to_be_visible()
            expect(page.locator('[data-field=title]')).to_have_value('Log-transform CPM')
            page.locator('#methods-tab').click()
            expect(page.locator('#methods-panel')).to_be_visible()
            check(snapshot(page) == base,
                  'processing work remains accessible from Step list with its complete method details')
            graph(page)
            if page.locator('#inspector').is_visible():
                page.locator('[data-action=close-inspector]').click()
            page.locator('#add-button').click()
            added = snapshot(page)
            new_overview = next(item for item in added['tasks'] if item['id'] not in {task['id'] for task in base['tasks']})
            check(new_overview.get('layer') == 'overview' and new_overview['id'] in graph_ids(page)
                  and len(added['tasks']) == len(base['tasks']) + 1,
                  'Add step in Graph creates an overview node without replacing lower-level work')
            page.locator(f'.task-node[data-id="{new_overview["id"]}"]').focus()
            page.keyboard.press('Enter')
            page.locator('[data-layer-field=layer]').select_option('operation')
            expect(page.locator('#layers-view')).to_be_visible()
            reclassified = snapshot(page)
            expect(page.locator('.flow-node[data-id="' + new_overview['id'] + '"]')).to_have_attribute('data-layer', 'operation')
            check(next(task for task in reclassified['tasks'] if task['id'] == new_overview['id'])['layer'] == 'operation'
                  and page.locator('.flow-node[data-id="' + new_overview['id'] + '"]').get_attribute('aria-pressed') == 'true'
                  and page.locator('[data-layer-field=layer]').input_value() == 'operation',
                  'reclassifying a new overview opens that same operation in Layers')
            graph(page)
            check(new_overview['id'] not in graph_ids(page),
                  'Graph no longer renders the reclassified lower-level operation')
            page.locator('#undo-button').click()
            check(snapshot(page) == added and new_overview['id'] in graph_ids(page),
                  'undo restores overview classification and Graph visibility')
            page.locator('#undo-button').click()
            check(snapshot(page) == base, 'undo removes the new overview and retains every operation and record')

            page.locator('.task-node[data-id=question]').focus()
            page.keyboard.press('Enter')
            child_button = page.locator('.task-node[data-id=preparation] [data-action=add-child]')
            child_button.focus()
            page.keyboard.press('Enter')
            expect(page.locator('#layers-view')).to_be_visible()
            added = snapshot(page)
            new_operation = next(item for item in added['tasks'] if item['id'] not in {task['id'] for task in base['tasks']})
            check(new_operation.get('layer') == 'operation'
                  and (new_operation.get('overview_id') == 'preparation' or new_operation.get('parent_id') == 'preparation')
                  and page.locator(f'.flow-node[data-id="{new_operation["id"]}"]').count() == 1,
                  'an unselected Graph card creates an operation under that card and opens it in Layers')
            check([task for task in added['tasks'] if task['id'] != new_operation['id']] == base['tasks'],
                  'adding an operation preserves all existing methods and historical records')
            page.locator('#layers-view [data-action=undo]').click()
            check(snapshot(page) == base, 'undo restores the full workflow after creating an operation from Graph')

            graph(page)
            saved = folder / 'saved-overview.html'
            saved.write_text(downloaded(page, 'save'), encoding='utf-8')
            reopened = opened(browser, saved)
            check(snapshot(reopened) == base,
                  'saving from overview-only Graph retains all operations, processing nodes, ideas and records')
            graph(reopened)
            check(graph_ids(reopened) == overview_ids and minimap_ids(reopened) == overview_ids,
                  'the saved full project reopens with the same overview-only Graph')
            reopened.close()
            page.close()

            custom = deepcopy(base)
            custom['layout']['positions']['question'] = {'x': 9000, 'y': -3000}
            custom['layout']['positions']['preparation'] = {'x': -3000, 'y': 5000}
            custom['layout']['layer_positions'] = {'normalization': {'x': 317, 'y': -225}}
            page = opened(browser, fixture_preview(folder, 'stored-positions', custom))
            custom_base = snapshot(page)
            graph(page)
            page.locator('#arrange-button').click()
            check(graph_positions(page) == staged_positions and snapshot(page) == custom_base,
                  'Graph ignores legacy free coordinates visually while preserving both stored position maps')
            choose_layer_node(page, 'normalization')
            expect(page.locator('.flow-node[data-id=normalization]')).to_have_attribute('data-x', '317')
            page.locator('[data-action=close-inspector]').click()
            page.locator('.flow-node[data-id=normalization]').focus()
            page.keyboard.press('ArrowRight')
            custom_moved = snapshot(page)
            check(custom_moved['layout']['layer_positions']['normalization']['x'] == 327
                  and custom_moved['layout']['positions'] == custom_base['layout']['positions']
                  and custom_moved['tasks'] == custom_base['tasks'],
                  'Layers keeps independent free movement while Graph coordinates and task data remain intact')
            graph(page)
            check(graph_positions(page) == staged_positions and snapshot(page) == custom_moved,
                  'returning from a freely moved Layers card leaves Graph automatically organized')
            page.locator('#undo-button').click()
            check(snapshot(page) == custom_base and graph_positions(page) == staged_positions,
                  'undoing Layers movement from Graph restores saved positions without changing stage placement')
            saved_custom = folder / 'saved-position-maps.html'
            saved_custom.write_text(downloaded(page, 'save'), encoding='utf-8')
            reopened = opened(browser, saved_custom)
            check(snapshot(reopened) == custom_base,
                  'Save copy retains legacy Graph coordinates and independent Layers coordinates for compatibility')
            graph(reopened)
            check(graph_positions(reopened) == staged_positions,
                  'a saved workflow with legacy coordinates still reopens as an organized Graph')
            reopened.close()
            page.close()

            mixed = {
                'schema_version': 1, 'project': {'name': 'Fictional cross-layer dependencies'},
                'tasks': [
                    {'id': 'a', 'title': 'Overview A', 'layer': 'overview'},
                    {'id': 'b', 'title': 'Overview B', 'layer': 'overview', 'depends_on': ['ob']},
                    {'id': 'c', 'title': 'Overview C', 'layer': 'overview', 'depends_on': ['a']},
                    {'id': 'oa', 'title': 'Operation A', 'layer': 'operation', 'overview_id': 'a'},
                    {'id': 'ob', 'title': 'Operation B', 'layer': 'operation', 'overview_id': 'b', 'depends_on': ['oa']},
                ],
            }
            page = opened(browser, fixture_preview(folder, 'cross-layer', mixed))
            mixed_base = snapshot(page)
            graph(page)
            check(graph_ids(page) == {'a', 'b', 'c'} and edge_ids(page) == {'a|c'},
                  'cross-layer and operation dependencies do not fabricate overview-to-overview arrows')
            check(page.locator('.stage-column').count() == 3
                  and graph_positions(page)['a']['x'] < graph_positions(page)['b']['x'] < graph_positions(page)['c']['x'],
                  'independent overview steps retain separate numbered columns regardless of hidden dependencies')
            check(snapshot(page) == mixed_base,
                  'the overview projection retains original cross-layer dependencies in export')
            page.close()

            numbered = {
                'schema_version': 1, 'project': {'name': 'Fictional numbered overview'},
                'tasks': [
                    {'id': 'c', 'title': 'Third step', 'layer': 'overview', 'step_number': 3},
                    {'id': 'a', 'title': 'First step', 'layer': 'overview', 'step_number': 1, 'depends_on': ['c']},
                    {'id': 'b', 'title': 'Second step', 'layer': 'overview', 'step_number': 2},
                ],
            }
            page = opened(browser, fixture_preview(folder, 'numbered-order', numbered))
            numbered_base = snapshot(page)
            graph(page)
            ordered = sorted(graph_positions(page), key=lambda task_id: graph_positions(page)[task_id]['x'])
            check(ordered == ['a', 'b', 'c'] and edge_ids(page) == {'c|a'}
                  and page.locator('.stage-column h2').all_text_contents() == ['Step 1', 'Step 2', 'Step 3'],
                  'explicit step numbers organize Graph even when authored dependencies run backward')
            page.locator('.task-node[data-id=a]').focus()
            page.keyboard.press('ArrowRight')
            expect(page.locator('.task-node[data-id=b]')).to_be_focused()
            page.keyboard.press('ArrowRight')
            expect(page.locator('.task-node[data-id=c]')).to_be_focused()
            check(True, 'Graph arrow keys follow the visible numbered order instead of moving cards')
            check(snapshot(page) == numbered_base,
                  'displaying a backward dependency does not rewrite it or infer a new step order')
            page.locator('.task-node[data-id=a]').focus()
            page.keyboard.press('Enter')
            page.locator('#step-number').fill('3')
            page.locator('#step-number').press('Tab')
            renumbered = snapshot(page)
            expected = deepcopy(numbered_base)
            next(task for task in expected['tasks'] if task['id'] == 'a')['step_number'] = 3
            next(task for task in expected['tasks'] if task['id'] == 'c')['step_number'] = 1
            check(renumbered == expected
                  and graph_positions(page)['c']['x'] < graph_positions(page)['b']['x'] < graph_positions(page)['a']['x']
                  and edge_ids(page) == {'c|a'},
                  'editing a step number reorders Graph while preserving the authored connection and stored coordinates')
            page.locator('#undo-button').click()
            check(snapshot(page) == numbered_base
                  and graph_positions(page)['a']['x'] < graph_positions(page)['b']['x'] < graph_positions(page)['c']['x'],
                  'undo restores the previous numbered Graph order')
            page.close()

            legacy_preview = build(ROOT / 'examples/research-project.yaml', folder / 'legacy.html')
            page = opened(browser, legacy_preview)
            legacy_base = snapshot(page)
            graph(page)
            check(graph_ids(page) == {'question', 'analysis', 'synthesis'}
                  and minimap_ids(page) == {'question', 'analysis', 'synthesis'},
                  'legacy workflows infer overview from root steps without exposing their child operations')
            check(snapshot(page) == legacy_base,
                  'viewing legacy overview does not persist inferred layer metadata or delete child work')
            page.close()

            operation_only = {
                'schema_version': 1, 'project': {'name': 'Fictional operation-only project'},
                'tasks': [
                    {'id': 'operation', 'title': 'Standalone operation', 'layer': 'operation', 'method': 'Illustrative plan.'},
                    {'id': 'processing', 'title': 'Standalone processing', 'layer': 'processing', 'operation_id': 'operation'},
                ],
            }
            page = opened(browser, fixture_preview(folder, 'operation-only', operation_only))
            operation_base = snapshot(page)
            graph(page)
            expect(page.locator('#empty-state')).to_be_visible()
            expect(page.locator('#minimap-wrap')).not_to_be_visible()
            check(not graph_ids(page) and snapshot(page) == operation_base,
                  'an operation-only project has an empty Graph without synthetic overview steps or data loss')
            page.locator('#list-button').click()
            page.locator('.table-task[data-id=operation]').click()
            expect(page.locator('[data-field=title]')).to_have_value('Standalone operation')
            page.locator('#methods-tab').click()
            expect(page.locator('#methods-panel')).to_be_visible()
            check(snapshot(page) == operation_base,
                  'unassigned operations remain reachable through Step list when Graph is empty')
            page.close()

            for width, height in [(390, 844), (700, 900)]:
                page = opened(browser, preview, width=width, height=height)
                mobile_base = snapshot(page)
                graph(page)
                check(graph_ids(page) == overview_ids and minimap_ids(page) == overview_ids
                      and page.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                      f'mobile Graph retains overview-only nodes and minimap without document overflow at {width}px')
                check(int(page.locator('#zoom-level').inner_text().rstrip('%')) >= 85
                      and page.locator('.task-node[data-id=preparation]').evaluate('''node => {
                        const card=node.getBoundingClientRect(),canvas=document.querySelector('#canvas').getBoundingClientRect();
                        const scale=card.width/parseFloat(node.style.width);
                        return parseFloat(getComputedStyle(node.querySelector('h3')).fontSize)*scale >= 12
                          && card.left>=canvas.left && card.right<=canvas.right
                          && card.top>=canvas.top && card.bottom<=canvas.bottom;
                      }'''), f'mobile Graph opens with a readable overview in view at {width}px')
                page.locator('#fit-button').click()
                check(page.locator('.task-node').evaluate_all('''nodes => {
                    const canvas=document.querySelector('#canvas').getBoundingClientRect();
                    return nodes.every(node => { const card=node.getBoundingClientRect();
                      return card.left>=canvas.left-1 && card.right<=canvas.right+1
                        && card.top>=canvas.top-1 && card.bottom<=canvas.bottom+1; });
                  }'''), f'explicit mobile Fit shows the entire overview chain at {width}px')
                check(snapshot(page) == mobile_base,
                      f'mobile opening and Fit preserve the complete project at {width}px')
                page.close()
            check(not ERRORS, 'overview-only Graph interactions produce no uncaught JavaScript errors')
            browser.close()
    (OUT / 'overview-graph-checks.json').write_text(json.dumps(
        {'count': len(CHECKS), 'checks': CHECKS, 'errors': ERRORS}, indent=2), encoding='utf-8')
    print('ALL', len(CHECKS), 'CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run()
