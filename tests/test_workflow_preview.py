"""Persistence and failure behavior of the workflow's automatic SVG sidecar."""
import copy
import http.client
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from server import ConflictError, ProjectStore, ValidationError, make_handler


WORKFLOW = '''# Keep source comments until Save.
schema_version: 1
project:
  name: Initial workflow
tasks:
  - id: collect
    title: Collect evidence
  - id: analyze
    title: Analyze evidence
    depends_on: [collect]
  - id: review
    title: Review quality
    parent_id: analyze
custom:
  owner: Research team
layout:
  positions:
    collect: {x: 30, y: 70}
    analyze: {x: 600, y: 400}
'''


class PreviewStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / 'workflow.yaml'
        self.path.write_text(WORKFLOW)
        self.preview = self.path.with_suffix('.svg')
        self.store = ProjectStore(self.path)

    def save(self, name='Saved workflow', **kwargs):
        snapshot = self.store.read()
        snapshot['document']['project']['name'] = name
        return self.store.save(snapshot['document'], snapshot['revision'], **kwargs)

    def assertPreviewContains(self, text):
        tree = ET.fromstring(self.preview.read_bytes())
        self.assertEqual(tree.tag, '{http://www.w3.org/2000/svg}svg')
        self.assertIn(text, ''.join(tree.itertext()))

    def assertSuccessfulWarning(self, result, title):
        self.assertEqual(result['revision'], self.store.read()['revision'])
        self.assertEqual(result['document']['project']['name'], title)
        self.assertEqual(self.store.read()['document']['project']['name'], title)
        self.assertIsNone(result['preview_file'])
        self.assertTrue(result['preview_warning'])

    def test_read_preserves_source_and_does_not_create_or_refresh_preview(self):
        original = self.path.read_bytes()
        self.store.read()
        self.assertFalse(self.preview.exists())
        self.preview.write_text('A manually created picture')
        self.store.read()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.preview.read_text(), 'A manually created picture')

    def test_every_save_creates_or_replaces_readable_svg_without_mutating_draft(self):
        snapshot = self.store.read()
        snapshot['document']['project']['name'] = 'First saved workflow'
        draft = copy.deepcopy(snapshot['document'])
        result = self.store.save(snapshot['document'], snapshot['revision'])
        self.assertEqual(result['preview_file'], str(self.preview.resolve()))
        self.assertIsNone(result['preview_warning'])
        self.assertEqual(snapshot['document'], draft)
        self.assertEqual(result['document']['custom'], {'owner': 'Research team'})
        self.assertPreviewContains('First saved workflow')
        original = self.preview.read_bytes()
        result = self.save('Second saved workflow')
        self.assertNotEqual(self.preview.read_bytes(), original)
        self.assertPreviewContains('Second saved workflow')
        self.assertEqual(result['preview_file'], str(self.preview.resolve()))
        self.assertIsNone(result['preview_warning'])

    def test_yml_file_uses_matching_svg_stem(self):
        self.path = self.path.rename(self.path.with_name('my study.yml'))
        self.store = ProjectStore(self.path)
        result = self.save()
        self.assertEqual(Path(result['preview_file']), self.path.with_suffix('.svg'))
        self.assertTrue(self.path.with_suffix('.svg').is_file())

    def test_svg_permissions_do_not_expose_private_workflow(self):
        self.path.chmod(0o600)
        self.save()
        self.assertEqual(stat.S_IMODE(self.preview.stat().st_mode), 0o600)
        self.preview.chmod(0o644)
        self.save('Updated private workflow')
        self.assertEqual(stat.S_IMODE(self.preview.stat().st_mode), 0o600)

    def test_stale_revision_and_invalid_document_leave_both_files_untouched(self):
        stale = self.store.read()
        self.save()
        saved, preview = self.path.read_bytes(), self.preview.read_bytes()
        with self.assertRaises(ConflictError):
            self.store.save(stale['document'], stale['revision'])
        current = self.store.read()
        current['document']['tasks'][0]['depends_on'] = ['analyze']
        with self.assertRaises(ValidationError):
            self.store.save(current['document'], current['revision'])
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(self.preview.read_bytes(), preview)

    def test_invalid_preview_layout_is_rejected_before_saving(self):
        self.save()
        saved, preview = self.path.read_bytes(), self.preview.read_bytes()
        for layout in ('unknown', '', None, {}, []):
            with self.subTest(layout=layout):
                with self.assertRaises(ValidationError):
                    self.save('Must not save', preview_layout=layout)
                self.assertEqual(self.path.read_bytes(), saved)
                self.assertEqual(self.preview.read_bytes(), preview)

    def test_render_failure_keeps_old_preview_and_returns_new_revision(self):
        self.save()
        preview = self.preview.read_bytes()
        with mock.patch.object(server, 'render_workflow_svg', side_effect=ValueError('Cannot render preview')):
            result = self.save('Saved despite renderer failure')
        self.assertSuccessfulWarning(result, 'Saved despite renderer failure')
        self.assertEqual(self.preview.read_bytes(), preview)
        result['document']['project']['name'] = 'Recovered preview'
        recovered = self.store.save(result['document'], result['revision'])
        self.assertIsNone(recovered['preview_warning'])
        self.assertPreviewContains('Recovered preview')

    def test_preview_replace_failure_keeps_old_preview_and_cleans_temp_files(self):
        self.save()
        preview = self.preview.read_bytes()
        replace = os.replace

        def reject_preview(source, destination):
            if Path(destination) == self.preview:
                raise PermissionError('Preview is temporarily locked')
            return replace(source, destination)

        with mock.patch.object(server.os, 'replace', side_effect=reject_preview):
            result = self.save('Saved despite locked preview')
        self.assertSuccessfulWarning(result, 'Saved despite locked preview')
        self.assertEqual(self.preview.read_bytes(), preview)
        self.assertEqual(list(self.path.parent.glob('.*.tmp')), [])

    def test_workflow_replace_failure_never_refreshes_preview(self):
        self.save()
        saved, preview = self.path.read_bytes(), self.preview.read_bytes()
        with mock.patch.object(server.os, 'replace', side_effect=PermissionError('Workflow is locked')):
            with mock.patch.object(server, 'render_workflow_svg') as render:
                with self.assertRaises(PermissionError):
                    self.save('This workflow was not saved')
        render.assert_not_called()
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(self.preview.read_bytes(), preview)
        self.assertEqual(list(self.path.parent.glob('.*.tmp')), [])

    def test_existing_unowned_svg_is_preserved_and_workflow_still_saves(self):
        self.preview.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>My artwork</text></svg>')
        original = self.preview.read_bytes()
        result = self.save('Saved next to existing artwork')
        self.assertSuccessfulWarning(result, 'Saved next to existing artwork')
        self.assertEqual(self.preview.read_bytes(), original)

    def test_concurrent_new_svg_collision_is_preserved_and_workflow_still_saves(self):
        original_link = os.link
        artwork = '<svg xmlns="http://www.w3.org/2000/svg"><text>New artwork</text></svg>'

        def create_collision(source, destination, *args, **kwargs):
            if Path(destination) == self.preview:
                self.preview.write_text(artwork)
            return original_link(source, destination, *args, **kwargs)

        with mock.patch.object(server.os, 'link', side_effect=create_collision) as publish:
            result = self.save('Saved during new preview collision')
        publish.assert_called_once()
        self.assertSuccessfulWarning(result, 'Saved during new preview collision')
        self.assertEqual(self.preview.read_text(), artwork)
        self.assertEqual(list(self.path.parent.glob('.*.tmp')), [])

    def test_preview_only_retries_preserve_workflow_and_backup_history(self):
        self.preview.write_text('Existing artwork blocks automatic preview')
        result = self.save('Saved with unavailable preview')
        self.assertSuccessfulWarning(result, 'Saved with unavailable preview')
        saved_bytes, saved_mtime = self.path.read_bytes(), self.path.stat().st_mtime_ns
        backup_dir = self.path.parent / '.research-flow' / 'backups' / self.path.name
        backups = {path.name: path.read_bytes() for path in backup_dir.glob('*.yaml')}
        self.assertEqual(len(backups), 1)

        for _ in range(21):
            result = self.store.save(result['document'], result['revision'])
            self.assertSuccessfulWarning(result, 'Saved with unavailable preview')
        self.assertEqual(self.path.read_bytes(), saved_bytes)
        self.assertEqual(self.path.stat().st_mtime_ns, saved_mtime)
        self.assertEqual({path.name: path.read_bytes() for path in backup_dir.glob('*.yaml')}, backups)

        self.preview.unlink()
        result = self.store.save(result['document'], result['revision'])
        self.assertIsNone(result['preview_warning'])
        self.assertPreviewContains('Saved with unavailable preview')
        self.assertEqual(self.path.read_bytes(), saved_bytes)
        self.assertEqual(self.path.stat().st_mtime_ns, saved_mtime)
        self.assertEqual({path.name: path.read_bytes() for path in backup_dir.glob('*.yaml')}, backups)

    def test_preview_from_different_workflow_is_not_overwritten(self):
        self.save()
        other = self.path.with_name('other.yaml')
        other.write_text(WORKFLOW)
        other_preview = other.with_suffix('.svg')
        other_preview.write_bytes(self.preview.read_bytes())
        original = other_preview.read_bytes()
        store = ProjectStore(other)
        snapshot = store.read()
        result = store.save(snapshot['document'], snapshot['revision'])
        self.assertTrue(result['preview_warning'])
        self.assertIsNone(result['preview_file'])
        self.assertEqual(other_preview.read_bytes(), original)

    def test_svg_symlinks_and_directories_are_preserved(self):
        self.save()
        original = self.preview.read_bytes()
        target = self.path.with_name('personal.svg')
        # Even an otherwise owned preview must not be replaced through a symlink.
        target.write_bytes(original)
        self.preview.unlink()
        self.preview.symlink_to(target)
        result = self.save('Saved with symlink collision')
        self.assertSuccessfulWarning(result, 'Saved with symlink collision')
        self.assertTrue(self.preview.is_symlink())
        self.assertEqual(target.read_bytes(), original)
        self.preview.unlink()
        self.preview.mkdir()
        result = self.save('Saved with directory collision')
        self.assertSuccessfulWarning(result, 'Saved with directory collision')
        self.assertTrue(self.preview.is_dir())

    def test_workflow_named_svg_is_not_replaced_by_its_preview(self):
        self.path = self.path.rename(self.path.with_suffix('.svg'))
        self.store = ProjectStore(self.path)
        result = self.save('Still a YAML workflow')
        self.assertSuccessfulWarning(result, 'Still a YAML workflow')
        self.assertIn('schema_version: 1', self.path.read_text())


class PreviewHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / 'workflow.yaml'
        self.path.write_text(WORKFLOW)
        self.store = ProjectStore(self.path)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.store))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request_save(self, payload):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        self.addCleanup(conn.close)
        conn.request('PUT', '/api/project', json.dumps(payload),
                     {'Content-Type': 'application/json', 'X-Research-Flow': '1'})
        response = conn.getresponse()
        return response.status, json.loads(response.read())

    def test_save_request_applies_layout_and_returns_preview_path(self):
        snapshot = self.store.read()
        snapshot['preview_layout'] = 'freeform'
        with mock.patch.object(server, 'render_workflow_svg', wraps=server.render_workflow_svg) as render:
            status, result = self.request_save(snapshot)
        self.assertEqual(status, 200)
        self.assertEqual(result['preview_file'], str(self.path.with_suffix('.svg')))
        self.assertIsNone(result['preview_warning'])
        self.assertIn('freeform', [*render.call_args.args, *render.call_args.kwargs.values()])

    def test_preview_failure_is_http_success_with_current_workflow(self):
        snapshot = self.store.read()
        snapshot['document']['project']['name'] = 'Successful HTTP save'
        with mock.patch.object(server, 'render_workflow_svg', side_effect=OSError('Preview unavailable')):
            status, result = self.request_save(snapshot)
        self.assertEqual(status, 200)
        self.assertTrue(result['preview_warning'])
        self.assertIsNone(result['preview_file'])
        self.assertEqual(result['revision'], self.store.read()['revision'])
        self.assertEqual(result['document']['project']['name'], 'Successful HTTP save')
        self.assertFalse(self.path.with_suffix('.svg').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
