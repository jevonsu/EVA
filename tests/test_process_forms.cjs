// Pure VM/DOM doubles; no browser, network or external process.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const render = fs.readFileSync('app/static/js/app-render.js', 'utf8');
const chat = fs.readFileSync('app/static/js/app-chat.js', 'utf8');
function extract(source, name, next) {
  const start = source.indexOf(' function ' + name + '(');
  const end = source.indexOf(' function ' + next + '(', start);
  assert(start >= 0 && end > start);
  return source.slice(start, end);
}
const latest = vm.runInNewContext(extract(chat, 'latestOpenKillFormId', 'extrasFromStored') + ';latestOpenKillFormId');
const card = {role:'assistant', metadata:{form:{id:'q1', purpose:'kill_confirm'}}};
assert.equal(latest([card]), 'q1');
assert.equal(latest([card, {role:'user'}, {role:'assistant', content:'普通文字'}]), 'q1');
assert.equal(latest([card, {role:'assistant',metadata:{form_resolved:'q1'}}]), null);
assert.equal(latest([card, {role:'assistant',metadata:{form:{id:'q2',purpose:'quiz'}}}]), null);
assert.equal(latest([card, {role:'assistant',metadata:{form:{id:'q2',purpose:'kill_confirm'}}}]), 'q2');
const msg = {isConnected:true};
let cards=[];
const root = {querySelectorAll: () => cards};
const wrap = {dataset:{purpose:'kill_confirm'}, closest:() => msg, isConnected:true};
const isLatest = vm.runInNewContext(extract(render,'askFormIsLatest','expireOpenAskForms') + ';askFormIsLatest', {els:{messages:root}});
cards=[wrap]; assert.equal(isLatest(wrap), true);
cards=[wrap, {}]; assert.equal(isLatest(wrap), false);
const kill={dataset:{purpose:'kill_confirm'}}, ordinary={dataset:{purpose:'quiz'}};
let locked=[];
const expire = vm.runInNewContext(extract(render,'expireOpenAskForms','watchAskSend') + ';expireOpenAskForms', {
  els:{messages:{querySelectorAll:()=>[kill,ordinary]}}, lockAskForm:(w)=>locked.push(w),
});
expire(null,true); assert.deepEqual(locked,[ordinary]);
locked=[]; expire(); assert.deepEqual(locked,[kill,ordinary]);
console.log('9 pure JS form-lifecycle assertions passed');
