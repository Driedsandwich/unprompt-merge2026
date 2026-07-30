// カウンタ行の一括操作と「処理の内訳」を機械で押さえる(domtest2.js と同型の最小 DOM シム)。
//
//   A) 〈委ねる〉は1件ずつだけ / カウンタ行の一括は「決める」の2つだけ
//      (2026-07-30 第6FB で「すべて委ねる」を撤去。以下はその後の期待値)
//      A-1 ストリーミング中(総数未確定)は一括2つを出さない
//      A-2 カードの「委ねる」を1件ずつ → カウンタ0 → 指示書ボタンが出る
//      A-3 1件を語クリックで選び直すと指示書ボタンが消え、カウンタが戻る
//      A-4 委任の経路は delegate() 1本だけ(順序に依らず同じ形・src は human-delegate)
//
//   B) 「処理の内訳」パネル
//      B-1 送信前は出さない。送信後に出る。既定は閉じている(open 属性を持たない)
//      B-2 固定情報は /api/health の実値から入る(文言をクライアントに書き置いていない)
//      B-3 explode 応答後に「問いの抽出」の行が入る(model / api / 判断点 / 棄却 / 二重確認)
//      B-4 zero_retry のときだけ「二重確認 あり」になる
//      B-5 見本の生成が届くと「見本の生成」の行が入る(件数 / 平均 / 最長)
//      B-6 指示書の根拠文が返ると「指示書の根拠文」の行が入る
const fs = require('fs');
const PATH = '/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon/app/index.html';
const html = fs.readFileSync(PATH, 'utf8');
const script = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const ids = [...new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]))];

/* ---------- 最小 DOM(domtest2.js と同一) ---------- */
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
  querySelectorAll: () => [],
  querySelector: () => null,
  body: new El('body'), documentElement: new El('html')
};
const window = {addEventListener(){}, matchMedia: () => ({matches: false})};
let rafQ = [];
const requestAnimationFrame = fn => { rafQ.push(fn); return rafQ.length; };
const cancelAnimationFrame = () => {};
const performance = {now: () => Date.now()};
const navigator = {clipboard: {writeText: async () => {}}};
function flushRAF(n){ for (let i = 0; i < (n || 8); i++){ const q = rafQ; rafQ = []; q.forEach(f => f(performance.now())); } }

/* ---------- スタブ ---------- */
// /api/health は本物のサーバと同じ形(2026-07-30 に engine / bind_host / prompts_dir /
// api_key_stripped を足した)。パネルの固定情報はここから来る値だけで組まれる。
const HEALTH = {
  ok: true, model: 'sonnet', render_model: 'haiku', compile_model: 'sonnet',
  effort: 'low', engine: 'claude-code-cli', claude_bin: 'claude',
  api_key_stripped: true, bind_host: '127.0.0.1', bind_port: 8321, prompts_dir: 'prompts/'
};
const BRANCHES = [
  {type:'branch', index:0, elapsed_ms:5700, branch:{id:'b0', question_point:'「うちの会社」の業種', anchor_words:['うちの会社'], options:[{label:'BtoB'},{label:'BtoC'}], default_if_unresolved:'BtoB'}},
  {type:'branch', index:1, elapsed_ms:6900, branch:{id:'b1', question_point:'LPの目的', anchor_words:['LP'], options:[{label:'問い合わせ'},{label:'購入'},{label:'認知'}], default_if_unresolved:'問い合わせ'}},
  {type:'branch', index:2, elapsed_ms:8300, branch:{id:'b2', question_point:'モダンと温かみの配分', anchor_words:['モダンだけど温かみのある'], options:[{label:'モダン寄り'},{label:'温かみ寄り'}], default_if_unresolved:'均等'}}
];
function doneEvent(extra){
  const o = {type:'done', ok:true, branches:[], residual_ambiguity_assessment:'業種が不明なままである。',
    missing_materials:['ロゴ素材'], rejected_branches:[{question_point:'棄却1'}, {question_point:'棄却2'}],
    branches_returned_by_model:5, timing:{wall_ms:118000, api_ms:81300}, api_ms:81300,
    first_branch_ms:5700, elapsed_ms:120000};
  return Object.assign(o, extra || {});
}
let EVENTS = [{type:'meta', partial:true, residual_ambiguity_assessment:'', missing_materials:[], elapsed_ms:4200}]
  .concat(BRANCHES, [doneEvent()]);
