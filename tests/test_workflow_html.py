"""Portable HTML rendering, data isolation, and safe embedded document content."""
import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import validate_project
from workflow_html import WEB, render_workflow_html


SAVED_AT = '2026-10-16T20:15:00Z'


class SnapshotParser(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.tags = []
        self.scripts = []
        self.title = ''
        self.current = None
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == 'script':
            self.scripts.append({'attrs': attrs, 'data': ''})
        self.current = tag

    def handle_endtag(self, tag):
        self.current = None

    def handle_data(self, data):
        if self.current == 'script':
            self.scripts[-1]['data'] += data
        if self.current == 'title':
            self.title += data


class HtmlSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.document = validate_project({
            'schema_version': 1,
            'project': {'name': 'Research study'},
            'tasks': [{'id': 'step', 'title': 'A research step', 'notes': 'Complete notes'}],
            'custom': {'preserve': ['Unknown', 'metadata']},
        })

    def render(self, **kwargs):
        return render_workflow_html(self.document, saved_at=SAVED_AT, **kwargs)

    def test_self_contained_snapshot_preserves_complete_document(self):
        content = self.render(layout_mode='freeform')
        parsed = SnapshotParser(content)
        initial = next(script for script in parsed.scripts if script['attrs'].get('id') == 'initial-project')
        self.assertEqual(json.loads(initial['data']), self.document)
        module = next(script for script in parsed.scripts if script['attrs'].get('type') == 'module')
        config = re.search(r'window.RESEARCH_FLOW_VIEWER = (.*?);\n', module['data'])
        self.assertEqual(json.loads(config[1]), {'saved_at': SAVED_AT, 'layout_mode': 'freeform'})
        for tag, attrs in parsed.tags:
            self.assertNotIn('src', attrs)
            if 'href' in attrs:
                self.assertTrue(attrs['href'].startswith(('#', 'data:')), attrs['href'])
        self.assertNotRegex(module['data'], r'(?m)^import\s', 'The standalone module cannot import local files.')
        self.assertEqual(parsed.title, 'Research study · Research Flow')

    def test_untrusted_text_cannot_escape_script_or_title_elements(self):
        attack = '</script><script>alert("injected")</script></title><img src="https://bad.example/pixel">'
        self.document['project']['name'] = attack
        self.document['tasks'][0]['notes'] = attack + '\u2028Unicode 🧬'
        parsed = SnapshotParser(self.render())
        self.assertEqual(len(parsed.scripts), 2)
        self.assertFalse(any(tag == 'img' for tag, attrs in parsed.tags))
        initial = next(script for script in parsed.scripts if script['attrs'].get('id') == 'initial-project')
        self.assertEqual(json.loads(initial['data']), self.document)
        self.assertEqual(parsed.title, attack + ' · Research Flow')

    def test_rendering_is_deterministic_and_preserves_project_and_source_assets(self):
        original = copy.deepcopy(self.document)
        assets = {path: path.read_bytes() for path in WEB.rglob('*') if path.is_file()}
        self.assertEqual(self.render(), self.render())
        self.assertEqual(self.document, original)
        self.assertEqual({path: path.read_bytes() for path in assets}, assets)

    def test_editable_copy_retains_existing_portable_mode(self):
        content = self.render(read_only=False)
        self.assertIn('window.RESEARCH_FLOW_PREVIEW = true;', content)
        self.assertNotIn('window.RESEARCH_FLOW_VIEWER = ', content)

    def test_invalid_layout_and_missing_snapshot_time_are_rejected(self):
        for layout in (None, '', 'other', {}, []):
            with self.subTest(layout=layout), self.assertRaises(ValueError):
                self.render(layout_mode=layout)
        with self.assertRaises(ValueError):
            render_workflow_html(self.document)


if __name__ == '__main__':
    unittest.main()
