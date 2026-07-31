// app/index.html のスクリプトを最小 DOM シムの上で実行し、
// SSE 受信 → 逐次カード追加 → done 確定 までの状態遷移を検証する。
// ブラウザそのものではないので「throw しないこと」「状態が期待どおりに遷移すること」を見る。
const fs = require('fs');
const PATH = require('path').resolve(__dirname,'../..') + '/app/index.html';
const html = fs.readFileSync(PATH, 'utf8');
const script = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const ids = [...new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]))];

/* ---------- 最小 DOM ---------- */
let seq = 0;
class CL {
  constructor(o){ this.o = o; this.s = new Set(); }
  add(...c){ c.forEach(x => this.s.add(x)); }
  remove(...c){ c.forEach(x => this.s.delete(x)); }
  contains(c){ return this.s.has(c); }
  toggle(c, on){ if (on === undefined) on = !this.s.has(c); on ? this.s.add(c) : this.s.delete(c); return on; }
}
class El {
  constructor(tag){
    this.tagName = String(tag).toUpperCase(); this.children = []; this.parent = null;
    this.classList = new CL(this); this.dataset = {}; this.style = {}; this.attrs = {};
    this._text = ''; this.hidden = false; this.id = ''; this._className = '';
    this.handlers = {}; this._uid = ++seq; this.disabled = false; this.value = '';
  }
  // 本物の DOM と同じく className と classList は同じものを指す
  set className(v){ this._className = String(v || ''); this.classList.s = new Set(this._className.split(/\s+/).filter(Boolean)); }
  get className(){ return [...this.classList.s].join(' '); }
  set textContent(v){ this._text = String(v); this.children = []; }
  get textContent(){ return this.children.length ? this.children.map(c => c.textContent).join('') : this._text; }
  appendChild(c){ c.parent = this; this.children.push(c); return c; }
  removeChild(c){ const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; }
  insertBefore(c, ref){ const i = this.children.indexOf(ref); this.children.splice(i < 0 ? this.children.length : i, 0, c); c.parent = this; return c; }
  setAttribute(k, v){ this.attrs[k] = String(v); }
  getAttribute(k){ return this.attrs[k]; }
  addEventListener(t, fn){ (this.handlers[t] = this.handlers[t] || []).push(fn); }
  removeEventListener(){}
  get firstChild(){ return this.children[0] || null; }
  _all(){ return this.children.flatMap(c => [c, ...c._all()]); }
  _match(sel){
    if (sel.startsWith('.')) return this.classList.contains(sel.slice(1));
    const m = sel.match(/^\.?([\w-]*)\[([\w-]+)="([^"]*)"\]$/);
    if (m){
      const cls = sel.startsWith('.') ? sel.slice(1).split('[')[0] : null;
      const key = m[2].replace(/^data-/, '');
      const okCls = !cls || this.classList.contains(cls);
      return okCls && (this.dataset[key] === m[3] || this.attrs[m[2]] === m[3]);
    }
    return false;
  }
  querySelector(sel){ return this._all().find(e => e._match(sel)) || null; }
  querySelectorAll(sel){ return this._all().filter(e => e._match(sel)); }
  getBoundingClientRect(){ return {left: 0, top: this._uid, right: 300, bottom: this._uid + 100, width: 300, height: 100}; }
  get offsetHeight(){ return 120; }
  scrollIntoView(){}
  focus(){} blur(){}
  get lastChild(){ return this.children[this.children.length - 1] || null; }
}
const registry = {};
const document = {
  createElement: t => new El(t),
  createElementNS: (ns, t) => new El(t),
  createTextNode: t => { const e = new El('#text'); e._text = String(t); return e; },
  getElementById: id => registry[id] || (registry[id] = new El('div')),
  addEventListener(){},
  // 例文チップの配線 document.querySelectorAll('.ex-chip') で script 評価が落ちないようにする。
  // シムは静的マークアップを持たないので空配列でよい(EVIDENCE/compare/domtest_compare.js と同じ流儀)。
  querySelectorAll: () => [],
  querySelector: () => null,
  body: new El('body'), documentElement: new El('html')
};
// HTML 上で hidden 属性が付いている要素は、シム側でも hidden=true から始める
ids.forEach(id => {
  registry[id] = new El('div');
  registry[id].id = id;
  const tag = html.match(new RegExp('<[a-z]+[^>]*\\bid="' + id + '"[^>]*>', 'i'));
  if (tag && /\shidden(\s|>|=)/.test(tag[0])) registry[id].hidden = true;
});
const window = {addEventListener(){}, matchMedia: () => ({matches: false})};
let rafQ = [];
const requestAnimationFrame = fn => { rafQ.push(fn); return rafQ.length; };
const cancelAnimationFrame = () => {};
const performance = {now: () => Date.now()};
const navigator = {clipboard: {writeText: async () => {}}};
function flushRAF(n){ for (let i = 0; i < (n || 8); i++){ const q = rafQ; rafQ = []; q.forEach(f => { try{ f(performance.now()); }catch(e){ throw e; } }); } }

