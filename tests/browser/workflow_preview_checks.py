#!/usr/bin/env python3
"""Saved HTML remains offline and read-only across Graph, Layers and Ideas."""
from copy import deepcopy
from datetime import datetime
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
from tempfile import TemporaryDirectory
import threading
import time
import xml.etree.ElementTree as ET

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from server import ProjectStore, make_handler, parse_project
from scripts.build_preview import build

OUT = ROOT / 'test-results'
CHECKS = []
LAST_DOWNLOAD = 0.0
OVERVIEWS = {'question', 'evidence', 'preparation', 'analysis', 'communication'}


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    CHECKS.append(label)
    print('PASS', label, flush=True)


def close_details(page):
    if page.locator('#inspector').is_visible():
        page.locator('[data-action=close-inspector]').click()


def overview(page):
    close_details(page)
    page.locator('#overview-button').click()
    expect(page.locator('#canvas')).to_be_visible()


def select(page, task_id, layer=False):
    selector = '.flow-node' if layer else '.task-node'
    node = page.locator(f'{selector}[data-id="{task_id}"]')
    node.focus()
    page.keyboard.press('Enter')
    expect(page.locator('#inspector')).to_be_visible()


def save(page, warning=False):
    with page.expect_response(lambda response: response.request.method == 'PUT'
                              and response.url.endswith('/api/project')) as response:
        page.locator('#save-button').click()
    check(response.value.status == 200, 'browser Save succeeds over authenticated HTTP')
    expect(page.locator('#save-state')).to_have_text(
        'Saved · preview unavailable' if warning else 'Saved')
    return response.value.json(), response.value.request.post_data_json


def download_gap(page):
    global LAST_DOWNLOAD
    pause = 1 - (time.monotonic() - LAST_DOWNLOAD)
    if pause > 0:
        page.wait_for_timeout(pause * 1000)
    LAST_DOWNLOAD = time.monotonic()


def snapshot(page):
    download_gap(page)
    page.locator('#more-menu summary').click()
    with page.expect_download() as download:
        page.locator('#more-menu [data-action=export-json]').click()
    return json.loads(Path(download.value.path()).read_text())


def geometry(page, layer=False):
    return page.locator('.flow-node' if layer else '.task-node').evaluate_all(
        'nodes => nodes.map(node => [node.dataset.id, node.style.left, node.style.top])')


def drag(page, selector, dx=75, dy=35):
    box = page.locator(selector).bounding_box()
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=8)
    page.mouse.up()


def pan(page, canvas_selector):
    box = page.locator(canvas_selector).bounding_box()
    x, y = box['x'] + 10, box['y'] + 10
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 55, y + 30, steps=8)
    page.mouse.up()


def no_editor_controls(page, selectors, label):
    check(not any(page.locator(selector).count() for selector in selectors), label)


