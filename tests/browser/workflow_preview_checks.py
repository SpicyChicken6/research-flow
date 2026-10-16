#!/usr/bin/env python3
"""Real saves produce an offline, interactive, read-only HTML snapshot."""
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

OUT = ROOT / 'test-results'
CHECKS = []
LAST_DOWNLOAD = 0.0


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    CHECKS.append(label)
    print('PASS', label, flush=True)


def select(page, task_id):
    page.locator(f'.task-node[data-id="{task_id}"]').focus()
    page.keyboard.press('Enter')
    expect(page.locator('#inspector')).to_be_visible()


def overview(page):
    if page.locator('#inspector').is_visible():
        page.locator('[data-action="close-inspector"]').click()
    page.locator('#overview-button').click()


def save(page, warning=False):
    with page.expect_response(lambda response:
                              response.request.method == 'PUT'
                              and response.url.endswith('/api/project')) as response:
        page.locator('#save-button').click()
    check(response.value.status == 200, 'browser Save succeeds over authenticated HTTP')
    data = response.value.json()
    expect(page.locator('#save-state')).to_have_text(
        'Saved · preview unavailable' if warning else 'Saved')
    return data, response.value.request.post_data_json


def download_gap(page):
    global LAST_DOWNLOAD
    # Chromium throttles bursts of downloads from one page.
    pause = 1 - (time.monotonic() - LAST_DOWNLOAD)
    if pause > 0:
        page.wait_for_timeout(pause * 1000)
    LAST_DOWNLOAD = time.monotonic()


def snapshot(page):
    download_gap(page)
    page.locator('#more-menu summary').click()
    with page.expect_download() as download:
        page.locator('[data-action="export-json"]').click()
    return json.loads(Path(download.value.path()).read_text())


def geometry(page):
    return page.locator('.task-node').evaluate_all(
        'nodes => nodes.map(node => [node.dataset.id, node.style.left, node.style.top])')