/* ---------- SSE を返す fetch スタブ ---------- */
const EVENTS = [
  {type:'meta', partial:true, residual_ambiguity_assessment:'', missing_materials:[], elapsed_ms:4200},
  {type:'branch', index:0, elapsed_ms:5700, branch:{id:'b0', question_point:'「うちの会社」の業種', anchor_words:['うちの会社'], options:[{label:'BtoB'},{label:'BtoC'}], default_if_unresolved:'BtoB'}},
  {type:'branch', index:1, elapsed_ms:6900, branch:{id:'b1', question_point:'LPの目的', anchor_words:['LP'], options:[{label:'問い合わせ'},{label:'購入'},{label:'認知'}], default_if_unresolved:'問い合わせ'}},
  {type:'branch', index:2, elapsed_ms:8300, branch:{id:'b2', question_point:'モダンと温かみの配分', anchor_words:['モダンだけど温かみのある'], options:[{label:'モダン寄り'},{label:'温かみ寄り'}], default_if_unresolved:'均等'}},
  {type:'done', ok:true, branches:[], residual_ambiguity_assessment:'業種が不明なままである。', missing_materials:['ロゴ素材'],
   rejected_branches:[], branches_returned_by_model:3, timing:{wall_ms:11500, api_ms:9300}, api_ms:9300, first_branch_ms:5700, elapsed_ms:11600}
];
let MODE = 'stream';
let EVENT_GAP_MS = 0;
const enc = s => Buffer.from(s, 'utf8');
function sseBody(events){
  let i = 0;
  return {
    getReader(){
      return { async read(){
        // 実際のストリームのように1件ずつ間隔を空けて届ける(途中状態を観測可能にする)
        await new Promise(r => setTimeout(r, EVENT_GAP_MS));
        if (i === 0){ i++; return {value: enc(': keepalive\n\n'), done: false}; }
        const k = i - 1; i++;
        if (k >= events.length) return {value: undefined, done: true};
        return {value: enc('data: ' + JSON.stringify(events[k]) + '\n\n'), done: false};
      }};
    }
  };
}
async function fetchStub(url, opt){
  if (url === '/api/health') return {ok: true, json: async () => ({ok: true})};
  if (url === '/api/explode_stream'){
    if (MODE === 'fail_http') return {ok: false, body: null};
    if (MODE === 'fail_early') return {ok: true, body: sseBody([{type:'error', error:'claude 起動失敗', hint:'h'}])};
    return {ok: true, body: sseBody(EVENTS)};
  }
  if (url === '/api/explode'){
    return {ok: true, json: async () => ({ok: true, branches: EVENTS.slice(1,4).map(e => e.branch),
      residual_ambiguity_assessment: 'batch', missing_materials: [], timing: {wall_ms: 13000, api_ms: 11000}})};
  }
  if (url === '/api/render'){
    return {ok: true, json: async () => ({ok: true, tokens: {palette:['#112233','#445566','#778899'], heading_font:'sans', density:'normal', corner:'soft', tone_sample:'見出し。一文。'}})};
  }
  return {ok: false, json: async () => ({ok: false})};
}
class TextDecoderShim { decode(b){ return b ? Buffer.from(b).toString('utf8') : ''; } }


/* ---------- 実行 ---------- */
const vm = require('vm');
const sleep = ms => new Promise(r => setTimeout(r, ms));
let FAILS = [];

function fresh(){
  Object.keys(registry).forEach(k => delete registry[k]);
  ids.forEach(id => {
    registry[id] = new El('div'); registry[id].id = id;
    const tag = html.match(new RegExp('<[a-z]+[^>]*\\bid="' + id + '"[^>]*>', 'i'));
    if (tag && /\shidden(\s|>|=)/.test(tag[0])) registry[id].hidden = true;
  });
  rafQ = [];
  const ctx = {document, window, requestAnimationFrame, cancelAnimationFrame, performance, navigator,
    fetch: fetchStub, TextDecoder: TextDecoderShim, setTimeout, clearTimeout, setInterval, clearInterval,
    console, JSON, Math, Date, Promise, Array, Object, String, Number, Boolean, parseInt, parseFloat, isNaN};
  vm.createContext(ctx);
  vm.runInContext(script + '\n;globalThis.__S=S; globalThis.__submit=submitBrief;', ctx);
  return ctx;
}
async function runCase(name, mode, opts){
  MODE = mode;
  const ctx = fresh();
  registry['briefInput'].value = 'モダンだけど温かみのあるLPを作って。うちの会社のやつ。';
  const p = ctx.__submit();
  const steps = (opts && opts.steps) || 60;
  for (let i=0;i<steps;i++){ flushRAF(3); await sleep(12); }
  if (!opts || !opts.stopEarly){ await p; flushRAF(6); await sleep(450); flushRAF(6); }
  return ctx.__S;
}
const chk=(n,c,e)=>{console.log((c?'OK   ':'FAIL ')+n+(e?'  '+e:'')); if(!c) FAILS.push(n);};