def check_layers_ideas_viewer(page, document):
    page.locator('#layers-button').click()
    expect(page.locator('#layers-view')).to_be_visible()
    expect(page.locator('.flow-node')).to_have_count(12)
    select(page, 'normalization', layer=True)
    expect(page.locator('#methods-panel')).to_be_visible()
    expect(page.locator('.record-entry')).to_have_count(2)
    page.locator('.record-entry').last.click()
    expect(page.locator('.record-entry').last).to_have_attribute('aria-pressed', 'true')
    no_editor_controls(page, ['#inspector input', '#inspector textarea', '#inspector select',
                              '[data-action=layer-record]:visible', '[data-action=layer-use-record]:visible',
                              '[data-layer-coordinate]', '.layer-position-editor'],
                       'read-only Methods retains browsable run history without editing, recording or result-selection controls')
    page.locator('#plan-tab').click()
    operation = next(task for task in document['tasks'] if task['id'] == 'normalization')
    for field in ('method', 'parameters', 'rationale'):
        expect(page.locator(f'[data-view-field={field}]')).to_have_text(operation[field])
    expect(page.locator('[data-view-field=layer]')).to_contain_text('Operation')
    expect(page.locator('[data-view-field=overview_id]')).to_have_text('Prepare data')
    no_editor_controls(page, ['#inspector input', '#inspector textarea', '#inspector select'],
                       'read-only Plan exposes layer, membership, planned method, parameters and rationale as text')
    close_details(page)
    no_editor_controls(page, ['[data-action=layer-add-overview]:visible', '[data-action=layer-add-operation]:visible',
                              '[data-action=layer-add-processing]:visible', '[data-action=layer-arrange]:visible',
                              '#layers-view [data-action=undo]:visible', '#layers-view [data-action=redo]:visible'],
                       'saved Layers exposes no Add, Arrange or editing-history controls')
    before = geometry(page, layer=True)
    page.locator('[data-action=layer-fit]').click()
    zoom = page.locator('#layer-zoom-level').inner_text()
    page.locator('[data-action=layer-zoom-in]').click()
    check(page.locator('#layer-zoom-level').inner_text() != zoom,
          'saved Layers keeps zoom and Fit available')
    camera = page.locator('#layer-world').get_attribute('style')
    pan(page, '#layer-canvas')
    check(page.locator('#layer-world').get_attribute('style') != camera,
          'saved Layers supports background panning')
    page.locator('[data-action=layer-fit]').click()
    drag(page, '.flow-node[data-id=normalization]')
    node = page.locator('.flow-node[data-id=normalization]')
    for key in ('ArrowRight', 'Shift+ArrowDown', 'Delete', 'Backspace', 'n', 'Control+z'):
        node.focus()
        page.keyboard.press(key)
    expect(page.locator('#delete-step-dialog')).to_be_hidden()
    check(geometry(page, layer=True) == before,
          'viewer card dragging and keyboard nudging cannot modify saved Layers positions')
    select(page, 'qc', layer=True)
    page.locator('#resources-tab').click()
    expect(page.locator('[data-view-field=notes]')).to_have_text(
        next(task['notes'] for task in document['tasks'] if task['id'] == 'qc'))
    check(not page.evaluate('Boolean(window.__snapshotInjection)'),
          'script-like notes remain inert while their full text is readable')
    close_details(page)
    page.locator('#ideas-button').click()
    expect(page.locator('#ideas-panel')).to_be_visible()
    expect(page.locator('[data-action=idea-toggle]')).to_have_count(3)
    expect(page.locator('.idea-details:visible')).to_have_count(0)
    first = page.locator('[data-action=idea-toggle][data-id=batch-question]')
    first.focus()
    page.keyboard.press('Enter')
    expect(first).to_have_attribute('aria-expanded', 'true')
    expect(page.locator('.idea-row[data-idea-id=batch-question] .idea-notes')).to_be_visible()
    page.locator('[data-action=idea-toggle][data-id=external-cohort]').click()
    expect(first).to_have_attribute('aria-expanded', 'false')
    expect(page.locator('.idea-details:visible')).to_have_count(1)
    no_editor_controls(page, ['[data-action=idea-add]:visible', '[data-action=idea-edit]:visible',
                              '[data-action=idea-delete]:visible'],
                       'saved Ideas retains compact disclosure rows without add, edit or delete actions')
    page.locator('#ideas-filter').select_option('all')
    page.locator('[data-action=idea-toggle][data-id=batch-question]').click()
    page.locator('[data-action=idea-link][data-id=batch-question]').click()
    expect(page.locator('#ideas-panel')).to_be_hidden()
    expect(page.locator('#methods-panel')).to_be_visible()
    check(snapshot(page) == document,
          'Layers browsing, history inspection and Ideas links leave every task, record, idea and coordinate unchanged')


