// 2026-07-29 の2点を検証する(domtest.js / domtest2.js と同じ最小 DOM シムを使う)。
//   A) branches 先スキーマ: meta より先に branch が届く順序でも画面が正しく作られる
//   B) 凍結の穴: 凍結中は equalizeCardHeights が既存カードの高さを変えない(解除後に適用)
// カードの高さは #cards の子インデックスごとに CARD_H で与える(シムなので min-height は
// offsetHeight に影響しない。ここで見たいのは「min-height に何が書かれるか」だけ)。
const fs = require('fs');
const PATH = '/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon/app/index.html';
const html = fs.readFileSync(PATH, 'utf8');
const script = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const ids = [...new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]))];

let CARD_H = [100, 100, 300];

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
  get offsetHeight(){
    if (this.parent && this.parent.id === 'cards'){
      const i = this.parent.children.indexOf(this);
      return CARD_H[i] != null ? CARD_H[i] : 120;
    }
    return 120;
  }
  scrollIntoView(){}
  focus(){} blur(){}
  get lastChild(){ return this.children[this.children.length - 1] || null; }
}
const registry = {};
const docHandlers = {};
const document = {
  createElement: t => new El(t),
  createElementNS: (ns, t) => new El(t),
  createTextNode: t => { const e = new El('#text'); e._text = String(t); return e; },
  getElementById: id => registry[id] || (registry[id] = new El('div')),
  addEventListener(t, fn){ (docHandlers[t] = docHandlers[t] || []).push(fn); },
  body: new El('body'), documentElement: new El('html')
};
const window = {addEventListener(){}, matchMedia: () => ({matches: false})};
let rafQ = [];
const requestAnimationFrame = fn => { rafQ.push(fn); return rafQ.length; };
const cancelAnimationFrame = () => {};
const performance = {now: () => Date.now()};
const navigator = {clipboard: {writeText: async () => {}}};
function flushRAF(n){ for (let i = 0; i < (n || 8); i++){ const q = rafQ; rafQ = []; q.forEach(f => f(performance.now())); } }

/* ---- branch が meta より先に届く SSE(branches 先スキーマの実際の順序) ---- */
const B = (i, qp, aw, def) => ({type:'branch', index:i, elapsed_ms:5000 + i*1000,
  branch:{id:'b'+i, question_point:qp, anchor_words:[aw],
          options:[{label:'案A'},{label:'案B'}], default_if_unresolved:def}});
const EVENTS = [
  B(0, '「うちの会社」の業種', 'うちの会社', 'BtoB'),
  B(1, 'LPの目的', 'LP', '問い合わせ'),
  B(2, 'モダンと温かみの配分', 'モダンだけど温かみのある', '均等'),
  // meta は branches を書き終えた後に来る(サーバは空の先触れを先に出すが、
  // ここでは「最悪の順序 = 完全に後着」で試す)
  {type:'meta', partial:false, residual_ambiguity_assessment:'業種が不明である。',
   missing_materials:['ロゴ素材'], elapsed_ms:9000},
  {type:'done', ok:true, branches:[], residual_ambiguity_assessment:'業種が不明である。',
   missing_materials:['ロゴ素材'], rejected_branches:[], branches_returned_by_model:3,
   timing:{wall_ms:11500, api_ms:9300}, api_ms:9300, first_branch_ms:5000, elapsed_ms:11600}
];
let EVENT_GAP_MS = 150;
const enc = s => Buffer.from(s, 'utf8');
function sseBody(events){
  let i = 0;
  return {getReader(){ return {async read(){
    await new Promise(r => setTimeout(r, EVENT_GAP_MS));
    if (i === 0){ i++; return {value: enc(': keepalive\n\n'), done: false}; }
    const k = i - 1; i++;
    if (k >= events.length) return {value: undefined, done: true};
    return {value: enc('data: ' + JSON.stringify(events[k]) + '\n\n'), done: false};
  }};}};
}
async function fetchStub(url){
  if (url === '/api/health') return {ok: true, json: async () => ({ok: true})};
  if (url === '/api/explode_stream') return {ok: true, body: sseBody(EVENTS)};
  if (url === '/api/render') return {ok: true, json: async () => ({ok: true,
    tokens: {palette:['#112233','#445566','#778899'], heading_font:'sans', density:'normal',
             corner:'soft', tone_sample:'見出し。一文。'}})};
  return {ok: false, json: async () => ({ok: false})};
}
class TextDecoderShim { decode(b){ return b ? Buffer.from(b).toString('utf8') : ''; } }

