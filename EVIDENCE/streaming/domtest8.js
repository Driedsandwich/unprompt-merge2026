// 2026-07-30 追加分を機械で押さえる(domtest7 と同型の最小 DOM シム)。
//
//   A) 「ランダムに決める」— AIを呼ばず、その場の乱数で各分岐から1つ引く
//      A-1 総数が確定するまで出さない(何を「全部」と呼ぶか決まっていない)
//      A-2 押すと未決が1件も残らない(全て decided・src='random')
//      A-3 押すたび引き直せる(同じボタンで別の目が出る)
//      A-4 自分の手で決めた分岐(human-pick)は上書きしない
//      A-5 カードの「委ねる」(human-delegate)も上書きしない
//      A-6 未決0になっても消えない(引き直す口を閉じない)
//      A-7 全件を人が決めたら消える(押す先が無い)
//      A-8 /api/recommend を呼ばない(AIを1度も使わない)
//
//   B) 「AIのおすすめで決める」— POST /api/recommend を1セッション1回だけ
//      B-1 待機中は静寂と同じ作法(実測秒数だけが動く)
//      B-2 成功: picks を適用し、理由をカウンタ行の下に1行出す
//      B-3 human-pick / human-delegate は上書きしない
//      B-4 2度目の押下は再呼び出しせず、持っている picks を再適用するだけ
//      B-5 失敗: 静かな注記を出し、次の押下で再試行する
//      B-6 処理の内訳に「おすすめの決定」の行(実ID・api秒)が入る
//      B-7 押さなければその行は存在しない
//
//   C) 固定情報のモデル名が正準IDに追随する(/api/health の model_ids + 実測)
//   D) ロゴの2度押しは畳まずに帰る(帯の「やり直す」と同じ経路)
//   E) 入力欄の自動成長(上限9行・上限までスクロールバーを出さない)
//   F) 同じ語の2度目以降の出現(エコー)が色とクリックだけ同期する
const fs = require('fs');
const PATH = '/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon/app/index.html';
const html = fs.readFileSync(PATH, 'utf8');
const script = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const ids = [...new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]))];

/* ---------- 最小 DOM(domtest7 と同じ) ---------- */
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
    this.open = false;
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
  removeAttribute(k){ delete this.attrs[k]; }
  addEventListener(t, fn){ (this.handlers[t] = this.handlers[t] || []).push(fn); }
  removeEventListener(){}
  get parentNode(){ return this.parent; }
  contains(n){ for (let x = n; x; x = x.parent){ if (x === this) return true; } return false; }
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
const docHandlers = {};
const document = {
  createElement: t => new El(t),
  createElementNS: (ns, t) => new El(t),
  createTextNode: t => { const e = new El('#text'); e._text = String(t); return e; },
  getElementById: id => registry[id] || (registry[id] = new El('div')),
  addEventListener(t, fn){ (docHandlers[t] = docHandlers[t] || []).push(fn); },
  querySelectorAll: () => [],
  querySelector: () => null,
  body: new El('body'), documentElement: new El('html')
};
const winHandlers = {};
const window = {
  addEventListener(t, fn){ (winHandlers[t] = winHandlers[t] || []).push(fn); },
  matchMedia: () => ({matches: false}),
  scrollTo(){}
};
let rafQ = [];
const requestAnimationFrame = fn => { rafQ.push(fn); return rafQ.length; };
const cancelAnimationFrame = () => {};
const performance = {now: () => Date.now()};
const navigator = {clipboard: {writeText: async () => {}}};
function flushRAF(n){ for (let i = 0; i < (n || 8); i++){ const q = rafQ; rafQ = []; q.forEach(f => f(performance.now())); } }
const sleep = ms => new Promise(r => setTimeout(r, ms));

// 乱数は差し替え可能にする(「引き」を決定論にして引き直しを見る)。
// Math 本体は触らず、prototype を Math にした派生オブジェクトを渡す。
let RAND_SEQ = [0];
let randCalls = 0;
const MathShim = Object.create(Math);
MathShim.random = () => { const v = RAND_SEQ[randCalls % RAND_SEQ.length]; randCalls++; return v; };

let reloads = 0;
const location = {reload(){ reloads++; }};
function clickEl(el){
  (docHandlers['click'] || []).forEach(fn => fn({target: el}));
  (el.handlers['click'] || []).forEach(fn => fn({target: el}));
}

