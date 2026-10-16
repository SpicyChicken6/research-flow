#!/usr/bin/env python3
"""Connected research canvas regressions through public controls and exports."""
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


def opened(browser, path, width=1600, height=1100):
    page = browser.new_page(viewport={'width': width, 'height': height},
                            accept_downloads=True, reduced_motion='reduce')
    page.set_default_timeout(7000)
    page.on('pageerror', lambda error: ERRORS.append(str(error)))
    page.goto(path.resolve().as_uri(), wait_until='load')
    expect(page.locator('#save-button')).to_be_enabled()
    expect(page.locator('#layer-canvas')).to_be_visible()
    return page


def downloaded(page, action):
    global LAST_DOWNLOAD
    # Keep Chromium's download burst limiter from swallowing successive exports.
    pause = 1 - (time.monotonic() - LAST_DOWNLOAD)
    if pause > 0:
        page.wait_for_timeout(pause * 1000)
    if action.startswith('export-'):
        page.locator('#more-menu summary').click()
    control = (page.locator(f'#more-menu [data-action="{action}"]')
               if action.startswith('export-') else page.locator(f'[data-action="{action}"]'))
    with page.expect_download() as download:
        control.click()
    LAST_DOWNLOAD = time.monotonic()
    return Path(download.value.path()).read_text(encoding='utf-8')


def snapshot(page):
    return json.loads(downloaded(page, 'export-json'))


def task(document, task_id):
    return next(item for item in document['tasks'] if item['id'] == task_id)


def choose_overview(page, task_id):
    card = page.locator(f'[data-action=layer-overview][data-id="{task_id}"]')
    card.focus()
    page.keyboard.press('Enter')
    expect(card).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#inspector')).to_be_visible()


def choose_operation(page, task_id):
    card = page.locator(f'[data-action=layer-operation][data-id="{task_id}"]')
    card.focus()
    page.keyboard.press('Enter')
    expect(card).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#methods-panel')).to_be_visible()


def choose_processing(page, task_id):
    card = page.locator(f'[data-action=layer-processing][data-id="{task_id}"]')
    card.focus()
    page.keyboard.press('Enter')
    expect(card).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#methods-panel')).to_be_visible()


def camera(page):
    return page.locator('#layer-world').evaluate('element => getComputedStyle(element).transform')


def nodes_inside_canvas(page, ids=None):
    selector = (','.join(f'.flow-node[data-id="{item}"]' for item in ids)
                if ids else '.flow-node')
    return page.locator(selector).evaluate_all('''nodes => {
        const canvas=document.querySelector('#layer-canvas').getBoundingClientRect();
        return nodes.every(node => {
            const box=node.getBoundingClientRect();
            return box.left>=canvas.left-1 && box.right<=canvas.right+1
                && box.top>=canvas.top-1 && box.bottom<=canvas.bottom+1;
        });
    }''')


def pan_canvas(page):
    point = page.locator('#layer-canvas').evaluate('''canvas => {
        const box = canvas.getBoundingClientRect();
        for (const [rx,ry] of [[.88,.9],[.7,.95],[.12,.9],[.8,.08]]) {
            const x=box.left+box.width*rx, y=box.top+box.height*ry;
            const target=document.elementFromPoint(x,y);
            if (target && canvas.contains(target) && !target.closest('button,[data-action]'))
                return {x,y};
        }
        return null;
    }''')
    if not point:
        raise AssertionError('canvas has a visible background area for panning')
    page.mouse.move(point['x'], point['y'])
    page.mouse.down()
    page.mouse.move(point['x'] - 70, point['y'] - 35, steps=6)
    page.mouse.up()


def choose_record(page, record_id):
    entry = page.locator(f'[data-action=layer-record-select][data-id="{record_id}"]')
    entry.click()
    expect(entry).to_have_attribute('aria-pressed', 'true')


