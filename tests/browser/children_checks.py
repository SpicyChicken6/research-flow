#!/usr/bin/env python3
"""Hierarchy, overview navigation and detailed child work in disposable projects."""
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import re
import shutil
import sys
import threading
import time

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.build_preview import build
from server import parse_project, ProjectStore, make_handler

OUT = ROOT / 'test-results'
CHECKS, ERRORS = [], []
LAST_EXPORT = 0.0


def check(value, label):
    if not value:
        raise AssertionError(label)
    CHECKS.append(label)
    print('PASS', label, flush=True)


def opened(browser, path, width=1600, height=1000):
    page = browser.new_page(viewport={'width': width, 'height': height}, accept_downloads=True,
                            reduced_motion='reduce')
    page.set_default_timeout(7000)
    page.on('pageerror', lambda error: ERRORS.append(str(error)))
    page.goto(path.resolve().as_uri(), wait_until='load')
    expect(page.locator('#save-button')).to_be_enabled()
    return page


def snap(page):
    global LAST_EXPORT
    page.wait_for_timeout(max(0, 1 - (time.monotonic() - LAST_EXPORT)) * 1000)
    page.locator('#more-menu summary').click()
    with page.expect_download() as download:
        page.locator('#more-menu [data-action=export-json]').click()
    LAST_EXPORT = time.monotonic()
    return json.loads(Path(download.value.path()).read_text())


def task(document, task_id):
    return next(item for item in document['tasks'] if item['id'] == task_id)


def close_details(page):
    if page.locator('#inspector').is_visible():
        page.locator('[data-action=close-inspector]').click()


def overview(page):
    close_details(page)
    page.locator('#overview-button').click()


def layers(page):
    close_details(page)
    page.locator('#layers-button').click()


def go(page, task_id, layer=False):
    node = page.locator(f'{".flow-node" if layer else ".task-node"}[data-id="{task_id}"]')
    node.focus()
    page.keyboard.press('Enter')
    expect(page.locator('#inspector')).to_be_visible()
    page.locator('#plan-tab').click()


def history(page, redo=False):
    page.locator('#layers-button').focus()
    page.keyboard.press('Control+Shift+z' if redo else 'Control+z')


def new_operation(page, owner):
    overview(page)
    go(page, owner)
    page.locator('#inspector [data-action=add-child]').click()
    expect(page.locator('#layers-view')).to_be_visible()
    expect(page.locator('[data-field=title]')).to_be_focused()
    document = snap(page)
    return document['tasks'][-1]['id'], document


def positions(page, layer=False):
    return page.locator('.flow-node' if layer else '.task-node:visible').evaluate_all(
        'nodes => Object.fromEntries(nodes.map(n => [n.dataset.id,{x:parseFloat(n.style.left),y:parseFloat(n.style.top)}]))')


def drag_node(page, task_id, layer=False):
    selector = '.flow-node' if layer else '.task-node'
    box = page.locator(f'{selector}[data-id="{task_id}"]').bounding_box()
    x, y = box['x'] + box['width'] * .4, box['y'] + box['height'] * .4
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 45, y + 24, steps=10)
    page.mouse.up()


def saved_copy(page, directory, name):
    with page.expect_download() as download:
        page.locator('#save-button').click()
    path = directory / name
    path.write_text(Path(download.value.path()).read_text(), encoding='utf-8')
    return path


def fixture_preview(directory, name, document):
    path = directory / f'{name}.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    return build(path, directory / f'{name}.html')


