#!/usr/bin/env python3
"""Authenticated browser saves create a complete, independently viewable SVG."""
from copy import deepcopy
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
import xml.etree.ElementTree as ET

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from server import ProjectStore, make_handler, parse_project

OUT = ROOT / 'test-results'
CHECKS = []
SVG_NS = {'svg': 'http://www.w3.org/2000/svg'}


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


def check_svg(path, document):
    root = ET.fromstring(path.read_bytes())
    check(root.tag == '{http://www.w3.org/2000/svg}svg',
          'sidecar is a well-formed standalone SVG')
    text = ' '.join(' '.join(root.itertext()).split())
    check(document['project']['name'] in text,
          'preview includes the saved project title and UTF-8 text')
    for task in document['tasks']:
        check(task['title'] in text, f'preview contains step {task["id"]}')
    groups = root.findall('.//svg:g[@data-task-id]', SVG_NS)
    check({group.get('data-task-id') for group in groups}
          == {task['id'] for task in document['tasks']},
          'preview draws each saved step even when hidden in the current view')
    arrows = root.findall('.//svg:path[@data-source]', SVG_NS)
    count = sum(len(task['depends_on']) for task in document['tasks'])
    check(len(arrows) == count, 'preview includes every real dependency arrow')
    markers = {marker.get('id') for marker in root.findall('.//svg:marker', SVG_NS)}
    check(bool(markers) and all(
        re.fullmatch(r'url\(#(.+)\)', arrow.get('marker-end')).group(1) in markers
        for arrow in arrows), 'dependency arrows reference embedded SVG markers')
    parents = root.findall('.//svg:path[@data-parent]', SVG_NS)
    check({(edge.get('data-parent'), edge.get('data-child')) for edge in parents}
          == {(task['parent_id'], task['id']) for task in document['tasks'] if task.get('parent_id')}
          and all(edge.get('marker-end') is None for edge in parents),
          'parent branches remain distinct from directed dependencies')
    check(root.find('.//svg:script', SVG_NS) is None
          and root.find('.//svg:foreignObject', SVG_NS) is None,
          'preview renders without scripts or an HTML embedding')
    return root


def capture_preview(browser, path, filename):
    # Open the actual sidecar without the Research Flow server or application.
    page = browser.new_page(viewport={'width': 1600, 'height': 1000})
    page.goto(path.as_uri(), wait_until='load')
    expect(page.locator('svg')).to_have_count(1)
    check(page.locator('parsererror').count() == 0
          and page.locator('svg').bounding_box()['width'] > 0,
          'saved SVG opens independently in Chromium')
    expect(page.locator('.legend')).to_have_text(['Dependency', 'Parent / child'])
    svg_bounds = page.locator('svg').bounding_box()
    legend_bounds = [legend.bounding_box() for legend in page.locator('.legend').all()]
    check(all(bounds['y'] > page.locator('#workflow-graph').bounding_box()['y']
              and bounds['y'] + bounds['height'] <= svg_bounds['y'] + svg_bounds['height']
              for bounds in legend_bounds),
          'standalone SVG keeps both legend labels inside the image')
    # Exercise ordinary image embedding too, using the same file rather than
    # injecting the SVG DOM. Capture the image at a size that fits the viewport.
    viewer = path.parent / 'preview-test.html'
    viewer.write_text(
        '<!doctype html><meta charset="utf-8"><title>Saved workflow preview</title>'
        '<style>body{margin:0;background:white}img{display:block;max-width:100vw;'
        'max-height:100vh;width:auto;height:auto}</style>'
        f'<img src="{path.name}" alt="Saved workflow">', encoding='utf-8')
    page.goto(viewer.as_uri(), wait_until='load')
    dimensions = page.locator('img').evaluate('''async image => {
        await image.decode();
        return {width: image.naturalWidth, height: image.naturalHeight};
    }''')
    check(dimensions['width'] > 0 and dimensions['height'] > 0,
          'the same saved SVG decodes as an ordinary embedded image')
    page.locator('img').screenshot(path=str(OUT / filename))
    page.close()