/* ---------- スタブ ---------- */
let HEALTH = null;
function freshHealth(){
  HEALTH = {
    ok: true, model: 'sonnet', render_model: 'haiku', compile_model: 'sonnet',
    model_ids: {sonnet: null, haiku: null},
    effort: 'low', engine: 'claude-code-cli', claude_bin: 'claude',
    api_key_stripped: true, bind_host: '127.0.0.1', bind_port: 8321, prompts_dir: 'prompts/'
  };
}
freshHealth();
let MODEL_ID = {explode: 'claude-sonnet-5', render: 'claude-haiku-4-5', compile: 'claude-sonnet-5'};

// 「LP」が2回出る依頼文(= エコーの検体)。「うちの会社」「モダン」は1回だけ。
const BRIEF = 'モダンだけど温かみのあるLPを作って。うちの会社のやつ。LPは一枚で。';
const BRANCHES = [
  {type:'branch', index:0, elapsed_ms:5700, branch:{id:'b0', question_point:'「うちの会社」の業種',
    anchor_words:['うちの会社'], options:[{label:'BtoB'},{label:'BtoC'}], default_if_unresolved:'BtoB'}},
  {type:'branch', index:1, elapsed_ms:6900, branch:{id:'b1', question_point:'LPの目的',
    anchor_words:['LP'], options:[{label:'問い合わせ'},{label:'購入'},{label:'資料請求'}], default_if_unresolved:'問い合わせ'}},
  {type:'branch', index:2, elapsed_ms:7400, branch:{id:'b2', question_point:'「モダン」の方向',
    anchor_words:['モダン'], options:[{label:'直線的'},{label:'やわらかい'}], default_if_unresolved:'直線的'}}
];
function doneEvent(){
  return {type:'done', ok:true, branches:[], residual_ambiguity_assessment:'業種が不明なままである。',
    missing_materials:[], rejected_branches:[{question_point:'棄却1'}], branches_returned_by_model:4,
    timing:{wall_ms:118000, api_ms:81300, model_id: MODEL_ID.explode},
    api_ms:81300, first_branch_ms:5700, elapsed_ms:120000};
}
const EVENTS = () => [{type:'meta', partial:true, residual_ambiguity_assessment:'', missing_materials:[], elapsed_ms:4200}]
  .concat(BRANCHES, [doneEvent()]);
const enc = s => Buffer.from(s, 'utf8');
let EVENT_GAP_MS = 0;                        // >0 にすると「受信中」の状態を観測できる
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
// /api/recommend の応答は差し替えて使う
let RECO = null;
let RECO_DELAY_MS = 0;
function freshReco(){
  RECO = {ok: true, picks: [0, 2, 1], reason: '落ち着いた一貫性で揃えました。',
          timing: {wall_ms: 4657, api_ms: 2607, model_id: 'claude-sonnet-5'}};
}
freshReco();
let calls = [];
async function fetchStub(url, opt){
  calls.push(url);
  if (url === '/api/health') return {ok: true, json: async () => HEALTH};
  if (url === '/api/explode_stream') return {ok: true, body: sseBody(EVENTS())};
  if (url === '/api/render'){
    return {ok: true, json: async () => ({ok: true,
      tokens: {palette:['#112233','#445566','#778899'], heading_font:'sans',
               density:'normal', corner:'soft', tone_sample:'見出し。一文。'},
      timing: {wall_ms: 84000, api_ms: 24000, model_id: MODEL_ID.render}})};
  }
  if (url === '/api/recommend'){
    if (RECO_DELAY_MS) await sleep(RECO_DELAY_MS);
    return {ok: true, json: async () => RECO};
  }
  if (url === '/api/compile'){
    return {ok: true, json: async () => ({ok: true, rationales: {'LPの目的': '問い合わせを増やすため。'},
      timing: {wall_ms: 40000, api_ms: 12800, model_id: MODEL_ID.compile}})};
  }
  return {ok: false, json: async () => ({ok: false})};
}
class TextDecoderShim { decode(b){ return b ? Buffer.from(b).toString('utf8') : ''; } }

/* ---------- 実行 ---------- */
const vm = require('vm');
const FAILS = [];
const chk = (n, c, e) => { console.log((c ? 'OK   ' : 'FAIL ') + n + (e ? '  ' + e : '')); if (!c) FAILS.push(n); };