def run():
    OUT.mkdir(exist_ok=True)
    source = parse_project((ROOT / 'examples/research-project.yaml').read_text())
    with TemporaryDirectory(prefix='research-flow-hierarchy-') as temporary:
        directory = Path(temporary)
        preview = build(ROOT / 'examples/research-project.yaml', directory / 'hierarchy.html')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])
            page = opened(browser, preview)
            base = snap(page)
            check(set(positions(page)) == {'question', 'analysis', 'synthesis'}
                  and page.locator('.stage-column h2').all_text_contents() == ['Step 1', 'Step 2', 'Step 3'],
                  'legacy hierarchy opens with three numbered overview cards in Graph')
            check(page.locator('.edge-hit[data-edge]').count() == 2,
                  'Graph displays only explicit dependencies between overview steps')
            check(page.locator('.substeps-section,.substep-row,.node-substeps,[data-action=add-substep]').count() == 0,
                  'the obsolete checklist editor is absent')
            check(not page.locator('#inspector').is_visible(), 'initial view remains a quiet canvas without details')
            layers(page)
            expect(page.locator('.flow-node')).to_have_count(8)
            check(page.locator('.flow-node[data-layer=operation]').count() == 5,
                  'legacy children and grandchildren remain accessible as five operations in Layers')
            check(snap(page) == base, 'showing legacy detailed work does not rewrite hierarchy or positions')
            page.screenshot(path=str(OUT / 'children-overview.png'))
            overview(page)
            page.locator('#add-button').click()
            added = snap(page)
            new = added['tasks'][-1]
            check(len(added['tasks']) == 9 and new['title'] == 'Untitled step'
                  and new['layer'] == 'overview' and not new.get('parent_id'),
                  'Graph Add inserts an independent overview step')
            history(page)
            check(snap(page) == base, 'undo reverses overview insertion')
            operation_id, document = new_operation(page, 'analysis')
            operation = task(document, operation_id)
            check(operation['layer'] == 'operation' and operation['overview_id'] == 'analysis'
                  and operation['depends_on'] == [] and not operation.get('parent_id'),
                  'Add operation assigns overview membership without inventing hierarchy or dependencies')
            page.locator('[data-field=title]').fill('Confirm provenance')
            page.locator('[data-field=goal]').fill('Validate source versions')
            page.locator('[data-field=status]').select_option('in_progress')
            page.locator('#resources-tab').click()
            page.locator('[data-field=notes]').fill('Keep records\nSecond line')
            page.locator('[data-field=inputs]').fill('data/source.tsv')
            page.locator('[data-field=outputs]').fill('notes/provenance.md')
            document = snap(page)
            check(task(document, operation_id)['notes'] == 'Keep records\nSecond line'
                  and task(document, operation_id)['inputs'] == ['data/source.tsv'],
                  'new operations use the existing notes and file-reference editor')
            page.locator('#plan-tab').click()
            page.locator('#inspector [data-action=add-child]').click()
            document = snap(page)
            processing_id = document['tasks'][-1]['id']
            check(task(document, processing_id)['layer'] == 'processing'
                  and task(document, processing_id)['operation_id'] == operation_id
                  and task(document, processing_id)['depends_on'] == [],
                  'adding detailed work to an operation creates a processing node with explicit membership')
            page.locator('[data-field=title]').fill('Record source checksum')
            page.locator('[data-field=status]').select_option('done')
            document = snap(page)
            check(task(document, operation_id)['status'] == 'in_progress'
                  and task(document, 'analysis')['status'] == 'in_progress',
                  'completing processing work does not overwrite operation or overview progress')
            copy = opened(browser, saved_copy(page, directory, 'saved-children.html'))
            check(snap(copy) == document, 'Save copy preserves hierarchy, layer membership, statuses and detailed notes')
            layers(copy)
            check(copy.locator(f'.flow-node[data-id="{processing_id}"]').count() == 1,
                  'saved copies render new processing work beneath its operation context')
            copy.close()
            page.close()

            # Keep legacy parent editing, hierarchical numbering and the full list.
            page = opened(browser, preview)
            base = snap(page)
            layers(page)
            go(page, 'metadata', layer=True)
            page.locator('#parent-step').select_option('model')
            check(task(snap(page), 'metadata')['parent_id'] == 'model', 'Part of can reparent existing legacy work')
            history(page)
            check(snap(page) == base, 'undo restores the previous parent and all project data')
            go(page, 'analysis', layer=True)
            options = page.locator('#parent-step option').evaluate_all('options => options.map(o => o.value)')
            check(not {'analysis', 'preparation', 'metadata', 'sensitivity'} & set(options),
                  'parent choices exclude self and all descendants')
            go(page, 'metadata', layer=True)
            page.locator('#parent-step').select_option('')
            promoted = snap(page)
            overview(page)
            check(not task(promoted, 'metadata').get('parent_id')
                  and page.locator('.task-node[data-id=metadata]').count() == 1,
                  'clearing an unrecorded legacy parent promotes that step into the overview Graph')
            history(page)
            layers(page)
            go(page, 'metadata', layer=True)
            page.locator('#add-dependency').select_option('question')
            document = snap(page)
            check(task(document, 'metadata')['depends_on'] == ['question']
                  and task(document, 'metadata')['parent_id'] == 'preparation',
                  'editing a child dependency does not alter its parent')
            history(page)
            overview(page)
            page.locator('.task-node[data-id=analysis] h3').dblclick()
            page.locator('.node-title-input').fill('Updated analysis')
            page.locator('.node-title-input').press('Enter')
            renamed = snap(page)
            check(task(renamed, 'analysis')['title'] == 'Updated analysis' and renamed['layout'] == base['layout'],
                  'inline overview rename preserves every stored position')
            history(page)
            check(snap(page) == base, 'one undo reverses the overview rename')
            history(page, redo=True)
            page.locator('.task-node[data-id=analysis] h3').dblclick()
            page.locator('.node-title-input').fill('Cancelled name')
            page.locator('.node-title-input').press('Escape')
            check(snap(page) == renamed, 'Escape cancels inline renaming without changing data')
            page.locator('#list-button').click()
            check(page.locator('.table-task').evaluate_all('nodes => nodes.map(n => n.dataset.id)') ==
                  ['question', 'analysis', 'preparation', 'metadata', 'batches', 'model', 'sensitivity', 'synthesis'],
                  'Step list groups interleaved source tasks by their original hierarchy')
            check(page.locator('.table-step').evaluate_all('nodes => nodes.map(n => parseFloat(getComputedStyle(n).paddingInlineStart))') ==
                  [0, 0, 22, 44, 44, 22, 44, 0], 'list indentation preserves each hierarchy depth')
            page.locator('.table-task[data-id=metadata]').click()
            page.locator('[data-field=title]').fill('Check provenance')
            page.locator('[data-field=title]').press('Tab')
            renamed = snap(page)
            check(page.locator('#list-view').is_visible() and task(renamed, 'metadata')['title'] == 'Check provenance',
                  'detailed legacy work can be selected and renamed from Step list')
            close_details(page)
            page.screenshot(path=str(OUT / 'hierarchical-list.png'))
            overview(page)
            go(page, 'analysis')
            page.locator('#step-number').fill('1')
            page.locator('#step-number').press('Enter')
            numbered = snap(page)
            check(task(numbered, 'analysis')['step_number'] == 1 and task(numbered, 'question')['step_number'] == 2,
                  'choosing an occupied overview number swaps main-step numbers')
            page.locator('#list-button').click()
            check(page.locator('.table-number').all_text_contents() == ['1', '1.1', '1.1.1', '1.1.2', '1.2', '1.2.1', '2', '3'],
                  'renumbering updates all derived child numbers and list order')
            overview(page)
            check(list(positions(page)) == ['analysis', 'question', 'synthesis'] and numbered['layout'] == renamed['layout'],
                  'Graph follows overview numbering while saved coordinates remain unchanged')
            go(page, 'analysis')
            page.locator('#step-number').fill('0')
            page.locator('#step-number').press('Enter')
            check(snap(page) == numbered, 'invalid step numbers leave project data unchanged')
            history(page)
            check(snap(page) == renamed, 'one undo restores both root numbers and descendant labels')
            history(page, redo=True)
            layers(page)
            go(page, 'preparation', layer=True)
            page.locator('[data-action=delete-task]').click()
            page.locator('#delete-step-cancel').click()
            check(snap(page) == numbered, 'canceling a child deletion preserves the workflow')
            page.locator('[data-action=delete-task]').click()
            page.locator('#confirm-delete-step').click()
            deleted = snap(page)
            check(not any(t['id'] == 'preparation' for t in deleted['tasks'])
                  and task(deleted, 'metadata')['parent_id'] == 'analysis'
                  and task(deleted, 'batches')['parent_id'] == 'analysis'
                  and task(deleted, 'metadata')['notes'] == task(numbered, 'metadata')['notes'],
                  'deleting a legacy parent promotes its direct children and preserves their work')
            history(page)
            check(snap(page) == numbered, 'undo restores deleted parents, descendant hierarchy and numbering')
            page.close()

            # Graph geometry is fixed; only Layers moves individual detailed cards.
            page = opened(browser, preview)
            base = snap(page)
            graph_positions = positions(page)
            drag_node(page, 'analysis')
            page.locator('.task-node[data-id=analysis]').focus()
            page.keyboard.press('ArrowRight')
            page.locator('#arrange-button').click()
            check(positions(page) == graph_positions and snap(page) == base
                  and page.locator('#layout-freeform').count() == 0,
                  'Graph dragging, arrow navigation and Arrange cannot edit saved positions')
            layers(page)
            page.locator('[data-action=layer-fit]').click()
            initial = positions(page, layer=True)
            drag_node(page, 'preparation', layer=True)
            moved = snap(page)
            changed = positions(page, layer=True)
            check(changed['preparation'] != initial['preparation']
                  and all(changed[key] == value for key, value in initial.items() if key != 'preparation'),
                  'Layers moves only the chosen card while descendants and neighbors stay in place')
            check(moved['tasks'] == base['tasks'] and moved['layout']['positions'] == base['layout']['positions'],
                  'free card movement preserves hierarchy, statuses and legacy Graph coordinates')
            history(page)
            check(snap(page) == base, 'one undo reverses a Layers move including its initial position snapshot')
            history(page, redo=True)
            check(snap(page) == moved, 'redo restores the individual card position')
            history(page)
            page.locator('.flow-node[data-id=preparation]').focus()
            page.keyboard.press('ArrowRight')
            nudged = positions(page, layer=True)
            check(nudged['preparation']['x'] == initial['preparation']['x'] + 10
                  and nudged['metadata'] == initial['metadata'],
                  'Layers keyboard nudging moves the chosen card without moving its legacy subtree')
            history(page)
            go(page, 'model', layer=True)
            page.locator('#add-dependency').select_option('batches')
            linked = snap(page)
            check('batches' in task(linked, 'model')['depends_on']
                  and task(linked, 'model')['parent_id'] == 'analysis',
                  'detailed dependency editing preserves containment')
            close_details(page)
            edge = page.locator('.layer-dependency-hit[data-source=batches][data-target=model]')
            edge.focus()
            page.keyboard.press('Enter')
            page.locator('#connection-target').select_option('synthesis')
            page.locator('#connection-form button[type=submit]').click()
            rewired = snap(page)
            check('batches' in task(rewired, 'synthesis')['depends_on']
                  and 'batches' not in task(rewired, 'model')['depends_on'],
                  'the connection editor rewires a real lower-level dependency')
            history(page)
            history(page)
            check(snap(page) == base, 'connection edits undo independently of hierarchy and card positions')
            page.close()

            # Explicit overview hierarchies retain Graph focus and collapse behavior.
            nested = deepcopy(source)
            for item in nested['tasks']:
                if item['id'] in {'preparation', 'metadata'}:
                    item['layer'] = 'overview'
            task(nested, 'synthesis')['depends_on'].append('metadata')
            page = opened(browser, fixture_preview(directory, 'nested-overviews', nested))
            nested_base = snap(page)
            page.locator('#canvas').dblclick(position={'x': 400, 'y': 120})
            inserted = snap(page)
            check(len(inserted['tasks']) == len(nested_base['tasks']) + 1
                  and inserted['tasks'][-1]['layer'] == 'overview',
                  'double-clicking empty Graph space adds exactly one overview step')
            history(page)
            check(snap(page) == nested_base, 'empty-canvas overview insertion remains undoable')
            go(page, 'question')
            close_details(page)
            page.locator('.task-node[data-id=preparation] .node-delete').click()
            expect(page.locator('#delete-step-dialog')).to_be_visible()
            expect(page.locator('#delete-step-name')).to_contain_text('Prepare the dataset')
            page.locator('#delete-step-cancel').click()
            check(snap(page) == nested_base,
                  'card deletion targets the clicked overview rather than another selected step and can be canceled')
            page.locator('.task-node[data-id=preparation] .node-delete').click()
            page.locator('#confirm-delete-step').click()
            deleted = snap(page)
            check(not any(item['id'] == 'preparation' for item in deleted['tasks'])
                  and task(deleted, 'metadata')['parent_id'] == 'analysis'
                  and task(deleted, 'question') == task(nested_base, 'question'),
                  'card delete removes its target and promotes its children without deleting the selected overview')
            history(page)
            check(snap(page) == nested_base, 'undo restores card deletion including overview hierarchy')
            go(page, 'preparation')
            page.locator('#focus-button').click()
            check(set(positions(page)) == {'analysis', 'preparation', 'metadata', 'synthesis'},
                  'Graph Focus includes explicit overview descendants and their ancestor context')
            check(snap(page) == nested_base, 'focusing an overview hierarchy changes presentation only')
            overview(page)
            page.locator('.task-node[data-id=analysis] .children-toggle').click()
            expect(page.locator('.task-node:visible')).to_have_count(3)
            check(page.locator('[data-bundle="analysis|synthesis"] text').text_content() == '2 hidden links',
                  'collapsing overview children bundles only their actual dependencies')
            page.locator('.bundle-label[data-bundle="analysis|synthesis"]').focus()
            page.keyboard.press('Enter')
            check(page.locator('.task-node[data-id=metadata]').is_visible()
                  and page.locator('[data-edge="metadata|synthesis"]').count() == 1,
                  'opening a bundle reveals its real overview endpoints')
            check(snap(page) == nested_base, 'collapse and reveal never invent parent dependencies')
            overview(page)
            page.locator('.task-node[data-id=preparation] .children-toggle').click()
            expect(page.locator('.task-node:visible')).to_have_count(4)
            page.locator('.task-node[data-id=preparation] .children-toggle').click()
            expect(page.locator('.task-node:visible')).to_have_count(5)
            check(True, 'nested overview collapse hides only its own descendants')
            page.screenshot(path=str(OUT / 'children-focus.png'))
            page.close()

            legacy = json.loads((ROOT / 'tests/fixtures/classic-project.json').read_text())
            legacy['tasks'][0]['substeps'] = [{'id': 'review', 'title': 'Prior checklist item',
                                             'notes': 'An existing note', 'status': 'done'}]
            page = opened(browser, fixture_preview(directory, 'migrated-checklist', legacy))
            migrated = snap(page)
            converted = task(migrated, 'question_review')
            check(converted['parent_id'] == 'question' and converted['notes'] == 'An existing note'
                  and converted['status'] == 'done', 'legacy checklist migration preserves child ownership, notes and status')
            check(not any('substeps' in item for item in migrated['tasks'])
                  and all(migrated['layout']['positions'][key] == value for key, value in legacy['layout']['positions'].items()),
                  'migration removes checklist fields without moving original cards')
            go(page, 'question')
            layers(page)
            page.locator('.flow-node[data-id=question]').click()
            check(page.locator('.flow-node[data-id=question_review]').count() == 1,
                  'migrated checklist work is accessible as an operation in Layers')
            page.close()

            for width, height in [(1280, 800), (820, 1000), (390, 844), (320, 640)]:
                page = opened(browser, preview, width=width, height=height)
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                      f'hierarchy views have no horizontal document overflow at {width}px')
                go(page, 'analysis')
                box = page.locator('#inspector').bounding_box()
                check(box['x'] >= 0 and box['x'] + box['width'] <= width + 1
                      and box['y'] + box['height'] <= height + 1,
                      f'overview hierarchy details fit at {width}px')
                expect(page.locator('#parent-step')).to_be_visible()
                close_details(page)
                page.locator('#list-button').click()
                expect(page.locator('.table-task')).to_have_count(8)
                check(page.locator('#list-view table').bounding_box()['y'] > page.locator('#list-button').bounding_box()['y'] + 31,
                      f'hierarchical list rows start below the toolbar at {width}px')
                if width == 390:
                    page.screenshot(path=str(OUT / 'hierarchical-list-mobile.png'))
                page.close()

            # Real local Save and external-conflict handling for newly linked operations.
            path = directory / 'project.yaml'
            path.write_text((ROOT / 'examples/research-project.yaml').read_text())
            httpd = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(ProjectStore(path)))
            server = threading.Thread(target=httpd.serve_forever, daemon=True)
            server.start()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 900}, accept_downloads=True,
                                        reduced_motion='reduce')
                page.set_default_timeout(10000)
                page.on('pageerror', lambda error: ERRORS.append(str(error)))
                page.goto(f'http://127.0.0.1:{httpd.server_port}/', wait_until='networkidle')
                expect(page.locator('#save-state')).to_have_text('Saved')
                operation_id, _ = new_operation(page, 'analysis')
                page.locator('[data-field=title]').fill('Operation persisted on disk')
                page.locator('#save-button').click()
                expect(page.locator('#save-state')).to_have_text('Saved')
                saved = parse_project(path.read_text())
                check(task(saved, operation_id)['overview_id'] == 'analysis'
                      and task(saved, operation_id)['title'] == 'Operation persisted on disk',
                      'local Save persists newly added operation membership and title')
                overview(page)
                go(page, 'analysis')
                page.locator('#step-number').fill('7')
                page.keyboard.press('Control+s')
                expect(page.locator('#save-state')).to_have_text('Saved')
                check(task(parse_project(path.read_text()), 'analysis')['step_number'] == 7,
                      'Ctrl+S commits the active step-number field to YAML')
                layers(page)
                go(page, operation_id, layer=True)
                page.locator('[data-layer-field=overview_id]').select_option('synthesis')
                page.locator('#save-button').click()
                expect(page.locator('#save-state')).to_have_text('Saved')
                check(task(parse_project(path.read_text()), operation_id)['overview_id'] == 'synthesis',
                      'local Save persists an operation moving to another overview')
                check(len([path for path in (directory / '.research-flow').rglob('*.yaml') if path.is_file()]) == 3,
                      'each actual save backs up the preceding on-disk version')
                page.locator('[data-field=goal]').fill('Unsaved operation draft')
                external = parse_project(path.read_text())
                external['project']['description'] = 'Changed externally'
                path.write_text(json.dumps(external))
                expect(page.locator('#file-alert')).to_be_visible(timeout=10000)
                check(page.locator('#save-button').is_disabled()
                      and page.locator('[data-field=goal]').input_value() == 'Unsaved operation draft',
                      'external conflicts continue protecting unsaved detailed work')
                page.close()
            finally:
                httpd.shutdown()
                httpd.server_close()
                server.join(timeout=5)
            check(not ERRORS, 'hierarchy integration has no uncaught JavaScript errors')
            browser.close()
    (OUT / 'children-checks.json').write_text(json.dumps({'count': len(CHECKS), 'checks': CHECKS, 'errors': ERRORS}, indent=2))
    print('ALL', len(CHECKS), 'CHILDREN CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run()