def check_viewer(browser, path, document, layout, filename, thorough=False):
    # Network is unavailable even though the editable server may still be running.
    context = browser.new_context(viewport={'width': 1600, 'height': 1000},
                                  reduced_motion='reduce', offline=True,
                                  accept_downloads=True)
    page = context.new_page()
    page.set_default_timeout(8000)
    errors, requests, downloads = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: requests.append(request.url))
    page.on('download', lambda download: downloads.append(download.suggested_filename))
    original = path.read_bytes()
    page.goto(path.as_uri(), wait_until='load')
    expect(page.locator('.task-node')).to_have_count(len(document['tasks']))
    expect(page.locator('body')).to_have_class(re.compile(r'\bread-only\b'))
    expect(page.locator('#save-state')).to_contain_text('Read-only')
    expect(page.locator('#save-state')).to_contain_text('Last saved')
    marker = page.evaluate('window.RESEARCH_FLOW_VIEWER')
    check(marker['layout_mode'] == layout
          and datetime.fromisoformat(marker['saved_at'].replace('Z', '+00:00')).tzinfo is not None,
          'saved HTML records its layout and an explicit timestamp')
    expect(page.locator('#save-state time')).to_have_attribute('datetime', marker['saved_at'])
    expect(page.locator(f'#layout-{layout}')).to_have_attribute('aria-pressed', 'true')
    check(snapshot(page) == document,
          'offline viewer contains the entire saved document including unknown metadata')
    check(page.locator('#project-title').input_value() == document['project']['name'],
          'offline viewer renders the saved UTF-8 project title')
    check(page.locator('#project-title').evaluate('element => element.readOnly'),
          'saved project title is selectable but read-only')
    for selector in ('#save-button', '#add-button', '#undo-button', '#redo-button',
                     '#arrange-button', '[data-action="export-svg"]'):
        expect(page.locator(selector)).to_be_hidden()
    check(page.locator('.port, .node-delete, .node-add-child').count() == 0,
          'viewer cards expose no connection, delete or add controls')
    select(page, 'metadata')
    page.locator('#resources-tab').click()
    expect(page.locator('[data-view-field="notes"]')).to_have_text(
        next(task['notes'] for task in document['tasks'] if task['id'] == 'metadata'))
    check(page.locator('#inspector input, #inspector textarea, #inspector select').count() == 0,
          'saved task details show readable text instead of editable forms')
    check(not page.evaluate('Boolean(window.__snapshotInjection)'),
          'script-like task strings remain inert in the offline HTML')
    page.screenshot(path=str(OUT / filename))
    overview(page)
    saved_geometry = geometry(page)

    if thorough:
        select(page, 'preparation')
        page.locator('#focus-button').click()
        check(page.locator('.task-node:visible').count() < len(document['tasks']),
              'offline viewer can focus a branch')
        page.locator('[data-mini-task="sensitivity"]').click()
        expect(page.locator('.task-node[data-id="sensitivity"]')).to_be_visible()
        expect(page.locator('#focus-button')).to_have_attribute('aria-pressed', 'false')
        check(True, 'global minimap reveals a task outside the focused branch')
        overview(page)
        page.locator('.task-node[data-id="analysis"] .children-toggle').click()
        expect(page.locator('.task-node:visible')).to_have_count(3)
        page.locator('.task-node[data-id="analysis"] .children-toggle').click()
        expect(page.locator('.task-node:visible')).to_have_count(len(document['tasks']))
        check(True, 'offline viewer can collapse and expand child branches')
        old_zoom = page.locator('#zoom-level').inner_text()
        page.locator('[data-action="zoom-in"]').click()
        check(page.locator('#zoom-level').inner_text() != old_zoom,
              'offline viewer retains zoom controls')
        before_pan = page.locator('#world').get_attribute('style')
        # Background drag pans without modifying stored card coordinates.
        canvas = page.locator('#canvas').bounding_box()
        x, y = canvas['x'] + 12, canvas['y'] + 30
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 65, y + 35, steps=8)
        page.mouse.up()
        check(page.locator('#world').get_attribute('style') != before_pan,
              'offline viewer retains canvas panning')
        page.locator('#fit-button').click()
        other_layout = 'freeform' if layout == 'stages' else 'stages'
        page.locator(f'#layout-{other_layout}').click()
        check(geometry(page) != saved_geometry,
              'offline viewer switches between stages and stored freeform positions')
        page.locator('#list-button').click()
        expect(page.locator('#list-view')).to_be_visible()
        check(page.locator('#list-view select, #list-view input').count() == 0,
              'step list presents statuses without editing controls')
        overview(page)

        # Exercise the editor's usual mutation gestures against the actual viewer.
        select(page, 'question')
        node = page.locator('.task-node[data-id="question"]')
        for key in ('n', 'Delete', 'Backspace', 'ArrowRight', 'Shift+ArrowDown',
                    'Control+z', 'Control+Shift+z', 'Meta+z'):
            node.focus()
            page.keyboard.press(key)
        expect(page.locator('#delete-step-dialog')).to_be_hidden()
        overview(page)
        page.locator('#layout-freeform').click()
        position_before_drag = geometry(page)
        node = page.locator('.task-node[data-id="question"]')
        bounds = node.bounding_box()
        x, y = bounds['x'] + bounds['width'] / 2, bounds['y'] + bounds['height'] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 95, y + 50, steps=10)
        page.mouse.up()
        check(geometry(page) == position_before_drag,
              'dragging a viewer card cannot change its saved position')
        # Native double-click exercises both card rename and background insertion.
        node.dblclick()
        check(page.locator('.node-title-input').count() == 0,
              'double-clicking a viewer card cannot rename it')
        overview(page)
        page.locator('#canvas').dblclick(position={'x': 12, 'y': 30})
        expect(page.locator('.task-node')).to_have_count(len(document['tasks']))
        before_downloads = len(downloads)
        page.locator('#canvas').focus()
        page.keyboard.press('Control+s')
        page.keyboard.press('Meta+s')
        # Hidden controls are also guarded if an event reaches their handlers.
        for selector in ('#save-button', '#add-button', '#undo-button', '#redo-button', '#arrange-button'):
            page.locator(selector).dispatch_event('click')
        page.locator('#project-title').evaluate('''element => {
            element.value = "Attempted edit";
            element.dispatchEvent(new Event("input", {bubbles:true}));
        }''')
        page.locator('#overview-button').click()
        check(page.locator('#project-title').input_value() == document['project']['name'],
              'a synthetic title input does not change the read-only document')
        check(len(downloads) == before_downloads,
              'Save shortcuts and hidden editor buttons cannot download an editable copy')
        page.locator('[data-edge="question|analysis"]').focus()
        page.keyboard.press('Enter')
        expect(page.locator('#inspector')).to_be_visible()
        check(page.locator('#connection-form').count() == 0,
              'connection details are viewable without rewiring controls')
        page.keyboard.press('Delete')
        check(snapshot(page) == document,
              'view navigation, gestures, shortcuts and input events preserve the saved model')
        page.locator('#layout-stages').click()
        overview(page)
        check(geometry(page) == saved_geometry,
              'switching back restores stages without mutating stored freeform positions')
        for width in (820, 390, 320):
            page.set_viewport_size({'width': width, 'height': 844})
            page.reload(wait_until='load')
            expect(page.locator('.task-node')).to_have_count(len(document['tasks']))
            expect(page.locator('#save-state')).to_be_visible()
            expect(page.locator('#save-state time')).to_be_visible()
            box = page.locator('#save-state').bounding_box()
            check(0 <= box['x'] and box['x'] + box['width'] <= width + 1
                  and page.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                  f'read-only status and saved time fit the {width}px viewport')
            page.wait_for_function('''() => {
                const card = document.querySelector('.task-node').getBoundingClientRect();
                return card.left < innerWidth && card.right > 0 && card.top < innerHeight && card.bottom > 0;
            }''')
            if width == 390:
                page.screenshot(path=str(OUT / 'workflow-preview-mobile.png'))

    check(path.read_bytes() == original, 'viewing the HTML never rewrites the saved snapshot')
    check(not errors, 'offline viewer has no uncaught JavaScript errors')
    check(all(url == path.as_uri() or url.startswith(('data:', 'blob:')) for url in requests),
          'HTML opens offline without requests for APIs, scripts, styles or other files')
    context.close()
    return saved_geometry


