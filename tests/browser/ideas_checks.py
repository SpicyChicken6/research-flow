#!/usr/bin/env python3
"""Ideas and questions regressions using public controls and exported documents."""
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


def unexpected_dialog(dialog):
    ERRORS.append(f'Unexpected browser dialog: {dialog.message}')
    dialog.dismiss()


def opened(browser, path, width=1600, height=1100):
    page = browser.new_page(viewport={'width': width, 'height': height},
                            accept_downloads=True, reduced_motion='reduce')
    page.set_default_timeout(7000)
    page.on('pageerror', lambda error: ERRORS.append(str(error)))
    page.on('dialog', unexpected_dialog)
    page.goto(path.resolve().as_uri(), wait_until='load')
    expect(page.locator('#save-button')).to_be_enabled()
    expect(page.locator('#layers-view')).to_be_visible()
    return page


def downloaded(page, action):
    global LAST_DOWNLOAD
    # Chromium limits quick consecutive downloads, including exported snapshots.
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


def idea(document, idea_id):
    return next(item for item in document['ideas'] if item['id'] == idea_id)


def expanded(page, value=True):
    toggle = page.locator('#ideas-button')
    if (toggle.get_attribute('aria-expanded') == 'true') != value:
        toggle.click()
    expect(toggle).to_have_attribute('aria-expanded', str(value).lower())
    if value:
        expect(page.locator('#ideas-panel')).to_be_visible()
    else:
        expect(page.locator('#ideas-panel')).not_to_be_visible()


def history(page, action):
    # Leave fields before the document-level shortcut, including on narrow screens.
    page.locator('#ideas-heading' if page.locator('#ideas-panel').is_visible() else '#ideas-button').focus()
    page.keyboard.press('Control+Shift+z' if action == 'redo' else 'Control+z')


def view_state(page):
    return page.evaluate("""() => ({
        view: document.querySelector('.view-controls [aria-pressed=true]')?.id,
        graphCamera: document.querySelector('#world').style.transform,
        layerCamera: document.querySelector('#layer-world')?.style.transform,
        selectedLayers: [...document.querySelectorAll('.flow-node[aria-pressed=true]')].map(n => n.dataset.id)
    })""")


def rows_are_clear(page):
    return page.locator('.ideas-list > .idea-row').evaluate_all("""rows => {
        const boxes = rows.map(row => row.getBoundingClientRect());
        return boxes.length > 0 && boxes.every((box, i) =>
            Math.abs(box.x - boxes[0].x) < 1 && Math.abs(box.width - boxes[0].width) < 1 &&
            (!i || box.top >= boxes[i - 1].bottom - 1) &&
            rows[i].scrollWidth <= rows[i].clientWidth);
    }""")


def open_item(page, item_id, value=True):
    toggle = page.locator(f'[data-action=idea-toggle][data-id="{item_id}"]')
    if (toggle.get_attribute('aria-expanded') == 'true') != value:
        toggle.click()
    expect(toggle).to_have_attribute('aria-expanded', str(value).lower())
    details = page.locator(f'.idea-row[data-idea-id="{item_id}"] .idea-details')
    if value:
        expect(details).to_be_visible()
    else:
        expect(details).not_to_be_visible()
    return toggle


def submit_item(page, values, item_id=None):
    expanded(page)
    if item_id:
        open_item(page, item_id)
        page.locator(f'#ideas-panel [data-action=idea-edit][data-id="{item_id}"]').click()
    else:
        page.locator('[data-action=idea-add]').click()
    expect(page.locator('#idea-dialog')).to_be_visible()
    form = page.locator('#idea-form')
    for name, value in values.items():
        field = form.locator(f'[name="{name}"]')
        if name in {'kind', 'status', 'related_task_id'}:
            field.select_option(value)
        else:
            field.fill(value)
    form.locator('button[type=submit]').click()
    expect(page.locator('#idea-dialog')).not_to_be_visible()
    expect(page.locator('[data-action=idea-toggle][aria-expanded=true]')).to_be_focused()
    expect(page.locator('.idea-details:visible')).to_have_count(1)


