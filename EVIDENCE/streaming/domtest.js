// app/index.html のスクリプトを最小 DOM シムの上で実行し、
// SSE 受信 → 逐次カード追加 → done 確定 までの状態遷移を検証する。
// ブラウザそのものではないので「throw しないこと」「状態が期待どおりに遷移すること」を見る。
const fs = require('fs');
const PATH = '/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon/app/index.html';
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
const enc = s => Buffer.from(s, 'utf8');
function sseBody(events){
  let i = 0;
  return {
    getReader(){
      return { async read(){
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
const ctx = {document, window, requestAnimationFrame, cancelAnimationFrame, performance, navigator,
  fetch: fetchStub, TextDecoder: TextDecoderShim, setTimeout, clearTimeout, setInterval, clearInterval,
  console, JSON, Math, Date, Promise, Array, Object, String, Number, Boolean, parseInt, parseFloat, isNaN};
const vm = require('vm');
vm.createContext(ctx);
vm.runInContext(script + '\n;globalThis.__S = S; globalThis.__submit = submitBrief; globalThis.__el = (i)=>document.getElementById(i);', ctx);

const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const S = ctx.__S;
  // 送信
  registry['briefInput'].value = 'モダンだけど温かみのあるLPを作って。うちの会社のやつ。';
  const p = ctx.__submit();
  for (let i = 0; i < 60; i++){ flushRAF(3); await sleep(12); }
  await p;
  flushRAF(6); await sleep(450); flushRAF(6);

  const cards = registry['cards'];
  const fail = [];
  const chk = (name, cond, extra) => { console.log((cond ? 'OK   ' : 'FAIL ') + name + (extra ? '  ' + extra : '')); if (!cond) fail.push(name); };

  chk('exploded / shattered が立つ', S.exploded === true && S.shattered === true);
  chk('streamDone が立つ', S.streamDone === true);
  chk('streaming が畳まれる', S.streaming === false);
  chk('分岐3件が state に入る', S.branches.length === 3, 'branches=' + S.branches.length);
  chk('カード3枚が DOM に入る', cards.children.length === 3, 'cards=' + cards.children.length);
  chk('decisions/renders が分岐数と一致', S.decisions.length === 3 && S.renders.length === 3);
  chk('全分岐がスパンを1本以上持つ', S.branches.every((_, bi) => S.spans.some(sp => sp.bis.indexOf(bi) >= 0)),
      'spans=' + JSON.stringify(S.spans.map(s => s.text)));
  chk('done で streaming クラスが外れる', cards.classList.contains('streaming') === false);
  chk('done でカードのフェードイン抑制(pending)が全て解ける',
      cards.children.every(c => !c.classList.contains('pending')));
  chk('meta ではなく done の assessment が採用される', S.assessment === '業種が不明なままである。', S.assessment);
  chk('missing_materials が done から入る', JSON.stringify(S.missing) === JSON.stringify(['ロゴ素材']));
  chk('first_branch_ms が記録される', S.explodeTiming && S.explodeTiming.first_branch_ms === 5700, JSON.stringify(S.explodeTiming));
  chk('streamed フラグが立つ', S.explodeTiming && S.explodeTiming.streamed === true);
  chk('allBranchesMs が記録される', typeof S.allBranchesMs === 'number');
  chk('カウンタが確定表示になる', registry['branchCounter'].textContent.indexOf('この文から抽出した判断点') === 0,
      JSON.stringify(registry['branchCounter'].textContent));
  chk('カウンタに「抽出中」が残らない', registry['branchCounter'].textContent.indexOf('抽出中') < 0);
  chk('原文の min-height が予約される', !!registry['briefText'].style.minHeight, registry['briefText'].style.minHeight);
  chk('未決なのでコンパイル行は出ない', registry['compileRow'].hidden === true);

  // 決める → カウンタ0 → コンパイル行
  vm.runInContext('decide(0,0); decide(1,1); delegate(2);', ctx);
  flushRAF(4);
  chk('3件解決でコンパイル行が出る', registry['compileRow'].hidden === false);
  chk('カウンタが 0 を示す', registry['branchCounter'].classList.contains('zero'));
  chk('決定した語の色が decided になる',
      S.spans.some(sp => sp.el && sp.el.dataset.state === 'decided'),
      JSON.stringify(S.spans.map(sp => sp.el && sp.el.dataset.state)));
  chk('委任した語の色が delegated になる',
      S.spans.some(sp => sp.el && sp.el.dataset.state === 'delegated'));

  console.log(fail.length ? '\n--- FAILED: ' + fail.join(' / ') : '\n--- ストリーミング経路: すべて期待どおり');
  process.exit(fail.length ? 1 : 0);
})().catch(e => { console.error('THREW:', e && e.stack || e); process.exit(2); });