def check_empty_viewer(browser, directory):
    path = directory / 'empty.yaml'
    path.write_text('schema_version: 1\nproject:\n  name: Empty workflow\ntasks: []\n',
                    encoding='utf-8')
    store = ProjectStore(path)
    source = store.read()
    result = store.save(source['document'], source['revision'])
    check(not result['preview_warning'], 'saving an empty workflow generates HTML')
    context = browser.new_context(offline=True, viewport={'width': 390, 'height': 844})
    page = context.new_page()
    page.goto(path.with_suffix('.html').as_uri(), wait_until='load')
    expect(page.locator('#empty-state')).to_be_visible()
    expect(page.locator('#empty-state')).to_contain_text('No steps saved yet')
    expect(page.locator('#empty-state [data-action="add"]')).to_be_hidden()
    expect(page.locator('#minimap-wrap')).to_be_hidden()
    expect(page.locator('#save-state')).to_contain_text('Read-only')
    page.locator('#canvas').focus()
    page.keyboard.press('n')
    page.locator('#canvas').dblclick(position={'x': 12, 'y': 30})
    expect(page.locator('.task-node')).to_have_count(0)
    check(snapshot(page) == source['document'],
          'empty offline viewer explains its state and cannot insert steps')
    page.screenshot(path=str(OUT / 'workflow-preview-empty.png'))
    context.close()