function wireTree(){
  const put = (p, c) => { if (registry[p] && registry[c]) registry[p].appendChild(registry[c]); };
  put('lockup', 'lockupHome');
  put('lockup', 'homeConfirm');
  put('homeConfirm', 'homeConfirmYes');
  put('homeConfirm', 'homeConfirmNo');
  put('procPanel', 'procBody');
  put('procBody', 'procFixed');
  put('procBody', 'procRows');
  put('meta', 'counterRow');
  put('counterRow', 'branchCounter');
  put('counterRow', 'btnRandomAll');
  put('counterRow', 'btnRecoAll');
}
function fresh(){
  Object.keys(registry).forEach(k => delete registry[k]);
  Object.keys(docHandlers).forEach(k => delete docHandlers[k]);
  Object.keys(winHandlers).forEach(k => delete winHandlers[k]);
  ids.forEach(id => {
    registry[id] = new El('div'); registry[id].id = id;
    const tag = html.match(new RegExp('<[a-z]+[^>]*\\bid="' + id + '"[^>]*>', 'i'));
    if (tag && /\shidden(\s|>|=)/.test(tag[0])) registry[id].hidden = true;
  });
  wireTree();
  rafQ = []; reloads = 0; randCalls = 0; calls = [];
  const ctx = {document, window, location, requestAnimationFrame, cancelAnimationFrame,
    performance, navigator, fetch: fetchStub, TextDecoder: TextDecoderShim,
    AbortController, setTimeout, clearTimeout, setInterval, clearInterval,
    console, JSON, Math: MathShim, Date, Promise, Array, Object, String, Number, Boolean, Set, Map,
    parseInt, parseFloat, isNaN, isFinite};
  vm.createContext(ctx);
  vm.runInContext(script +
    '\n;globalThis.__S=S; globalThis.__submit=submitBrief;' +
    '\n;globalThis.__decide=decide; globalThis.__delegate=delegate;' +
    '\n;globalThis.__random=randomAll; globalThis.__reco=recommendAll;' +
    '\n;globalThis.__bulkTargets=bulkTargets; globalThis.__compile=compile;' +
    '\n;globalThis.__growFit=growFit; globalThis.__INPUT_MAX_H=INPUT_MAX_H;' +
    '\n;globalThis.__echo=buildEchoRanges; globalThis.__LONG=LONG_BRIEF_CHARS;', ctx);
  return ctx;
}
async function runToDone(brief){
  const ctx = fresh();
  registry['briefInput'].value = (brief == null) ? BRIEF : brief;
  const p = ctx.__submit();
  for (let i = 0; i < 60; i++){ flushRAF(3); await sleep(8); }
  await p;
  flushRAF(6); await sleep(200); flushRAF(6);
  return ctx;
}
const srcs = (ctx) => ctx.__S.decisions.map(d => d.src);
const stats = (ctx) => ctx.__S.decisions.map(d => d.status);
const ois = (ctx) => ctx.__S.decisions.map(d => d.oi);

