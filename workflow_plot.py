"""Portable, deterministic SVG snapshots of validated Research Flow documents.

Geometry follows the browser's model layouts. Rendering never changes the document,
uses no browser or font dependency, and only includes the workflow's visible labels.
"""
from __future__ import annotations

from collections import defaultdict
import html
import math
import re
import unicodedata


_STATUS = {
    'todo': ('To do', '#8598a7'),
    'in_progress': ('In progress', '#f3b705'),
    'blocked': ('Blocked', '#bd655a'),
    'done': ('Done', '#0a7abf'),
}


def _xml(value):
    # Validation permits arbitrary strings; XML 1.0 does not permit every Unicode
    # code point (including lone surrogates). Replace those without losing labels.
    return html.escape(''.join(
        char if char in '\t\n\r' or 0x20 <= ord(char) <= 0xD7FF
        or 0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF
        else '\ufffd' for char in str(value)), quote=True)


def _n(value):
    """Stable, compact SVG coordinates, including negative freeform positions."""
    return f'{value:.3f}'.rstrip('0').rstrip('.') if value else '0'


def _size(task):
    return (212, 136) if task.get('parent_id') else (240, 148)


def _outline(tasks):
    children = defaultdict(list)
    roots = [task for task in tasks if not task.get('parent_id')]
    used = {task['step_number'] for task in roots if 'step_number' in task}
    numbers, next_number = {}, 1
    for task in roots:
        if 'step_number' in task:
            numbers[task['id']] = task['step_number']
        else:
            while next_number in used:
                next_number += 1
            numbers[task['id']] = next_number
            used.add(next_number)
            next_number += 1
    for task in tasks:
        children[task.get('parent_id')].append(task)
    pending = [(task, str(numbers[task['id']]), 0)
               for task in sorted(roots, key=lambda task: numbers[task['id']], reverse=True)]
    rows = []
    while pending:
        task, number, depth = pending.pop()
        rows.append((task, number, depth))
        pending.extend((child, f'{number}.{index + 1}', depth + 1)
                       for index, child in reversed(list(enumerate(children[task['id']]))))
    return rows


def _ranks(tasks, root_ids=None):
    selected = [task for task in tasks if root_ids is None or task['id'] in root_ids]
    ranks = {task['id']: 0 for task in selected}
    dependents, remaining = defaultdict(list), {}
    for task in selected:
        dependencies = [source for source in task['depends_on'] if source in ranks]
        remaining[task['id']] = len(dependencies)
        for source in dependencies:
            dependents[source].append(task['id'])
    ready = [task['id'] for task in selected if not remaining[task['id']]]
    for source in ready:
        for target in dependents[source]:
            ranks[target] = max(ranks[target], ranks[source] + 1)
            remaining[target] -= 1
            if not remaining[target]:
                ready.append(target)
    return ranks


def _stage_layout(tasks, outline):
    ranks, columns = _ranks(tasks), defaultdict(list)
    for task, _, _ in outline:
        columns[ranks[task['id']]].append(task)
    measured = []
    for index, column in sorted(columns.items()):
        sizes = [_size(task) for task in column]
        measured.append((index, column, max(size[0] for size in sizes) + 48,
                         sum(size[1] for size in sizes) + (len(column) - 1) * 34))
    content_height = max((column[3] for column in measured), default=0)
    positions, stages, x = {}, [], 0
    for index, column, width, height in measured:
        y = 72 + (content_height - height) / 2
        for task in column:
            task_width, task_height = _size(task)
            positions[task['id']] = (x + (width - task_width) / 2, y)
            y += task_height + 34
        stages.append((index, x, 0, width, content_height + 96))
        x += width + 84
    return positions, stages


