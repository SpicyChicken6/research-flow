#!/usr/bin/env python3
"""Browser checks for real child cards. All projects used here are disposable."""
from pathlib import Path
from tempfile import TemporaryDirectory
from http.server import ThreadingHTTPServer
import json,re,sys,threading,http.client,os,shutil
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from server import parse_project,ProjectStore,make_handler
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
HTML=(ROOT/'dist/research-flow.html').read_text()
CHECKS=[];ERRORS=[]
def check(value,label):
 if not value:raise AssertionError(label)
 CHECKS.append(label);print('PASS',label,flush=True)
def opened(b,html=HTML,width=1600,height=1000):
 p=b.new_page(viewport={'width':width,'height':height},accept_downloads=True,reduced_motion='reduce');p.set_default_timeout(5000);p.on('pageerror',lambda e:ERRORS.append(str(e)));p.set_content(html,wait_until='load');expect(p.locator('#save-button')).to_be_enabled();return p
def snap(p):
 p.locator('#more-menu summary').click()
 with p.expect_download() as d:p.locator('[data-action=export-json]').click()
 return json.loads(Path(d.value.path()).read_text())
def task(doc,id):return next(t for t in doc['tasks'] if t['id']==id)
def go(p,id):
 p.locator(f'.task-node[data-id="{id}"]').focus();p.keyboard.press('Enter');expect(p.locator('#inspector')).to_be_visible()
def overview(p):
 if p.locator('#inspector').is_visible():p.locator('[data-action=close-inspector]').click()
 p.locator('#overview-button').click()
def newchild(p,id):
 go(p,id);p.locator('#inspector [data-action=add-child]').click();d=snap(p);return d['tasks'][-1]['id'],d
def rect(p,id):return p.locator(f'.task-node[data-id="{id}"]').bounding_box()
def drag_node(p,id,dx=45,dy=24):
 a=rect(p,id);p.mouse.move(a['x']+a['width']*.4,a['y']+a['height']*.4);p.mouse.down();p.mouse.move(a['x']+a['width']*.4+dx,a['y']+a['height']*.4+dy,steps=10);p.mouse.up()
def edge(p,key):
 p.locator(f'[data-edge="{key}"]').focus();p.keyboard.press('Enter');expect(p.locator('#connection-form')).to_be_visible()
