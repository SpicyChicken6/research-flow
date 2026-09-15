#!/usr/bin/env python3
"""0.7.1 regression: global map, branch adoption, dialog deletion, title accent.
Tests use disposable projects; no real user's project is modified.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from http.server import ThreadingHTTPServer
import json,re,sys,threading,http.client,os,shutil
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server import parse_project,ProjectStore,make_handler
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
HTML=(ROOT/'dist/research-flow.html').read_text()
CHECKS=[];ERRORS=[]
def check(value,label):
 if not value:raise AssertionError(label)
 CHECKS.append(label);print('PASS',label,flush=True)
def opened(b,html=HTML,width=1600,height=1000):
 p=b.new_page(viewport={'width':width,'height':height},accept_downloads=True,reduced_motion='reduce');p.set_default_timeout(6000);p.on('pageerror',lambda e:ERRORS.append(str(e)));p.set_content(html,wait_until='load');expect(p.locator('#save-button')).to_be_enabled();return p
def snap(p):
 p.locator('#more-menu summary').click()
 with p.expect_download() as dl:p.locator('[data-action=export-json]').click()
 return json.loads(Path(dl.value.path()).read_text())
def task(d,id):return next(t for t in d['tasks'] if t['id']==id)
def go(p,id):
 p.locator(f'.task-node[data-id="{id}"]').focus();p.keyboard.press('Enter');expect(p.locator('#inspector')).to_be_visible()
def overview(p):
 if p.locator('#inspector').is_visible():p.locator('[data-action=close-inspector]').click()
 p.locator('#overview-button').click()
def add(p):
 p.locator('#add-button').click();d=snap(p);return d['tasks'][-1]['id'],d
def draglink(p,source,target):
 a=p.locator(f'.port.out[data-id="{source}"]').bounding_box();z=p.locator(f'.port.in[data-id="{target}"]').bounding_box();p.mouse.move(a['x']+a['width']/2,a['y']+a['height']/2);p.mouse.down();p.mouse.move(z['x']+z['width']/2,z['y']+z['height']/2,steps=12);p.mouse.up()
def edge(p,key):
 p.locator(f'[data-edge="{key}"]').focus();p.keyboard.press('Enter');expect(p.locator('#connection-form')).to_be_visible()
def mini_layout(p):return p.locator('.mini-node').evaluate_all('es=>es.map(e=>[e.dataset.miniTask,e.getAttribute("x"),e.getAttribute("y"),e.getAttribute("width"),e.getAttribute("height")])')
def delete(p,id):go(p,id);p.locator('[data-action=delete-task]').click();expect(p.locator('#delete-step-dialog')).to_be_visible();p.locator('#confirm-delete-step').click()
with sync_playwright() as pw:
 b=pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
 # Minimap is global, not a second rendering of the filtered canvas.
 p=opened(b);base=snap(p);layout=mini_layout(p)
 check(p.locator('#minimap-wrap').is_visible(),'global minimap is on by default')
 check(len(layout)==len(base['tasks']),'every step is represented in the overview map')
 check(p.locator('.mini-hierarchy').count()==5 and p.locator('.mini-dependency').count()==4,'map includes hierarchy branches and dependencies')
 check(p.locator('.mini-viewport').count()==1,'map includes a viewport rectangle')
 p.screenshot(path=str(OUT/'v071-overview.png'))
 go(p,'preparation');p.locator('#focus-button').click()
 check(p.locator('.task-node:visible').count()<len(base['tasks']),'test enters a genuine filtered Focus view')
 check(mini_layout(p)==layout,'minimap geometry and scale stay global in Focus')
 check(p.locator('.mini-node.is-context').count()>0,'off-focus steps remain visible as quieter context')
 check(p.locator('.mini-node.is-selected').get_attribute('data-mini-task')=='preparation','selected step is highlighted in minimap')
 p.screenshot(path=str(OUT/'v071-focus.png'))
 before=p.locator('#world').get_attribute('style');p.locator('[data-mini-task=sensitivity]').click()
 check(p.locator('#focus-button').get_attribute('aria-pressed')=='false','clicking an off-focus map node exits Focus')
 check(p.locator('.task-node[data-id=sensitivity]').is_visible(),'global map click brings the outside step into view')
 check(p.locator('#world').get_attribute('style')!=before,'map click pans the actual graph')
 check(snap(p)==base,'map navigation does not alter project state')
 overview(p);p.locator('.task-node[data-id=analysis] .children-toggle').click()
 check(p.locator('.task-node:visible').count()==3,'test collapses the analysis branch')
 check(mini_layout(p)==layout and p.locator('.mini-node.is-context').count()==5,'collapsed descendants remain globally mapped at original coordinates')
 p.locator('[data-mini-task=metadata]').click()
 check(p.locator('.task-node[data-id=metadata]').is_visible(),'clicking a collapsed descendant reveals its ancestor path')
 check(snap(p)==base,'expanding from the map leaves saved hierarchy and positions unchanged')
 overview(p);p.locator('.task-node[data-id=analysis] .children-toggle').click();p.locator('#minimap-wrap').focus();p.keyboard.press('Enter')
 check(p.locator('.task-node:visible').count()==8,'Enter on map restores an expanded full overview')
 previous=p.locator('.mini-viewport').get_attribute('width');p.locator('[data-action=zoom-in]').click();p.locator('[data-action=zoom-in]').click()
 check(float(p.locator('.mini-viewport').get_attribute('width'))<float(previous),'map viewport shrinks as graph zoom increases')
 p.locator('#more-menu summary').click();p.locator('#map-option').click();check(p.locator('#minimap-wrap').is_hidden(),'More can hide the restored map')
 p.locator('#more-menu summary').click();p.locator('#map-option').click();check(p.locator('#minimap-wrap').is_visible(),'More can restore the map')
 p.locator('#more-menu summary').click();p.locator('[data-action=view-list]').click();check(p.locator('#minimap-wrap').is_hidden(),'map does not float over the text-only Step list')
 p.locator('#overview-button').click();check(p.locator('#minimap-wrap').is_visible(),'returning to graph restores minimap')
 p.close()
 # Add connected step, as well as freehand links, now inherit parentage.
 p=opened(b);base=snap(p);go(p,'preparation');p.locator('[data-action=add-after]').click();d=snap(p);id=d['tasks'][-1]['id']
 check(task(d,id)['parent_id']=='analysis','Add connected step on a child inherits the same parent')
 check(task(d,id)['depends_on']==['preparation'],'only the requested child dependency is added')
 check(p.locator(f'.task-node[data-id={id}]').evaluate('e=>parseFloat(e.style.width)')==212,'connected blank block uses the smaller child dimensions')
 check(not p.locator('#inspector').is_visible(),'Add connected step remains place-first, edit-later')
 p.locator('#undo-button').click();check(snap(p)==base,'one undo reverses insertion, parentage and the connection')
 p.locator('#redo-button').click();check(snap(p)==d,'redo restores connected child and its parent')
 go(p,id);p.locator('[data-field=title]').fill('Summarize quality checks');p.locator('[data-action=add-after]').click();tail=snap(p);tailid=tail['tasks'][-1]['id']
 check(task(tail,tailid)['parent_id']=='analysis' and task(tail,tailid)['depends_on']==[id],'a chain continues in the same branch without direct main-step dependencies')
 p.close()
 p=opened(b);id,before=add(p);overview(p);draglink(p,'preparation',id);d=snap(p)
 check(task(d,id)['parent_id']=='analysis' and task(d,id)['depends_on']==['preparation'],'dragging a child dependency to an ungrouped card adopts it')
 check(d['layout']==before['layout'],'automatic membership does not rearrange saved positions')
 check(p.locator(f'.task-node[data-id={id}]').evaluate('e=>e.classList.contains("child-node")'),'drag connection updates child styling immediately')
 p.locator('#undo-button').click();check(snap(p)==before,'undo removes drag dependency and adoption atomically')
 p.locator('#redo-button').click();check(snap(p)==d,'redo restores both parts atomically')
 edge(p,f'preparation|{id}');p.locator('[data-action=delete-edge]').click();d=snap(p)
 check(task(d,id)['parent_id']=='analysis' and not task(d,id)['depends_on'],'removing a dependency does not discard chosen branch membership')
 p.close()
 p=opened(b);id,before=add(p);go(p,'preparation');p.locator('#add-dependency').select_option(id);d=snap(p)
 check(task(d,id)['parent_id']=='analysis' and id in task(d,'preparation')['depends_on'],'incoming prerequisites via Details also inherit the parent branch')
 p.locator('#undo-button').click();check(snap(p)==before,'Details connection and parentage undo together')
 overview(p);p.locator(f'.port.out[data-id={id}]').focus();p.keyboard.press('Enter');p.locator('.port.in[data-id=preparation]').focus();p.keyboard.press('Enter');d=snap(p)
 check(task(d,id)['parent_id']=='analysis','keyboard connections use the same branch inheritance rule')
 p.close()
 p=opened(b);id,before=add(p);go(p,id);p.locator('#add-dependency').select_option('preparation');id2,_=add(p);overview(p);edge(p,f'preparation|{id}');before=snap(p);p.locator('#connection-target').select_option(id2);p.locator('#connection-form button[type=submit]').click();d=snap(p)
 check(task(d,id2)['parent_id']=='analysis' and task(d,id2)['depends_on']==['preparation'],'connection rewiring adopts the new ungrouped endpoint')
 check(task(d,id)['parent_id']=='analysis' and not task(d,id)['depends_on'],'rewiring preserves the previous endpoint’s established parent')
 p.locator('#undo-button').click();check(snap(p)==before,'one undo restores edge and parent state after rewiring')
 # Preserve existing roots and separate groups.
 overview(p);go(p,'other' if any(t['id']=='other' for t in before['tasks']) else 'synthesis');p.locator('#add-dependency').select_option('metadata');d=snap(p)
 check(not task(d,'synthesis').get('parent_id'),'a main step already connected to a main container is not silently adopted')
 p.close()
 # Deletion: suppress native popups to reproduce the failed-confirm path.
 p=opened(b);base=snap(p);p.evaluate('() => {window.confirmCalls=0;window.confirm=()=>{window.confirmCalls++;return false}}')
 go(p,'preparation');p.locator('[data-action=delete-task]').click();expect(p.locator('#delete-step-dialog')).to_be_visible()
 check(p.evaluate('window.confirmCalls')==0,'deletion never calls the suppressed browser confirm API')
 check(p.locator('#delete-step-cancel').evaluate('e=>e===document.activeElement'),'Cancel receives default focus for a destructive action')
 check('2 child steps' in p.locator('#delete-step-impact').inner_text(),'confirmation explains that the direct children will be kept')
 check(p.locator('#delete-step-name').inner_text()=='Prepare the dataset','confirmation names the exact step being deleted')
 p.screenshot(path=str(OUT/'v071-delete.png'))
 p.locator('#delete-step-cancel').click();check(snap(p)==base,'Cancel preserves all nodes, connections and parentage')
 p.locator('[data-action=delete-task]').click();p.keyboard.press('Escape');expect(p.locator('#delete-step-dialog')).to_be_hidden();check(snap(p)==base,'Escape dismisses deletion without data changes')
 p.locator('[data-action=delete-task]').click();p.locator('#confirm-delete-step').click();d=snap(p)
 check(not any(t['id']=='preparation' for t in d['tasks']),'in-page confirmation deletes the intended step')
 check(task(d,'metadata')['parent_id']=='analysis' and task(d,'batches')['parent_id']=='analysis','direct children move up one level and remain editable')
 check(all('preparation' not in t['depends_on'] for t in d['tasks']),'all dependencies of the deleted step are removed')
 check(task(d,'metadata')['notes']==task(base,'metadata')['notes'],'child content survives deletion')
 check(p.locator('.mini-node').count()==7,'minimap updates immediately after deletion')
 p.locator('#undo-button').click();check(snap(p)==base,'Undo restores deleted step, hierarchy, dependencies and positions')
 p.locator('#redo-button').click();check(snap(p)==d,'Redo reapplies deletion consistently')
 p.close()
 # The native failure and the replacement are exercised in an actual iframe
 # without allow-modals, not just with a mocked confirm function.
 host=b.new_page(viewport={'width':1600,'height':1000});host.set_default_timeout(6000);host.set_content('<iframe sandbox="allow-scripts allow-same-origin" style="position:fixed;inset:0;width:100%;height:100%;border:0"></iframe>')
 host.locator('iframe').evaluate('(e,html)=>e.srcdoc=html',HTML);frame=host.frame_locator('iframe');expect(frame.locator('.task-node')).to_have_count(8)
 frame.locator('.task-node[data-id=preparation]').focus();host.keyboard.press('Enter');frame.locator('[data-action=delete-task]').click()
 expect(frame.locator('#delete-step-dialog')).to_be_visible();frame.locator('#confirm-delete-step').click();check(frame.locator('.task-node').count()==7,'in-page deletion works in sandbox without native-modal permissions')
 host.close()
 # Save copy retains the update and all changes.
 p=opened(b);go(p,'model');p.locator('[data-action=add-after]').click();d=snap(p);id=d['tasks'][-1]['id'];go(p,id);p.locator('[data-field=title]').fill('Check fit');p.locator('#resources-tab').click();p.locator('[data-field=notes]').fill('Do not lose this note');d=snap(p)
 with p.expect_download() as dl:p.locator('#save-button').click()
 saved=Path(dl.value.path()).read_text();q=opened(b,saved)
 check(snap(q)==d,'editable HTML copy reopens with inherited parentage and notes intact')
 check(q.locator('#minimap-wrap').is_visible() and q.locator('#delete-step-dialog').count()==1,'saved copy retains global minimap and new delete confirmation')
 delete(q,id);check(q.locator('.task-node').count()==8,'deletion also works in a reopened saved copy')
 q.close();p.close()
 # Last step, keyboard action and an empty map.
 empty={'schema_version':1,'project':{'name':'Single step'},'tasks':[{'id':'one','title':'Only step','notes':'Keep'}],'layout':{'positions':{'one':{'x':0,'y':0}}}}
 h=re.sub(r'(<script id="initial-project" type="application/json">).*?(</script>)',lambda m:m[1]+json.dumps(empty)+m[2],HTML,flags=re.S)
 p=opened(b,h);p.locator('.task-node[data-id=one]').focus();p.keyboard.press('Delete');expect(p.locator('#delete-step-dialog')).to_be_visible();p.locator('#confirm-delete-step').click()
 check(p.locator('#empty-state').is_visible() and p.locator('#minimap-wrap').is_hidden(),'deleting the final step yields the clean empty state and hides the map')
 p.locator('#undo-button').click();check(p.locator('.task-node').count()==1 and p.locator('#minimap-wrap').is_visible(),'Undo restores the final step and overview map')
 p.close()
 # Responsive title accent, map, and confirmation. No real-device touch claim.
 for width,height in [(1920,1080),(1600,1000),(1280,800),(1024,768),(820,1000),(390,844),(320,640)]:
  p=opened(b,width=width,height=height)
  check(p.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'no horizontal page overflow at {width}px')
  bar=p.locator('.header-divider').bounding_box();title=p.locator('#project-title').bounding_box();style=p.locator('.header-divider').evaluate('e=>({color:getComputedStyle(e).backgroundColor,width:parseFloat(getComputedStyle(e).width)})')
  check(style['color']=='rgb(17, 17, 17)' and style['width']==(1 if width<=700 else 2),f'title accent has the approved thin width at {width}px')
  check(0<=title['x']-bar['x']-bar['width']<=10,f'black accent remains closely grouped with project title at {width}px')
  box=p.locator('#minimap-wrap').bounding_box();check(box['x']>=0 and box['x']+box['width']<=width+1 and box['y']+box['height']<=height+1,f'global minimap fits viewport at {width}px')
  go(p,'analysis');p.locator('[data-action=delete-task]').click();box=p.locator('#delete-step-dialog').bounding_box()
  check(box['x']>=0 and box['x']+box['width']<=width+1 and box['y']+box['height']<=height+1,f'delete confirmation fits viewport at {width}px')
  p.locator('#delete-step-cancel').click();p.locator('[data-action=close-inspector]').click()
  box=p.locator('#minimap-wrap').bounding_box();check(box['x']>=0 and box['x']+box['width']<=width+1 and box['y']+box['height']<=height+1,f'minimap remains anchored after keyboard navigation and closing details at {width}px')
  check(p.locator('#canvas').evaluate('e=>e.scrollLeft===0&&e.scrollTop===0'),f'graph camera never native-scrolls its fixed controls at {width}px')
  if width==390:p.screenshot(path=str(OUT/'v071-mobile.png'))
  p.close()
 # Real temporary disk + HTTP, bridged into a browser page because file navigation
 # is blocked by this environment. The shipped runtime does not contain the bridge.
 with TemporaryDirectory() as td:
  path=Path(td)/'project.yaml';path.write_text((ROOT/'examples/research-project.yaml').read_text());httpd=ThreadingHTTPServer(('127.0.0.1',0),make_handler(ProjectStore(path)));threading.Thread(target=httpd.serve_forever,daemon=True).start()
  p=b.new_page(viewport={'width':1600,'height':1000},accept_downloads=True,reduced_motion='reduce');p.set_default_timeout(8000);p.on('pageerror',lambda e:ERRORS.append(str(e)))
  def bridge(url,options=None):
   options=options or {};assert url.startswith('/api/');c=http.client.HTTPConnection('127.0.0.1',httpd.server_port);c.request(options.get('method') or 'GET',url,body=options.get('body'),headers=options.get('headers') or {});r=c.getresponse();d={'status':r.status,'text':r.read().decode()};c.close();return d
  p.expose_function('__http',bridge)
  js="""window.RESEARCH_FLOW_PREVIEW=false;window.fetch=async(url,o={})=>{const d=await window.__http(url,{method:o.method,headers:o.headers,body:o.body});return new Response(d.text,{status:d.status,headers:{'Content-Type':'application/json'}})};"""
  p.set_content(HTML.replace('window.RESEARCH_FLOW_PREVIEW = true;',js));expect(p.locator('#save-state')).to_have_text('Saved')
  go(p,'preparation');p.locator('[data-action=add-after]').click();d=snap(p);id=d['tasks'][-1]['id'];p.locator('#save-button').click();expect(p.locator('#save-state')).to_have_text('Saved');disk=parse_project(path.read_text())
  check(task(disk,id)['parent_id']=='analysis' and task(disk,id)['depends_on']==['preparation'],'local Save persists inherited parent and requested dependency together')
  go(p,'preparation');p.locator('[data-action=delete-task]').click();p.locator('#confirm-delete-step').click();p.locator('#save-button').click();expect(p.locator('#save-state')).to_have_text('Saved');disk=parse_project(path.read_text())
  check(not any(t['id']=='preparation' for t in disk['tasks']) and task(disk,'metadata')['parent_id']=='analysis','local Save persists confirmed deletion and child promotion')
  check(len([f for f in (Path(td)/'.research-flow').rglob('*.yaml') if f.is_file()])==2,'both on-disk changes created backups of the previous file')
  p.locator('#undo-button').click();p.locator('#save-button').click();expect(p.locator('#save-state')).to_have_text('Saved');disk=parse_project(path.read_text())
  check(task(disk,'preparation')['id']=='preparation' and task(disk,'metadata')['parent_id']=='preparation','Undo of deletion can be saved back to the actual project file')
  p.close();httpd.shutdown();httpd.server_close()
 check(not ERRORS,'no uncaught JavaScript errors in branch-update checks')
 b.close()
(OUT/'branch-update-checks.json').write_text(json.dumps({'count':len(CHECKS),'checks':CHECKS,'errors':ERRORS},indent=2))
print('ALL',len(CHECKS),'BRANCH UPDATE CHECKS PASSED',flush=True)