def run():
    OUT.mkdir(exist_ok=True)
    preview = build(ROOT / 'examples/three-layers.yaml', ROOT / 'dist/ideas-checks.html')
    with TemporaryDirectory(prefix='research-flow-ideas-') as temporary:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),
                headless=True, args=['--no-sandbox'])
            page = opened(browser, preview)
            expect(page.locator('#ideas-button')).to_have_attribute('aria-expanded', 'false')
            expect(page.locator('#ideas-content')).not_to_be_visible()
            base = snapshot(page)
            check({entry['id'] for entry in base['ideas']} == {
                'batch-question', 'external-cohort', 'normalization-decision'},
                'the example retains its three fictional ideas while the separate panel starts closed')

            for button, surface in [('#layers-button', '#layers-view'),
                                    ('#overview-button', '#canvas'),
                                    ('#list-button', '#list-view')]:
                page.locator(button).click()
                before_open = view_state(page)
                expanded(page)
                expect(page.locator(surface)).to_be_visible()
                check(view_state(page) == before_open,
                      f'opening Ideas from {button} keeps the workflow view, camera and selection')
                page.locator('[data-action=ideas-close]').click()
                expect(page.locator('#ideas-button')).to_be_focused()
                expect(page.locator('#ideas-panel')).not_to_be_visible()
                check(view_state(page) == before_open,
                      f'closing Ideas from {button} restores button focus without changing the workflow')
            page.locator('#layers-button').click()
            node = page.locator('.flow-node[data-id=normalization]')
            node.focus()
            page.keyboard.press('Enter')
            expect(page.locator('#inspector')).to_be_visible()
            selected_view = view_state(page)
            expanded(page)
            expect(page.locator('#inspector')).not_to_be_visible()
            check(view_state(page) == selected_view,
                  'Ideas replaces Details while retaining the selected operation and canvas camera')
            page.locator('#details-button').click()
            expect(page.locator('#inspector')).to_be_visible()
            expect(page.locator('#ideas-panel')).not_to_be_visible()
            check(view_state(page) == selected_view,
                  'Details replaces Ideas without losing the selected operation')
            expanded(page)
            page.keyboard.press('Escape')
            expect(page.locator('#ideas-panel')).not_to_be_visible()
            expect(page.locator('#ideas-button')).to_be_focused()
            check(view_state(page) == selected_view,
                  'Escape closes Ideas and restores focus without clearing the selected operation')
            expanded(page)
            page.locator('#ideas-filter').select_option('all')
            expect(page.locator('.ideas-list > .idea-row')).to_have_count(3)
            check(rows_are_clear(page),
                  'ideas and questions appear as aligned full-width rows without overlap or clipping')
            expect(page.locator('[data-action=idea-toggle][aria-expanded=false]')).to_have_count(3)
            expect(page.locator('.idea-details:visible')).to_have_count(0)
            check(all(row['height'] <= 70 for row in page.locator('.idea-row').evaluate_all(
                'rows => rows.map(row => ({height:row.getBoundingClientRect().height}))'))
                  and page.locator('[data-action=idea-toggle] svg').count() == 3,
                  'closed rows are compact title-and-status summaries with a small disclosure icon')
            first = open_item(page, 'batch-question')
            first_details = page.locator('.idea-row[data-idea-id=batch-question] .idea-details')
            expect(first_details).to_contain_text(idea(base, 'batch-question')['notes'])
            expect(first_details).to_contain_text(idea(base, 'batch-question')['revisit_when'])
            expect(first_details.locator('[data-action=idea-edit]')).to_be_visible()
            expect(first_details.locator('[data-action=idea-link]')).to_be_visible()
            check(first.get_attribute('aria-controls') == first_details.get_attribute('id'),
                  'expanding a row exposes its notes, revisit context and actions through an associated details region')
            second = open_item(page, 'external-cohort')
            expect(first).to_have_attribute('aria-expanded', 'false')
            expect(first_details).not_to_be_visible()
            expect(page.locator('.idea-details:visible')).to_have_count(1)
            check(rows_are_clear(page),
                  'opening another idea closes the preceding details and keeps the remaining rows compact')
            second.focus()
            page.keyboard.press('Space')
            expect(second).to_have_attribute('aria-expanded', 'false')
            expect(second).to_be_focused()
            page.keyboard.press('Enter')
            expect(second).to_have_attribute('aria-expanded', 'true')
            expect(second).to_be_focused()
            page.keyboard.press('Tab')
            expect(page.locator('.idea-row[data-idea-id=external-cohort] [data-action=idea-edit]')).to_be_focused()
            open_item(page, 'external-cohort', False)
            check(snapshot(page) == base,
                  'click, Space and Enter browse details without changing research data or adding an undo entry')
            for value in ['resolved', 'active', 'all']:
                page.locator('#ideas-filter').select_option(value)
                expected_ids = {entry['id'] for entry in base['ideas']
                                if value == 'all' or (entry['status'] == 'resolved') == (value == 'resolved')}
                shown_ids = set(page.locator('.idea-row').evaluate_all(
                    'cards => cards.map(card => card.dataset.ideaId)'))
                check(shown_ids == expected_ids, f'the {value} filter shows the appropriate manual statuses')
            expanded(page, False)
            expanded(page)
            expect(page.locator('#save-state')).to_have_text('In this tab')
            check(snapshot(page) == base,
                  'filtering and closing Ideas preserve project data and its clean state')

            literal_title = '<img src=x onerror=alert(1)> A & B?'
            submit_item(page, {
                'title': literal_title, 'kind': 'idea', 'status': 'open',
                'notes': 'Illustrative general idea, with no linked operation.',
                'revisit_when': 'After reviewing the cohort description.',
                'related_task_id': '',
            })
            general_doc = snapshot(page)
            general_id = next(entry['id'] for entry in general_doc['ideas'] if entry['title'] == literal_title)
            general = idea(general_doc, general_id)
            check(len(general_doc['ideas']) == len(base['ideas']) + 1
                  and not general.get('related_task_id') and general['status'] == 'open'
                  and general_doc['tasks'] == base['tasks'],
                  'a general idea is saved independently without creating or changing research tasks')
            expect(page.locator(f'.idea-row[data-idea-id="{general_id}"]')).to_contain_text(literal_title)
            check(page.locator('.idea-row img,.idea-row script').count() == 0,
                  'idea titles containing HTML are rendered as literal text')

            page.locator(f'[data-action=idea-toggle][data-id="{general_id}"]').focus()
            page.keyboard.press('Control+z')
            expect(page.locator('[data-action=idea-add]')).to_be_focused()
            check(snapshot(page) == base,
                  'undoing creation while its new row is focused restores the project and moves focus to Add item')
            history(page, 'redo')
            check(snapshot(page) == general_doc,
                  'redo restores the created idea and its context after removing the focused row')

            linked_title = 'Browser example: inspect normalization choices'
            submit_item(page, {
                'title': linked_title, 'kind': 'question', 'status': 'open',
                'notes': 'Illustrative question about the recorded normalization choices.',
                'revisit_when': 'Before accepting the preparation stage.',
                'related_task_id': 'normalization',
            })
            linked_doc = snapshot(page)
            linked_id = next(entry['id'] for entry in linked_doc['ideas'] if entry['title'] == linked_title)
            check(idea(linked_doc, linked_id)['related_task_id'] == 'normalization'
                  and linked_doc['tasks'] == base['tasks']
                  and len(linked_doc['ideas']) == len(base['ideas']) + 2,
                  'a linked question retains its context without changing the operation or its run records')

            page.locator('#overview-button').click()
            expanded(page)
            open_item(page, linked_id)
            page.locator(f'[data-action=idea-link][data-id="{linked_id}"]').click()
            expect(page.locator('#ideas-panel')).not_to_be_visible()
            expect(page.locator('#layers-view')).to_be_visible()
            expect(page.locator('.flow-node[data-id=normalization]')).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('#methods-panel')).to_be_visible()
            expect(page.locator('[data-field=title]')).to_have_value('Normalize for exploration')
            check(snapshot(page) == linked_doc,
                  'following a linked question from Graph closes Ideas and opens its operation in Layers without changing data')
            page.locator('[data-action=close-inspector]').click()

            expanded(page)
            page.locator('#ideas-filter').select_option('all')
            revised_notes = 'Illustrative updated context: compare cohort eligibility before choosing a follow-up.'
            revisit = 'Revisit after the next methods review.'
            submit_item(page, {'notes': revised_notes, 'revisit_when': revisit, 'status': 'deferred'}, general_id)
            deferred_doc = snapshot(page)
            deferred = idea(deferred_doc, general_id)
            check(deferred['notes'] == revised_notes and deferred['revisit_when'] == revisit
                  and deferred['status'] == 'deferred' and deferred['title'] == literal_title
                  and deferred_doc['tasks'] == base['tasks'],
                  'editing preserves context and records an explicitly deferred status')

            resolution = 'Illustrative decision: retain the current scope; reconsider if new evidence arrives.'
            submit_item(page, {'status': 'resolved', 'resolution': resolution}, general_id)
            resolved_doc = snapshot(page)
            resolved = idea(resolved_doc, general_id)
            check(resolved['status'] == 'resolved' and resolved['resolution'] == resolution
                  and resolved['notes'] == revised_notes and resolved['revisit_when'] == revisit,
                  'resolving an item preserves its context, revisit condition and written resolution')
            history(page, 'undo')
            check(snapshot(page) == deferred_doc,
                  'undo restores the preceding manual status and context together')
            history(page, 'redo')
            check(snapshot(page) == resolved_doc,
                  'redo restores the resolution without changing any research task')

            page.locator('#ideas-filter').select_option('all')
            open_item(page, linked_id)
            page.locator(f'[data-action=idea-delete][data-id="{linked_id}"]').click()
            expect(page.locator('#delete-idea-dialog')).to_be_visible()
            page.locator('#delete-idea-dialog').get_by_role('button', name='Cancel', exact=True).click()
            expect(page.locator('#delete-idea-dialog')).not_to_be_visible()
            expect(page.locator(f'[data-action=idea-delete][data-id="{linked_id}"]')).to_be_focused()
            check(snapshot(page) == resolved_doc,
                  'canceling an idea deletion preserves the item and all of its context')
            page.locator(f'[data-action=idea-delete][data-id="{linked_id}"]').click()
            page.locator('#delete-idea-form button[type=submit]').click()
            expect(page.locator('#delete-idea-dialog')).not_to_be_visible()
            deleted_doc = snapshot(page)
            check(deleted_doc['ideas'] == [entry for entry in resolved_doc['ideas'] if entry['id'] != linked_id]
                  and deleted_doc['tasks'] == resolved_doc['tasks'],
                  'confirmed deletion removes only the idea and keeps the linked operation intact')
            history(page, 'undo')
            check(snapshot(page) == resolved_doc,
                  'undo restores the deleted question with its notes and task association')

            yaml_doc = parse_project(downloaded(page, 'export-yaml'))
            check(yaml_doc == resolved_doc,
                  'YAML export preserves general and linked ideas, manual statuses and resolutions')
            saved_path = Path(temporary) / 'saved-ideas.html'
            saved_path.write_text(downloaded(page, 'save'), encoding='utf-8')
            reopened = opened(browser, saved_path)
            check(snapshot(reopened) == resolved_doc,
                  'Save copy and reopen retain every idea and the unchanged research workflow')
            expanded(reopened)
            expect(reopened.locator('.idea-details:visible')).to_have_count(0)
            reopened.locator('#ideas-filter').select_option('resolved')
            expect(reopened.locator(f'.idea-row[data-idea-id="{general_id}"]')).to_contain_text(literal_title)
            check(idea(snapshot(reopened), general_id)['resolution'] == resolution,
                  'the resolved item and its decision remain available after reopening')
            reopened.close()
            page.close()

            for width, height in [(390, 844), (700, 900)]:
                page = opened(browser, preview, width=width, height=height)
                mobile_base = snapshot(page)
                expanded(page)
                filter_control = page.locator('#ideas-filter')
                filter_control.focus()
                filter_control.select_option('all')
                expect(filter_control).to_be_focused()
                page.keyboard.press('Tab')
                expect(filter_control).not_to_be_focused()
                check(page.locator(':focus').evaluate(
                    'element => element.matches("button,a,input,select,textarea,[tabindex]")'),
                    f'filter changes retain keyboard focus and Tab advances at {width}px')
                expect(page.locator('.idea-details:visible')).to_have_count(0)
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth') and rows_are_clear(page)
                      and page.locator('.idea-row').evaluate_all('rows => rows.every(row => row.getBoundingClientRect().height <= 100)'),
                      f'the compact Ideas summaries fit without horizontal document overflow at {width}px')
                page.locator('[data-action=idea-add]').click()
                expect(page.locator('#idea-dialog')).to_be_visible()
                check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                      f'the idea form fits without horizontal document overflow at {width}px')
                page.locator('#idea-dialog').get_by_role('button', name='Cancel', exact=True).click()
                expect(page.locator('[data-action=idea-add]')).to_be_focused()
                toggle = open_item(page, 'batch-question')
                check(rows_are_clear(page) and page.evaluate('document.documentElement.scrollWidth <= innerWidth'),
                      f'expanded notes and actions remain readable without overflow at {width}px')
                edit = page.locator('[data-action=idea-edit][data-id=batch-question]')
                edit.click()
                expect(page.locator('#idea-dialog')).to_be_visible()
                page.keyboard.press('Escape')
                expect(page.locator('#idea-dialog')).not_to_be_visible()
                expect(edit).to_be_focused()
                check(snapshot(page) == mobile_base,
                      f'canceling Add and detail-based Edit restores focus without changing items at {width}px')
                submit_item(page, {'notes': 'Illustrative mobile undo check.'}, 'batch-question')
                history(page, 'undo')
                expect(page.locator('#ideas-panel')).to_be_visible()
                expect(page.locator('#ideas-heading')).to_be_focused()
                check(snapshot(page) == mobile_base,
                      f'keyboard undo restores an idea edit from the mobile panel at {width}px')
                page.locator('#ideas-filter').focus()
                page.keyboard.press('Escape')
                expect(page.locator('#ideas-panel')).not_to_be_visible()
                expect(page.locator('#ideas-button')).to_be_focused()
                check(not page.locator('.canvas-column').evaluate('el => el.inert'),
                      f'Escape from the filter closes Ideas and returns access to the workflow at {width}px')
                page.close()

            check(not ERRORS, 'idea interactions produce no script errors or unexpected dialogs')
            browser.close()
    (OUT / 'ideas-checks.json').write_text(json.dumps(
        {'count': len(CHECKS), 'checks': CHECKS, 'errors': ERRORS}, indent=2), encoding='utf-8')
    print('ALL', len(CHECKS), 'CHECKS PASSED', flush=True)


if __name__ == '__main__':
    run()
