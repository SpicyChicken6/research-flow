#!/usr/bin/env python3
"""Minimap dragging and quiet card labels, using disposable workflow data."""
from pathlib import Path
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
    'project': {'name': 'Map navigation', 'metadata': {'keep': 'unchanged'}},
    'tasks': [
        {'id': 'literature', 'title': 'Review literature', 'step_number': 1},
        {'id': 'analysis', 'title': 'Analyze data', 'step_number': 2},
        {'id': 'helper', 'title': 'Check data sources', 'parent_id': 'analysis'},
        {'id': 'nested', 'title': 'Record provenance', 'parent_id': 'helper'},
        {'id': 'design', 'title': 'Design study', 'step_number': 3,
         'depends_on': ['analysis', 'literature']},
        {'id': 'report', 'title': 'Write report', 'step_number': 4,
         'depends_on': ['design']},
        {'id': 'outside', 'title': 'Independent follow-up', 'step_number': 5},
    ],
    'layout': {
        'metadata': {'keep': 'saved coordinates'},
        'positions': {
            'literature': {'x': 60, 'y': 60}, 'analysis': {'x': 60, 'y': 340},
            'helper': {'x': 74, 'y': 570}, 'nested': {'x': 74, 'y': 770},
            'design': {'x': 720, 'y': 360}, 'report': {'x': 1380, 'y': 360},
            'outside': {'x': 1380, 'y': 850},
        },
    },
}))


def check(value, label):
    if not value:
        raise AssertionError(label)
    CHECKS.append(label)
    print('PASS', label, flush=True)


def opened(browser, width=1600, height=1000):
    payload = json.dumps(FIXTURE).replace('<', '\\u003c')
    html = re.sub(r'(<script id="initial-project" type="application/json">).*?(</script>)',
                  lambda match: match[1] + payload + match[2], HTML, flags=re.S)
    page = browser.new_page(viewport={'width': width, 'height': height},
                            accept_downloads=True, reduced_motion='reduce', has_touch=True)
    page.set_default_timeout(6000)
    page.on('pageerror', lambda error: ERRORS.append(str(error)))
    page.set_content(html, wait_until='load')
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


def camera(page):
    return page.locator('#world').evaluate('''el => {
        const matrix = new DOMMatrix(getComputedStyle(el).transform);
        return {x: matrix.e, y: matrix.f, zoom: matrix.a};
    }''')


def same_camera(a, b):
    return all(abs(a[key] - b[key]) < .05 for key in a)


def view_state(page):
    return page.evaluate('''() => ({
        layout: document.querySelector('#layout-control [aria-pressed=true]').dataset.layout,
        focus: document.querySelector('#focus-button').getAttribute('aria-pressed'),
        selected: document.querySelector('.mini-node.is-selected')?.dataset.miniTask,
        visible: [...document.querySelectorAll('.task-node:not([hidden])')].map(el => el.dataset.id),
        branches: [...document.querySelectorAll('.task-node .children-toggle')]
            .map(el => [el.dataset.id, el.getAttribute('aria-expanded')]),
        undo: document.querySelector('#undo-button').disabled,
        redo: document.querySelector('#redo-button').disabled,
        save: document.querySelector('#save-state').textContent,
    })''')


def mini_point(page, kind):
    return page.locator('#minimap').evaluate('''(svg, kind) => {
        const matrix = svg.getScreenCTM();
        const screen = (x, y) => {
            const p = new DOMPoint(x, y).matrixTransform(matrix);
            return {x: p.x, y: p.y};
        };
        if (kind === 'caption') {
            const box = svg.parentElement.querySelector('.minimap-caption').getBoundingClientRect();
            return {x: box.x + box.width / 2, y: box.y + box.height / 2};
        }
        if (kind === 'blank') return screen(3, 3);
        const el = svg.querySelector(kind === 'viewport' ? '.mini-viewport' : `[data-mini-task="${kind}"]`);
        const x = Number(el.getAttribute('x')), y = Number(el.getAttribute('y'));
        const width = Number(el.getAttribute('width')), height = Number(el.getAttribute('height'));
        if (kind === 'viewport') {
            for (const fx of [.3, .5, .7]) for (const fy of [.3, .5, .7]) {
                const p = screen(x + width * fx, y + height * fy);
                if (!document.elementFromPoint(p.x, p.y)?.closest('.mini-node')) return p;
            }
            throw Error('Fixture needs empty space inside its minimap viewport');
        }
        return screen(x + width / 2, y + height / 2);
    }''', kind)


