import test from 'node:test';
import assert from 'node:assert/strict';
import { readAccessToken } from '../web/connection.mjs';

function environment(hash = '') {
  const values = new Map();
  const calls = [];
  return {
    location: {hash, pathname:'/', search:'?example=1'},
    history: {replaceState(...args) {calls.push(args);}},
    sessionStorage: {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)},
    calls,
  };
}
test('portable mode neither reads nor stores a credential',()=>{
  const e = environment('#token=secret');
  assert.equal(readAccessToken(true,e),'');
  assert.equal(e.calls.length,0);
  assert.equal(e.sessionStorage.getItem('research-flow-token'),null);
});
test('incoming token is removed from URL and stored separately',()=>{
  const e=environment('#token=secret_value');
  assert.equal(readAccessToken(false,e),'secret_value');
  assert.deepEqual(e.calls,[[null,'','/?example=1']]);
  assert.equal(e.sessionStorage.getItem('research-flow-token'),'secret_value');
});
test('reload retrieves the tab token when fragment is absent',()=>{
  const e=environment();e.sessionStorage.setItem('research-flow-token','saved');
  assert.equal(readAccessToken(false,e),'saved');
});
test('a different token replaces the existing tab credential',()=>{
  const e=environment('#token=new');e.sessionStorage.setItem('research-flow-token','old');
  assert.equal(readAccessToken(false,e),'new');
  assert.equal(e.sessionStorage.getItem('research-flow-token'),'new');
});
test('empty fragment does not clear a saved credential',()=>{
  const e=environment('#token=');e.sessionStorage.setItem('research-flow-token','saved');
  assert.equal(readAccessToken(false,e),'saved');
});
test('denied session storage still permits the incoming token in memory',()=>{
  const e=environment('#token=volatile');
  Object.defineProperty(e,'sessionStorage',{get(){throw new Error('Denied');}});
  assert.equal(readAccessToken(false,e),'volatile');
});
test('denied session storage and no token fail closed',()=>{
  const e=environment();Object.defineProperty(e,'sessionStorage',{get(){throw new Error('Denied');}});
  assert.equal(readAccessToken(false,e),'');
});
test('unavailable history does not crash initialization',()=>{
  const e=environment('#token=present');e.history.replaceState=()=>{throw new Error('Denied');};
  assert.equal(readAccessToken(false,e),'present');
});