(async () => {
  console.log('=== 1) HTTP が SSE を返せない → /api/explode へフォールバック ===');
  let S = await runCase('http', 'fail_http');
  chk('フォールバックで爆散する', S.exploded === true);
  chk('一括の分岐3件が入る', S.branches.length === 3, 'n='+S.branches.length);
  chk('streaming が残らない', S.streaming === false);
  chk('カウンタが確定表示', registry['branchCounter'].textContent.indexOf('この文から抽出した判断点')===0,
      JSON.stringify(registry['branchCounter'].textContent));
  chk('一括経路では allBranchesMs は null', S.allBranchesMs === null);
  chk('assessment は一括のもの', S.assessment === 'batch', S.assessment);

  console.log('\n=== 2) ストリームが1枚も出せずエラー → フォールバック ===');
  S = await runCase('early', 'fail_early');
  chk('フォールバックで爆散する', S.exploded === true);
  chk('一括の分岐3件が入る', S.branches.length === 3, 'n='+S.branches.length);
  chk('カウンタが「抽出中」で固まらない', registry['branchCounter'].textContent.indexOf('抽出中') < 0,
      JSON.stringify(registry['branchCounter'].textContent));
  chk('カード3枚', registry['cards'].children.length === 3);

  console.log('\n=== 3) 途中(done 未達)の画面状態 ===');
  MODE = 'stream'; EVENT_GAP_MS = 120;
  const ctx = fresh();
  registry['briefInput'].value = 'モダンだけど温かみのあるLPを作って。うちの会社のやつ。';
  ctx.__submit();
  // branch が1〜2枚届いた時点で止める
  let guard=0;
  while (ctx.__S.branches.length < 2 && guard++ < 300){ flushRAF(2); await sleep(8); }
  const mid = ctx.__S;
  chk('途中でも爆散は始まっている', mid.exploded === true);
  chk('途中は streaming=true / streamDone=false', mid.streaming === true && mid.streamDone === false);
  chk('途中のカウンタは「抽出中」', registry['branchCounter'].textContent.indexOf('抽出中') >= 0,
      JSON.stringify(registry['branchCounter'].textContent));
  chk('途中は「N→0」を出さない', registry['branchCounter'].textContent.indexOf('→0') < 0);
  chk('途中は streaming クラスが付く', registry['cards'].classList.contains('streaming'));
  chk('途中でもコンパイル行は出ない', registry['compileRow'].hidden === true);
  // 途中で全部決めてもコンパイルへ進ませない(総数未確定)
  vm.runInContext('decide(0,0); if (S.branches.length>1) decide(1,0);', ctx);
  chk('総数未確定なら残0でもコンパイル行は出ない', registry['compileRow'].hidden === true);
  chk('途中で決めた語も色が付く', mid.spans.some(sp => sp.el && sp.el.dataset.state === 'decided'));
  // 最後まで流す
  for (let i=0;i<120;i++){ flushRAF(3); await sleep(20); }
  flushRAF(6); await sleep(400); flushRAF(6);
  chk('done 後はコンパイル行の判定が復活する', mid.streamDone === true);
  chk('done 後 streaming クラスが外れる', registry['cards'].classList.contains('streaming') === false);
  chk('途中の決定が done 後も保持される', mid.decisions[0].status === 'decided');

  console.log('\n=== 4) 走査の朱(#briefText.scanning)が静寂で灯り、爆散で消える ===');
  // 2026-07-30 追加。startSilence(遷移 380ms)が付け、beginExplode(最初の分岐)が外す。
  // 分岐が 380ms より遅く着く経路でしか観測できないので、到着間隔を広げて確かめる。
  MODE = 'stream'; EVENT_GAP_MS = 500;
  const ctx4 = fresh();
  registry['briefInput'].value = 'モダンだけど温かみのあるLPを作って。うちの会社のやつ。';
  ctx4.__submit();
  const bt = registry['briefText'];
  chk('送信直後はまだ走査していない', bt.classList.contains('scanning') === false);
  for (let i = 0; i < 200 && !bt.classList.contains('scanning'); i++){ flushRAF(2); await sleep(10); }
  chk('静寂に入ると走査の朱が灯る', bt.classList.contains('scanning') === true, JSON.stringify(bt.className));
  for (let i = 0; i < 400 && ctx4.__S.exploded !== true; i++){ flushRAF(2); await sleep(10); }
  chk('前提: 最初の分岐で爆散が始まっている', ctx4.__S.exploded === true);
  chk('爆散(圏点を打つ)で走査が止まる', bt.classList.contains('scanning') === false, JSON.stringify(bt.className));

  console.log(FAILS.length ? '\n--- FAILED: ' + FAILS.join(' / ') : '\n--- フォールバック/途中状態/走査の朱: すべて期待どおり');
  process.exit(FAILS.length ? 1 : 0);
})().catch(e => { console.error('THREW:', e && e.stack || e); process.exit(2); });