def check_viewer(browser, path, document, layout, filename, thorough=False):
    context = browser.new_context(viewport={'width': 1600, 'height': 1000},
                                  reduced_motion='reduce', offline=True, accept_downloads=True)
    page = context.new_page()
    page.set_default_timeout(8000)
    errors, requests, downloads = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: requests.append(request.url))
    page.on('download', lambda download: downloads.append(download.suggested_filename))
    original = path.read_bytes()
    page.goto(path.as_uri(), wait_until='load')
    expect(page.locator('body')).to_have_class(re.compile(r'\bread-only\b'))
    expect(page.locator('#save-state')).to_contain_text('Read-only')
    expect(page.locator('#save-state')).to_contain_text('Last saved')
    marker = page.evaluate('window.RESEARCH_FLOW_VIEWER')
    check(marker['layout_mode'] == layout
          and datetime.fromisoformat(marker['saved_at'].replace('Z', '+00:00')).tzinfo is not None,
          'saved HTML records its compatibility layout and an explicit timestamp')
    expect(page.locator('#save-state time')).to_have_attribute('datetime', marker['saved_at'])
    check(snapshot(page) == document,
          'offline viewer contains the complete document including records, ideas and unknown metadata')
    check(page.locator('#project-title').input_value() == document['project']['name']
          and page.locator('#project-title').evaluate('element => element.readOnly'),
          'saved UTF-8 project title is selectable and read-only')
    for selector in ('#save-button', '#add-button', '#undo-button', '#redo-button',
                     '#arrange-button', '[data-action=export-svg]'):
        expect(page.locator(selector)).to_be_hidden()
    overview(page)
    expect(page.locator('.task-node')).to_have_count(5)
    check(set(page.locator('.task-node').evaluate_all('nodes=>nodes.map(n=>n.dataset.id)')) == OVERVIEWS
          and page.locator('.stage-column h2').all_text_contents() == ['Step 1', 'Step 2', 'Step 3', 'Step 4', 'Step 5']
          and page.locator('#layout-freeform,#layout-stages').count() == 0,
          'offline Graph shows only numbered overview steps regardless of legacy layout metadata')
    check(page.locator('.port,.node-delete,.node-add-child').count() == 0,
          'viewer Graph cards expose no connection, delete or add controls')
    saved_geometry = geometry(page)
    select(page, 'preparation')
    check(page.locator('#inspector input,#inspector textarea,#inspector select').count() == 0,
          'saved overview details show readable text instead of editable forms')
    page.screenshot(path=str(OUT / filename))
    overview(page)

    if thorough:
        zoom = page.locator('#zoom-level').inner_text()
        page.locator('[data-action=zoom-in]').click()
        check(page.locator('#zoom-level').inner_text() != zoom, 'offline Graph retains zoom controls')
        camera = page.locator('#world').get_attribute('style')
        pan(page, '#canvas')
        check(page.locator('#world').get_attribute('style') != camera, 'offline Graph retains background panning')
        page.locator('#fit-button').click()
        node = page.locator('.task-node[data-id=question]')
        drag(page, '.task-node[data-id=question]')
        for key in ('n', 'Delete', 'Backspace', 'ArrowRight', 'Shift+ArrowDown', 'Control+z', 'Meta+z'):
            node.focus()
            page.keyboard.press(key)
        expect(page.locator('#delete-step-dialog')).to_be_hidden()
        check(geometry(page) == saved_geometry, 'Graph mutation gestures cannot change ordered overview geometry')
        node.dblclick()
        check(page.locator('.node-title-input').count() == 0, 'double-clicking a viewer card cannot rename it')
        overview(page)
        page.locator('#canvas').dblclick(position={'x': 12, 'y': 30})
        expect(page.locator('.task-node')).to_have_count(5)
        page.locator('#list-button').click()
        expect(page.locator('.table-task')).to_have_count(len(document['tasks']))
        check(page.locator('#list-view select,#list-view input').count() == 0,
              'saved Step list includes all detailed tasks with no editing controls')
        check_layers_ideas_viewer(page, document)
        overview(page)
        before_downloads = len(downloads)
        page.locator('#canvas').focus()
        page.keyboard.press('Control+s')
        page.keyboard.press('Meta+s')
        for selector in ('#save-button', '#add-button', '#undo-button', '#redo-button', '#arrange-button'):
            page.locator(selector).dispatch_event('click')
        page.locator('#project-title').evaluate('''element => {
            element.value = 'Attempted edit';
            element.dispatchEvent(new Event('input', {bubbles:true}));
        }''')
        overview(page)
        check(page.locator('#project-title').input_value() == document['project']['name'],
              'a synthetic title input cannot change a read-only project')
        check(len(downloads) == before_downloads,
              'Save shortcuts and hidden editor controls cannot download an editable copy')
        page.locator('[data-edge="question|evidence"]').focus()
        page.keyboard.press('Enter')
        expect(page.locator('#inspector')).to_be_visible()
        check(page.locator('#connection-form').count() == 0,
              'saved dependency details are viewable without rewiring controls')
        page.keyboard.press('Delete')
        check(snapshot(page) == document, 'all viewer gestures and synthetic input preserve the saved model')
        overview(page)
        check(geometry(page) == saved_geometry, 'view switching leaves Graph organized by numbered steps')
        for width in (820, 390, 320):
            page.set_viewport_size({'width': width, 'height': 844})
            page.reload(wait_until='load')
            expect(page.locator('#save-state')).to_be_visible()
            expect(page.locator('#save-state time')).to_be_visible()
            box = page.locator('#save-state').bounding_box()
            check(0 <= box['x'] and box['x'] + box['width'] <= width + 1
                  and page.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                  f'read-only status and saved time fit the {width}px viewport')
            page.locator('#ideas-button').click()
            page.locator('[data-action=idea-toggle][data-id=normalization-decision]').click()
            check(page.locator('.idea-details:visible').count() == 1
                  and page.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                  f'read-only Ideas details remain accessible without overflow at {width}px')
            if width == 390:
                page.screenshot(path=str(OUT / 'workflow-preview-mobile.png'))
            page.locator('[data-action=ideas-close]').click()
            overview(page)
            expect(page.locator('.task-node')).to_have_count(5)
    check(path.read_bytes() == original, 'viewing HTML never rewrites the saved snapshot')
    check(not errors, 'offline viewer has no uncaught JavaScript errors')
    check(all(url == path.as_uri() or url.startswith(('data:', 'blob:')) for url in requests),
          'HTML opens offline without API, script, style or other file requests')
    context.close()
    return saved_geometry