def _auto_positions(tasks, outline):
    if not any(task.get('parent_id') for task in tasks):
        ranks, columns = _ranks(tasks), defaultdict(list)
        for task in tasks:
            columns[ranks[task['id']]].append(task)
        rows = max((len(column) for column in columns.values()), default=1)
        return {task['id']: (level * 316, row * 218 + (rows - len(column)) * 109)
                for level, column in columns.items() for row, task in enumerate(column)}
    children = defaultdict(list)
    roots = [task for task in tasks if not task.get('parent_id')]
    for task in tasks:
        children[task.get('parent_id')].append(task)
    widths, heights = {}, {}
    # Reverse preorder measures every child before its parent, without a recursion
    # limit for the maximum supported 500-node hierarchy.
    for task, _, _ in reversed(outline):
        descendants = children[task['id']]
        width, height = _size(task)
        widths[task['id']] = max(width, sum(widths[child['id']] for child in descendants)
                                + max(0, len(descendants) - 1) * 48)
        heights[task['id']] = height + (86 + max(heights[child['id']] for child in descendants)
                                        if descendants else 0)
    ranks = _ranks(tasks, {task['id'] for task in roots})
    columns = defaultdict(list)
    for task in roots:
        columns[ranks[task['id']]].append(task)
    positions, x = {}, 0
    for _, column in sorted(columns.items()):
        width, y = max(widths[task['id']] for task in column), 0
        for root in column:
            pending = [(root, x + (width - widths[root['id']]) / 2, y)]
            while pending:
                task, left, top = pending.pop()
                task_width, task_height = _size(task)
                positions[task['id']] = (math.floor(left + (widths[task['id']] - task_width) / 2 + .5),
                                         math.floor(top + .5))
                descendants = children[task['id']]
                total = sum(widths[child['id']] for child in descendants) + max(0, len(descendants) - 1) * 48
                child_x = left + (widths[task['id']] - total) / 2
                for child in descendants:
                    pending.append((child, child_x, top + task_height + 86))
                    child_x += widths[child['id']] + 48
            y += heights[root['id']] + 100
        x += width + 120
    return positions


def _freeform_positions(document, outline):
    tasks = document['tasks']
    saved = document.get('layout', {}).get('positions', {})
    positions = {task['id']: (saved[task['id']]['x'], saved[task['id']]['y'])
                 for task in tasks if task['id'] in saved}
    arranged = _auto_positions(tasks, outline)
    if not positions:
        return arranged
    by_id = {task['id']: task for task in tasks}
    for task in tasks:
        missing, current = [], task
        while current['id'] not in positions:
            missing.append(current)
            parent = by_id.get(current.get('parent_id'))
            if parent is None:
                break
            current = parent
        for current in reversed(missing):
            width, height = _size(current)
            parent = by_id.get(current.get('parent_id'))
            if parent:
                px, py = positions[parent['id']]
                pw, ph = _size(parent)
                x, y = px + (pw - width) / 2, py + ph + 86
            else:
                x, y = arranged[current['id']]
            while any(x < px + _size(by_id[key])[0] + 26 and x + width + 26 > px
                      and y < py + _size(by_id[key])[1] + 26 and y + height + 26 > py
                      for key, (px, py) in positions.items()):
                y += height + 50
            positions[current['id']] = (math.floor(x + .5), math.floor(y + .5))
    return positions


def _units(text):
    """Conservative system-font width estimate, counting wide Unicode characters."""
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in 'WF'
               else 1.65 if char in 'WM@#%&' else 1.4 if char == 'm' else 1.3 if char == 'w'
               else 1.15 if char.isupper() else 1 for char in text)


def _wrap(text, width, max_lines):
    """Wrap normal prose and unbroken labels without depending on local fonts."""
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []
    lines = []
    while text and len(lines) < max_lines:
        consumed, units = 0, 0
        for char in text:
            units += _units(char)
            if units > width:
                break
            consumed += 1
        if consumed == len(text):
            lines.append(text)
            text = ''
        else:
            stop = text.rfind(' ', 0, consumed + 1)
            stop = stop if stop > consumed / 2 else max(consumed, 1)
            lines.append(text[:stop].rstrip())
            text = text[stop:].lstrip()
    if text:
        while lines[-1] and _units(lines[-1]) + 1 > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] = lines[-1].rstrip(' .') + '…'
    return lines


def _text_lines(lines, x, y, line_height, css_class):
    return ''.join(f'<text class="{css_class}" x="{_n(x)}" y="{_n(y + index * line_height)}">'
                   f'{_xml(line)}</text>' for index, line in enumerate(lines))