def run():
    OUT.mkdir(exist_ok=True)
    fixture = parse_project((ROOT / 'examples/research-project.yaml').read_text())
    fixture['project']['name'] = 'Research α & validation'
    fixture['project']['owner'] = {'keep': 'unknown metadata'}
    fixture['tasks'][0]['title'] = 'Define α & β'
    fixture['tasks'][5]['title'] = 'QC <replicates>'
    fixture['tasks'][5]['notes'] = '</script><script>window.__snapshotInjection = true</script><img src="missing" onerror="window.__snapshotInjection = true">'
    fixture['tasks'][5]['evidence'] = {'keep': ['PMID:example']}
    fixture['layout']['note'] = 'Preserve stored positions'

    with TemporaryDirectory() as temp:
        path = Path(temp).resolve() / 'workflow.yaml'
        path.write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        sidecar = path.with_suffix('.html')
        original = path.read_bytes()
        token = secrets.token_urlsafe(24)
        httpd = ThreadingHTTPServer(('127.0.0.1', 0),
                                    make_handler(ProjectStore(path), auth_token=token))
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
                page.goto(f'http://127.0.0.1:{httpd.server_port}/#token={token}',
                          wait_until='networkidle')
                expect(page.locator('#save-state')).to_have_text('Saved')
                expect(page.locator('.task-node')).to_have_count(len(fixture['tasks']))
                check(path.read_bytes() == original and not sidecar.exists(),
                      'opening and rendering a workflow leave disk untouched')
                check('#token=' not in page.url and token not in page.content(),
                      'private token is absent from visible URL and rendered content')

                page.locator('.task-node[data-id="analysis"] .children-toggle').click()
                expect(page.locator('.task-node:visible')).to_have_count(3)
                select(page, 'question')
                page.locator('#focus-button').click()
                check(page.locator('.task-node:visible').count() < len(fixture['tasks']),
                      'save starts from a genuinely collapsed and focused view')
                page.locator('[data-field="title"]').fill('Define γ & δ')
                expected = deepcopy(fixture)
                expected['tasks'][0]['title'] = 'Define γ & δ'
                data, payload = save(page)
                check(payload['preview_layout'] == 'stages',
                      'browser sends the selected Stages layout with Save')
                check(data['preview_file'] == str(sidecar) and not data.get('preview_warning'),
                      'Save reports the adjacent generated HTML preview')
                check(parse_project(path.read_text()) == expected,
                      'saving a focused view changes only the edited title')
                stage_html = sidecar.read_bytes()
                check(token.encode() not in stage_html and token.encode() not in path.read_bytes(),
                      'workflow and HTML contain no authentication token')
                check(not path.with_suffix('.svg').exists(),
                      'Save creates HTML without an automatic SVG sidecar')
                staged = check_viewer(browser, sidecar, expected, 'stages',
                                      'workflow-preview-stages.png', thorough=True)
                expect(page.locator('#save-button')).to_be_disabled()

                overview(page)
                page.locator('#layout-freeform').click()
                check(parse_project(path.read_text()) == expected
                      and sidecar.read_bytes() == stage_html,
                      'switching layout and returning to Overview do not write files')
                page.locator('#project-title').fill('Research α & validation — freeform')
                page.locator('#project-title').press('Enter')
                expected['project']['name'] = 'Research α & validation — freeform'
                saved = path.read_bytes()
                page.locator('#more-menu summary').click()
                download_gap(page)
                with page.expect_response(lambda response:
                                          response.request.method == 'POST'
                                          and response.url.endswith('/api/export/svg')) as response:
                    with page.expect_download() as download:
                        page.locator('[data-action="export-svg"]').click()
                svg = Path(download.value.path()).read_text()
                root = ET.fromstring(svg)
                check(response.value.status == 200
                      and root.tag == '{http://www.w3.org/2000/svg}svg'
                      and root.get('data-layout') == 'freeform'
                      and expected['project']['name'] in ' '.join(root.itertext()),
                      'More downloads an optional SVG of the current unsaved workflow')
                check(path.read_bytes() == saved and sidecar.read_bytes() == stage_html,
                      'optional SVG export does not save the workflow or refresh its HTML')
                expect(page.locator('#save-state')).to_have_text('Unsaved changes')
                data, payload = save(page)
                check(payload['preview_layout'] == 'freeform',
                      'browser sends the selected Freeform layout with Save')
                check(parse_project(path.read_text()) == expected,
                      'freeform preview preserves positions, hierarchy and unknown metadata')
                freeform = check_viewer(browser, sidecar, expected, 'freeform',
                                       'workflow-preview-freeform.png')
                check(staged != freeform,
                      'saved Stages and Freeform previews use different graph geometry')

                # An unrelated HTML file must survive even when YAML Save succeeds.
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
                check(page.locator('#save-state .dirty').count() == 0,
                      'preview failure still marks workflow edits as saved')
                page.locator('#layout-stages').click()
                expect(page.locator('#save-state')).to_have_text('Saved · preview unavailable')
                page.screenshot(path=str(OUT / 'workflow-preview-warning.png'))
                check(True, 'preview warning survives subsequent interface rendering')
                sidecar.unlink()
                data, payload = save(page)
                check(payload['preview_layout'] == 'stages' and not data.get('preview_warning'),
                      'Save retries preview generation without another workflow edit')
                expect(page.locator('#save-button')).to_be_disabled()
                check(parse_project(path.read_text()) == expected,
                      'preview retry does not change the saved project model')

                saved, preview = path.read_bytes(), sidecar.read_bytes()
                modified = (path.stat().st_mtime_ns, sidecar.stat().st_mtime_ns)
                page.reload(wait_until='networkidle')
                expect(page.locator('#save-state')).to_have_text('Saved')
                check(path.read_bytes() == saved and sidecar.read_bytes() == preview
                      and modified == (path.stat().st_mtime_ns, sidecar.stat().st_mtime_ns),
                      'reopening a saved workflow neither regenerates HTML nor rewrites YAML')
                check(not errors, 'no uncaught JavaScript errors during HTML preview saves')
                check(all(url.startswith(f'http://127.0.0.1:{httpd.server_port}/')
                          for url in requests), 'browser Save uses no external runtime or asset requests')
                check_empty_viewer(browser, path.parent)
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