def check_editable_copy(browser, source, directory):
    path = build(source, directory / 'editable-copy.html')
    context = browser.new_context(offline=True, viewport={'width': 1600, 'height': 1000},
                                  reduced_motion='reduce', accept_downloads=True)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(path.as_uri(), wait_until='load')
    expect(page.locator('body')).not_to_have_class(re.compile(r'\bread-only\b'))
    expect(page.locator('#save-button')).to_be_enabled()
    select(page, 'normalization', layer=True)
    page.locator('#plan-tab').click()
    page.locator('[data-field=method]').fill('Fictional editable-copy integration check.')
    page.locator('[data-field=method]').press('Tab')
    page.locator('#methods-tab').click()
    page.locator('[data-action=layer-record]').click()
    page.locator('#record-work-form [name=method]').fill('Fictional manually recorded check.')
    page.locator('#record-work-form [name=status]').select_option('recorded')
    page.locator('#record-work-form button[type=submit]').click()
    expect(page.locator('.record-entry')).to_have_count(3)
    close_details(page)
    node = page.locator('.flow-node[data-id=normalization]')
    before = geometry(page, layer=True)
    node.focus()
    page.keyboard.press('Shift+ArrowRight')
    check(geometry(page, layer=True) != before,
          'editable HTML retains free Layers positioning and manual method/record edits')
    page.locator('#ideas-button').click()
    page.locator('[data-action=idea-toggle][data-id=batch-question]').click()
    page.locator('[data-action=idea-edit][data-id=batch-question]').click()
    page.locator('#idea-form [name=notes]').fill('Fictional editable-copy question note.')
    page.locator('#idea-form button[type=submit]').click()
    edited = snapshot(page)
    task = next(task for task in edited['tasks'] if task['id'] == 'normalization')
    check(task['method'] == 'Fictional editable-copy integration check.' and len(task['records']) == 3
          and next(item for item in edited['ideas'] if item['id'] == 'batch-question')['notes']
              == 'Fictional editable-copy question note.',
          'editable previews can change Ideas while retaining operation history')
    download_gap(page)
    with page.expect_download() as download:
        page.locator('#save-button').click()
    saved = directory / 'saved-editable-copy.html'
    saved.write_text(Path(download.value.path()).read_text(), encoding='utf-8')
    reopened = context.new_page()
    reopened.goto(saved.as_uri(), wait_until='load')
    check(snapshot(reopened) == edited and not reopened.evaluate('Boolean(window.RESEARCH_FLOW_VIEWER)'),
          'Save copy remains editable and preserves Layers positions, ideas and appended records')
    check(not errors, 'editable portable preview has no uncaught JavaScript errors')
    context.close()


