#!/usr/bin/env python3
"""Dependency-stage browser regressions using disposable workflow data."""
from pathlib import Path
from copy import deepcopy
import json
import os
import re
import shutil
import sys

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from server import parse_project

OUT = ROOT / 'test-results'
OUT.mkdir(exist_ok=True)
HTML = (ROOT / 'dist/research-flow.html').read_text()
CHECKS = []
ERRORS = []
FIXTURE = parse_project(json.dumps({
    'schema_version': 1,
    'project': {'name': 'Dependency stages', 'owner': {'keep': 'unchanged'}},
    'tasks': [
        {'id': 'data', 'title': 'Analyze data', 'status': 'done',
         'goal': 'Assess the supplied observations.', 'outputs': ['results/data.tsv']},
        {'id': 'literature', 'title': 'Review literature', 'status': 'done'},
        {'id': 'design', 'title': 'Design the study', 'depends_on': ['data', 'literature'],
         'notes': 'Keep this evidence note.', 'evidence': {'refs': ['PMID:example']}},
        {'id': 'review', 'title': 'Review design', 'depends_on': ['design'], 'status': 'blocked'},
        {'id': 'report', 'title': 'Write report', 'depends_on': ['review']},
        {'id': 'helper', 'title': 'Record data provenance', 'parent_id': 'data', 'status': 'in_progress'},
        {'id': 'side', 'title': 'Archive provenance', 'depends_on': ['helper']},
    ],
    'layout': {
        'note': 'Keep layout metadata',
        'positions': {
            'data': {'x': 70, 'y': 95}, 'literature': {'x': 470, 'y': 165},
            'design': {'x': 865, 'y': 255}, 'review': {'x': 1260, 'y': 365},
            'report': {'x': 1655, 'y': 465}, 'helper': {'x': 80, 'y': 590},
            'side': {'x': 480, 'y': 640},
        },
    },
}))


def fixture_html(document=FIXTURE):
    payload = json.dumps(document).replace('<', '\\u003c')
    return re.sub(r'(<script id="initial-project" type="application/json">).*?(</script>)',
                  lambda match: match[1] + payload + match[2], HTML, flags=re.S)


def check(value, label):
    if not value:
        raise AssertionError(label)
    CHECKS.append(label)
    print('PASS', label, flush=True)


def opened(browser, html=None, width=1600, height=1000):
    page = browser.new_page(viewport={'width': width, 'height': height},
                            accept_downloads=True, reduced_motion='reduce')
    page.set_default_timeout(6000)
    page.on('pageerror', lambda error: ERRORS.append(str(error)))
    page.set_content(html or fixture_html(), wait_until='load')
    expect(page.locator('#save-button')).to_be_enabled()
    return page


def snapshot(page):
    page.locator('#more-menu summary').click()
    with page.expect_download() as download:
        page.locator('[data-action=export-json]').click()
    return json.loads(Path(download.value.path()).read_text())


def select(page, task_id):
    page.locator(f'.task-node[data-id="{task_id}"]').focus()
    page.keyboard.press('Enter')
    expect(page.locator('#inspector')).to_be_visible()


def overview(page):
    if page.locator('#inspector').is_visible():
        page.locator('[data-action=close-inspector]').click()
    page.locator('#overview-button').click()


def positions(page):
    return page.locator('.task-node:not([hidden])').evaluate_all('''nodes => Object.fromEntries(
        nodes.map(node => [node.dataset.id, {
            x: parseFloat(node.style.left), y: parseFloat(node.style.top)
        }]))''')


def stages(page):
    return page.locator('.task-node:not([hidden])').evaluate_all('''nodes => {
        const columns = [...document.querySelectorAll('.stage-column')];
        return Object.fromEntries(nodes.map(node => {
            const x = parseFloat(node.style.left);
            const column = columns.find(el => x >= parseFloat(el.style.left)
                && x < parseFloat(el.style.left) + parseFloat(el.style.width));
            return [node.dataset.id, column ? Number(column.dataset.stage) : null];
        }));
    }''')


def drag_node(page, task_id, cancel=False):
    node = page.locator(f'.task-node[data-id="{task_id}"]')
    node.focus()
    box = node.bounding_box()
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 42, y + 28, steps=6)
    if cancel:
        page.locator('#canvas').dispatch_event('pointercancel', {
            'pointerId': 1, 'clientX': x + 42, 'clientY': y + 28,
        })
    page.mouse.up()


