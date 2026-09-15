import unittest, sys, json, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import validate_project, parse_project, ProjectStore, ValidationError, ConflictError

def base():return {'schema_version':1,'project':{'name':'Test'},'tasks':[{'id':'a','title':'A'},{'id':'b','title':'B','parent_id':'a'},{'id':'c','title':'C','parent_id':'b'}]}
class ChildrenValidation(unittest.TestCase):
 def test_roundtrip(self):
  p=validate_project(base());self.assertEqual(parse_project(json.dumps(p)),p);self.assertEqual(p['tasks'][2]['parent_id'],'b')
 def test_parent_cycle(self):
  for v in ['a','b','c']:
   p=base();p['tasks'][0]['parent_id']=v
   with self.assertRaises(ValidationError):validate_project(p)
 def test_unknown_parent(self):
  p=base();p['tasks'][0]['parent_id']='missing'
  with self.assertRaises(ValidationError):validate_project(p)
 def test_invalid_parent_types(self):
  for v in [[],{},23,True,'']:
   p=base();p['tasks'][0]['parent_id']=v
   with self.assertRaises(ValidationError):validate_project(p)
 def test_parent_null(self):
  p=base();p['tasks'][0]['parent_id']=None;self.assertIsNone(validate_project(p)['tasks'][0]['parent_id'])
 def test_graphs_are_separate(self):
  p=base();p['tasks'][0]['depends_on']=['c'];self.assertEqual(validate_project(p)['tasks'][0]['depends_on'],['c'])
 def test_dependency_cycle(self):
  p=base();p['tasks'][0]['depends_on']=['c'];p['tasks'][2]['depends_on']=['a']
  with self.assertRaises(ValidationError):validate_project(p)
 def test_deep_hierarchy(self):
  p=base()
  for i in range(200):p['tasks'].append({'id':f'n{i}','title':'Deep','parent_id':p['tasks'][-1]['id']})
  self.assertEqual(len(validate_project(p)['tasks']),203)
 def test_legacy_conversion(self):
  p=base();p['tasks'][0]['substeps']=[{'id':'s','title':'Review','notes':'Do not lose','status':'done'}]
  q=validate_project(p);c=q['tasks'][-1];self.assertNotIn('substeps',q['tasks'][0]);self.assertEqual((c['parent_id'],c['notes'],c['status']),('a','Do not lose','done'));self.assertEqual(c['depends_on'],[]);self.assertEqual(validate_project(q),q);self.assertIn('substeps',p['tasks'][0])
 def test_legacy_id_collision_and_metadata(self):
  p=base();p['tasks'].append({'id':'a_s','title':'Original'});p['tasks'][0]['substeps']=[{'id':'s','title':'Review','other':[1,2]}]
  c=validate_project(p)['tasks'][-1];self.assertEqual(c['id'],'a_s_2');self.assertEqual(c['legacy_substep']['other'],[1,2])
 def test_empty_legacy_list(self):
  p=base();p['tasks'][0]['substeps']=[];q=validate_project(p);self.assertEqual(len(q['tasks']),3);self.assertNotIn('substeps',q['tasks'][0])
 def test_legacy_limit_is_atomic(self):
  p=base();p['tasks']=[{'id':f'n{i}','title':'N'} for i in range(500)];p['tasks'][0]['substeps']=[{'id':'a','title':'A'}]
  with self.assertRaisesRegex(ValidationError,'500-step'):validate_project(p)
  self.assertEqual(len(p['tasks']),500)
 def test_backup_keeps_original_before_conversion_save(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'project.yaml';p=base();p['tasks'][0]['substeps']=[{'id':'a','title':'Existing notes','notes':'Keep'}];raw=json.dumps(p);path.write_text(raw)
   store=ProjectStore(path);r=store.read();self.assertEqual(path.read_text(),raw);d=r['document'];d['project']['name']='Edited';store.save(d,r['revision']);saved=parse_project(path.read_text());self.assertEqual(saved['tasks'][-1]['notes'],'Keep');backups=[b for b in (Path(td)/'.research-flow').rglob('*.yaml') if b.is_file()];self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_text(),raw)
 def test_bad_parent_save_does_not_touch_disk(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'p.yaml';raw=json.dumps(base());path.write_text(raw);store=ProjectStore(path);r=store.read();p=r['document'];p['tasks'][0]['parent_id']='c'
   with self.assertRaises(ValidationError):store.save(p,r['revision'])
   self.assertEqual(path.read_text(),raw)
 def test_stale_revision_preserves_disk(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'p.yaml';path.write_text(json.dumps(base()));store=ProjectStore(path);r=store.read();path.write_text(json.dumps(base(),indent=2));raw=path.read_text()
   with self.assertRaises(ConflictError):store.save(r['document'],r['revision'])
   self.assertEqual(path.read_text(),raw)
if __name__=='__main__':unittest.main()
