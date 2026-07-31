// 指示書画面(f)の「読む用 / AIに渡す用」を機械で押さえる(domtest6.js と同型の最小 DOM シム)。
// 2026-07-30 第6FB: 「読む用」を MD 原文の素見せから整形描画へ変えた。
//
//   0) 整形描画の様式が CSS にある(見出しの階層・引用の左罫・記号は鼠・角丸ゼロ・朱と藍を使わない)
//   1) 「読む用」は h1/h2/h3・blockquote・ul/li・hr の要素として組まれる(MD 記法を画面に出さない)
//   2) 「コピー」が渡すのは MD 原文そのまま(整形描画の見た目に依らない)
//   3) 「AIに渡す用」は JSON 原文のまま(reading を外し、断りが出る)。コピーも JSON 原文
//   4) タブを往復しても原文は変わらない / 同じ MD からは常に同じ DOM(決定論)
//   5) 表題欄の統計の文言が指示書本文の限定と矛盾しない
const fs = require('fs');
const PATH = require('path').resolve(__dirname,'../..') + '/app/index.html';
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
let COPIED = null;
const navigator = {clipboard: {writeText: async t => { COPIED = t; }}};
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
    '\n;globalThis.__decide=decide; globalThis.__compile=compile;' +
    '\n;globalThis.__md=buildMarkdown; globalThis.__json=buildJSON;' +
    '\n;globalThis.__renderReading=renderReading;', ctx);
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
const kids = (el) => el.children.map(c => c.tagName);
// DOM の形を1本の文字列にする(決定論の照合用)
const shape = (el) => el.children.map(c =>
  c.tagName + '[' + (c.className || '') + ']{' + c.textContent + '}' +
  (c.children.length ? '(' + shape(c) + ')' : '')).join('|');