def connect(page, source, target):
    page.locator(f'.port.out[data-id="{source}"]').focus()
    page.keyboard.press('Enter')
    page.locator(f'.port.in[data-id="{target}"]').focus()
    page.keyboard.press('Enter')


def run():
    expected = {'data': 0, 'literature': 0, 'design': 1, 'review': 2,
                'report': 3, 'helper': 0, 'side': 1}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),
            headless=True, args=['--no-sandbox'])
        page = opened(browser)
        expect(page.locator('#layout-stages')).to_have_attribute('aria-pressed', 'true')
        expect(page.get_by_role('group', name='Graph layout')).to_be_visible()
        expect(page.get_by_role('button', name='Stages', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='Freeform', exact=True)).to_be_visible()
        check(page.locator('#layout-control [aria-pressed=true]').count() == 1,
              'layout switch exposes both ends with exactly one selected')
        page.locator('#layout-freeform').focus()
        page.keyboard.press('Enter')
        expect(page.locator('#layout-freeform')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#layout-stages')).to_have_attribute('aria-pressed', 'false')
        check(positions(page) == FIXTURE['layout']['positions'] and snapshot(page) == FIXTURE,
              'Enter selects the freeform end without changing project data')
        page.locator('#layout-stages').focus()
        page.keyboard.press('Space')
        expect(page.locator('#layout-stages')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#layout-freeform')).to_have_attribute('aria-pressed', 'false')
        check(stages(page) == expected and snapshot(page) == FIXTURE,
              'Space selects the stages end without changing project data')
        page.locator('[data-action=zoom-in]').click()
        camera = page.locator('#world').evaluate('el => getComputedStyle(el).transform')
        page.locator('#layout-stages').click()
        check(page.locator('#world').evaluate('el => getComputedStyle(el).transform') == camera
              and stages(page) == expected and snapshot(page) == FIXTURE,
              'clicking the selected layout keeps the camera and project unchanged')
        overview(page)
        check(stages(page) == expected, 'default stage columns follow only dependency depth')
        check(page.locator('.stage-column').count() == 4, 'four dependency levels create four stages')
        check(page.locator('.stage-column').all_text_contents() ==
              ['Stage 1', 'Stage 2', 'Stage 3', 'Stage 4'],
              'stage headers have simple names without progress summaries')
        check(page.locator('.stage-column button,.stage-column [role=progressbar],'
                           '.stage-column progress,.stage-column [aria-expanded]').count() == 0,
              'stage columns have no progress or collapse controls')
        check(snapshot(page) == FIXTURE, 'opening and rendering stages preserves all project data')
        staged = positions(page)
        check(staged != FIXTURE['layout']['positions'], 'stage geometry is derived separately from saved positions')
        check(page.locator('.mini-node').count() == len(FIXTURE['tasks']),
              'global minimap includes every staged step')
        page.screenshot(path=str(OUT / 'stage-overview.png'))

        select(page, 'design')
        check(page.locator('.edge-path.related').count() == 4,
              'selection highlights complete upstream and downstream dependency paths')
        check(page.locator('[data-edge="helper|side"]').evaluate(
            'el => !el.parentElement.querySelector(".edge-path").classList.contains("related")'),
            'an unrelated dependency stays quiet despite shared hierarchy')
        page.locator('#focus-button').click()
        check(stages(page) == {key: expected[key] for key in positions(page)},
              'Focus preserves global dependency stage numbers')
        overview(page)
        page.locator('.task-node[data-id=data] .children-toggle').click()
        check('helper' not in positions(page), 'existing branch collapse remains available in stages')
        check(snapshot(page) == FIXTURE, 'focus and branch collapse do not persist derived stage positions')
        page.locator('#minimap-wrap').focus()
        page.keyboard.press('Enter')
        check(stages(page) == expected, 'global overview restores every step to its dependency stage')

        page.locator('#layout-freeform').click()
        check(page.locator('.stage-column').count() == 0, 'freeform hides stage containers')
        check(positions(page) == FIXTURE['layout']['positions'], 'freeform restores existing saved coordinates')
        check(snapshot(page) == FIXTURE, 'switching layout is a view operation')
        page.locator('#layout-stages').click()
        check(positions(page) == staged, 'returning to stages deterministically restores the organized layout')
        page.close()

        page = opened(browser)
        select(page, 'design')
        page.locator('[data-field=status]').select_option('in_progress')
        status_edited = snapshot(page)
        page.locator('#layout-freeform').click()
        page.locator('#undo-button').click()
        expect(page.locator('#layout-freeform')).to_have_attribute('aria-pressed', 'true')
        check(snapshot(page) == FIXTURE,
              'undoing an unrelated status edit preserves the chosen freeform view')
        page.locator('#redo-button').click()
        expect(page.locator('#layout-freeform')).to_have_attribute('aria-pressed', 'true')
        check(snapshot(page) == status_edited,
              'redoing an unrelated status edit also preserves the chosen freeform view')
        page.close()

        page = opened(browser)
        # Keep both keyboard moves inside the history grouping window, even on slow CI.
        page.evaluate('Date.now = () => 100000')
        page.locator('#layout-freeform').click()
        page.locator('.task-node[data-id=literature]').focus()
        page.keyboard.press('ArrowRight')
        first_nudge = deepcopy(FIXTURE)
        first_nudge['layout']['positions']['literature']['x'] += 10
        check(positions(page) == first_nudge['layout']['positions'],
              'freeform keyboard movement records the first nudge')
        page.locator('#layout-stages').click()
        page.locator('.task-node[data-id=literature]').focus()
        page.keyboard.press('ArrowRight')
        expect(page.locator('#layout-freeform')).to_have_attribute('aria-pressed', 'true')
        page.locator('#undo-button').click()
        expect(page.locator('#layout-stages')).to_have_attribute('aria-pressed', 'true')
        check(snapshot(page) == first_nudge and stages(page) == expected,
              'a layout switch separates rapid keyboard moves into atomic undo entries')
        page.locator('#undo-button').click()
        expect(page.locator('#layout-stages')).to_have_attribute('aria-pressed', 'true')
        check(snapshot(page) == FIXTURE,
              'a second undo reverses only the original freeform nudge')
        page.close()

        page = opened(browser)
        select(page, 'literature')
        page.locator('#add-dependency').select_option('data')
        linked = snapshot(page)
        check(stages(page) == {**expected, 'literature': 1, 'design': 2, 'review': 3, 'report': 4},
              'inspector dependency edits immediately shift all affected downstream stages')
        check(linked['layout'] == FIXTURE['layout'], 'dependency edits retain freeform coordinates and metadata')
        page.locator('#undo-button').click()
        check(snapshot(page) == FIXTURE and stages(page) == expected,
              'undo restores dependency data and stage placement together')
        page.locator('#redo-button').click()
        check(snapshot(page) == linked and stages(page)['report'] == 4,
              'redo recomputes downstream stages')
        page.locator('[data-action=remove-dependency][data-source=data][data-target=literature]').click()
        check(snapshot(page) == FIXTURE and stages(page) == expected,
              'removing a prerequisite immediately returns affected steps to earlier stages')
        overview(page)
        connect(page, 'review', 'side')
        connected = snapshot(page)
        check(stages(page)['side'] == 3 and stages(page)['helper'] == 0,
              'canvas connections update stages while hierarchy remains independent')
        check(connected['layout'] == FIXTURE['layout'], 'canvas connections do not overwrite freeform positions')
        page.locator('#undo-button').click()
        check(snapshot(page) == FIXTURE and stages(page) == expected,
              'a canvas connection and its derived placement undo atomically')
        page.locator('#redo-button').click()
        with page.expect_download() as download:
            page.locator('#save-button').click()
        reopened = opened(browser, Path(download.value.path()).read_text())
        check(snapshot(reopened) == connected and stages(reopened)['side'] == 3,
              'saved HTML reopens with edited dependencies and derived stage placement intact')
        reopened.locator('#layout-freeform').click()
        check(positions(reopened) == FIXTURE['layout']['positions'],
              'saved HTML also preserves the original freeform layout')
        reopened.close()
        page.close()

        metadata = deepcopy(FIXTURE)
        for task_id in ['data', 'literature']:
            metadata['layout']['positions'][task_id]['custom'] = {'keep': ['position metadata']}
        page = opened(browser, fixture_html(metadata))
        staged = positions(page)
        drag_node(page, 'literature', cancel=True)
        expect(page.locator('#layout-stages')).to_have_attribute('aria-pressed', 'true')
        check(snapshot(page) == metadata and positions(page) == staged,
              'cancelled stage drag restores the stage view and all original project data')
        drag_node(page, 'literature')
        expect(page.locator('#layout-freeform')).to_have_attribute('aria-pressed', 'true')
        moved = snapshot(page)
        check({key: moved['layout']['positions']['literature'][key] for key in ['x', 'y']} != staged['literature'],
              'dragging a staged card switches to freeform and records its movement')
        check(all({key: moved['layout']['positions'][task_id][key] for key in ['x', 'y']} == position
                  for task_id, position in staged.items() if task_id != 'literature'),
              'stage drag captures the other cards at their visible positions')
        check(all(moved['layout']['positions'][task_id]['custom'] ==
                  metadata['layout']['positions'][task_id]['custom'] for task_id in ['data', 'literature']),
              'stage drag preserves unknown metadata on moved and untouched saved positions')
        check(moved['layout']['note'] == FIXTURE['layout']['note'] and moved['tasks'] == FIXTURE['tasks'],
              'stage drag preserves project metadata and task contents')
        page.locator('#undo-button').click()
        expect(page.locator('#layout-stages')).to_have_attribute('aria-pressed', 'true')
        check(snapshot(page) == metadata and positions(page) == staged,
              'one undo restores saved freeform coordinates and the previous stage view')
        page.locator('#redo-button').click()
        expect(page.locator('#layout-freeform')).to_have_attribute('aria-pressed', 'true')
        check(snapshot(page) == moved, 'one redo reapplies the whole stage-to-freeform move')
        page.close()

        insertion = deepcopy(FIXTURE)
        insertion['tasks'] = [insertion['tasks'][0]]
        insertion['layout']['positions'] = {'data': {'x': 510, 'y': 72}}
        page = opened(browser, fixture_html(insertion))
        point = page.locator('#world').evaluate('''world => {
            const origin = world.parentElement.getBoundingClientRect();
            const point = new DOMPoint(630, 146).matrixTransform(
                new DOMMatrix(getComputedStyle(world).transform));
            return {x: origin.left + point.x, y: origin.top + point.y};
        }''')
        page.mouse.dblclick(point['x'], point['y'])
        expect(page.locator('.task-node')).to_have_count(2)
        inserted = snapshot(page)
        check(stages(page) == {'data': 0, 'step_1': 0},
              'blank canvas insertion adds an independent step to the first stage')
        check(inserted['layout']['positions']['data'] == insertion['layout']['positions']['data'],
              'adding a staged step preserves the existing saved freeform location')
        page.locator('#layout-freeform').click()
        check(page.locator('.task-node').evaluate_all('''nodes => {
            const [a, b] = nodes.map(node => node.getBoundingClientRect());
            return a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top;
        }'''), 'new staged steps avoid collisions with saved freeform cards')
        page.locator('#undo-button').click()
        check(snapshot(page) == insertion, 'blank stage insertion remains a single undoable edit')
        page.close()

        siblings = deepcopy(FIXTURE)
        siblings['tasks'] = [siblings['tasks'][0], siblings['tasks'][5], {
            'id': 'helper_two', 'title': 'Verify provenance', 'parent_id': 'data',
        }]
        siblings['layout']['positions'] = {key: siblings['layout']['positions'][key]
                                           for key in ['data', 'helper']}
        siblings['layout']['positions']['helper_two'] = {'x': 410, 'y': 590}
        page = opened(browser, fixture_html(siblings))
        check(stages(page) == {'data': 0, 'helper': 0, 'helper_two': 0},
              'independent sibling children stay with their parent in the first stage')
        check(page.locator('[data-hierarchy="helper_two"]').evaluate('''path => {
            const sibling = document.querySelector('.task-node[data-id="helper"]');
            const x = parseFloat(sibling.style.left), y = parseFloat(sibling.style.top);
            const width = parseFloat(sibling.style.width), height = parseFloat(sibling.style.height);
            for (let length = 0; length <= path.getTotalLength(); length += 2) {
                const point = path.getPointAtLength(length);
                if (point.x > x && point.x < x + width && point.y > y && point.y < y + height) {
                    return false;
                }
            }
            return true;
        }'''), 'stage hierarchy connectors avoid intervening sibling cards')
        page.close()

        for width, height in [(390, 844), (700, 900), (1024, 768)]:
            page = opened(browser, width=width, height=height)
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                  f'stage layout controls fit without document overflow at {width}px')
            expect(page.locator('#layout-stages')).to_be_visible()
            expect(page.locator('#layout-freeform')).to_be_visible()
            check(stages(page) == expected, f'responsive view retains stage grouping at {width}px')
            page.close()
        check(not ERRORS, 'stage interactions produce no uncaught JavaScript errors')
        browser.close()
    (OUT / 'stage-checks.json').write_text(json.dumps(
        {'count': len(CHECKS), 'checks': CHECKS, 'errors': ERRORS}, indent=2))
    print('ALL', len(CHECKS), 'CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run()
