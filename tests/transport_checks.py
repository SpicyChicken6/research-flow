#!/usr/bin/env python3
"""Restricted-environment bridge test. Real HTTP/API/disk, simulated browser transport.

Uses set_content + a Python fetch bridge because some managed browser environments
block all localhost navigation. This does NOT verify direct browser networking,
real sessionStorage persistence, SSH or deployment on the user's server.
"""
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright, expect
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server import ProjectStore, make_handler, access_token, parse_project
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
CHECKS=[]

def check(value,label):
    if not value: raise AssertionError(label)
    CHECKS.append(label);print('PASS',label,flush=True)


def run():
 with tempfile.TemporaryDirectory() as td:
  path=Path(td)/'workflow.yaml';path.write_bytes((ROOT/'examples/research-project.yaml').read_bytes())
  token=access_token(Path(td)/'access.token')
  store=ProjectStore(path)
  httpd=ThreadingHTTPServer(('127.0.0.1',0),make_handler(store,auth_token=token,browser_port=18765))
  thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
  before=path.read_bytes()
  def request(url,options=None):
   assert url.startswith('/api/');options=options or {}
   headers=options.get('headers') or {};headers['Host']='127.0.0.1:18765';headers['Origin']='http://127.0.0.1:18765'
   c=http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=5)
   c.request(options.get('method') or 'GET',url,body=options.get('body'),headers=headers)
   response=c.getresponse();result={'status':response.status,'text':response.read().decode()};c.close();return result
  html=(ROOT/'dist/research-flow.html').read_text()
  blank={'schema_version':1,'project':{'name':'Untitled project'},'tasks':[],'layout':{'positions':{}}}
  html=re.sub(r'(<script id="initial-project" type="application/json">).*?(</script>)',lambda m:m[1]+json.dumps(blank)+m[2],html,flags=re.S)
  # Production helper is exercised with a test environment adapter only in this fixture.
  html=html.replace('readAccessToken(portable);','readAccessToken(portable, window.__authEnvironment);')
  bridge="""window.RESEARCH_FLOW_PREVIEW=false;
window.fetch=async(url,o={})=>{const d=await window.__http(url,{method:o.method,headers:o.headers,body:o.body});return new Response(d.text,{status:d.status,headers:{'Content-Type':'application/json'}})};"""
  html=html.replace('window.RESEARCH_FLOW_PREVIEW = true;',bridge)
  errors=[]
  try:
   with sync_playwright() as pw:
    b=pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
    def opened(incoming='',saved=''):
     p=b.new_page(viewport={'width':1600,'height':1000},reduced_motion='reduce');p.set_default_timeout(6000)
     p.on('pageerror',lambda e:errors.append(str(e)))
     p.expose_binding('__http',lambda _,url,options=None:request(url,options))
     p.evaluate('''([incoming,saved])=>{const storage=new Map(saved?[['research-flow-token',saved]]:[]);
       window.__authEnvironment={location:{hash:incoming?'#token='+incoming:'',pathname:'/',search:''},
       history:{replaceState(){window.__tokenCleared=true}},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)}}}''',[incoming,saved])
     p.set_content(html,wait_until='load');return p
    p=opened(token);expect(p.locator('#save-state')).to_have_text('Saved');expect(p.locator('.task-node')).to_have_count(8)
    check(True,'browser loads authenticated project via the explicit HTTP bridge')
    check(p.evaluate('window.__tokenCleared===true'),'bootstrap requests removal of the token fragment')
    check(p.evaluate("window.__authEnvironment.sessionStorage.getItem('research-flow-token')")==token,'bootstrap passes the credential to its tab-storage adapter')
    check(token not in p.content(),'rendered HTML contains no private token')
    check(path.read_bytes()==before,'opening a workflow does not rewrite it')
    check(p.locator('#minimap-wrap').is_visible(),'global minimap remains visible in server mode')
    check(p.locator('.header-divider').evaluate("e=>getComputedStyle(e).width==='2px'&&getComputedStyle(e).borderRadius==='0px'"),'approved square 2px title divider remains unchanged')
    p.screenshot(path=str(OUT/'linux-overview.png'))
    p.locator('#add-button').click();expect(p.locator('.task-node')).to_have_count(9)
    check(not p.locator('#inspector').is_visible(),'blank-block insertion remains place-first and edit-later')
    p.locator('.task-node').last.focus();p.keyboard.press('Enter');p.locator('[data-field=title]').fill('Server-side test edit')
    p.locator('#save-button').click();expect(p.locator('#save-state')).to_have_text('Saved')
    check(parse_project(path.read_text())['tasks'][-1]['title']=='Server-side test edit','authenticated browser Save persists to the actual YAML')
    check(bool(list((path.parent/'.research-flow/backups/workflow.yaml').glob('*.yaml'))),'authenticated Save retains a previous-version backup')
    check(token not in path.read_text(),'access credential never enters workflow data')
    p.close();p=opened(saved=token);expect(p.locator('.task-node')).to_have_count(9)
    check(True,'bootstrap retrieves a retained credential through its storage adapter')
    p.close();p=opened();expect(p.locator('#file-alert')).to_be_visible()
    check('private access URL' in p.locator('#file-alert').inner_text(),'unauthenticated browser gets a clear private-URL message')
    check(p.locator('.task-node').count()==0,'unauthenticated browser sees neither private project nor stale sample')
    p.close();b.close()
   check(request('/api/project')['status']==401,'unauthenticated HTTP reads are rejected')
   check(request('/api/project',{'method':'PUT','headers':{'Content-Type':'application/json','X-Research-Flow':'1'},'body':'{}'})['status']==401,'unauthenticated HTTP writes are rejected')
   check(not errors,'no uncaught browser JavaScript errors in the transport harness')
  finally:
   httpd.shutdown();thread.join();httpd.server_close()
 (OUT/'transport-checks.json').write_text(json.dumps(CHECKS,indent=2))
 print(f'ALL {len(CHECKS)} TRANSPORT HARNESS CHECKS PASSED')

if __name__=='__main__':run()