with sync_playwright() as pw:
 b=pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
 p=opened(b);base=snap(p)
 check(p.locator('.task-node').count()==8,'eight ordinary cards make up the sample project')
 check(p.locator('.child-node').count()==5 and p.locator('.hierarchy-hit').count()==5,'five children have real hierarchy branches')
 check(p.locator('.edge-hit[data-edge]').count()==4,'only explicit dependencies have arrows')
 check(p.locator('.substeps-section,.substep-row,.node-substeps,[data-action=add-substep]').count()==0,'previous checklist editor and badges are absent')
 check(not p.locator('#inspector').is_visible(),'initial view remains a quiet canvas without details')
 check(all(not re.search(r'\d',x) for x in p.locator('.task-index').all_text_contents()),'no hierarchical numbers or decorative depth patterns')
 root=rect(p,'analysis');child=rect(p,'preparation');grand=rect(p,'metadata')
 check(child['width']<root['width'] and child['height']<root['height'],'child cards are physically smaller, not a scaled canvas')
 check(abs(child['width']-grand['width'])<.1 and abs(child['height']-grand['height'])<.1,'grandchildren keep the same readable child dimensions')
 check(p.locator('.child-node h3').first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')>=14,'child titles retain at least 14 px CSS type')
 p.screenshot(path=str(OUT/'children-overview.png'))
 p.locator('#add-button').click();d=snap(p);new=d['tasks'][-1]
 check(len(d['tasks'])==9 and new['title']=='Untitled step' and not new.get('parent_id'),'Add step still places an independent blank block immediately')
 check(not p.locator('#inspector').is_visible() and p.locator('dialog[open]').count()==0,'blank creation does not open a dialog or inspector')
 p.locator('#undo-button').click();check(snap(p)==base,'undo reverses blank insertion')
 childid,d=newchild(p,'analysis')
 check(task(d,childid)['parent_id']=='analysis' and task(d,childid)['depends_on']==[],'Add child assigns parent only, never an implicit dependency')
 check(not p.locator('#inspector').is_visible(),'child creation follows place-first, edit-later behavior')
 go(p,childid);p.locator('[data-field=title]').fill('Confirm provenance');p.locator('[data-field=goal]').fill('Validate source versions');p.locator('[data-field=status]').select_option('in_progress');p.locator('#resources-tab').click();p.locator('[data-field=notes]').fill('Keep records\nSecond line');p.locator('[data-field=inputs]').fill('data/source.tsv');p.locator('[data-field=outputs]').fill('notes/provenance.md')
 d=snap(p);check(task(d,childid)['notes']=='Keep records\nSecond line' and task(d,childid)['inputs']==['data/source.tsv'],'child notes and file references use the existing task editor')
 p.locator('#plan-tab').click();p.locator('#inspector [data-action=add-child]').click();d=snap(p);grandchild=d['tasks'][-1]['id']
 check(task(d,grandchild)['parent_id']==childid,'a newly added child can immediately have its own child')
 go(p,grandchild);p.locator('[data-field=title]').fill('Record source checksum');p.locator('[data-field=status]').select_option('done');d=snap(p)
 check(task(d,childid)['status']=='in_progress' and task(d,'analysis')['status']=='in_progress','descendant completion does not overwrite parent status')
 p.locator('#parent-step').select_option('preparation');d=snap(p);check(task(d,grandchild)['parent_id']=='preparation','Part of can move an existing step to a different parent')
 p.locator('#undo-button').click();check(task(snap(p),grandchild)['parent_id']==childid,'undo restores prior parentage')
 # Parent candidates exclude self and descendants.
 go(p,'analysis');opts=p.locator('#parent-step option').evaluate_all('es=>es.map(e=>e.value)')
 check('analysis' not in opts and 'preparation' not in opts and grandchild not in opts,'Parent selector excludes self and all descendants')
 go(p,grandchild);p.locator('#parent-step').select_option('');d=snap(p)
 check(not task(d,grandchild).get('parent_id') and not p.locator(f'.task-node[data-id={grandchild}]').evaluate("e=>e.classList.contains('child-node')"),'clearing parent promotes a card to main-step size')
 p.locator('#undo-button').click();go(p,grandchild);p.locator('#add-dependency').select_option('question');d=snap(p)
 check(task(d,grandchild)['depends_on']==['question'] and task(d,grandchild)['parent_id']==childid,'dependency editing does not alter hierarchy')
 # Save-copy roundtrip.
 with p.expect_download() as dl:p.locator('#save-button').click()
 saved=Path(dl.value.path()).read_text();q=opened(b,saved)
 check(snap(q)==d,'Save copy reopens with hierarchy, positions, statuses and details intact')
 check(q.locator('.child-node').count()==7,'saved copy renders the new child cards without the old checklist')
 q.close();p.close()
 # View operations, collapsed dependencies and drag behavior.
 p=opened(b);base=snap(p);go(p,'preparation');p.locator('#focus-button').click()
 check(p.locator('.task-node[data-id=metadata]').is_visible() and p.locator('.task-node[data-id=batches]').is_visible(),'Focus includes the selected step’s descendants')
 check(p.locator('.task-node[data-id=analysis]').is_visible(),'Focus retains the selected step’s parent context')
 check(snap(p)==base,'Focus leaves hierarchy, data and layout unchanged')
 p.screenshot(path=str(OUT/'children-focus.png'))
 check(p.locator('.task-node[data-id=model] .children-toggle').get_attribute('aria-expanded')=='false','off-focus descendants are honestly marked as hidden')
 p.locator('.task-node[data-id=model] .children-toggle').click()
 check(p.locator('.task-node[data-id=sensitivity]').is_visible(),'expanding a dependency neighbor brings its children into Focus')
 check(snap(p)==base,'changing the focused branch changes presentation only')
 overview(p)
 go(p,'synthesis');p.locator('#add-dependency').select_option('metadata');base=snap(p);overview(p)
 p.locator('.task-node[data-id=analysis] .children-toggle').click()
 check(p.locator('.task-node:visible').count()==3,'collapsing the main parent hides all levels of descendants')
 check(p.locator('[data-bundle="analysis|synthesis"] text').text_content()=='2 hidden links','collapsed boundary exposes a bundled count of actual dependencies')
 check(snap(p)==base,'collapsing and bundled links do not create fake parent dependencies')
 p.locator('.bundle-label[data-bundle="analysis|synthesis"]').focus();p.keyboard.press('Enter')
 check(p.locator('.task-node[data-id=metadata]').is_visible() and p.locator('[data-edge="metadata|synthesis"]').count()==1,'opening a hidden-link label reveals its true endpoints')
 check(snap(p)==base,'revealing a dependency bundle does not mutate project data')
 overview(p);p.locator('.task-node[data-id=preparation] .children-toggle').click();check(p.locator('.task-node:visible').count()==6,'nested collapse hides just that subtree')
 p.locator('.task-node[data-id=preparation] .children-toggle').click();check(p.locator('.task-node:visible').count()==8,'nested expansion restores its descendant cards')
 base=snap(p);drag_node(p,'preparation');moved=snap(p)
 delta={k:moved['layout']['positions']['preparation'][k]-base['layout']['positions']['preparation'][k] for k in ['x','y']}
 check(delta['x']!=0,'dragging parent changes its position')
 check(all(all(moved['layout']['positions'][id][k]-base['layout']['positions'][id][k]==delta[k] for k in ['x','y']) for id in ['metadata','batches']),'parent drag moves its whole subtree by the same offset')
 check(moved['layout']['positions']['model']==base['layout']['positions']['model'],'dragging parent does not move dependency neighbors')
 check(not p.locator('#inspector').is_visible(),'branch drag does not open details mid-gesture')
 p.locator('#undo-button').click();check(snap(p)==base,'one undo restores the entire dragged branch')
 p.locator('#redo-button').click();check(snap(p)==moved,'redo restores whole-branch movement');p.locator('#undo-button').click()
 # Drag a dependency from a child; endpoints must use child size.
 overview(p);a=p.locator('.port.out[data-id=batches]').bounding_box();z=p.locator('.port.in[data-id=model]').bounding_box();p.mouse.move(a['x']+a['width']/2,a['y']+a['height']/2);p.mouse.down();p.mouse.move(z['x']+z['width']/2,z['y']+z['height']/2,steps=12);p.mouse.up();d=snap(p)
 check('batches' in task(d,'model')['depends_on'],'dragging from a smaller child port creates a dependency')
 check(task(d,'model')['parent_id']=='analysis','drag-connect does not reparent the target')
 edge(p,'batches|model');p.locator('#connection-target').select_option('synthesis');p.locator('#connection-form button[type=submit]').click();d=snap(p)
 check('batches' in task(d,'synthesis')['depends_on'] and 'batches' not in task(d,'model')['depends_on'],'existing connection editor rewires edges between mixed-size cards')
 p.locator('#undo-button').click();p.locator('#undo-button').click();overview(p)
 go(p,'preparation');p.on('dialog',lambda d:d.accept());p.locator('[data-action=delete-task]').click();p.locator('#confirm-delete-step').click();d=snap(p)
 check(not any(t['id']=='preparation' for t in d['tasks']),'delete removes the selected parent')
 check(task(d,'metadata')['parent_id']=='analysis' and task(d,'batches')['parent_id']=='analysis','delete promotes direct children one level without deleting their work')
 check(task(d,'metadata')['notes']==task(base,'metadata')['notes'],'promoted child notes survive parent deletion')
 p.locator('#undo-button').click();check(snap(p)==base,'undo restores deleted parent and original hierarchy')
 overview(p);p.locator('.task-node[data-id=preparation]').focus();p.keyboard.press('ArrowRight');d=snap(p)
 check(all(d['layout']['positions'][id]['x']==base['layout']['positions'][id]['x']+10 for id in ['preparation','metadata','batches']),'keyboard movement also moves the branch consistently')
 p.close()
 # Migration from a saved 0.6 project.
 legacy=json.loads((ROOT/'tests/fixtures/classic-project.json').read_text());legacy['tasks'][0]['substeps']=[{'id':'review','title':'Prior checklist item','notes':'An existing note','status':'done'}]
 h=re.sub(r'(<script id="initial-project" type="application/json">).*?(</script>)',lambda m:m[1]+json.dumps(legacy)+m[2],HTML,flags=re.S)
 p=opened(b,h);d=snap(p);converted=task(d,'question_review')
 check(len(d['tasks'])==9 and converted['parent_id']=='question','existing checklist entries are converted to visible child cards')
 check(converted['notes']=='An existing note' and converted['status']=='done','legacy conversion preserves notes and status')
 check(not any('substeps' in t for t in d['tasks']),'converted document no longer contains the obsolete checklist field')
 check(all(d['layout']['positions'][id]==pos for id,pos in legacy['layout']['positions'].items()),'conversion places children without moving original cards')
 p.close()
 # Responsive details and offline behavior.
 for width,height in [(1920,1080),(1440,900),(1280,800),(1024,768),(820,1000),(390,844),(320,640)]:
  p=opened(b,width=width,height=height);requests=[];p.on('request',lambda r:requests.append(r.url))
  check(p.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'no horizontal document overflow at {width}px')
  # Select using the graph’s keyboard affordance, which reveals/pans to offscreen cards.
  go(p,'analysis');box=p.locator('#inspector').bounding_box()
  check(box['x']>=0 and box['x']+box['width']<=width+1 and box['y']+box['height']<=height+1,f'details fit the viewport at {width}px')
  p.locator('#parent-step').focus();check(p.locator('#parent-step').is_visible(),f'parent editing is reachable at {width}px')
  if width in [390,1280]:p.screenshot(path=str(OUT/f'children-details-{width}.png'))
  p.close()
 p=opened(b);network=[];p.on('request',lambda r:network.append(r.url));newchild(p,'analysis');check(not [url for url in network if url.startswith(('http:','https:'))],'adding children needs no external runtime, fonts or network requests');p.close()
 # Browser-to-real-server transport bridge, matching the baseline test setup.
 with TemporaryDirectory() as td:
  path=Path(td)/'project.yaml';path.write_text((ROOT/'examples/research-project.yaml').read_text());store=ProjectStore(path);httpd=ThreadingHTTPServer(('127.0.0.1',0),make_handler(store));threading.Thread(target=httpd.serve_forever,daemon=True).start()
  p=b.new_page(viewport={'width':1440,'height':900},accept_downloads=True,reduced_motion='reduce');p.set_default_timeout(10000);p.on('pageerror',lambda e:ERRORS.append(str(e)))
  def bridge(url,options=None):
   options=options or {};assert url.startswith('/api/');c=http.client.HTTPConnection('127.0.0.1',httpd.server_port);c.request(options.get('method') or 'GET',url,body=options.get('body'),headers=options.get('headers') or {});r=c.getresponse();d={'status':r.status,'text':r.read().decode()};c.close();return d
  p.expose_function('__http',bridge)
  js="""window.RESEARCH_FLOW_PREVIEW=false;window.fetch=async(url,o={})=>{const d=await window.__http(url,{method:o.method,headers:o.headers,body:o.body});return new Response(d.text,{status:d.status,headers:{'Content-Type':'application/json'}})};"""
  p.set_content(HTML.replace('window.RESEARCH_FLOW_PREVIEW = true;',js));expect(p.locator('#save-state')).to_have_text('Saved')
  cid,d=newchild(p,'preparation');go(p,cid);p.locator('[data-field=title]').fill('Child persisted on disk');p.locator('#save-button').click();expect(p.locator('#save-state')).to_have_text('Saved')
  saved=parse_project(path.read_text());check(task(saved,cid)['parent_id']=='preparation' and task(saved,cid)['title']=='Child persisted on disk','local Save writes child cards and parent IDs to the real project file')
  go(p,cid);p.locator('#parent-step').select_option('model');p.locator('#save-button').click();expect(p.locator('#save-state')).to_have_text('Saved');check(task(parse_project(path.read_text()),cid)['parent_id']=='model','local Save persists a parent change')
  check(len([f for f in (Path(td)/'.research-flow').rglob('*.yaml') if f.is_file()])==2,'each actual save backs up the preceding on-disk version')
  p.locator('[data-field=goal]').fill('Unsaved child draft');external=parse_project(path.read_text());external['project']['description']='Changed externally';path.write_text(json.dumps(external));expect(p.locator('#file-alert')).to_be_visible(timeout=10000)
  check(p.locator('#save-button').is_disabled() and p.locator('[data-field=goal]').input_value()=='Unsaved child draft','external conflict still protects unsaved child edits')
  p.close();httpd.shutdown();httpd.server_close()
 check(not ERRORS,'no uncaught JavaScript errors in children integration tests')
 b.close()
(OUT/'children-checks.json').write_text(json.dumps({'count':len(CHECKS),'checks':CHECKS,'errors':ERRORS},indent=2))
print('ALL',len(CHECKS),'CHILDREN CHECKS PASSED',flush=True)
