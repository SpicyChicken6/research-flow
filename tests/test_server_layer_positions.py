import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import ProjectStore, ValidationError, parse_project, validate_project
from scripts.build_preview import build


def project():
    return {'schema_version': 1, 'project': {'name': 'Separate canvases'}, 'tasks': [
        {'id': 'a', 'title': 'Prepare'},
        {'id': 'b', 'title': 'Normalize', 'layer': 'operation', 'overview_id': 'a'},
        {'id': 'c', 'title': 'Scale', 'layer': 'processing', 'operation_id': 'b', 'depends_on': ['a'],
         'records': [{'id': 'record', 'recorded_at': '2026-10-16', 'status': 'recorded', 'method': 'Preserve history'}]},
    ], 'layout': {'positions': {'a': {'x': 0, 'y': 0}, 'b': {'x': 20, 'y': 30}, 'c': {'x': 40, 'y': 50}},
                  'custom': {'note': 'Keep this'}}}


def positions():
    return {'a': {'x': -10000000, 'y': 10000000}, 'b': {'x': -42.5, 'y': -25.25, 'custom': {'locked': True}}, 'c': {'x': 0, 'y': 0}}


class LayerPositionsValidation(unittest.TestCase):
    def test_negative_fractional_coordinates_and_metadata_roundtrip(self):
        p = project()
        p['layout']['layer_positions'] = positions()
        before = copy.deepcopy(p)
        q = validate_project(p)
        self.assertEqual(parse_project(json.dumps(q)), q)
        self.assertEqual(q['layout'], p['layout'])
        self.assertEqual(q['tasks'], validate_project(project())['tasks'])
        self.assertEqual(p, before)

    def test_old_documents_do_not_gain_layer_positions(self):
        self.assertNotIn('layer_positions', validate_project(project())['layout'])

    def test_invalid_maps_ids_and_coordinates(self):
        for value in [None, [], 'text', 42, {'missing': {'x': 0, 'y': 0}}, {'a': None}, {'a': []}, {'a': {}},
                      {'a': {'x': 0}}, {'a': {'x': '0', 'y': 0}}, {'a': {'x': True, 'y': 0}},
                      {'a': {'x': 10000000.1, 'y': 0}}, {'a': {'x': 0, 'y': -10000000.1}},
                      {'a': {'x': float('inf'), 'y': 0}}, {'a': {'x': 0, 'y': float('nan')}}]:
            with self.subTest(value=value):
                p = project()
                p['layout']['layer_positions'] = value
                with self.assertRaises(ValidationError):
                    validate_project(p)

    def test_save_load_and_portable_html_keep_both_layouts_and_all_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'workflow.yaml'
            p = project()
            p['layout']['layer_positions'] = positions()
            raw = json.dumps(p)
            path.write_text(raw)
            store = ProjectStore(path)
            state = store.read()
            self.assertEqual(path.read_text(), raw)
            original_tasks = copy.deepcopy(state['document']['tasks'])
            original_graph_positions = copy.deepcopy(state['document']['layout']['positions'])
            state['document']['layout']['layer_positions']['c'] = {'x': -190.5, 'y': 242.25}
            store.save(state['document'], state['revision'])
            saved = store.read()['document']
            self.assertEqual(saved['tasks'], original_tasks)
            self.assertEqual(saved['layout']['positions'], original_graph_positions)
            self.assertEqual(saved['layout']['layer_positions'], state['document']['layout']['layer_positions'])
            html = build(path, Path(directory) / 'workflow.html').read_text()
            embedded = re.search(r'<script id="initial-project" type="application/json">(.*?)</script>', html, re.S)
            self.assertIsNotNone(embedded)
            self.assertEqual(validate_project(json.loads(embedded.group(1))), saved)

    @unittest.skipUnless(shutil.which('node'), 'Node required for cross-language contract verification')
    def test_python_javascript_and_yaml_contracts_match(self):
        p = project()
        p['layout']['layer_positions'] = positions()
        cases = [project(), p]
        for value in [{}, None, [], {'missing': {'x': 0, 'y': 0}}, {'a': {'x': True, 'y': 0}},
                      {'a': {'x': -10000000.1, 'y': 0}}, {'a': {'x': 0, 'y': '1'}}]:
            item = project()
            item['layout']['layer_positions'] = value
            cases.append(item)
        expected = []
        for item in cases:
            try:
                expected.append({'valid': True, 'document': validate_project(item)})
            except ValidationError:
                expected.append({'valid': False})
        script = """
import {validateProject, toYaml} from './web/model.mjs';
let input = ''; for await (const chunk of process.stdin) input += chunk;
console.log(JSON.stringify(JSON.parse(input).map(value => {
  try { const document = validateProject(value); return {valid: true, document, yaml: toYaml(document)}; }
  catch { return {valid: false}; }
})));
"""
        result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                                input=json.dumps(cases), capture_output=True, text=True, check=True)
        actual = json.loads(result.stdout)
        for entry in actual:
            if entry['valid']:
                self.assertEqual(parse_project(entry.pop('yaml')), entry['document'])
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