def check_empty_viewer(browser, directory):
    path = directory / 'empty.yaml'
    path.write_text('schema_version: 1\nproject:\n  name: Empty workflow\ntasks: []\n', encoding='utf-8')
    store = ProjectStore(path)
    source = store.read()
    result = store.save(source['document'], source['revision'])
    check(not result['preview_warning'], 'saving an empty workflow generates HTML')
    context = browser.new_context(offline=True, viewport={'width': 390, 'height': 844})
    page = context.new_page()
    page.goto(path.with_suffix('.html').as_uri(), wait_until='load')
    expect(page.locator('#empty-state')).to_be_visible()
    expect(page.locator('#empty-state')).to_contain_text('No steps saved yet')
    expect(page.locator('#empty-state [data-action=add]')).to_be_hidden()
    expect(page.locator('#minimap-wrap')).to_be_hidden()
    page.locator('#canvas').focus()
    page.keyboard.press('n')
    page.locator('#canvas').dblclick(position={'x': 12, 'y': 30})
    check(snapshot(page) == source['document'], 'empty offline viewer cannot insert steps')
    page.screenshot(path=str(OUT / 'workflow-preview-empty.png'))
    context.close()


def run():
    OUT.mkdir(exist_ok=True)
    fixture = parse_project((ROOT / 'examples/three-layers.yaml').read_text())
    fixture['project']['name'] = 'Research α & validation'
    fixture['project']['owner'] = {'keep': 'unknown metadata'}
    fixture['tasks'][0]['title'] = 'Define α & β'
    task = next(task for task in fixture['tasks'] if task['id'] == 'qc')
    task['title'] = 'QC <replicates>'
    task['notes'] = '</script><script>window.__snapshotInjection = true</script><img src="missing" onerror="window.__snapshotInjection = true">'
    task['evidence'] = {'keep': ['PMID:example']}
    fixture['layout']['note'] = 'Preserve stored positions'
    fixture['layout']['positions'] = {task['id']: {'x': index * 17, 'y': index * -13}
                                      for index, task in enumerate(fixture['tasks'])}
    fixture['layout']['layer_positions'] = {'normalization': {'x': 508, 'y': -104},
                                           'scale-cpm': {'x': 736, 'y': -164},
                                           'log-transform': {'x': 952, 'y': -164}}
    with TemporaryDirectory() as temp:
        directory = Path(temp).resolve()
        path = directory / 'workflow.yaml'
        path.write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        sidecar = path.with_suffix('.html')
        original = path.read_bytes()
        token = secrets.token_urlsafe(24)
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(ProjectStore(path), auth_token=token))
        server = threading.Thread(target=httpd.serve_forever, daemon=True)
        server.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),
                    headless=True, args=['--no-sandbox'])
                page = browser.new_page(viewport={'width': 1600, 'height': 1000},
                                        reduced_motion='reduce', accept_downloads=True)
                page.set_default_timeout(8000)
                errors, requests = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: requests.append(request.url))
                page.goto(f'http://127.0.0.1:{httpd.server_port}/#token={token}', wait_until='networkidle')
                expect(page.locator('#save-state')).to_have_text('Saved')
                expect(page.locator('#layers-view')).to_be_visible()
                check(path.read_bytes() == original and not sidecar.exists(),
                      'opening and rendering a workflow leave disk untouched')
                check('#token=' not in page.url and token not in page.content(),
                      'private token is absent from visible URL and rendered content')
                overview(page)
                select(page, 'question')
                page.locator('[data-field=title]').fill('Define γ & δ')
                expected = deepcopy(fixture)
                expected['tasks'][0]['title'] = 'Define γ & δ'
                data, payload = save(page)
                check(payload['preview_layout'] == 'stages', 'browser Save requests the organized Graph layout')
                check(data['preview_file'] == str(sidecar) and not data.get('preview_warning'),
                      'Save reports its adjacent generated HTML preview')
                check(parse_project(path.read_text()) == expected, 'saving changes only the edited overview title')
                stage_html = sidecar.read_bytes()
                check(token.encode() not in stage_html and token.encode() not in path.read_bytes(),
                      'saved workflow and HTML contain no authentication token')
                check(not path.with_suffix('.svg').exists(), 'Save creates HTML without an automatic SVG sidecar')
                staged = check_viewer(browser, sidecar, expected, 'stages', 'workflow-preview-stages.png', thorough=True)
                expect(page.locator('#save-button')).to_be_disabled()
                legacy = build(path, directory / 'legacy-layout.html', read_only=True, layout_mode='freeform')
                legacy_geometry = check_viewer(browser, legacy, expected, 'freeform', 'workflow-preview-legacy.png')
                check(staged == legacy_geometry, 'legacy Freeform metadata does not override numbered Graph organization')
                check_editable_copy(browser, path, directory)
                overview(page)
                page.locator('#project-title').fill('Research α & validation — revised')
                page.locator('#project-title').press('Enter')
                expected['project']['name'] = 'Research α & validation — revised'
                saved = path.read_bytes()
                page.locator('#more-menu summary').click()
                download_gap(page)
                with page.expect_response(lambda response: response.request.method == 'POST'
                                          and response.url.endswith('/api/export/svg')) as response:
                    with page.expect_download() as download:
                        page.locator('[data-action=export-svg]').click()
                svg = ET.fromstring(Path(download.value.path()).read_text())
                check(response.value.status == 200 and svg.tag == '{http://www.w3.org/2000/svg}svg'
                      and svg.get('data-layout') == 'stages'
                      and expected['project']['name'] in ' '.join(svg.itertext()),
                      'More exports the current unsaved workflow as an optional organized SVG')
                check(path.read_bytes() == saved and sidecar.read_bytes() == stage_html,
                      'optional SVG export does not save workflow changes or refresh HTML')
                data, payload = save(page)
                check(payload['preview_layout'] == 'stages' and parse_project(path.read_text()) == expected,
                      'subsequent saves preserve records, ideas and both coordinate maps')
                custom_html = b'<!doctype html><title>My custom report</title><p>Keep this report.</p>'
                sidecar.write_bytes(custom_html)
                page.locator('#project-title').fill('Saved with a preview collision')
                page.locator('#project-title').press('Enter')
                expected['project']['name'] = 'Saved with a preview collision'
                data, _ = save(page, warning=True)
                check(bool(data.get('preview_warning')) and not data.get('preview_file'),
                      'preview collision returns a warning without claiming a preview')
                check(parse_project(path.read_text()) == expected and sidecar.read_bytes() == custom_html,
                      'preview collision preserves custom HTML while saving workflow changes')
                expect(page.locator('#save-button')).to_be_enabled()
                page.locator('#layers-button').click()
                overview(page)
                expect(page.locator('#save-state')).to_have_text('Saved · preview unavailable')
                page.screenshot(path=str(OUT / 'workflow-preview-warning.png'))
                check(page.locator('#save-state .dirty').count() == 0,
                      'preview warning survives rendering while workflow edits remain saved')
                sidecar.unlink()
                data, payload = save(page)
                check(payload['preview_layout'] == 'stages' and not data.get('preview_warning')
                      and parse_project(path.read_text()) == expected,
                      'Save retries preview generation without changing the saved project')
                expect(page.locator('#save-button')).to_be_disabled()
                saved, preview = path.read_bytes(), sidecar.read_bytes()
                modified = (path.stat().st_mtime_ns, sidecar.stat().st_mtime_ns)
                page.reload(wait_until='networkidle')
                expect(page.locator('#save-state')).to_have_text('Saved')
                check(path.read_bytes() == saved and sidecar.read_bytes() == preview
                      and modified == (path.stat().st_mtime_ns, sidecar.stat().st_mtime_ns),
                      'reopening a saved workflow neither regenerates HTML nor rewrites YAML')
                check(not errors, 'HTML preview saves have no uncaught JavaScript errors')
                check(all(url.startswith(f'http://127.0.0.1:{httpd.server_port}/') for url in requests),
                      'browser Save uses no external runtime or asset requests')
                check_empty_viewer(browser, directory)
                browser.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            server.join(timeout=5)
    (OUT / 'workflow-preview-checks.json').write_text(json.dumps(CHECKS, indent=2))
    print(f'ALL {len(CHECKS)} WORKFLOW PREVIEW CHECKS PASSED', flush=True)


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        message = re.sub(r'#token=[A-Za-z0-9_-]+', '#token=[REDACTED]', str(error))
        print(f'Workflow preview verification failed: {message}', file=sys.stderr)
        sys.exit(1)
