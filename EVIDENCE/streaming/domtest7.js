// 2026-07-30 追加の2機能を機械で押さえる(domtest2/5/6 と同型の最小 DOM シム)。
//
//   A) ロックアップ(左上「GYAKUMON — Intent Compiler」)のクリックでトップへ帰る
//      A-1 初期画面(未送信)  → 確認帯を出さずに即帰還(状態は再読込で全て捨てる)
//      A-2 進行中(爆散後〜未コンパイル)→ 即帰らない。直下に確認帯が出る(モーダルではない)
//      A-3 [続ける] で確認帯だけが畳まれる(帰らない・選択は1つも壊れない)
//      A-4 [やり直す] で帰還。走行中レンダは AbortController で中断してから帰る
//      A-5 確認帯は他の場所を触れば黙って消える(=他操作で自動的に消える)
//      A-6 指示書ができた後は確認帯を出さずに即帰還
//
//   B) 「処理の内訳」パネルの閉じ方
//      B-1 パネルの外を1回クリックすると閉じる(open 属性も落ちる)
//      B-2 パネルの中(summary 行 / 表の中)のクリックでは閉じない = −ボタンは生きたまま
//      B-3 閉じているときの外クリックは何も起こさない(冪等)
//      B-4 確認帯とパネルは独立に畳まれる(同じ1回のクリックで両方畳めることも見る)
//
//   C) モデル表示が正準ID(claude CLI の modelUsage 由来)になる
//      C-1 timing.model_id が来たらそれを出す(エイリアスではなく実ID)
//      C-2 抽出 / 見本の生成 / 根拠文はそれぞれ自分の実IDを出す
//      C-3 model_id が来なければ /api/health のエイリアスへ倒す(推測でIDを作らない)
//      C-4 「model 」のような接頭辞は付けない(素のIDを置く)
const fs = require('fs');
const PATH = '/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon/app/index.html';
const html = fs.readFileSync(PATH, 'utf8');
const script = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const ids = [...new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]))];

/* ---------- 最小 DOM ----------
   domtest6 のものに3つだけ足す:
     ・contains / parentNode … 「外側クリック」の判定が実際に使う
     ・document の click 配信 … capture 段のハンドラを本物と同じ順で回す
     ・details の open      … パネルの開閉                                   */
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
    this.open = false;                          // <details> 用
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

// 本物のクリック: document の capture 段 → その要素自身の click ハンドラ、の順に回す。
// (製品コードは capture:true で document に1本だけ listener を置いている)
let reloads = 0;
const location = {reload(){ reloads++; }};
function clickEl(el){
  (docHandlers['click'] || []).forEach(fn => fn({target: el}));
  (el.handlers['click'] || []).forEach(fn => fn({target: el}));
}

/* ---------- スタブ ---------- */
const HEALTH = {
  ok: true, model: 'sonnet', render_model: 'haiku', compile_model: 'sonnet',
  effort: 'low', engine: 'claude-code-cli', claude_bin: 'claude',
  api_key_stripped: true, bind_host: '127.0.0.1', bind_port: 8321, prompts_dir: 'prompts/'
};
// サーバは timing.model_id に「CLI が実際に使ったモデルの正準ID」を載せて返す。
// null にすると「取れなかった」ことになり、クライアントはエイリアスへ倒すはずである。
let MODEL_ID = {explode: 'claude-sonnet-5', render: 'claude-haiku-4-5', compile: 'claude-sonnet-5'};
const BRANCHES = [
  {type:'branch', index:0, elapsed_ms:5700, branch:{id:'b0', question_point:'「うちの会社」の業種', anchor_words:['うちの会社'], options:[{label:'BtoB'},{label:'BtoC'}], default_if_unresolved:'BtoB'}},
  {type:'branch', index:1, elapsed_ms:6900, branch:{id:'b1', question_point:'LPの目的', anchor_words:['LP'], options:[{label:'問い合わせ'},{label:'購入'}], default_if_unresolved:'問い合わせ'}}
];
function doneEvent(){
  return {type:'done', ok:true, branches:[], residual_ambiguity_assessment:'業種が不明なままである。',
    missing_materials:[], rejected_branches:[{question_point:'棄却1'}],
    branches_returned_by_model:3,
    timing:{wall_ms:118000, api_ms:81300, model_id: MODEL_ID.explode},
    api_ms:81300, first_branch_ms:5700, elapsed_ms:120000};
}
const EVENTS = () => [{type:'meta', partial:true, residual_ambiguity_assessment:'', missing_materials:[], elapsed_ms:4200}]
  .concat(BRANCHES, [doneEvent()]);