def run():
    OUT.mkdir(exist_ok=True)
    fixture = parse_project((ROOT / 'examples/research-project.yaml').read_text())
    fixture['project']['name'] = 'Research α & validation'
    fixture['project']['owner'] = {'keep': 'unknown metadata'}
    fixture['tasks'][0]['title'] = 'Define α & β'
    fixture['tasks'][5]['title'] = 'QC <replicates>'
    fixture['tasks'][5]['evidence'] = {'keep': ['PMID:example']}
    fixture['layout']['note'] = 'Preserve stored positions'

    with TemporaryDirectory() as temp:
        path = Path(temp).resolve() / 'workflow.yaml'
        path.write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        sidecar = path.with_suffix('.svg')
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
                                        reduced_motion='reduce')
                page.set_default_timeout(8000)
                errors = []
                requests = []
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
                      'Save reports the adjacent generated preview')
                check(parse_project(path.read_text()) == expected,
                      'saving a focused view changes only the edited title')
                stage_svg = sidecar.read_bytes()
                check_svg(sidecar, expected)
                check(token.encode() not in stage_svg and token.encode() not in path.read_bytes(),
                      'workflow and SVG contain no authentication token')
                capture_preview(browser, sidecar, 'workflow-preview-stages.png')
                expect(page.locator('#save-button')).to_be_disabled()

                overview(page)
                page.locator('#layout-freeform').click()
                check(parse_project(path.read_text()) == expected
                      and sidecar.read_bytes() == stage_svg,
                      'switching layout and returning to Overview do not write files')
                page.locator('#project-title').fill('Research α & validation — freeform')
                page.locator('#project-title').press('Enter')
                expected['project']['name'] = 'Research α & validation — freeform'
                data, payload = save(page)
                check(payload['preview_layout'] == 'freeform',
                      'browser sends the selected Freeform layout with Save')
                check(parse_project(path.read_text()) == expected,
                      'freeform preview preserves positions, hierarchy and unknown metadata')
                freeform_svg = sidecar.read_bytes()
                check_svg(sidecar, expected)
                staged = ET.fromstring(stage_svg)
                freeform = ET.fromstring(freeform_svg)
                check(staged.get('data-layout') == 'stages'
                      and freeform.get('data-layout') == 'freeform',
                      'SVG identifies the layout selected for each Save')
                stage_paths = [element.get('d') for element in staged.findall('.//svg:path', SVG_NS)]
                freeform_paths = [element.get('d') for element in freeform.findall('.//svg:path', SVG_NS)]
                check(stage_paths != freeform_paths,
                      'saved Stages and Freeform previews use different graph geometry')
                capture_preview(browser, sidecar, 'workflow-preview-freeform.png')

                # A custom same-name file must survive even when YAML Save succeeds.
                custom_svg = b'<svg xmlns="http://www.w3.org/2000/svg"><text>My custom drawing</text></svg>'
                sidecar.write_bytes(custom_svg)
                page.locator('#project-title').fill('Saved with a preview collision')
                page.locator('#project-title').press('Enter')
                expected['project']['name'] = 'Saved with a preview collision'
                data, _ = save(page, warning=True)
                check(bool(data.get('preview_warning')) and not data.get('preview_file'),
                      'preview collision returns a warning without claiming a preview')
                check(parse_project(path.read_text()) == expected and sidecar.read_bytes() == custom_svg,
                      'preview collision preserves the custom SVG while saving workflow changes')
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
                check_svg(sidecar, expected)
                expect(page.locator('#save-button')).to_be_disabled()
                check(parse_project(path.read_text()) == expected,
                      'preview retry does not change the saved project model')

                saved = path.read_bytes()
                preview = sidecar.read_bytes()
                modified = (path.stat().st_mtime_ns, sidecar.stat().st_mtime_ns)
                page.reload(wait_until='networkidle')
                expect(page.locator('#save-state')).to_have_text('Saved')
                check(path.read_bytes() == saved and sidecar.read_bytes() == preview
                      and modified == (path.stat().st_mtime_ns, sidecar.stat().st_mtime_ns),
                      'reopening a saved workflow neither regenerates SVG nor rewrites YAML')
                check(not errors, 'no uncaught JavaScript errors during preview saves')
                check(all(url.startswith(f'http://127.0.0.1:{httpd.server_port}/')
                          for url in requests), 'browser Save uses no external runtime or asset requests')
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