def map_units(page):
    return page.locator('#minimap').evaluate('''svg => {
        const node = svg.querySelector('[data-mini-task="analysis"]');
        const card = document.querySelector('.task-node[data-id="analysis"]');
        const scale = Number(node.getAttribute('width')) / parseFloat(card.style.width);
        return {worldPerPixel: 1 / (scale * svg.getScreenCTM().a),
            screenPerUnit: svg.getScreenCTM().a};
    }''')


def viewport_position(page):
    return page.locator('.mini-viewport').evaluate('''el => ({
        x: Number(el.getAttribute('x')), y: Number(el.getAttribute('y')),
    })''')


def mouse_drag(page, kind, dx=16, dy=10, label='map drag', beyond=False):
    start = mini_point(page, kind)
    before, state, units = camera(page), view_state(page), map_units(page)
    viewport_before = viewport_position(page)
    page.mouse.move(start['x'], start['y'])
    page.mouse.down()
    check(same_camera(camera(page), before), f'{label}: pressing does not jump the canvas')
    page.mouse.move(start['x'] + dx / 2, start['y'] + dy / 2, steps=3)
    halfway = camera(page)
    page.mouse.move(start['x'] + dx, start['y'] + dy, steps=3)
    moved = camera(page)
    expected = {**before,
                'x': before['x'] - dx * units['worldPerPixel'] * before['zoom'],
                'y': before['y'] - dy * units['worldPerPixel'] * before['zoom']}
    check(not same_camera(halfway, before) and not same_camera(halfway, moved)
          and same_camera(moved, expected),
          f'{label}: movement continuously pans proportionally at the current zoom')
    if kind == 'viewport':
        viewport_after = viewport_position(page)
        check(all(abs(viewport_after[axis] - viewport_before[axis]
                      - delta / units['screenPerUnit']) < .05
                  for axis, delta in [('x', dx), ('y', dy)]),
              f'{label}: the viewport rectangle follows the gesture')
    if beyond:
        bounds = page.locator('#minimap-wrap').bounding_box()
        check(start['x'] + dx < bounds['x'] and start['y'] + dy < bounds['y'],
              f'{label}: pointer capture continues outside the overview control')
    page.mouse.up()
    check(same_camera(camera(page), moved), f'{label}: release does not recenter or trigger a click')
    check(view_state(page) == state, f'{label}: preserves layout, selection, visibility and edit history')