const vm = require('vm');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const FAILS = [];
const chk = (n, c, e) => { console.log((c ? 'OK   ' : 'FAIL ') + n + (e ? '  ' + e : '')); if (!c) FAILS.push(n); };

function fresh(){
  Object.keys(registry).forEach(k => delete registry[k]);
  Object.keys(docHandlers).forEach(k => delete docHandlers[k]);
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
const minHeights = () => registry['cards'].children.map(c => c.style.minHeight);
function firePointerOverCards(){
  const r = registry['cards'].getBoundingClientRect();
  (docHandlers['pointermove'] || []).forEach(fn => fn({clientX: 10, clientY: r.top + 10}));
}

(async () => {
  console.log('=== A) meta より先に branch が届く順序 ===');
  CARD_H = [100, 100, 100];
  let ctx = fresh();
  registry['briefInput'].value = 'モダンだけど温かみのあるLPを作って。うちの会社のやつ。';
  let p = ctx.__submit();
  let S = ctx.__S;
  let guard = 0;
  while (S.branches.length < 1 && guard++ < 400){ flushRAF(2); await sleep(8); }
  chk('meta 未着でも最初の branch で爆散が始まる', S.exploded === true && S.shattered === true);
  chk('meta 未着でも総数未確定の印が立っている', S.streaming === true && S.streamDone === false);
  chk('meta 未着でもカウンタは「抽出中」', registry['branchCounter'].textContent.indexOf('抽出中') >= 0,
      JSON.stringify(registry['branchCounter'].textContent));
  chk('meta 未着の間は assessment が空のまま(捏造しない)', S.assessment === '');
  await p; flushRAF(6); await sleep(400); flushRAF(6);
  chk('done まで流すと分岐3件', S.branches.length === 3, 'n=' + S.branches.length);
  chk('後着 meta / done の assessment が入る', S.assessment === '業種が不明である。', S.assessment);
  chk('後着の missing_materials が入る', JSON.stringify(S.missing) === '["ロゴ素材"]', JSON.stringify(S.missing));
  chk('カウンタが確定表示に変わる', registry['branchCounter'].textContent.indexOf('この文から抽出した判断点') === 0,
      JSON.stringify(registry['branchCounter'].textContent));
  chk('first_branch_ms が done の値で記録される',
      S.explodeTiming && S.explodeTiming.first_branch_ms === 5000,
      JSON.stringify(S.explodeTiming));

  console.log('\n=== B) 凍結中は高さを変えない(解除後に適用) ===');
  CARD_H = [100, 100, 300];          // 3枚目だけ背が高い
  ctx = fresh();
  registry['briefInput'].value = 'モダンだけど温かみのあるLPを作って。うちの会社のやつ。';
  p = ctx.__submit();
  S = ctx.__S;
  guard = 0;
  while (S.branches.length < 2 && guard++ < 400){ flushRAF(2); await sleep(8); }
  chk('2枚目までは高さが揃っている', JSON.stringify(minHeights()) === '["100px","100px"]', JSON.stringify(minHeights()));
  const before = minHeights().slice();
  firePointerOverCards();
  chk('ポインタ接近で凍結する', S.frozen === true);
  chk('凍結の直前に高さがロックされている', JSON.stringify(minHeights()) === JSON.stringify(before),
      JSON.stringify(minHeights()));
  guard = 0;
  while (S.branches.length < 3 && guard++ < 400){ flushRAF(2); await sleep(8); }
  chk('凍結中に背の高い3枚目が届いても既存2枚は変わらない',
      minHeights()[0] === '100px' && minHeights()[1] === '100px', JSON.stringify(minHeights()));
  chk('凍結中の要求は保留される', S.equalizePending === true);
  await p; flushRAF(6); await sleep(400); flushRAF(6);
  chk('done(equalize 呼び出し)でも凍結中は変わらない',
      minHeights()[0] === '100px' && minHeights()[1] === '100px', JSON.stringify(minHeights()));
  chk('凍結中も保留は立ったまま', S.equalizePending === true);
  vm.runInContext('S.frozen = false; equalizeCardHeights();', ctx);
  chk('凍結解除後の呼び出しで 300px に揃う',
      JSON.stringify(minHeights()) === '["300px","300px","300px"]', JSON.stringify(minHeights()));
  chk('保留が畳まれる', S.equalizePending === false);

  console.log(FAILS.length ? '\n--- FAILED: ' + FAILS.join(' / ') : '\n--- 到着順序 / 凍結: すべて期待どおり');
  process.exit(FAILS.length ? 1 : 0);
})().catch(e => { console.error('THREW:', e && e.stack || e); process.exit(2); });