def render_workflow_svg(document, layout_mode='stages'):
    """Return a standalone SVG of all steps in an already validated document.

    ``stages`` matches the browser's dependency layout. ``freeform`` preserves
    saved positions and fills absent ones using the browser's arrangement rules.
    Unknown metadata, notes, inputs, and outputs are intentionally not exported.
    """
    if layout_mode not in ('stages', 'freeform'):
        raise ValueError('layout_mode must be stages or freeform.')
    tasks = document['tasks']
    outline = _outline(tasks)
    if layout_mode == 'stages':
        positions, stages = _stage_layout(tasks, outline)
    else:
        positions, stages = _freeform_positions(document, outline), []
    by_id = {task['id']: task for task in tasks}
    edges, bounds = [], []
    for task in tasks:
        x, y = positions[task['id']]
        width, height = _size(task)
        bounds.extend([(x, y), (x + width, y + height)])
        for source in task['depends_on']:
            sx, sy = positions[source]
            sw, sh = _size(by_id[source])
            sx, sy, tx, ty = sx + sw, sy + sh / 2, x, y + height / 2
            curve = max(55, abs(tx - sx) * .5)
            bounds.extend([(sx + curve, sy), (tx - curve, ty)])
            path = f'M {_n(sx)} {_n(sy)} C {_n(sx + curve)} {_n(sy)}, {_n(tx - curve)} {_n(ty)}, {_n(tx)} {_n(ty)}'
            edges.append(f'<path class="dependency" data-source="{_xml(source)}" data-target="{_xml(task["id"])}" '
                         f'd="{path}" marker-end="url(#dependency-arrow)"/>')
        parent = task.get('parent_id')
        if parent:
            px, py = positions[parent]
            pw, ph = _size(by_id[parent])
            if layout_mode == 'stages' and abs(px - x) < max(pw, width):
                gutter = min(px, x) - 14
                bounds.extend([(gutter, py + ph - 20), (gutter, y + 20)])
                path = f'M {_n(px)} {_n(py + ph - 20)} H {_n(gutter)} V {_n(y + 20)} H {_n(x)}'
            else:
                sx, sy, tx, ty = px + pw / 2, py + ph, x + width / 2, y
                middle = (sy + ty) / 2
                path = f'M {_n(sx)} {_n(sy)} C {_n(sx)} {_n(middle)}, {_n(tx)} {_n(middle)}, {_n(tx)} {_n(ty)}'
            edges.append(f'<path class="hierarchy" data-parent="{_xml(parent)}" data-child="{_xml(task["id"])}" d="{path}"/>')
    for _, x, y, width, height in stages:
        bounds.extend([(x, y), (x + width, y + height)])
    left = min((p[0] for p in bounds), default=0)
    top = min((p[1] for p in bounds), default=0)
    right = max((p[0] for p in bounds), default=640)
    bottom = max((p[1] for p in bounds), default=100)
    graph_width, graph_height = right - left, bottom - top
    width = max(720, graph_width + 80)
    project_name = document['project']['name']
    title_lines = _wrap(project_name, min(88, int((width - 80) / 15)), 3)
    heading_height = 72 + len(title_lines) * 32
    height = heading_height + graph_height + 110
    title = _xml(project_name)
    scale = min(1, 1600 / width, 1400 / height)
    result = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(width * scale)}" '
              f'height="{_n(height * scale)}" viewBox="0 0 {_n(width)} {_n(height)}" '
              f'role="img" data-layout="{layout_mode}" aria-labelledby="workflow-title workflow-description">',
              f'<title id="workflow-title">{title}</title>',
              f'<desc id="workflow-description">Saved workflow with {len(tasks)} steps. '
              'Solid arrows show dependencies. Dashed lines show parent-child hierarchy.</desc>',
              '<defs><marker id="dependency-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
              'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
              '<path d="M 0 0 L 10 5 L 0 10 z" fill="#647785"/></marker></defs>',
              '<style>text{font-family:Arial,Helvetica,sans-serif;fill:#243746}'
              '.heading{font-size:26px;font-weight:700}.subtitle{font-size:13px;fill:#617483}'
              '.stage{fill:#f5f8fa;stroke:#dce5eb;stroke-width:1}'
              '.stage-label{font-size:12px;font-weight:700;fill:#657d8e;letter-spacing:1px}'
              '.dependency{fill:none;stroke:#647785;stroke-width:2}'
              '.hierarchy{fill:none;stroke:#9aaaba;stroke-width:1.5;stroke-dasharray:5 5}'
              '.card{fill:white;stroke:#cfdbe4;stroke-width:1.2}'
              '.number{font-size:11px;fill:#627787;font-weight:700}'
              '.card-title{font-size:14px;font-weight:700}'
              '.goal{font-size:12px;fill:#627787}.status{font-size:11px;fill:#4b6071}'
              '.legend{font-size:12px;fill:#617483}</style>',
              f'<rect width="{_n(width)}" height="{_n(height)}" fill="#ffffff"/>',
              _text_lines(title_lines, 40, 48, 32, 'heading'),
              f'<text class="subtitle" x="40" y="{heading_height - 25}">'
              f'Research Flow · {len(tasks)} step{"s" if len(tasks) != 1 else ""} · '
              f'{"Dependency stages" if layout_mode == "stages" else "Freeform layout"}</text>',
              f'<g id="workflow-graph" transform="translate({_n(40 - left)} {_n(heading_height - top)})">']
    for index, x, y, stage_width, stage_height in stages:
        result.append(f'<rect class="stage" x="{_n(x)}" y="{_n(y)}" width="{_n(stage_width)}" '
                      f'height="{_n(stage_height)}" rx="16"/>')
        result.append(f'<text class="stage-label" x="{_n(x + 24)}" y="{_n(y + 30)}">STAGE {index + 1}</text>')
    result.extend(edges)
    for card_index, (task, number, depth) in enumerate(outline):
        x, y = positions[task['id']]
        card_width, card_height = _size(task)
        status, color = _STATUS[task['status']]
        tooltip = f'{number}. {task["title"]}\n{status}'
        if task.get('goal'):
            tooltip += '\n' + task['goal']
        result.extend([f'<g class="task" data-task-id="{_xml(task["id"])}" data-depth="{depth}" '
                       f'transform="translate({_n(x)} {_n(y)})">',
                       f'<title>{_xml(tooltip)}</title>',
                       f'<rect class="card" width="{card_width}" height="{card_height}" rx="12"/>',
                       f'<rect x="0" y="16" width="4" height="{card_height - 32}" rx="2" fill="{color}"/>',
                       f'<defs><clipPath id="card-labels-{card_index}"><rect x="12" y="8" '
                       f'width="{card_width - 24}" height="{card_height - 16}"/></clipPath></defs>',
                       f'<g clip-path="url(#card-labels-{card_index})">'])
        number_label = _wrap(f'STEP {number}', int((card_width - 32) / 7), 1)
        result.append(_text_lines(number_label, 16, 25, 13, 'number'))
        result.append(_text_lines(_wrap(task['title'], int((card_width - 32) / 8.3), 2), 16, 48, 18, 'card-title'))
        result.append(_text_lines(_wrap(task.get('goal', ''), int((card_width - 32) / 7.2), 2), 16, 87, 15, 'goal'))
        result.extend([f'<circle cx="20" cy="{card_height - 20}" r="4" fill="{color}"/>',
                       f'<text class="status" x="30" y="{card_height - 16}">{status}</text></g></g>'])
    if not tasks:
        result.append('<text class="subtitle" x="0" y="48">No steps yet.</text>')
    legend_y = height - 45
    result.extend(['</g>',
                   f'<path class="dependency" d="M 40 {_n(legend_y - 4)} H 76" marker-end="url(#dependency-arrow)"/>',
                   f'<text class="legend" x="88" y="{_n(legend_y)}">Dependency</text>',
                   f'<path class="hierarchy" d="M 208 {_n(legend_y - 4)} H 244"/>',
                   f'<text class="legend" x="256" y="{_n(legend_y)}">Parent / child</text>', '</svg>\n'])
    return '\n'.join(result)
