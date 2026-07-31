// 2026-07-29 ユーザー実機報告の2件を機械で押さえる(domtest.js と同じ最小 DOM シム)。
//   A) 確定/委任済みの語をクリックして選び直すとき、判断点カウントが戻ること
//      (旧実装はカードだけ再提示して status を触らず、カウンタが戻らなかった)
//   B) 一度コンパイルボタンが出た後に決定を解除したら、押せなくなること
//      (旧実装は「一度出したら出しっぱなし」で、未決が戻っても押せたまま)
// どちらも「画面は毎回 S.decisions[].status から導出する」構造でしか通らない。
const fs = require('fs');
const PATH = require('path').resolve(__dirname,'../..') + '/app/index.html';
const html = fs.readFileSync(PATH, 'utf8');
const script = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const ids = [...new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]))];

/* ---------- 最小 DOM(domtest.js と同一) ---------- */
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
  // 引出線の幾何を見たいので、シムでも「原文は上・カードは下」を固定して返す
  // (既定シムの top=_uid では生成順に依存し、カードが原文より上に来てしまう)。
  getBoundingClientRect(){
    if (this.id === 'stage') return {left: 0, top: 0, right: 1000, bottom: 1200, width: 1000, height: 1200};
    let p = this;
    while (p){ if (p.id === 'cards') return {left: 40, top: 700, right: 340, bottom: 820, width: 300, height: 120}; p = p.parent; }
    return {left: 100, top: 120, right: 180, bottom: 160, width: 80, height: 40};
  }
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
  // 例文チップの配線 document.querySelectorAll('.ex-chip') で script 評価が落ちないようにする。
  // シムは静的マークアップを持たないので空配列でよい(EVIDENCE/compare/domtest_compare.js と同じ流儀)。
  querySelectorAll: () => [],
  querySelector: () => null,
  body: new El('body'), documentElement: new El('html')
};
let REDUCE_MATCH = false;        // E) で prefers-reduced-motion: reduce を再現する
const window = {addEventListener(){}, matchMedia: () => ({matches: REDUCE_MATCH})};
let rafQ = [];
const requestAnimationFrame = fn => { rafQ.push(fn); return rafQ.length; };
const cancelAnimationFrame = () => {};
const performance = {now: () => Date.now()};
const navigator = {clipboard: {writeText: async () => {}}};
function flushRAF(n){ for (let i = 0; i < (n || 8); i++){ const q = rafQ; rafQ = []; q.forEach(f => f(performance.now())); } }