(async () => {
  /* ================= 0) 静的マークアップと様式 ================= */
  console.log('=== 0) 静的マークアップ(2つのボタンと理由の行) ===');
  const row = html.slice(html.indexOf('<div id="counterRow">'), html.indexOf('<div id="assessNote"'));
  chk('「ランダムに決める」がある',
      /<button id="btnRandomAll" type="button" hidden title="[^"]*">ランダムに決める<\/button>/.test(row));
  chk('「AIのおすすめで決める」がある',
      /<button id="btnRecoAll" type="button" hidden title="[^"]*">AIのおすすめで決める<\/button>/.test(row));
  chk('どちらも既定で hidden',
      /id="btnRandomAll"[^>]*\shidden[\s>]/.test(row) && /id="btnRecoAll"[^>]*\shidden[\s>]/.test(row));
  // 2026-07-30(第6FB): カウンタ行は「カウンタ + 一括2つ」だけ。まとめて委ねる口は撤去した。
  chk('カウンタ行(#counterRow)の中・カウンタの右に2つだけ',
      row.indexOf('id="branchCounter"') < row.indexOf('id="btnRandomAll"') &&
      row.indexOf('id="btnRandomAll"') < row.indexOf('id="btnRecoAll"') &&
      (row.match(/<button /g) || []).length === 2 &&
      row.indexOf('btnDelegateAll') < 0);
  chk('★ランダムの title が「AIは使いません」と明言する',
      /title="AIは使いません。この場で無作為に決めます。何度でも引き直せます。"/.test(row));
  chk('文言の動詞は「決める」「委ねる」だけ(生成語を持ち込まない)',
      !/>[^<]*(生成|作成|つくる|書き)[^<]*<\/button>/.test(row));
  chk('同じゴースト様式(枠線のみ・鼠・ホバー藍)',
      /#btnRandomAll, #btnRecoAll\{[^}]*background:transparent[^}]*border:1px solid var\(--line\)[^}]*color:var\(--muted\)/.test(html) &&
      /#btnRandomAll:hover, #btnRecoAll:hover\{[^}]*color:var\(--ai\)[^}]*border-color:var\(--ai\)/.test(html));
  chk('角丸ゼロ', /#btnRandomAll, #btnRecoAll\{[^}]*border-radius:0/.test(html));
  chk('方眼マスキングも同じ扱い', /#btnRandomAll, #btnRecoAll\{background:var\(--paper\)\}/.test(html));
  chk('待機中の様式は等幅数字・枠は騒がない',
      /#btnRecoAll\[data-state="loading"\][^{]*\{[^}]*font-variant-numeric:tabular-nums/.test(html));
  chk('理由の行はカウンタ行の直下・既定 hidden',
      html.indexOf('id="counterRow"') < html.indexOf('id="recoNote"') &&
      html.indexOf('id="recoNote"') < html.indexOf('id="assessNote"') &&
      /<div id="recoNote"[^>]*\shidden[\s>]/.test(html));
  chk('理由の行は注記の格(--ink-soft・小さい)',
      /#recoNote\{[^}]*font-size:11px[^}]*color:var\(--ink-soft\)/.test(html));
  {
    const inputCss = html.slice(html.indexOf('#briefInput{'), html.indexOf('#briefInput:focus'));
    chk('入力欄の上限は 374px・既定はスクロールバーを出さない',
        /max-height:374px/.test(inputCss) && /overflow-y:hidden/.test(inputCss) &&
        !/overflow-y:auto/.test(inputCss), JSON.stringify(inputCss.length));
  }
  chk('長文ヒーローの逃げ(32→24 / モバイル 24→19)',
      /#briefText\.long\{font-size:24px\}/.test(html) && /#briefText\.long\{font-size:19px\}/.test(html));
  chk('圏点はエコーに打たない(セレクタで除外)',
      /#briefText\.tenten-on \.tok\[data-state="open"\]:not\(\[data-echo="1"\]\) \.ch::before/.test(html));

  /* ================= A) ランダムに決める ================= */
  console.log('\n=== A-1) 総数が確定するまで出さない ===');
  {
    EVENT_GAP_MS = 40;
    const c = fresh();
    registry['briefInput'].value = BRIEF;
    const p = c.__submit();
    // 「1件は着いたが done は未達」の瞬間まで進める(そこが最も危ない状態)
    for (let i = 0; i < 40 && c.__S.branches.length < 1; i++){ flushRAF(2); await sleep(10); }
    chk('前提: まだ受信中(判断点は出はじめている)',
        c.__S.streaming === true && c.__S.streamDone === false && c.__S.branches.length > 0,
        'streaming=' + c.__S.streaming + ' n=' + c.__S.branches.length);
    chk('★受信中は出ていない',
        registry['btnRandomAll'].hidden === true && registry['btnRecoAll'].hidden === true);
    for (let i = 0; i < 80; i++){ flushRAF(3); await sleep(10); }
    await p; flushRAF(6); await sleep(120); flushRAF(6);
    chk('done 後は2つとも出る',
        registry['btnRandomAll'].hidden === false && registry['btnRecoAll'].hidden === false);
    EVENT_GAP_MS = 0;
  }

  console.log('\n=== A-2) 押すと未決が1件も残らない ===');
  RAND_SEQ = [0];
  let ctx = await runToDone();
  chk('前提: 3判断点が未決', ctx.__S.branches.length === 3 &&
      stats(ctx).every(s => s === null));
  clickEl(registry['btnRandomAll']);
  flushRAF(4);
  chk('★全て decided', stats(ctx).every(s => s === 'decided'), JSON.stringify(stats(ctx)));
  chk('★src は random', srcs(ctx).every(s => s === 'random'), JSON.stringify(srcs(ctx)));
  chk('★カウンタが 0(未決なし)', registry['branchCounter'].classList.contains('zero'));
  chk('★指示書ボタンが出る(コンパイル可)', registry['compileRow'].hidden === false);
  chk('★選択肢の範囲内の添字だけを置く',
      ois(ctx).every((oi, bi) => oi >= 0 && oi < ctx.__S.branches[bi].options.length), JSON.stringify(ois(ctx)));
  chk('★AIを1度も呼んでいない', calls.indexOf('/api/recommend') < 0, JSON.stringify(calls.filter(u => u !== '/api/render')));

  console.log('\n=== A-3) 押すたび引き直せる ===');
  const first = JSON.stringify(ois(ctx));
  RAND_SEQ = [0.99];                       // 各分岐の最後の選択肢が出る目
  clickEl(registry['btnRandomAll']);
  flushRAF(4);
  const second = JSON.stringify(ois(ctx));
  chk('★同じボタンで別の目が出る', first !== second, first + ' → ' + second);
  chk('★引き直しても未決0のまま', stats(ctx).every(s => s === 'decided'));
  chk('★ボタンは消えない(未決0でも引き直せる)', registry['btnRandomAll'].hidden === false);

  console.log('\n=== A-4/A-5) 自分の手で決めた分岐は上書きしない ===');
  RAND_SEQ = [0];
  ctx = await runToDone();
  ctx.__decide(0, 1);                      // 見本クリック相当(human-pick)
  ctx.__delegate(1);                       // カードの「委ねる」(human-delegate)
  flushRAF(4);
  chk('前提: src が human 2件', srcs(ctx)[0] === 'human-pick' && srcs(ctx)[1] === 'human-delegate');
  RAND_SEQ = [0.99];
  clickEl(registry['btnRandomAll']);
  flushRAF(4);
  chk('★human-pick は選択肢も出自もそのまま',
      ctx.__S.decisions[0].status === 'decided' && ctx.__S.decisions[0].oi === 1 &&
      srcs(ctx)[0] === 'human-pick');
  chk('★human-delegate もそのまま',
      ctx.__S.decisions[1].status === 'delegated' && srcs(ctx)[1] === 'human-delegate');
  chk('★未決だった分岐だけが引かれた',
      ctx.__S.decisions[2].status === 'decided' && srcs(ctx)[2] === 'random');

  console.log('\n=== A-6/A-7) 出す条件 ===');
  chk('★human 2件 + random 1件 → まだ出る(random は引き直せる)',
      registry['btnRandomAll'].hidden === false && ctx.__bulkTargets().length === 1);
  ctx.__decide(2, 0);                      // 残り1件も人が決める
  flushRAF(4);
  chk('★全件が人の手で決まったら消える(押す先が無い)',
      registry['btnRandomAll'].hidden === true && registry['btnRecoAll'].hidden === true &&
      ctx.__bulkTargets().length === 0);

  console.log('\n=== A-8) 選び直し中を狙って奪わない ===');
  RAND_SEQ = [0];
  ctx = await runToDone();
  ctx.__decide(0, 1);                      // human-pick
  flushRAF(2);
  ctx.__S.decisions[0] = {status: null, oi: null, src: null,
                          prev: {status: 'decided', oi: 1, src: 'human-pick'}};   // 語をクリックして選び直し中
  chk('前提: status は null(未決の見た目)', ctx.__S.decisions[0].status === null);
  chk('★それでも一括の対象に入らない(prev の出自で見る)', ctx.__bulkTargets().indexOf(0) < 0,
      JSON.stringify(ctx.__bulkTargets()));

  /* ================= B) AIのおすすめで決める ================= */
  console.log('\n=== B-1) 待機中は静寂と同じ作法 ===');
  freshReco();
  RECO_DELAY_MS = 120;
  ctx = await runToDone();
  {
    const p = ctx.__reco();
    flushRAF(2);
    chk('★文言が実測秒数になる', /^考えています · \d+\.\d+s$/.test(registry['btnRecoAll'].textContent),
        JSON.stringify(registry['btnRecoAll'].textContent));
    chk('★data-state=loading', registry['btnRecoAll'].dataset.state === 'loading');
    chk('待機中も消えない', registry['btnRecoAll'].hidden === false);
    chk('待機中に押しても2本目を投げない', (() => {
      const n = calls.filter(u => u === '/api/recommend').length;
      clickEl(registry['btnRecoAll']);
      return calls.filter(u => u === '/api/recommend').length === n;
    })());
    for (let i = 0; i < 30; i++){ flushRAF(2); await sleep(10); }
    await p;
    flushRAF(4);
  }
  RECO_DELAY_MS = 0;

  console.log('\n=== B-2) picks の適用と理由の1行 ===');
  chk('★呼んだのは1回だけ', calls.filter(u => u === '/api/recommend').length === 1);
  chk('★picks どおりに決まる(0,2,1)', JSON.stringify(ois(ctx)) === '[0,2,1]', JSON.stringify(ois(ctx)));
  chk('★src は reco', srcs(ctx).every(s => s === 'reco'), JSON.stringify(srcs(ctx)));
  chk('★未決0・指示書ボタンが出る',
      registry['branchCounter'].classList.contains('zero') && registry['compileRow'].hidden === false);
  chk('★理由がカウンタ行の下に1行',
      registry['recoNote'].hidden === false &&
      registry['recoNote'].textContent === 'おすすめの理由: 落ち着いた一貫性で揃えました。',
      JSON.stringify(registry['recoNote'].textContent));
  chk('注記の色は静かなほうではない(理由は --ink-soft のまま)',
      registry['recoNote'].classList.contains('quiet') === false);
  chk('文言は元へ戻る', registry['btnRecoAll'].textContent === 'AIのおすすめで決める');
  chk('AIが成果物を書いていない(適用したのは選択肢の添字だけ)',
      ois(ctx).every((oi, bi) => typeof ctx.__S.branches[bi].options[oi].label === 'string'));

  console.log('\n=== B-4) 2度目は再呼び出しせず再適用だけ ===');
  RAND_SEQ = [0];
  clickEl(registry['btnRandomAll']);        // reco の結果を一旦引き直す(reco は流動)
  flushRAF(4);
  chk('前提: ランダムで上書きされた', JSON.stringify(ois(ctx)) === '[0,0,0]', JSON.stringify(ois(ctx)));
  clickEl(registry['btnRecoAll']);
  flushRAF(4);
  chk('★モデルを呼び直さない', calls.filter(u => u === '/api/recommend').length === 1);
  chk('★picks が再適用される', JSON.stringify(ois(ctx)) === '[0,2,1]', JSON.stringify(ois(ctx)));
  chk('★理由の行は出たまま', registry['recoNote'].hidden === false);

  console.log('\n=== B-3) human は上書きしない ===');
  freshReco();
  ctx = await runToDone();
  ctx.__decide(1, 0);                       // human-pick(picks は 2 を指す)
  flushRAF(2);
  await ctx.__reco();
  flushRAF(4);
  chk('★human-pick の分岐は picks を当てない',
      ctx.__S.decisions[1].oi === 0 && srcs(ctx)[1] === 'human-pick', JSON.stringify(ois(ctx)));
  chk('★残りには当てる',
      ctx.__S.decisions[0].oi === 0 && ctx.__S.decisions[2].oi === 1 &&
      srcs(ctx)[0] === 'reco' && srcs(ctx)[2] === 'reco', JSON.stringify(srcs(ctx)));

  console.log('\n=== B-6) 処理の内訳に「おすすめの決定」 ===');
  {
    const rows = registry['procRows'].textContent;
    chk('★実IDと api秒が出る', rows.indexOf('おすすめの決定claude-sonnet-5 ・ api 2.6秒') >= 0,
        JSON.stringify(rows));
    chk('「失敗」は付かない', rows.indexOf('おすすめの決定claude-sonnet-5 ・ api 2.6秒 ・ 失敗') < 0);
  }

  console.log('\n=== B-7) 押さなければ行は存在しない ===');
  {
    const c = await runToDone();
    chk('★S.recoStat は null', c.__S.recoStat === null);
    chk('★内訳にも行が無い', registry['procRows'].textContent.indexOf('おすすめの決定') < 0);
    chk('理由の行も出ていない', registry['recoNote'].hidden === true);
  }

  console.log('\n=== B-5) 失敗しても静かに。次の押下で再試行する ===');
  RECO = {ok: false, error: '推奨の検証に失敗した(picks の長さが判断点数と一致しない)',
          hint: 'モデルの picks: [1]', timing: {wall_ms: 3100, api_ms: 1900, model_id: 'claude-sonnet-5'}};
  ctx = await runToDone();
  await ctx.__reco();
  flushRAF(4);
  chk('★決定は1件も置かない', stats(ctx).every(s => s === null), JSON.stringify(stats(ctx)));
  chk('★静かな注記が出る',
      registry['recoNote'].hidden === false &&
      registry['recoNote'].textContent === 'おすすめを取得できませんでした。もう一度押すと再試行します',
      JSON.stringify(registry['recoNote'].textContent));
  chk('★注記は静かな色(quiet)', registry['recoNote'].classList.contains('quiet') === true);
  chk('★内訳には「失敗」と書く',
      registry['procRows'].textContent.indexOf('おすすめの決定claude-sonnet-5 ・ api 1.9秒 ・ 失敗') >= 0,
      JSON.stringify(registry['procRows'].textContent));
  chk('ボタンの文言は元へ戻る', registry['btnRecoAll'].textContent === 'AIのおすすめで決める');
  {
    const n = calls.filter(u => u === '/api/recommend').length;
    freshReco();
    await ctx.__reco();                      // 2度目 = 再試行
    flushRAF(4);
    chk('★次の押下で呼び直す', calls.filter(u => u === '/api/recommend').length === n + 1);
    chk('★再試行が通れば picks が入る', JSON.stringify(ois(ctx)) === '[0,2,1]', JSON.stringify(ois(ctx)));
    chk('★注記が理由へ入れ替わる',
        registry['recoNote'].classList.contains('quiet') === false &&
        registry['recoNote'].textContent.indexOf('おすすめの理由: ') === 0);
  }

  /* ================= C) 固定情報が正準IDに追随する ================= */
  console.log('\n=== C) 固定情報のモデル名 ===');
  {
    const c = fresh();
    await sleep(20);                         // 起動時の /api/health を待つ
    const f0 = registry['procFixed'].textContent;
    chk('★未観測のあいだはエイリアスだけ',
        f0.indexOf('問いの抽出 sonnet /') >= 0 && f0.indexOf('claude-') < 0, JSON.stringify(f0));
    chk('★「おすすめの決定」も固定情報にある', f0.indexOf('おすすめの決定 sonnet') >= 0, JSON.stringify(f0));
    void c;
  }
  ctx = await runToDone();
  {
    const f1 = registry['procFixed'].textContent;
    chk('★実測が入った時点で正準IDが添えられる(抽出)',
        f1.indexOf('問いの抽出 sonnet(= claude-sonnet-5)') >= 0, JSON.stringify(f1));
    chk('★見本の生成も別モデルのIDで添えられる',
        f1.indexOf('見本の生成 haiku(= claude-haiku-4-5)') >= 0, JSON.stringify(f1));
    chk('★おすすめの決定の欄も追随する',
        f1.indexOf('おすすめの決定 sonnet(= claude-sonnet-5)') >= 0, JSON.stringify(f1));
    chk('エイリアスを消してIDだけにはしない(起動時の指定は残す)',
        f1.indexOf('sonnet(= ') >= 0);
  }
  {
    // /api/health が最初から model_ids を持っていれば、実行前でも添えられる
    HEALTH.model_ids = {sonnet: 'claude-sonnet-5', haiku: 'claude-haiku-4-5'};
    fresh();
    await sleep(20);
    const f2 = registry['procFixed'].textContent;
    chk('★health の model_ids だけでも添えられる',
        f2.indexOf('問いの抽出 sonnet(= claude-sonnet-5)') >= 0, JSON.stringify(f2));
    freshHealth();
  }
  {
    // 一度も観測できなければ、それらしいIDをでっち上げない
    MODEL_ID = {explode: null, render: null, compile: null};
    await runToDone();
    const f3 = registry['procFixed'].textContent;
    chk('★取れなければ従来どおりエイリアスのみ', f3.indexOf('claude-') < 0, JSON.stringify(f3));
    MODEL_ID = {explode: 'claude-sonnet-5', render: 'claude-haiku-4-5', compile: 'claude-sonnet-5'};
  }

  /* ================= D) ロゴの2度押し ================= */
  console.log('\n=== D) ロゴ2度押し = 帯の「やり直す」と同じ経路 ===');
  ctx = await runToDone();
  chk('前提: 爆散済み・未コンパイル', ctx.__S.exploded === true && ctx.__S.compileDone === false);
  clickEl(registry['lockupHome']);
  chk('1度目は帯だけ(帰らない)',
      registry['homeConfirm'].hidden === false && reloads === 0, 'reloads=' + reloads);
  clickEl(registry['lockupHome']);
  chk('★2度目で帰る(再読込1回)', reloads === 1, 'reloads=' + reloads);
  chk('★帯は畳んでから帰る', registry['homeConfirm'].hidden === true);
  {
    ctx = await runToDone();
    clickEl(registry['lockupHome']);
    clickEl(registry['homeConfirmYes']);
    const viaBand = reloads;
    ctx = await runToDone();
    clickEl(registry['lockupHome']);
    clickEl(registry['lockupHome']);
    chk('★「やり直す」と同じ結果(どちらも再読込1回)', viaBand === 1 && reloads === 1,
        viaBand + ' / ' + reloads);
  }

  /* ================= E) 入力欄の自動成長 ================= */
  console.log('\n=== E) 入力欄は9行まで伸び、上限までスクロールバーを出さない ===');
  {
    const c = fresh();
    const G = c.__growFit, cap = c.__INPUT_MAX_H;
    chk('★上限は9行ぶん(39.9px × 9 + 枠15px = 374px)', cap === 374, 'cap=' + cap);
    chk('★CSS の max-height と同じ数', /max-height:374px/.test(html));
    chk('★1行(54px)はそのまま・バーを出さない',
        G(54, cap).height === '54px' && G(54, cap).overflowY === 'hidden', JSON.stringify(G(54, cap)));
    chk('★5行(214px)も伸びる・バーは出ない',
        G(214, cap).height === '214px' && G(214, cap).overflowY === 'hidden');
    chk('★上限ちょうどはまだバーを出さない',
        G(374, cap).height === '374px' && G(374, cap).overflowY === 'hidden');
    chk('★上限を超えたら頭打ちにしてバーを出す',
        G(375, cap).height === '374px' && G(375, cap).overflowY === 'auto');
    chk('★12行相当(493px)でも高さは上限で止まる',
        G(493, cap).height === '374px' && G(493, cap).overflowY === 'auto');
    chk('scrollHeight が取れない環境でも壊れない',
        G(undefined, cap).height === '0px' && G(undefined, cap).overflowY === 'hidden');
    chk('Enter送信は残っている(挙動を変えていない)',
        /if \(e\.key === 'Enter' && !e\.shiftKey && !e\.isComposing\)/.test(script));
    void c;
  }

  /* ================= F) エコー(同じ語の2度目以降) ================= */
  console.log('\n=== F) 同じ語が2度出たら、色とクリックだけ同期する ===');
  {
    const c = fresh();
    const ranges = c.__echo('AとBとA', [{start: 0, end: 1, text: 'A', bis: [0]}]);
    chk('★主出現の外にある同じ語を拾う', ranges.length === 1 && ranges[0].start === 4, JSON.stringify(ranges));
    chk('★主出現の占有には食い込まない',
        c.__echo('AA', [{start: 0, end: 1, text: 'A', bis: [0]}]).length === 1);
    chk('★出現が1度だけならエコーは無い',
        c.__echo('AとB', [{start: 0, end: 1, text: 'A', bis: [0]}]).length === 0);
    chk('★エコー同士も重ならない(取り合いは start 順で決まる)',
        JSON.stringify(c.__echo('AAAA', [{start: 0, end: 2, text: 'AA', bis: [0]}])
                        .map(r => [r.start, r.end])) === '[[2,4]]');
    void c;
  }
  ctx = await runToDone();
  {
    const toks = registry['briefText'].querySelectorAll('.tok');
    const echo = toks.filter(t => t.dataset.echo === '1');
    const main = toks.filter(t => t.dataset.echo !== '1');
    chk('★「LP」の2度目がトークンになっている', echo.length === 1, 'echo=' + echo.length + ' main=' + main.length);
    chk('★エコーは同じ分岐に結び付く', echo[0] && echo[0].dataset.bi === '1', echo[0] && echo[0].dataset.bi);
    chk('★S.spans は増えていない(判断点3件ぶんのまま)', ctx.__S.spans.length === 3,
        'spans=' + ctx.__S.spans.length);
    chk('★引出線の起点は主出現のまま(sp.el がエコーを指さない)',
        ctx.__S.spans.every(sp => sp.el && sp.el.dataset.echo !== '1'));
    chk('前提: エコーも朱(未決)', echo[0].dataset.state === 'open');
    ctx.__decide(1, 0);
    flushRAF(4);
    chk('★決めた瞬間にエコーも藍になる', echo[0].dataset.state === 'decided', echo[0].dataset.state);
    chk('主出現も藍', ctx.__S.spans.find(sp => sp.bis.indexOf(1) >= 0).el.dataset.state === 'decided');
    ctx.__delegate(1);
    flushRAF(4);
    chk('★委ねたらエコーも鼠になる', echo[0].dataset.state === 'delegated');
    chk('★カウンタは語の出現数ではなく判断点を数える',
        registry['branchCounter'].textContent.indexOf('抽出した判断点 3') >= 0,
        JSON.stringify(registry['branchCounter'].textContent));
    // エコーのクリックは主出現と同じ選択UIを開く
    const before = JSON.stringify(ctx.__S.decisions[1]);
    clickEl(echo[0]);
    flushRAF(4);
    chk('★エコーをクリックすると選び直しに入る(同じ経路)',
        ctx.__S.decisions[1].status === null && ctx.__S.decisions[1].prev !== null,
        before + ' → ' + JSON.stringify(ctx.__S.decisions[1]));
  }

  console.log('\n=== G) 長文ヒーローの逃げ ===');
  {
    const c = fresh();
    chk('★しきい値は120字', c.__LONG === 120, 'LONG=' + c.__LONG);
  }
  {
    const short = 'モダンだけど温かみのあるLPを作って。';
    await runToDone(short);
    chk('★短い文には .long を付けない', registry['briefText'].classList.contains('long') === false);
    const long = 'モダンだけど温かみのあるLPを作ってほしい。' +
      'うちの会社は創業から十年ほどで、扱っているのは製造業向けの小さな道具である。' +
      '若い人にも刺さる感じで、問い合わせが増えるようにしてほしい。写真はこれから撮る。' +
      '色は落ち着いた方がいいが、古臭くはしたくない。' ;
    chk('前提: 120字を超える', long.length > 120, 'len=' + long.length);
    await runToDone(long);
    chk('★長い文には .long が付く', registry['briefText'].classList.contains('long') === true);
  }

  console.log(FAILS.length ? '\n--- FAILED: ' + FAILS.join(' / ')
                           : '\n--- ランダム / おすすめ / 正準ID / ロゴ2度押し / 自動成長 / エコー: すべて期待どおり');
  process.exit(FAILS.length ? 1 : 0);
})().catch(e => { console.error('THREW:', e && e.stack || e); process.exit(2); });
