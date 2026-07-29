// 2026-07-29 Codex監査の採択指摘(M1 / M7 / N4 / M2b)を機械で押さえる。
// domtest3.js と同じ最小 DOM シムを使う。
//   A) 途中切断: done 未到達の部分集合を「確定」にしない。一括 /api/explode で
//      取り直して question_point で照合し、既にユーザーが決めた決定を失わない(M1)
//   B) 再取得も失敗: 総数を確定させない(コンパイル不可のまま)。決定は保持し、
//      帯に理由と「再取得」ボタンを出す(M1)
//   C) 凍結解除: pointerleave / 操作確定(decide)で S.frozen が解け、
//      保留していた高さそろえが適用される(M7)
//   D) 380ms 未満で最初の分岐が着いたとき、遷移タイマーが cancel される(N4)
//   E) 復旧時に走行中レンダを AbortController で中断し、復旧後に再開する(M2b)
const fs = require('fs');
const PATH = '/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon/app/index.html';
const html = fs.readFileSync(PATH, 'utf8');
const script = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const ids = [...new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]))];

let CARD_H = [100, 100, 300, 100, 100];

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
const winHandlers = {};
const window = {
  addEventListener(t, fn){ (winHandlers[t] = winHandlers[t] || []).push(fn); },
  matchMedia: () => ({matches: false})
};
let rafQ = [];
const requestAnimationFrame = fn => { rafQ.push(fn); return rafQ.length; };
const cancelAnimationFrame = () => {};
const performance = {now: () => Date.now()};
const navigator = {clipboard: {writeText: async () => {}}};
function flushRAF(n){ for (let i = 0; i < (n || 8); i++){ const q = rafQ; rafQ = []; q.forEach(f => f(performance.now())); } }
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ---------- タイマーのスパイ(N4: 380ms の遷移タイマーが cancel されたか) ---------- */
const t380 = [];
const cleared = new Set();
const setTimeoutSpy = (fn, ms) => { const id = setTimeout(fn, ms); if (ms === 380) t380.push(id); return id; };
const clearTimeoutSpy = (id) => { cleared.add(id); return clearTimeout(id); };

/* ---------- SSE / fetch のスタブ ---------- */
const BRIEF = 'モダンだけど温かみのあるLPを作って。うちの会社のやつ。';
const B = (i, qp, aw, def) => ({type: 'branch', index: i, elapsed_ms: 5000 + i * 1000,
  branch: {id: 'b' + i, question_point: qp, anchor_words: [aw],
           options: [{label: '案A'}, {label: '案B'}], default_if_unresolved: def}});
const QP = ['「うちの会社」の業種', 'LPの目的', 'モダンと温かみの配分', '想定読者'];
const AW = ['うちの会社', 'LP', 'モダンだけど温かみのある', '作って'];
const STREAM_EVENTS = [B(0, QP[0], AW[0], 'BtoB'), B(1, QP[1], AW[1], '問い合わせ')];
// 一括再取得は「ストリームで出た2件 + まだ出ていない2件」を返す(照合の本番形)
const BULK_BRANCHES = [0, 1, 2, 3].map(i => ({
  id: 'x' + i, question_point: QP[i], anchor_words: [AW[i]],
  options: [{label: '案A'}, {label: '案B'}], default_if_unresolved: 'd' + i
}));

let GAP = 60;
let FAIL_AFTER = STREAM_EVENTS.length;   // この回数だけ読めたら切断する
let BULK_OK = true;
let RENDER_MS = 30;
let renderCalls = 0;
const enc = s => Buffer.from(s, 'utf8');
function sseBodyFailing(events){
  let i = 0;
  return {getReader(){ return {async read(){
    await sleep(GAP);
    if (i >= FAIL_AFTER) throw new Error('network reset (simulated)');
    const ev = events[i++];
    return {value: enc('data: ' + JSON.stringify(ev) + '\n\n'), done: false};
  }};}};
}
function renderStub(opt){
  renderCalls++;
  const ms = RENDER_MS;
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => resolve({ok: true, json: async () => ({ok: true,
      tokens: {palette: ['#112233', '#445566', '#778899'], heading_font: 'sans',
               density: 'normal', corner: 'soft', tone_sample: '見出し。一文。'}})}), ms);
    if (opt && opt.signal){
      opt.signal.addEventListener('abort', () => {
        clearTimeout(t);
        const e = new Error('aborted'); e.name = 'AbortError'; reject(e);
      });
    }
  });
}
async function fetchStub(url, opt){
  if (url === '/api/health') return {ok: true, json: async () => ({ok: true})};
  if (url === '/api/explode_stream') return {ok: true, body: sseBodyFailing(STREAM_EVENTS)};
  if (url === '/api/render') return renderStub(opt);
  if (url === '/api/explode'){
    await sleep(40);
    if (!BULK_OK) return {ok: true, json: async () => ({ok: false, error: 'claude CLI がエラーを返した'})};
    return {ok: true, json: async () => ({
      ok: true, branches: BULK_BRANCHES,
      residual_ambiguity_assessment: '業種が不明である。', missing_materials: ['ロゴ素材'],
      timing: {wall_ms: 9000, api_ms: 7000}
    })};
  }
  return {ok: false, json: async () => ({ok: false})};
}
class TextDecoderShim { decode(b){ return b ? Buffer.from(b).toString('utf8') : ''; } }