def run():
    OUT.mkdir(exist_ok=True)
    preview = build(ROOT / 'examples/three-layers.yaml', ROOT / 'dist/three-layers.html')
    with TemporaryDirectory(prefix='research-flow-layers-') as temporary:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])
            page = opened(browser, preview)
            expect(page.locator('#layers-button')).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('.overview-card')).to_have_count(5)
            base = snapshot(page)
            check(page.locator('.overview-card strong').all_text_contents() == [
                'Define question', 'Gather evidence', 'Prepare data', 'Analyze', 'Communicate'],
                'layered example opens with the five overview stages')
            check('fictional' in base['project']['description'].lower(),
                  'the example retains its fictional-data description')
            check(page.locator('#layer-world .flow-node[data-layer=overview]').count() == 5
                  and page.locator('#layer-world .flow-node[data-layer=operation]').count() == 4
                  and page.locator('#layer-world .flow-node[data-layer=processing]').count() == 3,
                  'one connected canvas shows overview, preparation operations and processing steps together')
            check(page.locator('.overview-rail,.operations-rail,.methods-layer').count() == 0,
                  'the canvas replaces separate rail sections and an always-open methods dashboard')
            sequential = page.locator('.layer-dependency-path[data-source=scale-cpm][data-target=log-transform]')
            memberships = page.locator('.layer-membership-path[data-source=normalization]')
            expect(sequential).to_have_count(1)
            check(set(memberships.evaluate_all('paths => paths.map(path => path.dataset.target)')) ==
                  {'scale-cpm', 'log-transform'},
                  'library scaling and log transformation are distinct nodes linked to their operation')
            check(sequential.evaluate('path => getComputedStyle(path).strokeDasharray') in {'none', '0px'}
                  and all(value not in {'none', '0px'} for value in memberships.evaluate_all(
                      'paths => paths.map(path => getComputedStyle(path).strokeDasharray)')),
                  'solid arrows express dependencies and dashed connectors express membership')
            recorded_ids = {record['id'] for item in base['tasks'] for record in item.get('records', [])}
            node_ids = set(page.locator('.flow-node').evaluate_all('nodes => nodes.map(node => node.dataset.id)'))
            check(not (node_ids & recorded_ids)
                  and all(not task(base, item).get('records') for item in ['scale-cpm', 'log-transform', 'filter-rule']),
                  'processing plans are nodes while alternative recorded runs remain history')
            page.locator('.flow-node[data-id=normalization]').click()
            expect(page.locator('#methods-panel')).to_be_visible()
            expect(page.locator('#methods-panel .record-entry')).to_have_count(2)
            check(page.locator('#layers-view .record-entry').count() == 0,
                  'clicking an operation opens methods and recorded runs in the details sidebar')
            choose_processing(page, 'scale-cpm')
            expect(page.locator('#methods-panel')).to_contain_text('cpm.tsv')
            expect(page.locator('#methods-panel .record-entry')).to_have_count(0)
            check(snapshot(page) == base, 'opening planned processing details does not invent execution records')

            choose_operation(page, 'normalization')
            page.locator('#plan-tab').click()
            page.locator('[data-layer-field=overview_id]').select_option('analysis')
            expect(page.locator('.flow-node[data-id=normalization]')).to_be_visible()
            expect(page.locator('.flow-node[data-id=analysis-code]')).to_have_count(1)
            expect(page.locator('.flow-node[data-id=metadata]')).to_have_count(0)
            expected_reassignment = deepcopy(base)
            task(expected_reassignment, 'normalization')['overview_id'] = 'analysis'
            check(snapshot(page) == expected_reassignment and page.locator('#inspector').is_visible(),
                  'reassigning the selected operation follows its new overview while keeping its details open')
            page.locator('#layers-view [data-action=undo]').click()
            expect(page.locator('[data-layer-field=overview_id]')).to_have_value('preparation')
            expect(page.locator('.flow-node[data-id=normalization]')).to_be_visible()
            expect(page.locator('.flow-node[data-id=metadata]')).to_have_count(1)
            check(snapshot(page) == base,
                  'undoing operation reassignment restores the visible overview context and selected details')
            page.locator('#layers-view [data-action=redo]').click()
            expect(page.locator('[data-layer-field=overview_id]')).to_have_value('analysis')
            expect(page.locator('.flow-node[data-id=normalization]')).to_be_visible()
            expect(page.locator('.flow-node[data-id=analysis-code]')).to_have_count(1)
            check(snapshot(page) == expected_reassignment,
                  'redoing operation reassignment keeps the selected node visible in its correct context')
            page.locator('#layers-view [data-action=undo]').click()

            choose_processing(page, 'scale-cpm')
            page.locator('#plan-tab').click()
            page.locator('[data-layer-field=operation_id]').select_option('analysis-code')
            expect(page.locator('.flow-node[data-id=scale-cpm]')).to_be_visible()
            expect(page.locator('.flow-node[data-id=analysis-code]')).to_have_count(1)
            expect(page.locator('.layer-membership-path[data-source=analysis-code][data-target=scale-cpm]')).to_have_count(1)
            expected_reassignment = deepcopy(base)
            task(expected_reassignment, 'scale-cpm')['operation_id'] = 'analysis-code'
            check(snapshot(page) == expected_reassignment and page.locator('#inspector').is_visible(),
                  'reassigning selected processing work follows its operation across overview contexts')
            page.locator('#layers-view [data-action=undo]').click()
            expect(page.locator('[data-layer-field=operation_id]')).to_have_value('normalization')
            expect(page.locator('.flow-node[data-id=scale-cpm]')).to_be_visible()
            expect(page.locator('.layer-membership-path[data-source=normalization][data-target=scale-cpm]')).to_have_count(1)
            check(snapshot(page) == base,
                  'undoing processing reassignment restores its membership, canvas scope and inspector')
            page.locator('#layers-view [data-action=redo]').click()
            expect(page.locator('[data-layer-field=operation_id]')).to_have_value('analysis-code')
            expect(page.locator('.flow-node[data-id=scale-cpm]')).to_be_visible()
            expect(page.locator('.flow-node[data-id=analysis-code]')).to_have_count(1)
            check(snapshot(page) == expected_reassignment,
                  'redoing processing reassignment retains selected processing details in the new scope')
            page.locator('#layers-view [data-action=undo]').click()

            choose_overview(page, 'evidence')
            check(page.locator('.operation-card strong').all_text_contents() == [
                'Review literature', 'Download dataset'],
                'overview selection exposes its literature and download operations')
            choose_operation(page, 'literature')
            expect(page.locator('#methods-panel')).to_contain_text('Illustrative literature search')
            choose_operation(page, 'download')
            expect(page.locator('#methods-panel')).to_contain_text('DEMO-RNA-001')
            check(snapshot(page) == base,
                  'browsing non-processing operations preserves all project data')

            choose_overview(page, 'preparation')
            check(page.locator('.operation-card').count() == 4,
                  'data preparation exposes four operations with their own details')
            page.locator('[data-layer-field=layer]').select_option('operation')
            expect(page.locator('[data-layer-field=layer]')).to_have_value('overview')
            expect(page.locator('.toast.error').last).to_contain_text('Invalid overview association')
            page.locator('[data-action=close-inspector]').click()
            check(snapshot(page) == base,
                  'reclassifying a referenced overview is rejected with its selector and operation links intact')
            choose_processing(page, 'scale-cpm')
            page.locator('#plan-tab').click()
            candidates = page.locator('#add-dependency option').evaluate_all('options => options.map(option => option.value)')
            check('scale-cpm' not in candidates and 'log-transform' not in candidates,
                  'dependency controls exclude self-links and downstream processing steps that would create cycles')
            page.locator('[data-action=close-inspector]').click()
            edge = page.locator('.layer-dependency-hit[data-source=scale-cpm][data-target=log-transform]')
            for key in ['Enter', 'Space']:
                edge.focus()
                page.keyboard.press(key)
                expect(page.locator('#connection-form')).to_be_visible()
                expect(page.locator('#connection-source')).to_have_value('scale-cpm')
                expect(page.locator('#connection-target')).to_have_value('log-transform')
                page.locator('[data-action=close-inspector]').click()
            check(snapshot(page) == base,
                  'Enter and Space open processing dependency details without changing data')
            edge.focus()
            page.keyboard.press('Enter')
            page.locator('#connection-target').select_option('scale-cpm')
            page.locator('#connection-form button[type=submit]').click()
            expect(page.locator('#connection-error')).not_to_have_text('')
            check(snapshot(page) == base,
                  'submitting a self-dependency is rejected without changing the original processing connection')
            page.locator('[data-action=close-inspector]').click()
            initial_camera = camera(page)
            page.locator('[data-action=layer-zoom-in]').click()
            check(camera(page) != initial_camera, 'zoom controls change the canvas camera')
            zoomed_camera = camera(page)
            pan_canvas(page)
            check(camera(page) != zoomed_camera, 'dragging empty canvas space pans the workflow')
            page.locator('[data-action=layer-fit]').click()
            check(snapshot(page) == base,
                  'zooming, panning, fitting and inspecting dependency choices preserve project data')
            choose_operation(page, 'normalization')
            expect(page.locator('.record-entry')).to_have_count(2)
            expect(page.locator('#methods-panel')).to_contain_text('zero counts now map to 0')
            expect(page.locator('.record-entry[data-id=normalization-v2]')).to_contain_text('Selected result')
            check(page.locator('.record-history-heading').inner_text().split()[-1] == '2',
                  'normalization exposes both run records and the recorded data changes')
            page.screenshot(path=str(OUT / 'layers-overview.png'), full_page=True)

            choose_overview(page, 'evidence')
            keyboard_steps = [
                ('layer-overview', 'preparation'),
                ('layer-operation', 'normalization'),
                ('layer-record-select', 'normalization-v1'),
            ]
            for action, item_id in keyboard_steps:
                control = page.locator(f'[data-action="{action}"][data-id="{item_id}"]')
                control.focus()
                page.keyboard.press('Enter')
                expect(control).to_have_attribute('aria-pressed', 'true')
                expect(control).to_be_focused()
                page.keyboard.press('Tab')
                expect(control).not_to_be_focused()
                check(page.locator(':focus').evaluate(
                    'element => element.matches("button,a,input,select,textarea,[tabindex]")'),
                    f'Tab advances from the selected {action} control')
            check(snapshot(page) == base,
                  'keyboard selection retains focus after each layer refresh and Tab advances without data changes')

            choose_record(page, 'normalization-v1')
            expect(page.locator('#methods-panel')).to_contain_text('zero counts map to -1')
            expect(page.locator('#save-state')).to_have_text('In this tab')
            check(snapshot(page) == base,
                  'viewing an earlier record does not change the selected result or dirty the project')

            page.locator('[data-action=layer-use-record]').click()
            selected = snapshot(page)
            expected = deepcopy(base)
            task(expected, 'normalization')['selected_record_id'] = 'normalization-v1'
            check(selected == expected,
                  'selecting a result changes only the operation selected_record_id')
            expect(page.locator('#save-state')).to_have_text('Unsaved changes')
            page.locator('#layers-view [data-action=undo]').click()
            check(snapshot(page) == base,
                  'one undo restores the previously selected result and every prior record')

            page.locator('[data-action=layer-record]').click()
            form = page.locator('#record-work-form')
            expect(page.locator('#record-work-dialog')).to_be_visible()
            form.locator('[name=method]').fill('Browser-test illustration: inspect an alternative transform.')
            form.locator('[name=status]').select_option('partial')
            form.locator('[name=parameters]').fill('illustrative_option: 3')
            recorded_rationale = 'Illustrative historical reason: compare the documented alternative.'
            form.locator('[name=rationale]').fill(recorded_rationale)
            form.locator('[name=inputs]').fill('data/processed/filtered-counts.tsv\nnotes/test-input.md')
            form.locator('[name=outputs]').fill('reports/test-transform-review.md')
            form.locator('[name=changes]').fill('Illustrative review only; no real computation was performed.')
            form.locator('button[type=submit]').click()
            expect(page.locator('#record-work-dialog')).not_to_be_visible()
            expect(page.locator('.record-entry')).to_have_count(3)
            recorded = snapshot(page)
            original_operation = task(base, 'normalization')
            recorded_operation = task(recorded, 'normalization')
            new_record = recorded_operation['records'][-1]
            check(recorded_operation['records'][:-1] == original_operation['records']
                  and new_record['id'] not in {entry['id'] for entry in original_operation['records']}
                  and new_record['status'] == 'partial'
                  and new_record['inputs'] == ['data/processed/filtered-counts.tsv', 'notes/test-input.md']
                  and new_record['outputs'] == ['reports/test-transform-review.md']
                  and bool(new_record['recorded_at']),
                  'recording work appends a separate timestamped record and preserves earlier history')
            expected = deepcopy(base)
            task(expected, 'normalization')['records'].append(new_record)
            check(recorded == expected
                  and recorded_operation['status'] == 'in_progress'
                  and recorded_operation['selected_record_id'] == 'normalization-v2',
                  'recording partial work leaves task progress and the selected result unchanged')

            page.locator('#plan-tab').click()
            expect(page.locator('#inspector')).to_be_visible()
            planned_method = 'Illustrative revised plan: review the transform before accepting it.'
            planned_rationale = 'Illustrative revised reason: revisit the method after new evidence.'
            page.locator('[data-field=method]').fill(planned_method)
            page.locator('[data-field=rationale]').fill(planned_rationale)
            page.locator('#resources-tab').click()
            page.locator('[data-field=inputs]').fill('data/processed/filtered-counts.tsv\nnotes/review-plan.md')
            edited = snapshot(page)
            expected = deepcopy(recorded)
            task(expected, 'normalization')['method'] = planned_method
            task(expected, 'normalization')['rationale'] = planned_rationale
            task(expected, 'normalization')['inputs'] = [
                'data/processed/filtered-counts.tsv', 'notes/review-plan.md']
            check(edited == expected,
                  'editing the operation plan and input references preserves historical run records')
            page.locator('#methods-tab').click()
            choose_record(page, new_record['id'])
            expect(page.locator('#methods-panel')).to_contain_text(recorded_rationale)
            expect(page.locator('#methods-panel')).not_to_contain_text(planned_rationale)
            check(task(edited, 'normalization')['records'] == recorded_operation['records']
                  and task(edited, 'normalization')['records'][-1]['rationale'] == recorded_rationale,
                  'editing the planned rationale preserves each historical record and its displayed rationale')
            page.locator('#plan-tab').click()
            expect(page.locator('[data-field=method]')).to_have_value(planned_method)
            page.locator('#resources-tab').click()
            expect(page.locator('[data-field=inputs]')).to_have_value(
                'data/processed/filtered-counts.tsv\nnotes/review-plan.md')
            page.locator('[data-action=close-inspector]').click()

            before_processing = edited
            page.locator('[data-action=layer-add-processing]').click()
            expect(page.locator('[data-layer-field=layer]')).to_have_value('processing')
            expect(page.locator('[data-layer-field=operation_id]')).to_have_value('normalization')
            page.locator('[data-field=title]').fill('Inspect transformed values')
            page.locator('[data-field=method]').fill('Illustrative planned check of transformed values.')
            page.locator('[data-field=parameters]').fill('illustrative_check: range')
            page.locator('#add-dependency').select_option('log-transform')
            page.locator('#resources-tab').click()
            page.locator('[data-field=inputs]').fill('data/processed/log-cpm-v2.tsv')
            page.locator('[data-field=outputs]').fill('reports/value-checks.md')
            edited = snapshot(page)
            new_processing = next(item for item in edited['tasks']
                                  if item['id'] not in {previous['id'] for previous in before_processing['tasks']})
            check(new_processing['layer'] == 'processing'
                  and new_processing['operation_id'] == 'normalization'
                  and new_processing['depends_on'] == ['log-transform']
                  and new_processing['method'] == 'Illustrative planned check of transformed values.'
                  and new_processing['inputs'] == ['data/processed/log-cpm-v2.tsv']
                  and not new_processing.get('records'),
                  'adding and editing a processing step records membership, explicit order and its planned method')
            expect(page.locator(f'.layer-dependency-path[data-source=log-transform][data-target="{new_processing["id"]}"]')).to_have_count(1)
            expect(page.locator(f'.layer-membership-path[data-source=normalization][data-target="{new_processing["id"]}"]')).to_have_count(1)
            check(task(edited, 'normalization')['records'] == task(before_processing, 'normalization')['records'],
                  'a sequential processing step does not alter its parent operation run history')
            page.locator('[data-action=close-inspector]').click()

            yaml_document = parse_project(downloaded(page, 'export-yaml'))
            check(yaml_document == edited,
                  'YAML export preserves processing nodes, memberships, selected results and complete record history')
            for button_id, view_id in [('overview-button', 'canvas'), ('list-button', 'list-view'),
                                       ('layers-button', 'layers-view')]:
                page.locator(f'#{button_id}').click()
                expect(page.locator(f'#{view_id}')).to_be_visible()
            check(snapshot(page) == edited,
                  'switching Graph, Step list and Layers changes presentation without changing data')

            saved_path = Path(temporary) / 'saved-three-layers.html'
            saved_path.write_text(downloaded(page, 'save'), encoding='utf-8')
            expect(page.locator('#save-state')).to_have_text('Copy downloaded')
            reopened = opened(browser, saved_path)
            check(snapshot(reopened) == edited,
                  'Save copy reopens with operation and processing edits, ideas, selected result and all records intact')
            choose_overview(reopened, 'preparation')
            choose_processing(reopened, new_processing['id'])
            expect(reopened.locator('#methods-panel')).to_contain_text('Illustrative planned check')
            choose_operation(reopened, 'normalization')
            expect(reopened.locator('.record-entry')).to_have_count(3)
            reopened.close()
            page.close()

            for width, height in [(390, 844), (700, 900), (1024, 768)]:
                page = opened(browser, preview, width=width, height=height)
                if width <= 700:
                    mobile_base = snapshot(page)
                    effective_title_size = page.locator('.flow-node[data-id=normalization] strong').evaluate('''title =>
                        parseFloat(getComputedStyle(title).fontSize) * new DOMMatrix(
                            getComputedStyle(document.querySelector('#layer-world')).transform).a''')
                    check(effective_title_size >= 10
                          and nodes_inside_canvas(page, ['normalization']),
                          f'the phone opens with its current operation centered at readable scale at {width}px')
                    page.locator('[data-action=layer-fit]').click()
                    fit_camera = camera(page)
                    check(nodes_inside_canvas(page),
                          f'explicit Fit reveals every visible workflow node at {width}px')
                    page.locator('#ideas-button').click()
                    page.locator('[data-action=ideas-close]').click()
                    check(camera(page) == fit_camera and nodes_inside_canvas(page),
                          f'opening and closing Ideas preserves the explicit canvas Fit at {width}px')
                    page.locator('[data-action=layer-zoom-in]').click()
                    page.locator('#layer-canvas').focus()
                    page.keyboard.press('f')
                    check(camera(page) == fit_camera and snapshot(page) == mobile_base,
                          f'keyboard Fit restores the whole view without changing project data at {width}px')
                choose_processing(page, 'log-transform')
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                      f'the connected canvas and processing details fit without document overflow at {width}px')
                page.locator('[data-action=layer-record]').click()
                expect(page.locator('#record-work-dialog')).to_be_visible()
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                      f'the processing work-record form fits without document overflow at {width}px')
                page.locator('#record-work-dialog [data-action=close-dialog]').last.click()
                page.close()

            check(not ERRORS, 'layer interactions produce no uncaught JavaScript errors')
            browser.close()
    (OUT / 'layers-checks.json').write_text(json.dumps(
        {'count': len(CHECKS), 'checks': CHECKS, 'errors': ERRORS}, indent=2), encoding='utf-8')
    print('ALL', len(CHECKS), 'CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run()