/* ---------- SSE スタブ(分岐3件 → done) ---------- */
const EVENTS = [
  {type:'meta', partial:true, residual_ambiguity_assessment:'', missing_materials:[], elapsed_ms:4200},
  {type:'branch', index:0, elapsed_ms:5700, branch:{id:'b0', question_point:'「うちの会社」の業種', anchor_words:['うちの会社'], options:[{label:'BtoB'},{label:'BtoC'}], default_if_unresolved:'BtoB'}},
  {type:'branch', index:1, elapsed_ms:6900, branch:{id:'b1', question_point:'LPの目的', anchor_words:['LP'], options:[{label:'問い合わせ'},{label:'購入'},{label:'認知'}], default_if_unresolved:'問い合わせ'}},
  {type:'branch', index:2, elapsed_ms:8300, branch:{id:'b2', question_point:'モダンと温かみの配分', anchor_words:['モダンだけど温かみのある'], options:[{label:'モダン寄り'},{label:'温かみ寄り'}], default_if_unresolved:'均等'}},
  {type:'done', ok:true, branches:[], residual_ambiguity_assessment:'業種が不明なままである。', missing_materials:['ロゴ素材'],
   rejected_branches:[], branches_returned_by_model:3, timing:{wall_ms:11500, api_ms:9300}, api_ms:9300, first_branch_ms:5700, elapsed_ms:11600}
];
const enc = s => Buffer.from(s, 'utf8');
let EVENT_GAP_MS = 0;            // C) では間隔を空けて「done 未達」の瞬間を作る
function sseBody(events){
  let i = 0;
  return {getReader(){ return {async read(){
    if (EVENT_GAP_MS) await new Promise(r => setTimeout(r, EVENT_GAP_MS));
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

/* ---------- 実行 ---------- */
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
async function runToDone(){
  const ctx = fresh();
  registry['briefInput'].value = 'モダンだけど温かみのあるLPを作って。うちの会社のやつ。';
  const p = ctx.__submit();
  for (let i = 0; i < 60; i++){ flushRAF(3); await sleep(12); }
  await p;
  flushRAF(6); await sleep(500); flushRAF(6);
  return ctx;
}
const counter  = () => registry['branchCounter'].textContent;
// カウンタは「総数」と「未決」を分けて出す(2026-07-30 の文言改訂)。
// 旧書式「この文から抽出した判断点 N→0」は総数に見える誤読を招いたので廃した。
const CT = (undecided, total) => 'この文から抽出した判断点 ' + (total == null ? 3 : total) + ' ・ 未決 ' + undecided;
const rowHidden = () => registry['compileRow'].hidden;
const btnDisabled = () => registry['btnCompile'].disabled === true;
const click = (el) => { (el.handlers.click || []).forEach(f => f()); };
// 2026-07-30(第7FB 5b): 決めても見本は全部出たままになった(決定表示 .resolved は廃止)。
// カードの姿は data-state と「選ばれた見本の data-chosen」で見る。
const cardOf   = (bi) => registry['cards'].children[bi];
const cardState = (bi) => cardOf(bi).dataset.state;
const optsOf   = (bi) => cardOf(bi).querySelectorAll('.opt');
const chosenOi = (bi) => {
  const hit = optsOf(bi).filter(b => b.dataset.chosen === '1');
  return hit.length ? Number(hit[0].dataset.oi) : null;
};

(async () => {
  /* ================= A) 決める → 解除 → カウント復元 ================= */
  console.log('=== A) 確定した語をクリックして選び直すとカウントが戻る ===');
  let ctx = await runToDone();
  let S = ctx.__S;
  chk('前提: 分岐3件・未決3', S.branches.length === 3 && S.decisions.filter(d => !d.status).length === 3);
  chk('前提: 初期カウンタは 総数3・未決3', counter() === CT(3), JSON.stringify(counter()));

  vm.runInContext('decide(0,0);', ctx);
  chk('1件決めると未決が 2 になる(総数は3のまま)', counter() === CT(2), JSON.stringify(counter()));
  chk('決めた分岐の status が decided', S.decisions[0].status === 'decided');
  chk('決めても見本は全部出たまま(選ばれた1枚に「決めた」が付く)',
      optsOf(0).length === 2 && chosenOi(0) === 0 && cardState(0) === 'decided');

  vm.runInContext('onTokenClick(0);', ctx);
  chk('★解除で未決が 3 に戻る', counter() === CT(3), JSON.stringify(counter()));
  chk('★解除で status が null に戻る(単一のソースが巻き戻る)', S.decisions[0].status === null);
  chk('★解除でカードが未決の姿に戻る(「決めた」の印が外れる)',
      cardState(0) === 'open' && chosenOi(0) === null);
  chk('解除しても直前の選択は prev に残る', !!S.decisions[0].prev && S.decisions[0].prev.oi === 0,
      JSON.stringify(S.decisions[0].prev));
  chk('解除中の語の色は open に戻る',
      S.spans.filter(sp => sp.bis.indexOf(0) >= 0).every(sp => sp.el.dataset.state === 'open'),
      JSON.stringify(S.spans.map(sp => sp.bis + ':' + sp.el.dataset.state)));

  vm.runInContext('decide(0,1);', ctx);
  chk('選び直すと未決は再び 2', counter() === CT(2), JSON.stringify(counter()));
  chk('選び直した内容で status が上書きされる', S.decisions[0].status === 'decided' && S.decisions[0].oi === 1);

  // 委任も同じ経路で戻ること
  vm.runInContext('delegate(1);', ctx);
  chk('委ねると未決が 1', counter() === CT(1), JSON.stringify(counter()));
  vm.runInContext('onTokenClick(1);', ctx);
  chk('★委任も解除で未決が 2 に戻る', counter() === CT(2), JSON.stringify(counter()));
  chk('委任の解除で status が null', S.decisions[1].status === null);

  // 選び直しをやめる(同じ語をもう一度押す)と元の決定へ戻る
  vm.runInContext('onTokenClick(1);', ctx);
  chk('もう一度押すと選び直しをやめて元の決定に戻る', S.decisions[1].status === 'delegated');
  chk('やめたあと未決は 1', counter() === CT(1), JSON.stringify(counter()));

  // 解除は常に1枚だけ(2枚目を解除すると1枚目の解除は畳まれる)
  vm.runInContext('onTokenClick(0); onTokenClick(1);', ctx);
  chk('解除中のカードは同時に1枚だけ',
      S.decisions.filter(d => !d.status && d.prev).length === 1,
      JSON.stringify(S.decisions.map(d => (d.status || 'open') + (d.prev ? '/prev' : ''))));
  chk('畳まれた側は元の決定へ戻っている', S.decisions[0].status === 'decided');

  /* ================= B) 全部決める → 1件解除 → コンパイル不可 ================= */
  console.log('\n=== B) 決定を解除したらコンパイルできない ===');
  ctx = await runToDone();
  S = ctx.__S;
  chk('前提: 未決3ではコンパイル行が出ない', rowHidden() === true);
  chk('前提: 未決3ではボタンも無効', btnDisabled() === true);

  vm.runInContext('decide(0,0); decide(1,1); delegate(2);', ctx);
  chk('全件決めるとコンパイル行が出る', rowHidden() === false);
  chk('全件決めるとボタンが有効', btnDisabled() === false);
  chk('未決0 / zero クラス(総数は3のまま出る)', counter() === CT(0) &&
      registry['branchCounter'].classList.contains('zero'), JSON.stringify(counter()));

  vm.runInContext('onTokenClick(1);', ctx);
  chk('★1件解除でコンパイル行が消える', rowHidden() === true);
  chk('★1件解除でボタンが無効に戻る', btnDisabled() === true);
  chk('★解除で未決が 1 に戻る', counter() === CT(1), JSON.stringify(counter()));
  chk('解除中は zero クラスが外れる', registry['branchCounter'].classList.contains('zero') === false);

  // 押せない状態で compile() を直接叩いても走らない(表示と実行が同じ導出を見ている)
  vm.runInContext('compile();', ctx);
  chk('★押せない状態では compile() が走らない', S.compiling === false && registry['screenCompiled'].hidden === true);

  vm.runInContext('decide(1,2);', ctx);
  chk('決め直すとコンパイル行が戻る', rowHidden() === false && btnDisabled() === false);

  /* ================= C) ストリーミング中は常に不可 ================= */
  console.log('\n=== C) 総数が未確定のあいだはコンパイル不可のまま ===');
  EVENT_GAP_MS = 120;
  ctx = fresh();
  registry['briefInput'].value = 'モダンだけど温かみのあるLPを作って。うちの会社のやつ。';
  ctx.__submit();
  let guard = 0;
  while (ctx.__S.branches.length < 1 && guard++ < 400){ flushRAF(2); await sleep(8); }
  S = ctx.__S;
  chk('前提: done 未達(streaming=true / streamDone=false)', S.streaming === true && S.streamDone === false);
  vm.runInContext('S.branches.forEach((_,i) => decide(i,0));', ctx);
  chk('ストリーミング中は残0でもコンパイル行が出ない', rowHidden() === true);
  chk('ストリーミング中はボタンも無効', btnDisabled() === true);
  vm.runInContext('compile();', ctx);
  chk('ストリーミング中は compile() も走らない', S.compiling === false);
  for (let i = 0; i < 80; i++){ flushRAF(3); await sleep(12); }
  flushRAF(6); await sleep(500); flushRAF(6);
  chk('done 後、未決が残っていればやはり不可',
      (S.decisions.filter(d => !d.status).length > 0) === (rowHidden() === true),
      '未決=' + S.decisions.filter(d => !d.status).length + ' hidden=' + rowHidden());

  /* ================= D) 爆散演出が実際に走り切ること ================= */
  // シムは描画しないので「throw しないこと」と「最終状態の DOM/クラス」を見る。
  console.log('\n=== D) 爆散(散らばり → 静定 → 圏点 → 引出線)が走り切る ===');
  EVENT_GAP_MS = 0;
  ctx = await runToDone();
  S = ctx.__S;
  const bt = registry['briefText'];
  const svg = registry['tethers'];
  // 遷移(380ms)より先に抽出が返る速い経路。原文の語スパンが消されないことも同時に見る。
  chk('速い抽出でも原文の語スパンが残る(遷移タイマーに上書きされない)',
      bt.children.length > 0 && bt._text === '', 'children=' + bt.children.length);
  const toks = bt.querySelectorAll('.tok');
  const chs  = bt.querySelectorAll('.ch');
  chk('原文が1文字スパンに割れている', chs.length > 10, 'ch=' + chs.length);
  chk('anchor 語が .tok になっている', toks.length === 3, 'tok=' + toks.length);
  chk('.tok の中も1文字スパンになっている(圏点の単位)',
      toks.every(t => t.querySelectorAll('.ch').length > 0));
  chk('字間を広げる spread が付く', bt.classList.contains('spread'));
  chk('圏点が打たれている(tenten-on)', bt.classList.contains('tenten-on'));
  chk('打つ前の抑制(dot-pending)が全て解けている',
      chs.every(c => !c.classList.contains('dot-pending')));
  chk('散らばりが静定している(scatterActive=false)', S.scatterActive === false);
  chk('散らばりのインライン transform が残っていない',
      S.chEls.every(c => !c.style.transform), JSON.stringify(S.chEls.slice(0,3).map(c => c.style.transform)));
  chk('引出線を引いてよい状態になっている', S.leaderReady === true);
  chk('引出線が SVG に引かれている', svg.children.filter(c => c.tagName === 'PATH').length >= 3,
      'path=' + svg.children.filter(c => c.tagName === 'PATH').length);
  chk('先端の小円が打たれている', svg.children.filter(c => c.tagName === 'CIRCLE').length >= 3,
      'circle=' + svg.children.filter(c => c.tagName === 'CIRCLE').length);
  chk('引出線は直線だけで組まれている(製図の引出線様式。ベジェを使わない)',
      svg.children.filter(c => c.tagName === 'PATH').every(p => /^M [\d.]+ [\d.]+( L [\d.]+ [\d.]+){1,3}$/.test(p.attrs.d)),
      JSON.stringify(svg.children.filter(c => c.tagName === 'PATH').map(p => p.attrs.d)));
  chk('描画アニメは1本につき1度だけ(既描画キーを持っている)',
      Object.keys(S.leaderSeen).length >= 3, JSON.stringify(Object.keys(S.leaderSeen)));
  // 決定すると線と語の色が朱から藍へ移る
  vm.runInContext('decide(0,0);', ctx);
  await sleep(320); flushRAF(4);
  vm.runInContext('drawTethers();', ctx);
  chk('決定した分岐の引出線が藍になる',
      svg.children.some(c => c.tagName === 'PATH' && c.attrs.stroke === '#2B3A67'),
      JSON.stringify(svg.children.filter(c => c.tagName === 'PATH').map(p => p.attrs.stroke)));
  chk('未決の分岐の引出線は朱のまま',
      svg.children.some(c => c.tagName === 'PATH' && c.attrs.stroke === '#C73E2E'));

  /* ================= E) prefers-reduced-motion: 簡略版 ================= */
  console.log('\n=== E) reduced-motion では待ち時間0で最終状態へ飛ぶ ===');
  REDUCE_MATCH = true;
  ctx = await runToDone();
  S = ctx.__S;
  const btR = registry['briefText'];
  const svgR = registry['tethers'];
  chk('簡略版でも字間は広がる', btR.classList.contains('spread'));
  chk('簡略版でも圏点は打たれる(点は結果であって演出ではない)', btR.classList.contains('tenten-on'));
  chk('簡略版では散らばりを行わない', S.scatterActive === false &&
      S.chEls.every(c => !c.style.transform));
  chk('簡略版でも引出線は引かれる', svgR.children.filter(c => c.tagName === 'PATH').length >= 3,
      'path=' + svgR.children.filter(c => c.tagName === 'PATH').length);
  chk('簡略版では描画アニメ(dashoffset)を仕込まない',
      svgR.children.filter(c => c.tagName === 'PATH').every(p => p.style.strokeDashoffset === undefined),
      JSON.stringify(svgR.children.filter(c => c.tagName === 'PATH').map(p => p.style.strokeDashoffset)));
  chk('簡略版でもカード操作は同じに効く', (function(){
    vm.runInContext('decide(0,0);', ctx);
    const a = counter() === CT(2);
    vm.runInContext('onTokenClick(0);', ctx);
    return a && counter() === CT(3);
  })());
  REDUCE_MATCH = false;

  /* ================= F) 並置比較の事前生成ラベル(2026-07-30 文言改訂) ================= */
  // 並置比較はその場生成ではない。どの依頼文で作った実例かを常に名乗り、
  // いまのセッションの依頼文と違うときだけ、違うと明言する。
  console.log('\n=== F) 並置比較は「事前生成の実例」であることを常設で名乗る ===');
  chk('常設ラベルが静的マークアップとして存在する(hidden でない)',
      html.indexOf('<p id="compareFixture">事前生成の実例 — 依頼文「モダンだけど温かみのあるLPを作って。うちの会社のやつ。」による</p>') > 0);
  // 2026-07-30 トリアージ改訂: 不安が最高潮になる画面なので、事実の語順を
  // 「あなたの成果物(指示書)は実在する」→「この比較は別の依頼文の事前生成物」に変えた。
  // 事前生成の開示(DISCLOSURE #7)そのものは文面に残したままである。
  chk('不一致の注記の文面が承認どおり',
      html.indexOf('あなたの意図の指示書は前の画面で完成しています。この比較は、別の依頼文で事前生成した実例です(その場生成は行いません)。') > 0);
  // 実装は paintCompareFixture() から pickComparePair() + paintComparePair() へ分かれた
  // (2026-07-30 の5パターン化)。ここでは「manifest 無し = 既定ペア」の経路で、
  // 一致/不一致が毎回 S.brief から導出されることを見る。manifest 有りの5パターンと
  // iframe の遅延読み込みは EVIDENCE/compare/domtest_compare.js が担当する。
  const paint = 'var __sel = pickComparePair(null); paintComparePair(__sel.pair, __sel.matched);';
  ctx = await runToDone();
  vm.runInContext(paint, ctx);
  chk('依頼文が事前生成と同じなら注記は出ない', registry['compareMismatch'].hidden === true);
  chk('常設ラベルは表示中ペアの依頼文を名乗る',
      registry['compareFixture'].textContent ===
        '事前生成の実例 — 依頼文「モダンだけど温かみのあるLPを作って。うちの会社のやつ。」による',
      JSON.stringify(registry['compareFixture'].textContent));
  vm.runInContext('S.brief = "社内向けの資料をいい感じにして。"; ' + paint, ctx);
  chk('★依頼文が違うときだけ注記が出る', registry['compareMismatch'].hidden === false);
  chk('不一致でもラベルは表示中ペアの依頼文のまま(セッションの依頼文を名乗らない)',
      registry['compareFixture'].textContent.indexOf('社内向けの資料') < 0 &&
      registry['compareFixture'].textContent.indexOf('モダンだけど温かみのある') > 0,
      JSON.stringify(registry['compareFixture'].textContent));
  vm.runInContext('S.brief = "モダンだけど温かみのあるLPを作って。うちの会社のやつ。"; ' + paint, ctx);
  chk('一致に戻せば注記も引っ込む(毎回導出している)', registry['compareMismatch'].hidden === true);

  /* ================= H) 決定後も全候補を表示 / 直接選び直せる(2026-07-30 第7FB 5b) =========
     旧実装は「決めると選んだ見本以外が消え、選び直しには原文の語クリックが要る」形だった。
     新実装ではカードは常に全ての見本を出し、選ばれた1枚に藍の枠と「決めた」が付き、
     他は減光する。別の見本を押せば reopen を経ずにその場で選び直せる(human-pick 上書き)。
     カードの高さが状態で変わらないことも同時に押さえる(「決めた」の場所は常に確保)。 */
  console.log('\n=== H) 決定後も全候補を出したまま、直接選び直せる ===');
  ctx = await runToDone();
  S = ctx.__S;
  chk('前提: 見本2枚・未決', optsOf(0).length === 2 && cardState(0) === 'open');
  chk('未決では「決めた」の印が誰にも付いていない', chosenOi(0) === null);
  chk('★どの見本も「決めた」の札を最初から持っている(高さを変えないため場所を確保)',
      optsOf(0).every(b => b.querySelectorAll('.obadge').length === 1 &&
                           b.querySelector('.obadge').textContent === '決めた'));
  chk('★決定表示ブロック(.resolved)は存在しない', cardOf(0).querySelectorAll('.resolved').length === 0);

  click(optsOf(0)[0]);
  chk('★決めても見本は消えない(2枚のまま)', optsOf(0).length === 2);
  chk('★選ばれた見本に「決めた」が付く', chosenOi(0) === 0 && cardState(0) === 'decided');
  click(optsOf(0)[1]);
  chk('★別の見本を押すとその場で選び直せる(reopen を経由しない)',
      S.decisions[0].status === 'decided' && S.decisions[0].oi === 1);
  chk('★出自は human-pick(自分の手で決めた扱い)', S.decisions[0].src === 'human-pick');
  chk('★prev は残さない(往復の1段だけの退避を壊さない)', S.decisions[0].prev === null);
  chk('★「決めた」の印も移る', chosenOi(0) === 1);
  chk('選び直しても未決は増えない', counter() === CT(2), JSON.stringify(counter()));

  vm.runInContext('delegate(1);', ctx);
  chk('★委ねても見本は全部出たまま', optsOf(1).length === 3);
  chk('★委任の表記は足元に1行だけ',
      cardOf(1).querySelector('.fstatus').hidden === false &&
      cardOf(1).querySelector('.fstatus').textContent === '委ねた 制作者(AI)の裁量',
      JSON.stringify(cardOf(1).querySelector('.fstatus').textContent));
  chk('委任では「決めた」の印は誰にも付かない', chosenOi(1) === null);
  click(optsOf(1)[2]);
  chk('★委ねたカードの見本を押せば決定に変わる',
      S.decisions[1].status === 'decided' && S.decisions[1].oi === 2 &&
      S.decisions[1].src === 'human-pick');
  chk('★足元の委任表記は畳まれる', cardOf(1).querySelector('.fstatus').hidden === true);
  chk('★決定済みでも「委ねる」は押せる(2動詞はいつでも効く)', (function(){
    click(cardOf(1).querySelector('.delegate'));
    return S.decisions[1].status === 'delegated' && S.decisions[1].src === 'human-delegate';
  })());

  vm.runInContext('decide(2,0); onTokenClick(2);', ctx);
  chk('★選び直し中は藍の枠だけ残り「決めた」は外れる(決定ではないから)',
      optsOf(2)[0].getAttribute('aria-pressed') === 'true' && chosenOi(2) === null &&
      cardState(2) === 'open' && cardOf(2).classList.contains('editing'));

  chk('見本の行は上端揃え・ラベルは2行ぶんを確保(サムネイルの上端が揃う)',
      /\.card \.opts\{[^}]*align-items:flex-start/.test(html) &&
      /\.olabel\{[^}]*min-height:3\.2em/.test(html));
  chk('選ばれていない見本は減光する',
      html.indexOf('.card[data-state="decided"] .opt:not([data-chosen="1"]),') > 0 &&
      /\.card\[data-state="delegated"\] \.opt\{opacity:\.5\}/.test(html));
  chk('減光は hover / focus で戻る',
      html.indexOf('.card[data-state="delegated"] .opt:focus-visible{opacity:1}') > 0);
  chk('「決めた」の札は場所を確保したまま見えるかどうかだけを切り替える',
      /\.obadge\{[^}]*visibility:hidden/.test(html) &&
      /\.opt\[data-chosen="1"\] \.obadge\{visibility:visible\}/.test(html));
  chk('委任の表記は「委ねる」と同じ行(カードの高さを増やさない)',
      /\.card-foot \.fstatus\{[^}]*margin-right:auto/.test(html));

  /* ================= G) 生活語への置換が画面文言に残っている ================= */
  console.log('\n=== G) 置換後の生活語が画面にあり、旧語が残っていない ===');
  [['指示書にまとめる', 'コンパイル(ボタン)'],
   ['意図の指示書', 'コンパイル済みブリーフ(見出し)'],
   ['compiled brief', '英字併記'],
   ['読む用', '人間可読 MD'],
   ['AIに渡す用', '機械可読 JSON'],
   // 2026-07-30(第7FB 3): 並置比較への口は「次の一歩」の副ボタンへ移し、改称した。
   ['この指示書で作らせた実例を見る', 'この指示書でAIに作らせると?'],
   ['この指示書は完成品ではありません。ここから先は、あなたのAIの仕事です。', '(なし。新設の一文)'],
   ['指示書をコピーしてAIに渡す', '(なし。新設の主ボタン)'],
   ['指示書に戻る', 'ブリーフに戻る'],
   ['生成の代わりに、問いを組み立てています', '静寂コピー主文'],
   // 2026-07-30 トリアージ改訂: 「x1.0」は『誇張のない実測』の記号化だったが記号が
   // 主張を伝えていなかったため、指示書本文・注記も含めて平語へ置換した。
   // 2026-07-30(第6FB): 待機画面からは平語の但し書きごと外した。画面を見れば
   // 分かることを言い足さないため。記録用の注記(指示書本文・#compileNote)は残す。
   ['実測・早送りなし', '指示書本文の記録用注記'],
   ['早送りなしの実測', '#compileNote の記録用注記'],
   ['見本が未着', 'レンダ未着']].forEach(pair => {
    chk('新文言「' + pair[0] + '」が存在する(旧: ' + pair[1] + ')', html.indexOf(pair[0]) > 0);
  });
  ['>コンパイル<', '人間可読 MD', '機械可読 JSON', 'このブリーフで作らせた結果を見る',
   'ブリーフに戻る', 'x1.0 — 生成は、始まらない', 'レンダ未着', 'COMPILED BRIEF',
   // 平語化した以上、記号としての x1.0 は画面にも指示書にも一切残っていないこと
   'x1.0',
   // 第6FB で削った静寂コピーの2要素。画面にも(コメントにも)残っていないこと
   '届くまで、動くのはこの数字だけです', '早送りなしの実時間',
   'いまの依頼文とは別の実例です(その場生成は行いません)',
   // 第7FB で置き換えた旧文言(並置ボタン / 決定表示の案内 / 委任の見本)
   'この指示書でAIに作らせると?', '原文の語をクリックすると選び直せます',
   'この決定をクリックすると選び直せます', 'mini delegated',
   '見本をクリックすると決まる。決めないなら「委ねる」。どちらも、あとで選び直せます。'].forEach(bad => {
    chk('旧文言「' + bad + '」が残っていない', html.indexOf(bad) < 0);
  });
  chk('★静寂コピーは主文1つだけ(但し書きの帯 .s-sub を持たない)',
      /<div id="silenceNote"><span class="s-main">生成の代わりに、問いを組み立てています。<\/span><\/div>/
        .test(html) && html.indexOf('s-sub') < 0);

  console.log(FAILS.length ? '\n--- FAILED: ' + FAILS.join(' / ')
                           : '\n--- 解除でのカウント復元 / コンパイル可否の導出 / 爆散演出 / reduced-motion / 事前生成ラベル / 生活語文言: すべて期待どおり');
  process.exit(FAILS.length ? 1 : 0);
})().catch(e => { console.error('THREW:', e && e.stack || e); process.exit(2); });