const vm = require('vm');
const FAILS = [];
const chk = (n, c, e) => { console.log((c ? 'OK   ' : 'FAIL ') + n + (e ? '  ' + e : '')); if (!c) FAILS.push(n); };

function fresh(withAbort){
  Object.keys(registry).forEach(k => delete registry[k]);
  Object.keys(docHandlers).forEach(k => delete docHandlers[k]);
  Object.keys(winHandlers).forEach(k => delete winHandlers[k]);
  ids.forEach(id => {
    registry[id] = new El('div'); registry[id].id = id;
    const tag = html.match(new RegExp('<[a-z]+[^>]*\\bid="' + id + '"[^>]*>', 'i'));
    if (tag && /\shidden(\s|>|=)/.test(tag[0])) registry[id].hidden = true;
  });
  rafQ = [];
  const ctx = {document, window, requestAnimationFrame, cancelAnimationFrame, performance, navigator,
    fetch: fetchStub, TextDecoder: TextDecoderShim,
    setTimeout: setTimeoutSpy, clearTimeout: clearTimeoutSpy, setInterval, clearInterval,
    console, JSON, Math, Date, Promise, Array, Object, String, Number, Boolean, Set, Map,
    parseInt, parseFloat, isNaN};
  if (withAbort) ctx.AbortController = AbortController;
  vm.createContext(ctx);
  vm.runInContext(script + '\n;globalThis.__S=S; globalThis.__submit=submitBrief;', ctx);
  return ctx;
}
const counter = () => registry['branchCounter'].textContent;
const notice = () => registry['streamNotice'];
const minHeights = () => registry['cards'].children.map(c => c.style.minHeight);
function firePointerOverCards(){
  const r = registry['cards'].getBoundingClientRect();
  (docHandlers['pointermove'] || []).forEach(fn => fn({clientX: 10, clientY: r.top + 10}));
}
function firePointerLeaveCards(){
  (registry['cards'].handlers['pointerleave'] || []).forEach(fn => fn({}));
}
async function waitFor(cond, limit){
  for (let i = 0; i < (limit || 400); i++){
    flushRAF(2); await sleep(10);
    if (cond()) return true;
  }
  return false;
}

