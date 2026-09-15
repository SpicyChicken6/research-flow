#!/usr/bin/env python3
"""Logo-motion integration checks; Playwright and Pillow are test-only."""
import io, json, re, shutil, xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'dist/research-flow.html').read_text()
CLASSIC=json.loads((ROOT/'tests/fixtures/classic-project.json').read_text())
HTML=re.sub(r'(<script id="initial-project" type="application/json">).*?(</script>)',lambda m:m[1]+json.dumps(CLASSIC)+m[2],HTML,flags=re.S)
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
CHECKS=[];ERRORS=[]
def check(v,s):
 if not v: raise AssertionError(s)
 CHECKS.append(s);print('PASS',s,flush=True)
def opened(browser,reduced='no-preference',html=HTML):
 p=browser.new_page(viewport={'width':1440,'height':900},reduced_motion=reduced,accept_downloads=True)
 p.set_default_timeout(5000);p.on('pageerror',lambda e:ERRORS.append(str(e)))
 p.set_content(html,wait_until='load');expect(p.locator('.task-node')).to_have_count(8)
 return p
def count(p): return p.locator('[data-logo-dots]').evaluate('(el)=>el.getAnimations().length')
def finish(p):
 p.locator('[data-logo-dots]').evaluate('(el)=>el.getAnimations().forEach(a=>a.finish())')
 p.wait_for_function("document.querySelector('[data-logo-dots]').getAnimations().length===0")
def pause(p):
 p.locator('[data-logo-dots]').evaluate('(el)=>{window.__turn=el.getAnimations()[0];window.__turn.pause();window.__turn.currentTime=0;}')
