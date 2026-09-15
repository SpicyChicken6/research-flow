import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// The local server intentionally has a fixed static-file allowlist. Keep the
// controller in app.js; isolate its marked, DOM-independent factory for tests.
const source = readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');
const block = source.split('// BEGIN LOGO MOTION')[1].split('// END LOGO MOTION')[0];
const code = '// BEGIN LOGO MOTION' + block + '\nexport {createLogoMotion, LOGO_MOTION};';
const {createLogoMotion, LOGO_MOTION} = await import('data:text/javascript,' + encodeURIComponent(code));
function target() {
  const handlers = new Map();
  return {
    handlers,
    addEventListener(name, fn) { handlers.set(name, fn); },
    removeEventListener(name, fn) { if(handlers.get(name) === fn) handlers.delete(name); },
    emit(name) { handlers.get(name)?.(); }
  };
}
function setup({reduced=false, hidden=false, unsupported=false, failed=false} = {}) {
  const media={...target(),matches:reduced};
  const win={...target(),matchMedia:()=>media};
  const doc={...target(),defaultView:win,hidden};
  const animations=[];
  const dots={animate(frames, options) {
    if(failed) throw Error('Animation failed');
    const a={frames,options,cancelled:false,cancel(){this.cancelled=true;this.oncancel?.();}};
    animations.push(a);return a;
  }};
  if(unsupported) delete dots.animate;
  const svg={ownerDocument:doc,querySelector:()=>dots};
  return {motion:createLogoMotion(svg),animations,doc,win,media};
}
test('initial load is one 720 ms turn, never an infinite animation',()=>{
 const {motion,animations}=setup();assert.equal(motion.play('load'),true);
 assert.equal(animations[0].options.duration,LOGO_MOTION.loadDuration);
 assert.equal(animations[0].options.iterations,1);
 assert.equal(animations[0].frames.at(-1).transform,'rotate(360deg)');
});
test('view changes use the shorter 480 ms duration',()=>{
 const {motion,animations}=setup();motion.play();assert.equal(animations[0].options.duration,480);
});
test('rapid triggers neither stack nor restart the active rotation',()=>{
 const {motion,animations}=setup();motion.play();for(let i=0;i<20;i++)assert.equal(motion.play(),false);
 assert.equal(animations.length,1);assert.equal(animations[0].cancelled,false);
});
test('finished effects are released and a later transition can play',()=>{
 const {motion,animations}=setup();motion.play();animations[0].onfinish();
 assert.equal(animations[0].cancelled,true);assert.equal(motion.play(),true);assert.equal(animations.length,2);
});
test('a cancelled effect permits a later transition',()=>{
 const {motion,animations}=setup();motion.play();animations[0].cancel();assert.equal(motion.play(),true);
});
test('reduced motion skips all startup and transition animations',()=>{
 const {motion,animations}=setup({reduced:true});assert.equal(motion.play('load'),false);assert.equal(motion.play(),false);assert.equal(animations.length,0);
});
test('changing reduced-motion preference cancels an active animation',()=>{
 const {motion,animations,media}=setup();motion.play();media.matches=true;media.emit('change');
 assert.equal(animations[0].cancelled,true);assert.equal(motion.play(),false);
 media.matches=false;media.emit('change');assert.equal(animations.length,1);assert.equal(motion.play(),true);
});
test('hidden pages skip motion and visibility loss cancels in-flight motion',()=>{
 const {motion,animations,doc}=setup({hidden:true});assert.equal(motion.play(),false);
 doc.hidden=false;doc.emit('visibilitychange');motion.play();doc.hidden=true;doc.emit('visibilitychange');assert.equal(animations[0].cancelled,true);
});
test('pagehide cancels motion rather than keeping effects alive',()=>{
 const {motion,animations,win}=setup();motion.play();win.emit('pagehide');assert.equal(animations[0].cancelled,true);
});
test('a missing logo or missing animation API safely leaves the app static',()=>{
 assert.equal(createLogoMotion(null).play(),false);
 assert.equal(setup({unsupported:true}).motion.play(),false);
});
test('animation failure does not throw into the editor',()=>{
 assert.doesNotThrow(()=>setup({failed:true}).motion.play());assert.equal(setup({failed:true}).motion.play(),false);
});
test('destroy cancels motion and removes listeners',()=>{
 const {motion,animations,win,doc,media}=setup();motion.play();motion.destroy();
 assert.equal(animations[0].cancelled,true);assert.equal(win.handlers.size,0);assert.equal(doc.handlers.size,0);assert.equal(media.handlers.size,0);assert.equal(motion.play(),false);
});