(async () => {
  /* ================= 0) 整形描画の様式 ================= */
  console.log('=== 0) 「読む用」の様式(CSS) ===');
  // 切り出す範囲は「読む用」の規則だけ。2026-07-30(第7FB 3)で本文の直下に
  // 「次の一歩」(#nextStep。主ボタンだけが藍を地に使う)が入ったので、終端はそこにする。
  const readCss = (() => {
    const i0 = html.indexOf('#out.reading{');
    const i1 = html.indexOf('#nextStep{');
    return (i0 < 0 || i1 < i0) ? '' : html.slice(i0, i1);
  })();
  chk('#out.reading の規則がある', readCss.length > 400, 'css=' + readCss.length + '字');
  chk('★MD 記法を出さないための整形指定(pre-wrap をやめて normal にする)',
      /#out\.reading\{[^}]*white-space:normal/.test(readCss));
  chk('★見出しは3階層すべて様式を持つ',
      /#out\.reading h1\{/.test(readCss) && /#out\.reading h2\{/.test(readCss) &&
      /#out\.reading h3\{/.test(readCss));
  chk('★見出しの階層は寸法と罫で示す(h1=太い罫 / h2=細い罫 / h3=左罫)',
      /#out\.reading h1\{[^}]*border-bottom:1px solid var\(--ink\)/.test(readCss) &&
      /#out\.reading h2\{[^}]*border-bottom:1px solid var\(--line\)/.test(readCss) &&
      /#out\.reading h3\{[^}]*border-left:2px solid var\(--line\)/.test(readCss));
  chk('★引用は左罫の枠・明朝(原文と同じ声で読ませる)',
      /#out\.reading blockquote\{[^}]*border-left:2px solid var\(--ink-soft\)/.test(readCss) &&
      /#out\.reading blockquote\{[^}]*font-family:var\(--mincho\)/.test(readCss));
  chk('★リストの記号は鼠(list-style は使わず ::before で置く)',
      /#out\.reading ul\{[^}]*list-style:none/.test(readCss) &&
      /#out\.reading li::before\{[^}]*color:var\(--muted\)/.test(readCss));
  chk('★項目名は鼠・値は墨', /#out\.reading li \.k\{[^}]*color:var\(--muted\)/.test(readCss) &&
      /#out\.reading li \.v\{[^}]*color:var\(--ink\)/.test(readCss));
  chk('角丸ゼロ(引用の枠も)', /#out\.reading blockquote\{[^}]*border-radius:0/.test(readCss));
  chk('★状態の3色のうち朱と藍は使わない(この画面は判断の状態を語らない)',
      !/var\(--shu/.test(readCss) && !/var\(--ai/.test(readCss));

  console.log('\n=== 0b) 表題欄の統計の文言 ===');
  chk('★ヘッダは「最初の一文のあと、タイプした文字」',
      /<div class="item">最初の一文のあと、タイプした文字<b id="numTyped">0<\/b><\/div>/.test(html));
  chk('旧文言「あなたがタイプした文字<b」が残っていない',
      html.indexOf('あなたがタイプした文字<b') < 0);
  chk('指示書本文側の限定と矛盾しない(本文は「(最初の一文以降)」のまま)',
      html.indexOf("'- あなたがタイプした文字(最初の一文以降): '") > 0);

  /* ================= 1) 読む用 = 整形描画 ================= */
  console.log('\n=== 1) 「読む用」は要素として組まれる ===');
  const ctx = await runToDone();
  ctx.__S.decisions.forEach((_, bi) => ctx.__delegate(bi));   // 未決0にする
  ctx.__decide(1, 0);                                        // 1件は「決める」(両方の節を出す)
  flushRAF(4);
  await ctx.__compile();
  flushRAF(4);
  const box = registry['out'];
  const md = ctx.__md();
  chk('前提: コンパイル画面が出ている', registry['screenCompiled'].hidden === false);
  chk('★#out に reading が付く', box.classList.contains('reading'));
  chk('★h1 が要素として出ている(記法「# 」ではない)',
      kids(box).indexOf('H1') >= 0, JSON.stringify(kids(box)));
  chk('★h2 の数が MD の「## 」の行数と一致する',
      kids(box).filter(t => t === 'H2').length === (md.match(/^## /gm) || []).length,
      kids(box).filter(t => t === 'H2').length + ' vs ' + (md.match(/^## /gm) || []).length);
  chk('★h3 の数が MD の「### 」の行数と一致する',
      kids(box).filter(t => t === 'H3').length === (md.match(/^### /gm) || []).length);
  chk('★引用は blockquote 要素', kids(box).indexOf('BLOCKQUOTE') >= 0);
  chk('★箇条書きは ul/li 要素',
      kids(box).indexOf('UL') >= 0 &&
      box.children.filter(c => c.tagName === 'UL').every(u => u.children.every(li => li.tagName === 'LI')));
  chk('★li の総数が MD の「- 」の行数と一致する',
      box.children.filter(c => c.tagName === 'UL').reduce((a, u) => a + u.children.length, 0)
        === (md.match(/^- /gm) || []).length);
  chk('★水平罫は hr 要素(「---」を文字で出さない)', kids(box).indexOf('HR') >= 0);
  chk('★画面の文字列に MD の記法が残っていない',
      box.children.every(c => !/^(#|-\s|>\s|---)/.test(c.textContent)) &&
      box.textContent.indexOf('# ') < 0 && box.textContent.indexOf('> ') < 0,
      JSON.stringify(box.children.map(c => c.textContent.slice(0, 12))));
  chk('★引用の中身は依頼文そのもの',
      box.children.find(c => c.tagName === 'BLOCKQUOTE').textContent === BRIEF,
      JSON.stringify(box.children.find(c => c.tagName === 'BLOCKQUOTE').textContent));
  chk('★「項目名: 値」は k / v に分かれる(項目名だけを鼠にできる)', (() => {
    const li = box.children.filter(c => c.tagName === 'UL')
                  .flatMap(u => u.children)
                  .find(x => x.children.length === 2);
    return !!li && li.children[0].className === 'k' && li.children[1].className === 'v' &&
           li.children[0].textContent.indexOf(':') < 0;
  })());
  chk('見出しの文字列は MD の見出しと一致する',
      box.children.filter(c => c.tagName === 'H2').map(c => c.textContent).join('/')
        === (md.match(/^## (.*)$/gm) || []).map(s => s.slice(3)).join('/'),
      JSON.stringify(box.children.filter(c => c.tagName === 'H2').map(c => c.textContent)));

  /* ================= 2) コピーは MD 原文のまま ================= */
  console.log('\n=== 2) コピーされるのは MD 原文 ===');
  COPIED = null;
  click(registry['btnCopy']);
  await sleep(10);
  chk('★コピーは MD 原文そのまま(整形描画の見た目ではない)', COPIED === md,
      COPIED === null ? 'null' : ('先頭: ' + JSON.stringify(String(COPIED).slice(0, 24))));
  chk('★MD 原文は記法を保っている(コピー先で読める形)',
      COPIED.indexOf('# 意図の指示書 (compiled brief)') === 0 &&
      COPIED.indexOf('\n> ') > 0 && COPIED.indexOf('\n- ') > 0 && COPIED.indexOf('\n## ') > 0);

  /* ================= 3) AIに渡す用 = JSON 原文 ================= */
  console.log('\n=== 3) 「AIに渡す用」は原文のまま ===');
  click(registry['tabJson']);
  flushRAF(2);
  // compiled_at は呼ぶたびに now を入れるので、そこだけ外して形で照合する
  // (「表示とコピーが同一の1本の原文である」ことは文字列の一致で別に押さえる)。
  const noTime = (t) => { const o = JSON.parse(t); delete o.compiled_at; return JSON.stringify(o); };
  const js = ctx.__json();
  chk('★reading は外れる', box.classList.contains('reading') === false);
  chk('★中身は JSON 原文そのまま(整形しない)', noTime(box.textContent) === noTime(js));
  chk('★整形描画の要素を持たない(子要素なし)', box.children.length === 0);
  chk('断りが出る', registry['jsonNote'].hidden === false);
  COPIED = null;
  click(registry['btnCopy']);
  await sleep(10);
  chk('★コピーは画面に出ている JSON 原文と同一の1本', COPIED === box.textContent);
  chk('★コピーは JSON 原文の形', noTime(COPIED) === noTime(js));
  chk('JSON として読める', (() => { try { JSON.parse(COPIED); return true; } catch(e){ return false; } })());

  /* ================= 4) 往復と決定論 ================= */
  console.log('\n=== 4) タブを往復しても原文は変わらない / 決定論 ===');
  click(registry['tabMd']);
  flushRAF(2);
  chk('★読む用に戻ると整形描画に戻る',
      box.classList.contains('reading') && kids(box).indexOf('H1') >= 0);
  chk('★MD 原文は往復で1文字も変わらない', ctx.__md() === md);
  chk('断りは引っ込む', registry['jsonNote'].hidden === true);
  COPIED = null;
  click(registry['btnCopy']);
  await sleep(10);
  chk('★往復後もコピーは MD 原文', COPIED === md);
  const shot = shape(box);
  const probe = document.createElement('div');
  ctx.__renderReading(probe, md);
  chk('★同じ MD からは常に同じ DOM(決定論)', shape(probe) === shot,
      'len ' + shape(probe).length + ' vs ' + shot.length);
  const probe2 = document.createElement('div');
  ctx.__renderReading(probe2, md);
  ctx.__renderReading(probe2, md);            // 2度組んでも積み重ならない
  chk('★組み直しても積み重ならない(毎回まっさらから組む)', shape(probe2) === shot);

  /* ================= 5) 次の一歩(2026-07-30 第7FB 3、第8FB 2でJSONへ) ============
     「これで完成?」で手が止まる人への答え。本文の直下・フッタ注記の上に
     一文 + 主ボタン(コピーして渡す) + 副ボタン(実例を見る)を置く。
     主ボタンが渡すのは「AIに渡す用」タブと同一の JSON 原文である(渡す物は1本。
     ボタンの動詞「AIに渡す」とタブ「AIに渡す用」を画面の語彙で一致させる)。 */
  console.log('\n=== 5) 次の一歩(指示書は完成品ではない) ===');
  chk('★静的マークアップの順序は 本文 → 次の一歩 → フッタ注記',
      html.indexOf('<div id="out"></div>') < html.indexOf('<div id="nextStep">') &&
      html.indexOf('<div id="nextStep">') < html.indexOf('<div id="compileNote"></div>'));
  chk('★一文が承認どおり',
      html.indexOf('<p id="nextStepLead">この指示書は完成品ではありません。ここから先は、あなたのAIの仕事です。</p>') > 0);
  chk('★主ボタンの文言', /<button id="btnHandoff" type="button">指示書をコピーしてAIに渡す<\/button>/.test(html));
  chk('★主ボタンだけが藍を地に使う(指示書にまとめるボタンと同じ格)',
      /#btnHandoff\{[^}]*background:var\(--ai-strong\)[^}]*color:var\(--ai-strong-ink\)/.test(html));
  chk('★副ボタンは並置比較への同じ経路(改称・移設。重複させない)',
      /<button id="btnCompare" type="button">この指示書で作らせた実例を見る<\/button>/.test(html) &&
      (html.match(/id="btnCompare"/g) || []).length === 1 &&
      html.indexOf('<div id="nextStep">') < html.indexOf('id="btnCompare"') &&
      html.indexOf('id="btnCompare"') < html.indexOf('<div id="compileNote"></div>'));
  chk('★方眼の上に浮くボタン・タブは地を紙で塞ぐ',
      /\.seg\{[^}]*background:var\(--paper\)/.test(html) &&
      /#btnCopy\{[^}]*background:var\(--paper\)/.test(html) &&
      /#btnCompare\{[^}]*background:var\(--paper\)/.test(html) &&
      /#btnRestart\{[^}]*background:var\(--paper\)/.test(html) &&
      /#btnCompareBack\{[^}]*background:var\(--paper\)/.test(html));
  chk('★藍地のボタンもホバーで地を透かさない(罫が文字の下を走らない)',
      /#btnCompile:hover:not\(:disabled\)\{background:var\(--paper\)/.test(html) &&
      /#btnHandoff:hover\{background:var\(--paper\)/.test(html));
  // 押す前は注記が無く、押すとコピーと注記が同時に出る
  click(registry['tabMd']);
  flushRAF(2);
  chk('前提: 読む用に戻っている・注記は出ていない', registry['handoffNote'].hidden === true);
  COPIED = null;
  click(registry['btnHandoff']);
  await sleep(10);
  chk('★渡すのは「AIに渡す用」と同一の JSON 原文(バイト同一)', COPIED === ctx.__json(),
      COPIED === null ? 'null' : ('先頭: ' + JSON.stringify(String(COPIED).slice(0, 24))));
  chk('★MD 原文とは別物(タブのコピーとの役割分担が機能している)', COPIED !== md);
  chk('★成功の注記が承認どおり',
      registry['handoffNote'].hidden === false &&
      registry['handoffNote'].textContent ===
        'コピーしました。ChatGPT・Claude・Gemini など、いつものAIに貼り付けてください。',
      JSON.stringify(registry['handoffNote'].textContent));
  chk('★注記は静かな色ではない(成功はただの事実)',
      registry['handoffNote'].classList.contains('quiet') === false);
  // 「AIに渡す用」を開いていても渡すのは MD(貼り付け先は対話のAIである)
  click(registry['tabJson']);
  flushRAF(2);
  chk('★タブを切り替えると注記は畳まれる(次の操作まで残す作法)',
      registry['handoffNote'].hidden === true && registry['handoffNote'].textContent === '');
  COPIED = null;
  click(registry['btnHandoff']);
  await sleep(10);
  chk('★AIに渡す用タブでも主ボタンが渡すのは同じ JSON 原文(タブに依らず1本)', COPIED === ctx.__json());
  COPIED = null;
  click(registry['btnCopy']);
  await sleep(10);
  chk('★同じ画面で「コピー」は JSON 原文を渡す(役割が違う2つが共存する)',
      COPIED !== md && noTime(COPIED) === noTime(ctx.__json()));

  console.log(FAILS.length ? '\n--- FAILED: ' + FAILS.join(' / ')
                           : '\n--- 読む用の整形描画 / コピーは原文 / AIに渡す用は原文 / 決定論 / 次の一歩: すべて期待どおり');
  process.exit(FAILS.length ? 1 : 0);
})().catch(e => { console.error('THREW:', e && e.stack || e); process.exit(2); });
