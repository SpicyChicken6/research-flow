"""SVG snapshot regression tests: safe labels, model geometry, and pure rendering."""
import copy
import re
import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import validate_project
from workflow_plot import render_workflow_svg


SVG = '{http://www.w3.org/2000/svg}'


def document(tasks=None, positions=None):
    return validate_project({
        'schema_version': 1, 'project': {'name': 'Saved workflow'},
        'tasks': tasks or [], 'layout': {'positions': positions or {}},
    })


def groups(svg):
    return {node.get('data-task-id'): node for node in ET.fromstring(svg).iter(SVG + 'g')
            if node.get('data-task-id')}


def position(group):
    return tuple(float(value) for value in re.findall(r'-?\d+(?:\.\d+)?', group.get('transform')))


class WorkflowPlotTests(unittest.TestCase):
    def test_render_is_deterministic_and_does_not_modify_document(self):
        project = document([
            {'id': 'a', 'title': 'Plan', 'notes': 'PRIVATE NOTES', 'custom': {'keep': [1, 2]}},
            {'id': 'b', 'title': 'Run', 'depends_on': ['a'], 'parent_id': 'a'},
        ], {'a': {'x': 80, 'y': -10, 'custom': 'POSITION METADATA'}})
        project['project']['private'] = 'PROJECT SECRET'
        project['layout']['collapsed'] = ['a']
        project['layout']['focus'] = 'a'
        before = copy.deepcopy(project)
        for mode in ('stages', 'freeform'):
            svg = render_workflow_svg(project, mode)
            self.assertEqual(svg, render_workflow_svg(project, mode))
            self.assertEqual(set(groups(svg)), {'a', 'b'})
            for private in ('PRIVATE NOTES', 'PROJECT SECRET', 'POSITION METADATA'):
                self.assertNotIn(private, svg)
        self.assertEqual(project, before)

    def test_stage_positions_follow_dependency_ranks_and_browser_card_sizes(self):
        project = document([
            {'id': 'a', 'title': 'Plan'},
            {'id': 'b', 'title': 'Independent child', 'parent_id': 'a'},
            {'id': 'c', 'title': 'Run', 'depends_on': ['a']},
        ])
        cards = groups(render_workflow_svg(project))
        self.assertEqual(position(cards['a']), (24, 72))
        self.assertEqual(position(cards['b']), (38, 254))
        self.assertEqual(position(cards['c']), (396, 157))
        for key, expected in [('a', (240, 148)), ('b', (212, 136))]:
            rect = cards[key].find(SVG + 'rect')
            self.assertEqual((int(rect.get('width')), int(rect.get('height'))), expected)

    def test_hierarchy_and_dependency_have_distinct_meanings_and_styling(self):
        project = document([
            {'id': 'a', 'title': 'Parent'},
            {'id': 'b', 'title': 'Child', 'parent_id': 'a'},
            {'id': 'c', 'title': 'Dependent', 'depends_on': ['a']},
        ])
        root = ET.fromstring(render_workflow_svg(project))
        dependencies = [node for node in root.iter(SVG + 'path') if node.get('data-source')]
        hierarchy = [node for node in root.iter(SVG + 'path') if node.get('data-parent')]
        self.assertEqual([(node.get('data-source'), node.get('data-target')) for node in dependencies], [('a', 'c')])
        self.assertEqual([(node.get('data-parent'), node.get('data-child')) for node in hierarchy], [('a', 'b')])
        self.assertEqual(dependencies[0].get('class'), 'dependency')
        self.assertEqual(dependencies[0].get('marker-end'), 'url(#dependency-arrow)')
        self.assertEqual(hierarchy[0].get('class'), 'hierarchy')
        self.assertIsNone(hierarchy[0].get('marker-end'))
        self.assertIn('stroke-dasharray:5 5', root.find(SVG + 'style').text)
        self.assertEqual(hierarchy[0].get('d'), 'M 24 200 H 10 V 274 H 38')

    def test_numbering_matches_explicit_root_numbers_and_child_order(self):
        project = document([
            {'id': 'a', 'title': 'Explicit', 'step_number': 7},
            {'id': 'child', 'title': 'Child', 'parent_id': 'a'},
            {'id': 'grandchild', 'title': 'Grandchild', 'parent_id': 'child'},
            {'id': 'b', 'title': 'Implicit'},
        ])
        cards = groups(render_workflow_svg(project))
        self.assertEqual(list(cards), ['b', 'a', 'child', 'grandchild'])
        for key, number in [('b', '1'), ('a', '7'), ('child', '7.1'), ('grandchild', '7.1.1')]:
            texts = [node.text for node in cards[key].iter(SVG + 'text')]
            self.assertIn('STEP ' + number, texts)

    def test_freeform_keeps_saved_coordinates_and_fills_missing_children(self):
        project = document([
            {'id': 'a', 'title': 'Parent'},
            {'id': 'b', 'title': 'Child', 'parent_id': 'a'},
            {'id': 'c', 'title': 'Sibling', 'parent_id': 'a'},
        ], {'a': {'x': -400.25, 'y': 200.5}})
        cards = groups(render_workflow_svg(project, 'freeform'))
        self.assertEqual(position(cards['a']), (-400.25, 200.5))
        self.assertEqual(position(cards['b']), (-386, 435))
        self.assertEqual(position(cards['c']), (-386, 621))
        self.assertEqual(set(project['layout']['positions']), {'a'})

    def test_freeform_without_positions_uses_dependency_auto_layout(self):
        project = document([
            {'id': 'a', 'title': 'Start'},
            {'id': 'b', 'title': 'Next', 'depends_on': ['a']},
            {'id': 'c', 'title': 'Other start'},
        ])
        cards = groups(render_workflow_svg(project, 'freeform'))
        self.assertEqual(position(cards['a']), (0, 0))
        self.assertEqual(position(cards['b']), (316, 109))
        self.assertEqual(position(cards['c']), (0, 218))

    def test_freeform_without_positions_uses_hierarchy_auto_layout(self):
        project = document([
            {'id': 'a', 'title': 'Root'},
            {'id': 'b', 'title': 'Left', 'parent_id': 'a'},
            {'id': 'c', 'title': 'Right', 'parent_id': 'a'},
        ])
        cards = groups(render_workflow_svg(project, 'freeform'))
        self.assertEqual(position(cards['a']), (116, 0))
        self.assertEqual(position(cards['b']), (0, 234))
        self.assertEqual(position(cards['c']), (260, 234))

    def test_labels_are_xml_safe_and_no_executable_or_external_content_exists(self):
        label = '<script>alert("x")</script> & 研究 \x00 \ud800 \ufffe'
        project = document([{'id': 'a', 'title': label, 'goal': '<image href="https://example.test/a"/>'}])
        project['project']['name'] = label
        svg = render_workflow_svg(project)
        root = ET.fromstring(svg)
        self.assertIn('&lt;script&gt;', svg)
        self.assertIn('研究', svg)
        self.assertIn('\ufffd', svg)
        self.assertNotIn('\x00', svg)
        self.assertNotIn('\ud800', svg)
        self.assertNotIn('\ufffe', svg)
        self.assertFalse(svg.startswith('<?xml'))
        for node in root.iter():
            self.assertNotIn(node.tag.removeprefix(SVG), ('script', 'foreignObject', 'image', 'a'))
            self.assertFalse(any(key.startswith('on') or key.endswith('href') for key in node.attrib))
        self.assertEqual(root.get('data-layout'), 'stages')

    def test_long_unicode_labels_wrap_and_keep_full_accessible_text(self):
        long_title = '研究の結果と解析🧬' * 50
        project = document([{'id': 'a', 'title': long_title, 'goal': 'Long goal with spaces ' * 50}])
        card = groups(render_workflow_svg(project))['a']
        title_lines = [node.text for node in card.iter(SVG + 'text') if node.get('class') == 'card-title']
        goals = [node.text for node in card.iter(SVG + 'text') if node.get('class') == 'goal']
        self.assertEqual(len(title_lines), 2)
        self.assertEqual(len(goals), 2)
        self.assertTrue(title_lines[-1].endswith('…'))
        self.assertTrue(goals[-1].endswith('…'))
        self.assertIn(long_title, card.find(SVG + 'title').text)

    def test_wide_glyphs_wrap_and_all_card_labels_have_local_clip_guards(self):
        project = document([{'id': 'a', 'title': 'W' * 100, 'goal': 'M' * 100}])
        card = groups(render_workflow_svg(project))['a']
        titles = [node.text for node in card.iter(SVG + 'text') if node.get('class') == 'card-title']
        self.assertLessEqual(max(map(len, titles)), 16)
        clip = next(card.iter(SVG + 'clipPath'))
        guard = next(node for node in card.iter(SVG + 'g') if node.get('clip-path'))
        self.assertEqual(guard.get('clip-path'), 'url(#' + clip.get('id') + ')')
        self.assertEqual(len(list(guard.iter(SVG + 'text'))), len(list(card.iter(SVG + 'text'))))

    def test_empty_workflow_is_valid_and_has_project_title(self):
        for mode in ('stages', 'freeform'):
            root = ET.fromstring(render_workflow_svg(document(), mode))
            self.assertIn('No steps yet.', ''.join(root.itertext()))
            self.assertEqual(root.find(SVG + 'title').text, 'Saved workflow')
            self.assertGreater(float(root.get('width')), 0)
            self.assertGreater(float(root.get('height')), 0)

    def test_large_coordinates_fit_in_viewbox_with_bounded_intrinsic_dimensions(self):
        project = document([
            {'id': 'a', 'title': 'Start'}, {'id': 'b', 'title': 'End', 'depends_on': ['a']},
        ], {'a': {'x': 10000000, 'y': -10000000}, 'b': {'x': -10000000, 'y': 10000000}})
        svg = render_workflow_svg(project, 'freeform')
        root = ET.fromstring(svg)
        self.assertLessEqual(float(root.get('width')), 1600)
        self.assertLessEqual(float(root.get('height')), 1400)
        viewbox = [float(value) for value in root.get('viewBox').split()]
        self.assertGreater(viewbox[2], 20000000)
        self.assertGreater(viewbox[3], 20000000)
        self.assertAlmostEqual(float(root.get('width')) / float(root.get('height')),
                               viewbox[2] / viewbox[3], places=5)
        self.assertEqual(position(groups(svg)['a']), (10000000, -10000000))
        self.assertNotIn('nan', svg.lower())
        self.assertNotIn('inf', svg.lower())

    def test_maximum_depth_is_rendered_without_recursion(self):
        tasks = [{'id': 'root', 'title': 'Root'}]
        for index in range(499):
            tasks.append({'id': f'child{index}', 'title': 'Descendant', 'parent_id': tasks[-1]['id']})
        project = document(tasks)
        for mode in ('stages', 'freeform'):
            self.assertEqual(len(groups(render_workflow_svg(project, mode))), 500)

    def test_invalid_layout_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            render_workflow_svg(document(), 'unknown')


if __name__ == '__main__':
    unittest.main()