let EVENT_GAP_MS = 0;
let RENDER_DELAY_MS = 0;                 // >0 にすると帰還の瞬間にレンダが飛んだままになる
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
function renderStub(opt){
  return new Promise((resolve, reject) => {
    const finish = () => resolve({ok: true, json: async () => ({ok: true,
      tokens: {palette:['#112233','#445566','#778899'], heading_font:'sans',
               density:'normal', corner:'soft', tone_sample:'見出し。一文。'},
      timing: {wall_ms: 84000, api_ms: 24000, model_id: MODEL_ID.render}})});
    if (!RENDER_DELAY_MS){ finish(); return; }
    const t = setTimeout(finish, RENDER_DELAY_MS);
    if (opt && opt.signal){
      opt.signal.addEventListener('abort', () => {
        clearTimeout(t);
        const e = new Error('aborted'); e.name = 'AbortError'; reject(e);
      });
    }
  });
}
async function fetchStub(url, opt){
  if (url === '/api/health') return {ok: true, json: async () => HEALTH};
  if (url === '/api/explode_stream') return {ok: true, body: sseBody(EVENTS())};
  if (url === '/api/render') return renderStub(opt);
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

// 実マークアップの入れ子(#lockup > #lockupHome, #homeConfirm > 各ボタン,
// #procPanel > #procBody)をシムでも作る。この配線が実物と食い違わないことは、
// 下の「静的マークアップ」の節が正規表現で別途押さえている。
function wireTree(){
  const put = (p, c) => { if (registry[p] && registry[c]) registry[p].appendChild(registry[c]); };
  put('lockup', 'lockupHome');
  put('lockup', 'homeConfirm');
  put('homeConfirm', 'homeConfirmYes');
  put('homeConfirm', 'homeConfirmNo');
  put('procPanel', 'procBody');
  put('procBody', 'procFixed');
  put('procBody', 'procRows');
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
  rafQ = []; reloads = 0;
  const ctx = {document, window, location, requestAnimationFrame, cancelAnimationFrame,
    performance, navigator, fetch: fetchStub, TextDecoder: TextDecoderShim,
    AbortController, setTimeout, clearTimeout, setInterval, clearInterval,
    console, JSON, Math, Date, Promise, Array, Object, String, Number, Boolean, Set, Map,
    parseInt, parseFloat, isNaN};
  vm.createContext(ctx);
  vm.runInContext(script +
    '\n;globalThis.__S=S; globalThis.__submit=submitBrief; globalThis.__delegate=delegate;' +
    '\n;globalThis.__compile=compile; globalThis.__aborts=renderAborts;', ctx);
  return ctx;
}
const BRIEF = 'モダンだけど温かみのあるLPを作って。うちの会社のやつ。';
async function runToDone(){
  const ctx = fresh();
  registry['briefInput'].value = BRIEF;
  const p = ctx.__submit();
  for (let i = 0; i < 60; i++){ flushRAF(3); await sleep(12); }
  await p;
  flushRAF(6); await sleep(RENDER_DELAY_MS ? 60 : 400); flushRAF(6);
  return ctx;
}

(async () => {
  /* ================= 0) 静的マークアップ ================= */
  console.log('=== 0) 静的マークアップ(押せる口と確認帯の既定) ===');
  const lockupBlock = html.slice(html.indexOf('<div id="lockup">'),
                                 html.indexOf('<!-- ============ (a) 初期画面'));
  chk('ロックアップはボタンである(キーボードでも押せる)',
      /<button id="lockupHome" type="button"[^>]*><b>GYAKUMON<\/b> — Intent Compiler<\/button>/.test(lockupBlock));
  chk('確認帯はロックアップの直下(同じ #lockup の中)',
      lockupBlock.indexOf('id="lockupHome"') < lockupBlock.indexOf('id="homeConfirm"') &&
      /<div id="homeConfirm"[^>]*>[\s\S]*?id="homeConfirmYes"[\s\S]*?id="homeConfirmNo"[\s\S]*?<\/div>/.test(lockupBlock));
  chk('確認帯は既定で hidden', /<div id="homeConfirm"[^>]*\shidden[\s>]/.test(lockupBlock));
  chk('文言は「最初からやり直しますか?」「やり直す」「続ける」',
      lockupBlock.indexOf('最初からやり直しますか?') >= 0 &&
      /<button id="homeConfirmYes" type="button">やり直す<\/button>/.test(lockupBlock) &&
      /<button id="homeConfirmNo" type="button">続ける<\/button>/.test(lockupBlock));
  chk('モーダルではない(覆いも固定配置も持たない)',
      !/#homeConfirm\{[^}]*position:fixed/.test(html) && html.indexOf('homeConfirmBackdrop') < 0);
  // ロックアップ一式の CSS を切り出し、朱と藍が1度も出ないことを見る
  const lockCss = (() => {
    const i0 = html.indexOf('#lockup{');
    const i1 = html.indexOf('#homeConfirm button:hover{');
    return (i0 < 0 || i1 < i0) ? '' : html.slice(i0, html.indexOf('}', i1) + 1);
  })();
  chk('ホバーは控えめ(朱・藍を使わない)', lockCss.length > 500 && !/--shu|--ai\b/.test(lockCss),
      'css=' + lockCss.length + '字');
  chk('当たり判定は文字だけ(地は pointer-events:none のまま)',
      /#lockup\{[^}]*pointer-events:none/.test(html) &&
      /#lockupHome\{[^}]*pointer-events:auto/.test(html));
  chk('角丸ゼロ', /#lockupHome\{[^}]*border-radius:0/.test(html) &&
      /#homeConfirm\{[^}]*border-radius:0/.test(html));
  chk('summary 行の当たり判定を広げた(padding と min-width)',
      /#procPanel > summary\{[^}]*padding:9px 13px/.test(html) &&
      /#procPanel\{[^}]*min-width:196px/.test(html));
  chk('−ボタン(＋/−の記号)は残っている',
      /#procPanel > summary::after\{content:"＋"/.test(html) &&
      /#procPanel\[open\] > summary::after\{content:"−"\}/.test(html));

  /* ================= A) ロゴ帰還 ================= */
  console.log('\n=== A-1) 初期画面: 確認せずに即帰る ===');
  {
    const c = fresh();
    chk('前提: まだ送信していない', c.__S.submitted === false && c.__S.exploded === false);
    clickEl(registry['lockupHome']);
    chk('★確認帯を出さない', registry['homeConfirm'].hidden === true);
    chk('★即座にトップへ帰る(再読込1回)', reloads === 1, 'reloads=' + reloads);
  }

  console.log('\n=== A-2) 進行中(爆散後〜未コンパイル): 確認帯を出す ===');
  let ctx = await runToDone();
  chk('前提: 爆散済み・未コンパイル', ctx.__S.exploded === true && ctx.__S.compileDone === false);
  chk('前提: 判断点が出ている', ctx.__S.branches.length === 2);
  clickEl(registry['lockupHome']);
  chk('★すぐには帰らない', reloads === 0, 'reloads=' + reloads);
  chk('★確認帯が出る', registry['homeConfirm'].hidden === false);

  console.log('\n=== A-3) [続ける] は帰らない。選択も壊さない ===');
  const before = JSON.stringify(ctx.__S.decisions);
  clickEl(registry['homeConfirmNo']);
  chk('★確認帯だけが畳まれる', registry['homeConfirm'].hidden === true);
  chk('★帰らない', reloads === 0);
  chk('★決定は1つも変わらない', JSON.stringify(ctx.__S.decisions) === before);
  chk('画面はステージのまま', registry['screenStage'].hidden === false);

  console.log('\n=== A-5) 確認帯は他の場所を触れば黙って消える ===');
  clickEl(registry['lockupHome']);
  chk('前提: もう一度出した', registry['homeConfirm'].hidden === false);
  clickEl(registry['cards']);                     // 他の操作(カードのあたり)
  chk('★他所を触ると確認帯が消える', registry['homeConfirm'].hidden === true);
  chk('★消えるだけで帰らない', reloads === 0);
  clickEl(registry['lockupHome']);
  chk('前提: 3度目', registry['homeConfirm'].hidden === false);
  clickEl(registry['lockupHome']);
  chk('ロックアップをもう一度押しても畳める(閉じ込めない)', registry['homeConfirm'].hidden === true);

  console.log('\n=== A-4) [やり直す]: レンダを中断してから帰る ===');
  RENDER_DELAY_MS = 4000;                          // 帰還の瞬間にレンダが飛んだままになる
  ctx = await runToDone();
  const nInflight = ctx.__aborts.size;
  chk('前提: レンダが飛んだままである', nInflight > 0, 'inflight=' + nInflight);
  let aborted = 0;
  ctx.__aborts.forEach(c => { c.signal.addEventListener('abort', () => { aborted++; }); });
  clickEl(registry['lockupHome']);
  chk('前提: 確認帯が出た', registry['homeConfirm'].hidden === false);
  clickEl(registry['homeConfirmYes']);
  chk('★走行中のレンダを全て中断してから帰る', aborted === nInflight,
      'aborted=' + aborted + '/' + nInflight);
  chk('★中断簿が空になる', ctx.__aborts.size === 0);
  chk('★トップへ帰る(再読込1回)', reloads === 1, 'reloads=' + reloads);
  chk('★確認帯は畳んでから帰る', registry['homeConfirm'].hidden === true);
  RENDER_DELAY_MS = 0;

  console.log('\n=== A-6) 指示書ができた後: 確認せずに即帰る ===');
  ctx = await runToDone();
  ctx.__S.decisions.forEach((_, bi) => ctx.__delegate(bi));
  flushRAF(4);
  await ctx.__compile();
  flushRAF(4);
  chk('前提: 指示書ができている', ctx.__S.compileDone === true && registry['screenCompiled'].hidden === false);
  clickEl(registry['lockupHome']);
  chk('★確認帯を出さない', registry['homeConfirm'].hidden === true);
  chk('★即座にトップへ帰る', reloads === 1, 'reloads=' + reloads);

  /* ================= B) パネル外クリックで閉じる ================= */
  console.log('\n=== B) 「処理の内訳」はパネルの外を1回クリックで閉じる ===');
  ctx = await runToDone();
  const P = registry['procPanel'];
  chk('前提: 送信後なのでパネルは出ている(既定は閉じている)',
      P.hidden === false && P.open === false);

  P.open = true; P.setAttribute('open', '');       // ユーザーが開いた状態を作る
  clickEl(registry['procBody']);
  chk('★パネルの中(本文)では閉じない', P.open === true);
  clickEl(registry['procRows']);
  chk('★表の中でも閉じない', P.open === true);
  clickEl(P);
  chk('★summary 行(パネル自身)でも閉じない = −ボタンは生きたまま', P.open === true);

  clickEl(registry['cards']);
  chk('★パネルの外を触ると閉じる', P.open === false);
  chk('★open 属性も落ちる(CSS の [open] が確実に外れる)',
      P.getAttribute('open') === undefined, JSON.stringify(P.attrs));

  const openBefore = P.open;
  clickEl(registry['cards']);
  chk('★閉じているときの外クリックは何も起こさない', P.open === openBefore && P.open === false);
  chk('外クリックでパネルが消えたりはしない(閉じるだけ)', P.hidden === false);

  console.log('\n=== B-4) 確認帯とパネルは同じ1本のハンドラで、別々に畳まれる ===');
  P.open = true; P.setAttribute('open', '');
  clickEl(registry['lockupHome']);
  chk('★ロックアップはパネルの外なので、押した時点でパネルが閉じる', P.open === false);
  chk('同じクリックで確認帯のほうは出る(ロックアップの中だから畳まれない)',
      registry['homeConfirm'].hidden === false);
  P.open = true; P.setAttribute('open', '');
  clickEl(registry['cards']);
  chk('★1回の外クリックで確認帯もパネルも畳まれる',
      registry['homeConfirm'].hidden === true && P.open === false);
  chk('それで帰りはしない', reloads === 0, 'reloads=' + reloads);

  /* ================= C) モデル表示が正準ID ================= */
  console.log('\n=== C-1/C-2) 実IDが各行の先頭に出る ===');
  ctx = await runToDone();
  ctx.__S.decisions.forEach((_, bi) => ctx.__delegate(bi));
  flushRAF(4);
  await ctx.__compile();
  flushRAF(4);
  const rows = registry['procRows'].textContent;
  chk('★問いの抽出は claude-sonnet-5', rows.indexOf('問いの抽出claude-sonnet-5 ・ api 81.3秒') >= 0,
      JSON.stringify(rows));
  chk('★見本の生成は claude-haiku-4-5(抽出とは別モデル)',
      rows.indexOf('見本の生成claude-haiku-4-5 ・ ') >= 0, JSON.stringify(rows));
  chk('★指示書の根拠文は claude-sonnet-5',
      rows.indexOf('指示書の根拠文claude-sonnet-5 ・ api 12.8秒') >= 0, JSON.stringify(rows));
  chk('★エイリアス単体はもう出ていない(実IDで置き換わった)',
      rows.indexOf('sonnet ・') < 0 && rows.indexOf('haiku ・') < 0, JSON.stringify(rows));
  chk('★「model 」のような接頭辞を付けない', rows.indexOf('model ') < 0);
  chk('状態にも正準IDを控えている',
      ctx.__S.extractStat.modelId === 'claude-sonnet-5' &&
      ctx.__S.extractStat.modelAlias === 'sonnet');
  chk('レンダ1本ごとにも控えている',
      Object.keys(ctx.__S.renderStat).every(k => ctx.__S.renderStat[k].modelId === 'claude-haiku-4-5'),
      JSON.stringify(ctx.__S.renderStat));
  chk('固定情報のほうは従来どおりエイリアス(起動時の指定を転記する欄なので)',
      registry['procFixed'].textContent.indexOf('問いの抽出 sonnet') >= 0);

  console.log('\n=== C-3) model_id が取れなければエイリアスへ倒す ===');
  MODEL_ID = {explode: null, render: null, compile: null};
  ctx = await runToDone();
  ctx.__S.decisions.forEach((_, bi) => ctx.__delegate(bi));
  flushRAF(4);
  await ctx.__compile();
  flushRAF(4);
  const rows2 = registry['procRows'].textContent;
  chk('★抽出は health の model へ倒れる', rows2.indexOf('問いの抽出sonnet ・ api') >= 0, JSON.stringify(rows2));
  chk('★見本は health の render_model へ倒れる', rows2.indexOf('見本の生成haiku ・ ') >= 0);
  chk('★根拠文は health の compile_model へ倒れる', rows2.indexOf('指示書の根拠文sonnet ・ api') >= 0);
  chk('★それらしいIDをでっち上げない', rows2.indexOf('claude-') < 0, JSON.stringify(rows2));
  chk('状態の modelId は null のまま(取れていない事実を残す)',
      ctx.__S.extractStat.modelId === null);
  MODEL_ID = {explode: 'claude-sonnet-5', render: 'claude-haiku-4-5', compile: 'claude-sonnet-5'};

  console.log(FAILS.length ? '\n--- FAILED: ' + FAILS.join(' / ')
                           : '\n--- ロゴ帰還 / パネル外クリック / モデル正準ID: すべて期待どおり');
  process.exit(FAILS.length ? 1 : 0);
})().catch(e => { console.error('THREW:', e && e.stack || e); process.exit(2); });