let EVENT_GAP_MS = 0;
let RENDER_API_MS = [24000, 31000, 24000, 31000, 24000, 31000, 24000];
let renderCall = 0;
const enc = s => Buffer.from(s, 'utf8');
function sseBody(events){
  let i = 0;
  return {
    getReader(){
      return { async read(){
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
  if (url === '/api/health') return {ok: true, json: async () => HEALTH};
  if (url === '/api/explode_stream') return {ok: true, body: sseBody(EVENTS)};
  if (url === '/api/explode'){
    return {ok: true, json: async () => ({ok: true, branches: BRANCHES.map(e => e.branch),
      residual_ambiguity_assessment: 'batch', missing_materials: [],
      rejected_branches: [], branches_returned_by_model: 3, timing: {wall_ms: 13000, api_ms: 11000}})};
  }
  if (url === '/api/render'){
    const ms = RENDER_API_MS[(renderCall++) % RENDER_API_MS.length];
    return {ok: true, json: async () => ({ok: true,
      tokens: {palette:['#112233','#445566','#778899'], heading_font:'sans', density:'normal', corner:'soft', tone_sample:'見出し。一文。'},
      timing: {wall_ms: ms + 60000, api_ms: ms}})};
  }
  if (url === '/api/compile'){
    return {ok: true, json: async () => ({ok: true, rationales: {'LPの目的': '問い合わせを増やすため。'},
      timing: {wall_ms: 40000, api_ms: 12800}})};
  }
  return {ok: false, json: async () => ({ok: false})};
}
class TextDecoderShim { decode(b){ return b ? Buffer.from(b).toString('utf8') : ''; } }

/* ---------- 実行 ---------- */
const vm = require('vm');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const FAILS = [];
const chk = (n, c, e) => { console.log((c ? 'OK   ' : 'FAIL ') + n + (e ? '  ' + e : '')); if (!c) FAILS.push(n); };

function fresh(){
  Object.keys(registry).forEach(k => delete registry[k]);
  ids.forEach(id => {
    registry[id] = new El('div'); registry[id].id = id;
    const tag = html.match(new RegExp('<[a-z]+[^>]*\\bid="' + id + '"[^>]*>', 'i'));
    if (tag && /\shidden(\s|>|=)/.test(tag[0])) registry[id].hidden = true;
  });
  rafQ = []; renderCall = 0;
  const ctx = {document, window, requestAnimationFrame, cancelAnimationFrame, performance, navigator,
    fetch: fetchStub, TextDecoder: TextDecoderShim, setTimeout, clearTimeout, setInterval, clearInterval,
    console, JSON, Math, Date, Promise, Array, Object, String, Number, Boolean, parseInt, parseFloat, isNaN};
  vm.createContext(ctx);
  vm.runInContext(script +
    '\n;globalThis.__S=S; globalThis.__submit=submitBrief; globalThis.__delegate=delegate;' +
    '\n;globalThis.__decide=decide; globalThis.__compile=compile;', ctx);
  return ctx;
}
const BRIEF = 'モダンだけど温かみのあるLPを作って。うちの会社のやつ。';
async function runToDone(){
  const ctx = fresh();
  registry['briefInput'].value = BRIEF;
  const p = ctx.__submit();
  for (let i = 0; i < 60; i++){ flushRAF(3); await sleep(12); }
  await p;
  flushRAF(6); await sleep(450); flushRAF(6);
  return ctx;
}
const click = (el) => { (el.handlers.click || []).forEach(f => f()); };

(async () => {
  /* ================= 静的マークアップ ================= */
  console.log('=== 0) 静的マークアップ(文言と既定状態) ===');
  // 2026-07-30(第6FB): 一括は「決める」の2つだけ。まとめて委ねる口は撤去した。
  // 〈委ねる〉はカード1枚ずつの行為として残る(委任状態=鼠は不変)。
  chk('★「すべて委ねる」のボタンが存在しない', html.indexOf('btnDelegateAll') < 0);
  chk('★「すべて委ねる」の文言が画面に残っていない', html.indexOf('すべて委ねる') < 0);
  chk('★一括委任の内部経路も残っていない(delegateAll / bulk-delegate)',
      html.indexOf('delegateAll') < 0 && html.indexOf('bulk-delegate') < 0);
  // 2026-07-30(第7FB 1): 同じ行の左端に「すべて選び直す」が加わった。
  // 決める口は依然2つだけ(ランダム / AIのおすすめ)で、これは決定をほどく口である。
  chk('カウンタ行は「カウンタ + すべて選び直す + 一括2つ」',
      /<div id="counterRow">[\s\S]{0,900}?id="branchCounter"[\s\S]{0,500}?id="btnResetAll"[\s\S]{0,500}?id="btnRandomAll"[\s\S]{0,500}?id="btnRecoAll"[\s\S]{0,160}?<\/div>/
        .test(html) &&
      (html.slice(html.indexOf('<div id="counterRow">'), html.indexOf('<div id="recoNote"'))
           .match(/<button /g) || []).length === 3);
  chk('カウンタが先・ボタンが後(= 行の右端)',
      html.indexOf('id="branchCounter"') < html.indexOf('id="btnResetAll"') &&
      html.indexOf('id="btnResetAll"') < html.indexOf('id="btnRandomAll"'));
  chk('カード個別の「委ねる」は残っている',
      /el\('button', 'delegate', '委ねる'\)/.test(html) && /\.delegate\{/.test(html));
  chk('処理の内訳は details 要素', /<details id="procPanel"[^>]*>/.test(html));
  chk('処理の内訳は既定で閉じている(open 属性なし)', !/<details id="procPanel"[^>]*\sopen[\s>]/.test(html));
  chk('処理の内訳は既定で hidden(送信前は出さない)', /<details id="procPanel"[^>]*\shidden[\s>]/.test(html));
  chk('summary の文言は「処理の内訳」', /<summary>処理の内訳<\/summary>/.test(html));
  chk('summary は 11px・鼠・字間広め',
      /#procPanel > summary\{[^}]*font-size:11px[^}]*letter-spacing:\.16em[^}]*color:var\(--muted\)/.test(html));
  chk('パネルは左下に固定', /#procPanel\{[^}]*position:fixed[^}]*left:22px[^}]*bottom:18px/.test(html));
  chk('パネルの数字は等幅', /\.proc-t td\{[^}]*font-variant-numeric:tabular-nums/.test(html));
  // パネルの CSS 一式(#procPanel{ ... .proc-empty{...})を切り出して、朱と藍が
  // 1度も現れないことを見る(このパネルは判断の状態を語らないので墨と鼠だけで組む)
  const procCss = (() => {
    const i0 = html.indexOf('#procPanel{');
    const i1 = html.indexOf('.proc-empty{');
    return (i0 < 0 || i1 < i0) ? '' : html.slice(i0, html.indexOf('}', i1) + 1);
  })();
  chk('パネルに朱・藍を使っていない', procCss.length > 400 && !/--shu|--ai\b/.test(procCss),
      'css=' + procCss.length + '字');
  chk('ゴースト様式(枠線のみ・鼠・ホバー藍)',
      /#btnResetAll, #btnRandomAll, #btnRecoAll\{[^}]*background:transparent[^}]*border:1px solid var\(--line\)[^}]*color:var\(--muted\)/.test(html) &&
      /#btnResetAll:hover, #btnRandomAll:hover, #btnRecoAll:hover\{[^}]*color:var\(--ai\)[^}]*border-color:var\(--ai\)/.test(html));
  chk('角丸ゼロ', /#btnResetAll, #btnRandomAll, #btnRecoAll\{[^}]*border-radius:0/.test(html) && /#procPanel\{[^}]*border-radius:0/.test(html));

  /* ================= A) 委ねるは1件ずつ / 一括は「決める」だけ ================= */
  console.log('\n=== A-1) ストリーミング中は一括を出さない ===');
  EVENT_GAP_MS = 120;
  {
    const ctx = fresh();
    registry['briefInput'].value = BRIEF;
    ctx.__submit();
    let guard = 0;
    while (ctx.__S.branches.length < 2 && guard++ < 300){ flushRAF(2); await sleep(8); }
    chk('前提: 総数未確定で未決あり',
        ctx.__S.streaming === true && ctx.__S.streamDone === false && ctx.__S.branches.length >= 2);
    chk('★ストリーミング中は一括2つを出さない',
        registry['btnRandomAll'].hidden === true && registry['btnRecoAll'].hidden === true);
    while (guard++ < 900 && ctx.__S.streamDone !== true){ flushRAF(2); await sleep(8); }
    flushRAF(4);
    chk('done 後は出る',
        registry['btnRandomAll'].hidden === false && registry['btnRecoAll'].hidden === false);
  }
  EVENT_GAP_MS = 0;

  console.log('\n=== A-2) 1件ずつ委ねる → カウンタ0 → 指示書ボタン ===');
  let ctx = await runToDone();
  let S = ctx.__S;
  chk('前提: 分岐3件・全て未決', S.branches.length === 3 && S.decisions.every(d => !d.status));
  chk('前提: 指示書ボタンはまだ出ていない', registry['compileRow'].hidden === true);
  S.decisions.forEach((_, bi) => ctx.__delegate(bi));      // カードの「委ねる」を1件ずつ
  flushRAF(4);
  chk('★全分岐が delegated になる',
      S.decisions.every(d => d.status === 'delegated'),
      JSON.stringify(S.decisions.map(d => d.status)));
  chk('★委任は oi を持たない', S.decisions.every(d => d.oi === null && d.prev === null));
  chk('★委任の src は human-delegate だけ(一括の出自を持たない)',
      S.decisions.every(d => d.src === 'human-delegate'),
      JSON.stringify(S.decisions.map(d => d.src)));
  chk('★カウンタの未決が 0', registry['branchCounter'].textContent.indexOf('未決 0') > 0,
      JSON.stringify(registry['branchCounter'].textContent));
  chk('★カウンタが zero(藍)になる', registry['branchCounter'].classList.contains('zero'));
  chk('★指示書ボタンが出る', registry['compileRow'].hidden === false);
  chk('原文の語が全て鼠(委任)になる',
      S.spans.every(sp => sp.el && sp.el.dataset.state === 'delegated'),
      JSON.stringify(S.spans.map(sp => sp.el && sp.el.dataset.state)));

  console.log('\n=== A-3) 1件だけ選び直すと指示書ボタンが消える ===');
  const sp0 = S.spans[0];
  const bi0 = sp0.bis[0];
  click(sp0.el);
  flushRAF(4);
  chk('★選び直した1件が未決へ戻る', S.decisions[bi0].status === null, 'bi=' + bi0);
  chk('★直前の委任は prev に1段だけ退避される',
      S.decisions[bi0].prev && S.decisions[bi0].prev.status === 'delegated');
  chk('★指示書ボタンが消える', registry['compileRow'].hidden === true);
  chk('★カウンタの未決が 1 に戻る', registry['branchCounter'].textContent.indexOf('未決 1') > 0,
      JSON.stringify(registry['branchCounter'].textContent));
  chk('他の2件の委任は残る', S.decisions.filter(d => d.status === 'delegated').length === 2);
  // 個別に決め直せば元に戻る(選び直しの経路が生きている)
  ctx.__decide(bi0, 0);
  flushRAF(4);
  chk('選び直して「決める」と再び未決0', registry['branchCounter'].classList.contains('zero'));
  chk('指示書ボタンが戻る', registry['compileRow'].hidden === false);
  chk('選んだ1件だけ藍(decided)になる', S.decisions[bi0].status === 'decided');

  console.log('\n=== A-4) 委任は1件ずつの経路だけが残っている ===');
  {
    // 一括委任の撤去後も、委任そのものの状態遷移は 1件ずつの delegate() が唯一の道である。
    // 同じ委任を2度通しても形が変わらないこと(専用の遷移を持たないこと)を押さえる。
    const shape = (ds) => JSON.stringify(ds.map(d => ({status: d.status, oi: d.oi, prev: d.prev, src: d.src})));
    const ctxA = await runToDone();
    ctxA.__S.decisions.forEach((_, bi) => ctxA.__delegate(bi));
    flushRAF(4);
    const first = shape(ctxA.__S.decisions);
    const ctxB = await runToDone();
    for (let bi = ctxB.__S.decisions.length - 1; bi >= 0; bi--) ctxB.__delegate(bi);   // 逆順でも同じ
    flushRAF(4);
    chk('★順序に依らず同じ形になる(委任に専用の遷移が無い)',
        first === shape(ctxB.__S.decisions), first + ' vs ' + shape(ctxB.__S.decisions));
    chk('★src は全て human-delegate', ctxB.__S.decisions.every(d => d.src === 'human-delegate'),
        JSON.stringify(ctxB.__S.decisions.map(d => d.src)));
  }

  /* ================= B) 処理の内訳 ================= */
  console.log('\n=== B-1) 送信前は出さない / 送信後に出る ===');
  {
    const c = fresh();
    chk('★送信前はパネルが hidden', registry['procPanel'].hidden === true);
    chk('送信前は S.extractStat が空', c.__S.extractStat === null);
  }
  ctx = await runToDone();
  S = ctx.__S;
  chk('★送信後はパネルが出る', registry['procPanel'].hidden === false);

  console.log('\n=== B-2) 固定情報は /api/health の実値 ===');
  const fixed = registry['procFixed'].textContent;
  chk('health を保持している', !!S.health && S.health.model === 'sonnet');
  chk('★実行エンジン(ローカル実行・APIキー不使用)',
      fixed.indexOf('Claude Code CLI(ローカル実行・APIキー不使用)') >= 0, JSON.stringify(fixed));
  chk('★モデルは health の実値', fixed.indexOf('問いの抽出 sonnet') >= 0 &&
      fixed.indexOf('見本の生成 haiku') >= 0 && fixed.indexOf('指示書 sonnet') >= 0);
  chk('★接続先は 127.0.0.1 のみ', fixed.indexOf('127.0.0.1:8321 のみ') >= 0);
  chk('★プロンプトの公開先', fixed.indexOf('リポジトリ prompts/ で公開') >= 0);
  chk('固定情報が4行', registry['procFixed'].children.length === 4);

  console.log('\n=== B-3) explode 応答後に「問いの抽出」の行が入る ===');
  const rows = () => registry['procRows'].textContent;
  chk('★抽出の行が入る', rows().indexOf('問いの抽出') >= 0, JSON.stringify(rows()));
  // 2026-07-30: 行の先頭はモデル名そのもの(「model 」の接頭辞は置かない)。
  // このスタブの timing には model_id が無いので、/api/health のエイリアスへ倒れる。
  // 正準IDが載る場合と、載らない場合のフォールバックは domtest7.js が見る。
  chk('★model が先頭に入る(エイリアスへのフォールバック)',
      rows().indexOf('問いの抽出sonnet ・ api') >= 0, JSON.stringify(rows()));
  chk('★api 秒が実測から入る', rows().indexOf('api 81.3秒') >= 0, JSON.stringify(rows()));
  chk('★判断点の数が入る', rows().indexOf('判断点 3') >= 0);
  chk('★棄却の数が入る', rows().indexOf('棄却 2') >= 0);
  chk('★二重確認なしなら「二重確認 なし」', rows().indexOf('二重確認 なし') >= 0);
  chk('「まだ実行された処理はありません」が畳まれる', registry['procEmpty'].hidden === true);
  chk('生活語で通す(抽出/レンダ/コンパイルの語を出さない)',
      rows().indexOf('レンダ') < 0 && rows().indexOf('コンパイル') < 0 && rows().indexOf('explode') < 0);

  console.log('\n=== B-4) zero_retry のときだけ「二重確認 あり」 ===');
  EVENTS = [{type:'meta', partial:true, residual_ambiguity_assessment:'', missing_materials:[], elapsed_ms:4200}]
    .concat(BRANCHES, [doneEvent({zero_retry: true, timing: {wall_ms: 236000, api_ms: 162600}, api_ms: 162600})]);
  const ctxZ = await runToDone();
  const rowsZ = registry['procRows'].textContent;
  chk('★zero_retry で「二重確認 あり」', rowsZ.indexOf('二重確認 あり') >= 0, JSON.stringify(rowsZ));
  chk('zeroRetry が state にも入る', ctxZ.__S.extractStat.zeroRetry === true);
  chk('2回ぶんの合計 api 秒が出る', rowsZ.indexOf('api 162.6秒') >= 0);
  EVENTS = [{type:'meta', partial:true, residual_ambiguity_assessment:'', missing_materials:[], elapsed_ms:4200}]
    .concat(BRANCHES, [doneEvent()]);

  console.log('\n=== B-5) 見本の生成の行 ===');
  ctx = await runToDone();
  S = ctx.__S;
  const rows2 = registry['procRows'].textContent;
  const nOpts = S.branches.reduce((a, b) => a + b.options.length, 0);
  chk('★見本の生成の行が入る', rows2.indexOf('見本の生成') >= 0, JSON.stringify(rows2));
  chk('★件数は届いた見本の数(先頭はレンダ側のモデル名)',
      rows2.indexOf('見本の生成haiku ・ ' + nOpts + '件') >= 0, 'nOpts=' + nOpts);
  chk('★平均秒が入る', /平均 \d+\.\d秒/.test(rows2));
  chk('★最長秒が入る', /最長 \d+\.\d秒/.test(rows2));
  chk('最長 >= 平均', (() => {
    const avg = parseFloat((rows2.match(/平均 (\d+\.\d)秒/) || [0, '0'])[1]);
    const max = parseFloat((rows2.match(/最長 (\d+\.\d)秒/) || [0, '0'])[1]);
    return max >= avg && max > 0;
  })());
  chk('同じスロットを二重計上しない', Object.keys(S.renderStat).length === nOpts,
      JSON.stringify(Object.keys(S.renderStat)));

  console.log('\n=== B-6) 指示書の根拠文の行 ===');
  ctx.__S.decisions.forEach((_, bi) => ctx.__delegate(bi));   // 未決を1件ずつ委ねて未決0にする
  flushRAF(4);
  await ctx.__compile();
  flushRAF(4);
  const rows3 = registry['procRows'].textContent;
  chk('★根拠文の行が入る', rows3.indexOf('指示書の根拠文') >= 0, JSON.stringify(rows3));
  chk('★api 秒が入る', rows3.indexOf('api 12.8秒') >= 0);
  chk('コンパイル後もパネルは出たまま(指示書画面で読める)', registry['procPanel'].hidden === false);
  chk('3つの処理が全て並ぶ', registry['procRows'].children.length === 3);

  console.log(FAILS.length ? '\n--- FAILED: ' + FAILS.join(' / ') : '\n--- 委ねるは1件ずつ / 一括は決めるの2つ / 処理の内訳: すべて期待どおり');
  process.exit(FAILS.length ? 1 : 0);
})().catch(e => { console.error('THREW:', e && e.stack || e); process.exit(2); });