def matrix(p,selector):return p.locator(selector).evaluate('(el)=>{const m=el.getScreenCTM();return [m.a,m.b,m.c,m.d,m.e,m.f]}')
with sync_playwright() as pw:
 b=pw.chromium.launch(executable_path=shutil.which('chromium'),headless=True,args=['--no-sandbox'])
 p=opened(b);check(count(p)==1,'startup creates one dot-ring animation');pause(p)
 check(p.evaluate('__turn.effect.getTiming().duration')==720,'startup duration is 720 ms')
 check(p.evaluate('__turn.effect.getTiming().iterations')==1,'startup is one revolution, not a loop')
 # Freeze an intermediate frame; the fixed artwork and mask must not rotate.
 arrow=matrix(p,'#rf-logo-arrow');frame=matrix(p,'#rf-logo-background');win=matrix(p,'.logo-dot-window');ring=matrix(p,'[data-logo-dots]')
 pivot=p.locator('[data-logo-dots]').evaluate('(el)=>new DOMPoint(0,0).matrixTransform(el.getScreenCTM()).toJSON()')
 p.evaluate('__turn.currentTime=220');p.wait_for_timeout(40)
 check(matrix(p,'#rf-logo-arrow')==arrow,'arrow remains stationary during rotation')
 check(matrix(p,'#rf-logo-background')==frame,'background frame remains stationary')
 check(matrix(p,'.logo-dot-window')==win,'mask is attached to a stationary outer group')
 check(matrix(p,'[data-logo-dots]')!=ring,'only the dot group changes its rotation matrix')
 pivot2=p.locator('[data-logo-dots]').evaluate('(el)=>new DOMPoint(0,0).matrixTransform(el.getScreenCTM()).toJSON()')
 check(abs(pivot['x']-pivot2['x'])<1e-6 and abs(pivot['y']-pivot2['y'])<1e-6,'ring center stays fixed through rotation')
 center=p.locator('.brand-logo').evaluate('(el)=>new DOMPoint(256,256).matrixTransform(el.getScreenCTM()).toJSON()')
 check(abs(pivot['x']-center['x'])<1e-5 and abs(pivot['y']-center['y'])<1e-5,'rotation pivot is the icon artboard center, not the changing dot bounds')
 finish(p);check(count(p)==0,'finished animation releases its effect and returns to the original pose')
 # Do not spin for editing, panning, repeated Overview or inspector tabs.
 p.locator('.task-node[data-id=design]').click();check(count(p)==0,'selecting a step does not trigger decorative motion')
 p.locator('#resources-tab').click();check(count(p)==0,'Plan/Notes tabs do not trigger the logo')
 p.locator('[data-field=notes]').fill('Motion must not touch these notes.');check(count(p)==0,'editing notes does not trigger motion')
 p.locator('#overview-button').click();check(count(p)==0,'clicking the already-active Overview does not spin')
 p.locator('#focus-button').click();check(count(p)==1,'entering Focus triggers the view animation');pause(p)
 check(p.evaluate('__turn.effect.getTiming().duration')==480,'view-change duration is 480 ms')
 p.locator('#overview-button').click();p.locator('#focus-button').click();p.locator('#overview-button').click()
 check(p.locator('[data-logo-dots]').evaluate('(el)=>el.getAnimations()[0]===window.__turn'),'rapid view switches reuse the current turn without jumping or queueing')
 check(p.locator('.task-node').count()==8 and p.locator('#overview-button').get_attribute('aria-pressed')=='true','actual view changes happen immediately while the animation is active')
 finish(p);p.locator('#more-menu summary').click();p.locator('[data-action=view-list]').click()
 check(count(p)==1 and p.locator('#list-view').is_visible(),'switching to Step list triggers motion without blocking the list');finish(p)
 p.locator('#overview-button').click();check(count(p)==1,'returning from Step list to the graph triggers motion');finish(p)
 # Export during a paused turn. The saved template must have pristine SVG, not a frozen frame.
 p.locator('#focus-button').click();pause(p);p.evaluate('__turn.currentTime=140')
 with p.expect_download() as d:p.locator('#save-button').click()
 saved=Path(d.value.path()).read_text()
 q=opened(b,html=saved);check(count(q)==1,'an editable saved HTML copy starts a fresh animation when reopened');finish(q)
 q.locator('.task-node[data-id=design]').click();q.locator('#resources-tab').click()
 check(q.locator('[data-field=notes]').input_value()=='Motion must not touch these notes.','saving during animation preserves edited project data')
 check(not q.locator('[data-logo-dots]').get_attribute('style'),'saved copies do not retain an in-flight transform')
 q.close();p.close()
 p=opened(b,reduced='reduce');check(count(p)==0,'reduced-motion preference disables the initial rotation')
 p.locator('.task-node[data-id=design]').click();p.locator('#focus-button').click();check(count(p)==0,'reduced-motion preference disables transition rotations')
 check(p.locator('.task-node:visible').count()==4,'Focus still works normally with reduced motion')
 p.emulate_media(reduced_motion='no-preference');check(count(p)==0,'reenabling motion does not start a surprise spin')
 p.locator('#overview-button').click();check(count(p)==1,'next actual view change can animate after reenabling motion')
 p.emulate_media(reduced_motion='reduce');p.wait_for_function("document.querySelector('[data-logo-dots]').getAnimations().length===0");check(count(p)==0,'changing the preference stops an active animation immediately')
 p.close()
 p=opened(b);finish(p);p.wait_for_timeout(1100);check(count(p)==0,'the logo stays still while the user is idle');p.close()
 # Original geometry and colors are kept; only grouping and masks are added.
 p=opened(b,reduced='reduce');ns={'s':'http://www.w3.org/2000/svg'}
 original=ET.parse(ROOT/'web/assets/research-flow-icon-light.svg').getroot()
 circles=[{key:c.get(key) for key in ['cx','cy','r','fill']} for c in original.findall('.//s:circle',ns)]
 actual=p.locator('[data-logo-dots] circle').evaluate_all("els=>els.map(el=>Object.fromEntries(['cx','cy','r','fill'].map(k=>[k,el.getAttribute(k)])))")
 check(actual==circles,'all 64 original dots retain their positions, sizes and colors')
 check(p.locator('#rf-logo-arrow').get_attribute('d')==original.find('.//s:path',ns).get('d'),'the original arrow path is unchanged')
 p.close()
 # Raster probes of the actual shipped mask. Cover it with a solid swatch,
 # hide the arrow/background, and test alpha instead of relying on layering.
 svg=re.search(r'<svg\b[^>]*class="brand-logo".*?</svg>',HTML,re.S).group(0)
 fixture='<style>html,body{margin:0;background:transparent}svg{display:block;width:512px;height:512px}.logo-dots{transform-origin:0 0;transform-box:view-box}</style>'+svg
 p=b.new_page(viewport={'width':512,'height':512});p.set_content(fixture)
 p.evaluate("""()=>{
 document.querySelector('#rf-logo-background').remove();document.querySelector('#rf-logo-arrow').style.display='none';
 document.querySelector('.logo-dot-artwork').innerHTML='<rect x="-500" y="-500" width="1800" height="1800" fill="#ff0080"/>';
 }""")
 def shot(): return Image.open(io.BytesIO(p.screenshot(omit_background=True))).convert('RGBA')
 def pixel(im,x,y):return im.getpixel((round(x*.9532878-114.63557),round(y*.9532878-9.58467)))
 im=shot();im.save(OUT/'mask-alpha-probe.png')
 check(pixel(im,513,178)[3]==0,'dots under the arrow are actually masked away, not painted over')
 check(pixel(im,477,166)[3]==0,'a small transparent clearance extends beyond the arrow shape')
 check(0<pixel(im,470,166)[3]<255,'the surrounding transition contains partial opacity for the soft fade')
 check(pixel(im,350,95)[3]==255,'dots away from the arrow remain fully opaque')
 p.locator('[data-logo-dots]').evaluate("el=>el.style.transform='rotate(180deg)'");im2=shot()
 check(ImageChops.difference(im,im2).getbbox() is None,'mask clearance stays fixed even as its contents rotate 180 degrees')
 p.locator('[data-logo-dots]').evaluate("el=>el.style.transform='none'")
 for color,rgb in [('#ffffff',(255,255,255)),('#0b1220',(11,18,32))]:
  p.evaluate('(c)=>document.body.style.background=c',color)
  image=Image.open(io.BytesIO(p.screenshot())).convert('RGB')
  check(pixel(image,477,166)==rgb,'clearance reveals the actual '+color+' background without a white halo')
 p.close()
 # Offline and compact layout checks for the actual new SVG element.
 for width in [320,390,820,1440]:
  p=b.new_page(viewport={'width':width,'height':900},reduced_motion='reduce');requests=[]
  p.on('request',lambda r:requests.append(r.url));p.set_content(HTML,wait_until='load');expect(p.locator('.task-node')).to_have_count(8)
  check(p.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'inline animated logo introduces no horizontal overflow at {width}px')
  check(not [u for u in requests if u.startswith(('https:','http:'))],f'animation and artwork need no external network requests at {width}px')
  if width==1440:p.screenshot(path=str(OUT/'motion-overview.png'))
  p.close()
 check(not ERRORS,'no uncaught JavaScript errors in motion integration tests')
 b.close()
(OUT/'logo-motion-checks.json').write_text(json.dumps({'count':len(CHECKS),'checks':CHECKS,'errors':ERRORS},indent=2))
print('ALL',len(CHECKS),'MOTION CHECKS PASSED',flush=True)