def run():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),
            headless=True, args=['--no-sandbox'])
        for mode in ['stages', 'freeform']:
            page = opened(browser)
            page.locator(f'#layout-{mode}').click()
            check(page.locator('.task-node .task-index,.task-node .step-number-button').count() == 0,
                  f'{mode}: main and child cards omit small step-number labels')
            if mode == 'stages':
                page.screenshot(path=str(OUT / 'minimap-overview.png'))
            # A central, magnified viewport makes rectangle motion observable without clipping.
            for _ in range(10):
                page.locator('[data-action=zoom-in]').click()
            page.locator('#minimap').click(position={'x': 85, 'y': 45})
            mouse_drag(page, 'viewport', label=f'{mode} viewport drag')
            mouse_drag(page, 'analysis', label=f'{mode} miniature-step drag')
            mouse_drag(page, 'blank', label=f'{mode} blank-map drag')
            mouse_drag(page, 'caption', label=f'{mode} caption drag')
            mouse_drag(page, 'design', dx=-210, dy=-140,
                       label=f'{mode} outside-bounds drag', beyond=True)
            check(snapshot(page) == FIXTURE, f'{mode}: minimap navigation leaves saved data unchanged')
            page.close()

        page = opened(browser)
        select(page, 'analysis')
        expect(page.locator('#step-number')).to_have_value('2')
        check(page.locator('#step-number').is_enabled(), 'step numbers remain editable in Details')
        page.locator('[data-field=status]').select_option('in_progress')
        page.locator('[data-action=close-inspector]').click()
        page.locator('.task-node[data-id=analysis] .children-toggle').click()
        select(page, 'design')
        page.locator('#focus-button').click()
        check(page.locator('.task-node:not([hidden])').count() < len(FIXTURE['tasks']),
              'fixture has a filtered Focus view and a collapsed branch')
        mouse_drag(page, 'outside', label='off-focus miniature-step drag')
        mouse_drag(page, 'nested', label='collapsed-descendant drag')
        page.locator('#undo-button').click()
        check(snapshot(page) == FIXTURE, 'one undo after map dragging reverses only the prior status edit')
        page.locator('#redo-button').click()
        check(next(t for t in snapshot(page)['tasks'] if t['id'] == 'analysis')['status'] == 'in_progress',
              'redo after map dragging restores the prior edit')
        page.locator('[data-mini-task=outside]').click()
        expect(page.locator('#focus-button')).to_have_attribute('aria-pressed', 'false')
        check(page.locator('.task-node[data-id=outside]').is_visible(),
              'a real click following a drag still reveals an off-focus step')
        page.locator('[data-mini-task=nested]').click()
        check(page.locator('.task-node[data-id=nested]').is_visible(),
              'a real click still reveals a collapsed descendant')
        page.locator('#list-button').click()
        check(page.locator('.table-number').all_text_contents() == ['1', '2', '2.1', '2.1.1', '3', '4', '5'],
              'Step list retains hierarchical numbering')
        page.close()

        for ending in ['pointercancel', 'lostpointercapture']:
            page = opened(browser)
            start = mini_point(page, 'analysis')
            page.mouse.move(start['x'], start['y'])
            page.mouse.down()
            page.mouse.move(start['x'] - 15, start['y'] - 12, steps=3)
            if ending == 'pointercancel':
                page.locator('#minimap-wrap').dispatch_event(ending, {'pointerId': 1})
            else:
                page.locator('#minimap-wrap').evaluate('el => el.releasePointerCapture(1)')
            stopped = camera(page)
            page.mouse.move(start['x'] - 40, start['y'] - 30, steps=3)
            page.mouse.up()
            check(same_camera(camera(page), stopped), f'{ending} ends map dragging without a release jump')
            page.locator('[data-mini-task=report]').click()
            check(not same_camera(camera(page), stopped), f'{ending} leaves the next real map click functional')
            mouse_drag(page, 'blank', label=f'drag following {ending}')
            check(snapshot(page) == FIXTURE, f'{ending} leaves the workflow unchanged')
            page.close()

        page = opened(browser, width=700, height=900)
        session = page.context.new_cdp_session(page)
        start = mini_point(page, 'analysis')
        before, state = camera(page), view_state(page)
        session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [start]})
        session.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [
            {'x': start['x'] - 15, 'y': start['y'] - 10}]})
        moved = camera(page)
        session.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        check(not same_camera(before, moved) and same_camera(camera(page), moved)
              and before['zoom'] == moved['zoom'],
              'touch dragging pans the map without a release click on a narrow screen')
        check(view_state(page) == state, 'touch dragging preserves zoom-independent view and history state')
        session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [start]})
        session.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [
            {'x': start['x'] - 18, 'y': start['y'] - 12}]})
        moved = camera(page)
        session.send('Input.dispatchTouchEvent', {'type': 'touchCancel', 'touchPoints': []})
        check(same_camera(camera(page), moved), 'touch cancellation retains the current camera position')
        mouse_drag(page, 'blank', label='mouse drag after touch cancellation')
        check(snapshot(page) == FIXTURE, 'touch gestures do not modify workflow data')
        page.close()

        for key in ['Enter', 'Space']:
            page = opened(browser)
            page.locator('.task-node[data-id=analysis] .children-toggle').click()
            select(page, 'design')
            page.locator('#focus-button').click()
            mouse_drag(page, 'outside', label=f'drag before {key} overview')
            page.locator('#minimap-wrap').focus()
            page.keyboard.press(key)
            check(page.locator('.task-node:not([hidden])').count() == len(FIXTURE['tasks'])
                  and page.locator('#focus-button').get_attribute('aria-pressed') == 'false',
                  f'{key} on the minimap still restores an expanded global overview')
            page.close()
        check(not ERRORS, 'minimap interactions produce no uncaught JavaScript errors')
        browser.close()
    (OUT / 'minimap-checks.json').write_text(json.dumps(
        {'count': len(CHECKS), 'checks': CHECKS, 'errors': ERRORS}, indent=2))
    print('ALL', len(CHECKS), 'CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run()