(async () => {
  /* ============ A) 途中切断 → 一括再取得で照合(決定は保持) ============ */
  console.log('=== A) done 未到達の部分集合を確定にしない(一括で取り直して照合) ===');
  GAP = 60; FAIL_AFTER = 2; BULK_OK = true; RENDER_MS = 30;
  let ctx = fresh(false);
  registry['briefInput'].value = BRIEF;
  let p = ctx.__submit();
  let S = ctx.__S;
  await waitFor(() => S.branches.length >= 1);
  // 切断より前に1件決めておく(この決定は絶対に失われてはならない)
  vm.runInContext('decide(0,0);', ctx);
  chk('切断前に1件決めてある', S.decisions[0].status === 'decided' && S.decisions[0].oi === 0);

  await waitFor(() => S.recovery.state === 'running');
  chk('切断を検知して復旧が始まる', S.recovery.state === 'running', S.recovery.reason);
  chk('復旧の最中は総数を確定させない', S.streamDone === false && S.streaming === true);
  chk('復旧の最中もコンパイル不可', vm.runInContext('compileReady()', ctx) === false);
  chk('復旧の最中は帯が「作業中」で出る',
      notice().hidden === false && notice().classList.contains('working'),
      JSON.stringify(notice().textContent));

  await p;
  await waitFor(() => S.recovery.state === 'ok' || S.recovery.state === 'failed');
  flushRAF(6); await sleep(120); flushRAF(6);
  chk('★部分集合(2件)で締めていない — 一括の4件に揃う', S.branches.length === 4, 'n=' + S.branches.length);
  chk('★既出2件は question_point で照合され、決定が生き残る',
      S.decisions[0].status === 'decided' && S.decisions[0].oi === 0,
      JSON.stringify(S.decisions.map(d => d.status)));
  chk('照合の内訳が記録される',
      S.recovery.matched === 2 && S.recovery.added === 2 && S.recovery.extra === 0 && S.recovery.kept === 2,
      JSON.stringify(S.recovery));
  chk('照合後に総数が確定する', S.streamDone === true && S.streaming === false);
  chk('カウンタが総数4・未決3を出す',
      counter().indexOf('この文から抽出した判断点') === 0 && counter().indexOf('4') > 0 && counter().indexOf('3') > 0,
      JSON.stringify(counter()));
  chk('未決が残るのでコンパイルは不可', vm.runInContext('compileReady()', ctx) === false);
  chk('カード4枚が並ぶ', registry['cards'].children.length === 4);
  chk('追加された分岐にもスパンが付く',
      [0, 1, 2, 3].every(bi => S.spans.some(sp => sp.bis.indexOf(bi) >= 0)),
      JSON.stringify(S.spans.map(sp => sp.text)));
  chk('復旧した事実が timing に残る', S.explodeTiming && S.explodeTiming.recovered_via_bulk === true,
      JSON.stringify(S.explodeTiming));
  chk('帯が「作業中」から注意帯へ変わる', notice().classList.contains('working') === false,
      JSON.stringify(notice().textContent));
  vm.runInContext('decide(1,0); decide(2,1); delegate(3);', ctx);
  chk('全件決めればコンパイルできる', vm.runInContext('compileReady()', ctx) === true);
  chk('証拠JSONに復旧の記録が載る', (function(){
    const j = JSON.parse(vm.runInContext('buildJSON()', ctx));
    return j.evidence.extraction_recovery && j.evidence.extraction_recovery.state === 'ok'
        && j.evidence.extraction_recovery.matched === 2 && j.decisions.length === 4;
  })());

  /* ============ B) 再取得も失敗 → 確定させない ============ */
  console.log('\n=== B) 再取得も失敗したら総数を確定させない(決定は保持) ===');
  GAP = 60; FAIL_AFTER = 2; BULK_OK = false;
  ctx = fresh(false);
  registry['briefInput'].value = BRIEF;
  p = ctx.__submit();
  S = ctx.__S;
  await waitFor(() => S.branches.length >= 1);
  vm.runInContext('decide(0,1);', ctx);
  await p;
  await waitFor(() => S.recovery.state === 'failed');
  flushRAF(6); await sleep(80); flushRAF(6);
  chk('★総数は確定しない(部分集合を成功にしない)', S.streamDone === false);
  chk('★コンパイルは不可のまま', vm.runInContext('compileReady()', ctx) === false &&
      registry['compileRow'].hidden === true);
  chk('既出カードは消えない', S.branches.length === 2 && registry['cards'].children.length === 2);
  chk('決定は保持される', S.decisions[0].status === 'decided' && S.decisions[0].oi === 1);
  chk('帯に理由と再取得ボタンが出る',
      notice().hidden === false &&
      notice()._all().filter(e => e.tagName === 'BUTTON').length === 2,
      JSON.stringify(notice().textContent));
  // 帯の「再取得」を押すと、今度は成功して照合まで進む
  BULK_OK = true;
  const btnRetry = notice()._all().find(e => e.tagName === 'BUTTON');
  btnRetry.handlers['click'][0]();
  await waitFor(() => S.recovery.state === 'ok');
  flushRAF(6); await sleep(80); flushRAF(6);
  chk('★再取得ボタンで復旧できる', S.streamDone === true && S.branches.length === 4,
      'n=' + S.branches.length + ' attempts=' + S.recovery.attempts);
  chk('再取得後も最初の決定は生きている', S.decisions[0].status === 'decided' && S.decisions[0].oi === 1);

  /* ============ C) 凍結の解除(M7) ============ */
  console.log('\n=== C) 凍結が pointerleave / 操作確定で解ける ===');
  GAP = 60; FAIL_AFTER = 2; BULK_OK = true;
  CARD_H = [100, 100, 300, 300];
  ctx = fresh(false);
  registry['briefInput'].value = BRIEF;
  p = ctx.__submit();
  S = ctx.__S;
  await waitFor(() => S.branches.length >= 2);
  firePointerOverCards();
  chk('前提: ポインタ接近で凍結する', S.frozen === true);
  await p;
  await waitFor(() => S.recovery.state === 'ok');
  flushRAF(6); await sleep(80); flushRAF(6);
  chk('前提: 凍結中に届いたカードの高さは保留される', S.equalizePending === true);
  chk('前提: 既存カードは動いていない', minHeights()[0] === '100px' && minHeights()[1] === '100px',
      JSON.stringify(minHeights()));
  firePointerLeaveCards();
  chk('★pointerleave で凍結が解ける', S.frozen === false);
  chk('★保留していた高さそろえが適用される',
      minHeights().every(h => h === '300px'), JSON.stringify(minHeights()));
  chk('保留が畳まれる', S.equalizePending === false);

  // 操作確定(decide)でも解ける
  CARD_H = [100, 100, 300, 300];
  ctx = fresh(false);
  registry['briefInput'].value = BRIEF;
  p = ctx.__submit();
  S = ctx.__S;
  await waitFor(() => S.branches.length >= 2);
  firePointerOverCards();
  await p;
  await waitFor(() => S.recovery.state === 'ok');
  flushRAF(6); await sleep(80); flushRAF(6);
  chk('前提: 凍結が残っている', S.frozen === true && S.equalizePending === true);
  vm.runInContext('decide(0,0);', ctx);
  chk('★決めた瞬間に凍結が解ける', S.frozen === false);
  chk('★保留していた高さそろえが適用される(操作確定)',
      minHeights().every(h => h === '300px'), JSON.stringify(minHeights()));

  /* ============ D) 380ms 未満で最初の分岐(N4) ============ */
  console.log('\n=== D) 380ms より先に分岐が着いたら遷移タイマーを取り消す ===');
  GAP = 20; FAIL_AFTER = 2; BULK_OK = true;
  CARD_H = [100, 100, 100, 100];
  t380.length = 0; cleared.clear();
  ctx = fresh(false);
  registry['briefInput'].value = BRIEF;
  p = ctx.__submit();
  S = ctx.__S;
  await waitFor(() => S.exploded === true);
  const explodedAt = Date.now();
  chk('380ms より先に爆散している', S.exploded === true);
  chk('★遷移タイマーが仕掛けられていた', t380.length === 1, 'n=' + t380.length);
  chk('★爆散でそのタイマーが取り消される', t380.every(id => cleared.has(id)));
  await sleep(Math.max(0, 500 - (Date.now() - explodedAt)));
  flushRAF(6);
  chk('タイマー時刻を過ぎても原文の語スパンが残る',
      S.spans.length > 0 && S.spans.every(sp => sp.el && sp.el.classList.contains('tok')),
      'spans=' + S.spans.length);
  chk('原文が素の文字列へ戻っていない', registry['briefText'].children.length > 1,
      'children=' + registry['briefText'].children.length);
  await p; await waitFor(() => S.recovery.state === 'ok');

  /* ============ E) 復旧時のレンダ中断と再開(M2b) ============ */
  console.log('\n=== E) 復旧のとき走行中レンダを中断し、復旧後に再開する ===');
  GAP = 60; FAIL_AFTER = 2; BULK_OK = true; RENDER_MS = 4000;   // 復旧中も終わらない長さ
  renderCalls = 0;
  ctx = fresh(true);                                            // AbortController あり
  registry['briefInput'].value = BRIEF;
  p = ctx.__submit();
  S = ctx.__S;
  await waitFor(() => S.branches.length >= 2);
  const callsBefore = renderCalls;
  chk('前提: レンダが走っている', callsBefore >= 2, 'calls=' + callsBefore);
  RENDER_MS = 20;                                               // 再開分はすぐ返る
  await waitFor(() => S.recovery.state === 'ok', 800);
  chk('復旧は完了した', S.recovery.state === 'ok' && S.branches.length === 4);
  await waitFor(() => S.renders.every(row => row.every(st => st.state === 'ok')), 800);
  chk('★中断したレンダが再発注される', renderCalls > callsBefore + 4,
      'before=' + callsBefore + ' after=' + renderCalls);
  chk('★中断は失敗として焼き付かない(全ミニレンダが ok)',
      S.renders.every(row => row.every(st => st.state === 'ok')),
      JSON.stringify(S.renders.map(row => row.map(st => st.state))));
  await p;

  console.log(FAILS.length ? '\n--- FAILED: ' + FAILS.join(' / ')
                           : '\n--- 途中切断の復旧 / 凍結解除 / 遷移タイマー / レンダ中断: すべて期待どおり');
  process.exit(FAILS.length ? 1 : 0);
})().catch(e => { console.error('THREW:', e && e.stack || e); process.exit(2); });
