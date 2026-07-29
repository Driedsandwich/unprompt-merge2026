// 並置比較の5パターン化(app/index.html の比較部)を機械で押さえる。
// DOM シムは EVIDENCE/streaming/domtest5.js と同型(document.querySelectorAll を追加した。
// 直前コミット a176481 で index.html が document.querySelectorAll('.ex-chip') を
// 呼ぶようになり、旧シムでは script の評価自体が落ちるため)。
//
//   A) セッションの依頼文と一致するペアが manifest にあれば、そのペアを表示する
//      (5本すべて / iframe src・常設ラベル・不一致注記を確認)
//   B) 一致しない依頼文なら既定ペア(lp-warm)へ落ち、不一致注記が出る
//   C) 常設ラベルには「いま表示しているペアの依頼文」が常に入る(不一致時も)
//   D) manifest が読めないときは既定ペアのパスへフォールバックする
//   E) 比較画面を開くまで iframe の src は空(1バイトも読まない)
//   F) 注記はそのペア自身の verification / timings から作る
const fs = require('fs');
const PATH = '/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon/app/index.html';
const html = fs.readFileSync(PATH, 'utf8');
const script = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const ids = [...new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]))];

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
  scrollTo: () => {}
};
let rafQ = [];
const requestAnimationFrame = fn => { rafQ.push(fn); return rafQ.length; };
const cancelAnimationFrame = () => {};
const performance = {now: () => Date.now()};
const navigator = {clipboard: {writeText: async () => {}}};
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ---------- 事前生成 manifest のスタブ(実ファイルと同じ形) ---------- */
const PAIRS = [
  ['lp-warm',    'モダンだけど温かみのあるLPを作って。うちの会社のやつ。'],
  ['event-page', '来月やる交流イベントの告知ページを作ってほしい。若い人にも刺さる感じで、申込みが増えるように。'],
  ['portfolio',  '転職活動用に個人ポートフォリオサイトが欲しい。作品はいくつかあるんだけど、センスよくまとめて。'],
  ['scout-mail', 'エンジニアに送るスカウトメールの文面をお願い。うちっぽさが伝わって、返信したくなるやつ。'],
  ['ec-product', 'ネットショップに載せるタンブラーの商品説明文を書いて。ちゃんと良さが伝わって、ポチりたくなるように。'],
];
const MANIFEST = {
  format: 'gyakumon.split_compare.v1',
  pregenerated: true,
  engine: {model: 'sonnet', effort: 'low'},
  default_pair: 'lp-warm',
  pair_ids: PAIRS.map(p => p[0]),
  pairs: PAIRS.map(([id, brief], i) => ({
    brief_id: id, brief: brief,
    generated_at: '2026-07-30T00:0' + i + ':00+00:00',
    outputs: {raw: id + '/raw.html', compiled: id + '/compiled.html'},
    decisions: [], timings: {raw: {api_ms: 20000 + i}, compiled: {api_ms: 40000 + i}},
    verification: {compiled: {traced: 4 + i, of: 4 + i}},
  })),
};
let MANIFEST_OK = true;
async function fetchStub(url){
  if (url === 'compare/manifest.json'){
    if (!MANIFEST_OK) return {ok: false, json: async () => ({})};
    return {ok: true, json: async () => JSON.parse(JSON.stringify(MANIFEST))};
  }
  if (url === '/api/health') return {ok: true, json: async () => ({ok: true})};
  return {ok: false, json: async () => ({ok: false})};
}

const vm = require('vm');
const FAILS = [];
const chk = (n, c, e) => { console.log((c ? 'OK   ' : 'FAIL ') + n + (e ? '  ' + e : '')); if (!c) FAILS.push(n); };

function fresh(){
  Object.keys(registry).forEach(k => delete registry[k]);
  Object.keys(docHandlers).forEach(k => delete docHandlers[k]);
  Object.keys(winHandlers).forEach(k => delete winHandlers[k]);
  ids.forEach(id => {
    registry[id] = new El('div'); registry[id].id = id;
    const tag = html.match(new RegExp('<[a-z]+[^>]*\\bid="' + id + '"[^>]*>', 'i'));
    if (tag && /\shidden(\s|>|=)/.test(tag[0])) registry[id].hidden = true;
  });
  // 静的マークアップの初期テキスト(常設ラベル)を再現する
  const fx = html.match(/<p id="compareFixture">([^<]*)<\/p>/);
  if (fx) registry['compareFixture']._text = fx[1];
  rafQ = [];
  const ctx = {document, window, requestAnimationFrame, cancelAnimationFrame, performance, navigator,
    fetch: fetchStub, setTimeout, clearTimeout, setInterval, clearInterval,
    console, JSON, Math, Date, Promise, Array, Object, String, Number, Boolean, Set, Map,
    parseInt, parseFloat, isNaN, AbortController};
  vm.createContext(ctx);
  vm.runInContext(script + '\n;globalThis.__S=S;', ctx);
  return ctx;
}

async function openCompare(ctx, brief){
  ctx.__S.brief = brief;
  const hs = registry['btnCompare'].handlers['click'] || [];
  hs.forEach(fn => fn({}));
  for (let i = 0; i < 60; i++){ await sleep(5); if (registry['frameRaw'].src) break; }
  await sleep(10);
  return {
    raw: registry['frameRaw'].src, compiled: registry['frameCompiled'].src,
    label: registry['compareFixture'].textContent,
    mismatchHidden: registry['compareMismatch'].hidden,
    note: registry['compareNote'].textContent,
    screenShown: registry['screenCompare'].hidden === false,
  };
}

(async () => {
  /* A) 5本それぞれで、依頼文に一致するペアが出る */
  for (const [id, brief] of PAIRS){
    const ctx = fresh();
    chk('[' + id + '] 開く前は iframe が空', registry['frameRaw'].src === undefined ||
        registry['frameRaw'].src === '' || registry['frameRaw'].src === null);
    const r = await openCompare(ctx, brief);
    chk('[' + id + '] 一致ペアの raw が入る', r.raw === 'compare/' + id + '/raw.html', r.raw);
    chk('[' + id + '] 一致ペアの compiled が入る', r.compiled === 'compare/' + id + '/compiled.html', r.compiled);
    chk('[' + id + '] 不一致注記は出ない', r.mismatchHidden === true);
    chk('[' + id + '] ラベルにその依頼文が入る', r.label === '事前生成の実例 — 依頼文「' + brief + '」による', r.label);
    chk('[' + id + '] 比較画面が開く', r.screenShown === true);
  }

  /* B/C) 一致なし → 既定ペア + 不一致注記。ラベルは表示中(既定)ペアの依頼文 */
  {
    const ctx = fresh();
    const r = await openCompare(ctx, 'ぜんぜん別の依頼文。カレー屋のメニューを作って。');
    chk('[不一致] 既定ペア(lp-warm)へ落ちる', r.raw === 'compare/lp-warm/raw.html', r.raw);
    chk('[不一致] 不一致注記が出る', r.mismatchHidden === false);
    chk('[不一致] ラベルは表示中ペア(lp-warm)の依頼文', r.label === '事前生成の実例 — 依頼文「' + PAIRS[0][1] + '」による', r.label);
    chk('[不一致] ラベルにセッションの依頼文は入らない', r.label.indexOf('カレー屋') < 0);
  }

  /* D) manifest が読めない → 既定ペアのパスへフォールバック */
  {
    MANIFEST_OK = false;
    const ctx = fresh();
    const r = await openCompare(ctx, PAIRS[3][1]);   // scout-mail の依頼文でも
    chk('[manifest不能] フォールバックは lp-warm', r.raw === 'compare/lp-warm/raw.html', r.raw);
    chk('[manifest不能] compiled も lp-warm', r.compiled === 'compare/lp-warm/compiled.html', r.compiled);
    chk('[manifest不能] 不一致注記が出る', r.mismatchHidden === false);
    chk('[manifest不能] ラベルは lp-warm の依頼文', r.label.indexOf(PAIRS[0][1]) >= 0, r.label);
    chk('[manifest不能] 注記は同一条件の断りを残す', r.note.indexOf('同一モデル') >= 0, r.note);
    MANIFEST_OK = true;
  }

  /* F) 注記はそのペア自身の数値から作る */
  {
    const ctx = fresh();
    const r = await openCompare(ctx, PAIRS[2][1]);   // portfolio: traced 6/6, api 20002 / 40002
    chk('[注記] モデルと effort', r.note.indexOf('sonnet') >= 0 && r.note.indexOf('low') >= 0, r.note);
    chk('[注記] そのペアの照合数', r.note.indexOf('6/6') >= 0, r.note);
    chk('[注記] そのペアの api 実時間', r.note.indexOf('20.0秒') >= 0 && r.note.indexOf('40.0秒') >= 0, r.note);
    chk('[注記] そのペアの生成時刻', r.note.indexOf('2026-07-30T00:02') >= 0, r.note);
  }

  /* 実ファイルとの突き合わせ: manifest.json の5ペアが実在し、依頼文がチップと一致するか */
  {
    const root = PATH.replace(/\/app\/index\.html$/, '');
    const mp = root + '/app/compare/manifest.json';
    if (fs.existsSync(mp)){
      const m = JSON.parse(fs.readFileSync(mp, 'utf8'));
      chk('[実体] manifest に5ペア', Array.isArray(m.pairs) && m.pairs.length === 5,
          m.pairs ? String(m.pairs.length) : 'none');
      const chips = [...html.matchAll(/class="ex-chip" data-example="([^"]+)"/g)].map(x => x[1]);
      chk('[実体] 例文チップが5件', chips.length === 5, String(chips.length));
      chips.forEach((c) => {
        chk('[実体] チップの依頼文にペアが対応: ' + c.slice(0, 12) + '…',
            (m.pairs || []).some(p => p.brief === c));
      });
      (m.pairs || []).forEach(p => {
        chk('[実体] ' + p.brief_id + ' の raw.html が実在',
            fs.existsSync(root + '/app/compare/' + p.outputs.raw));
        chk('[実体] ' + p.brief_id + ' の compiled.html が実在',
            fs.existsSync(root + '/app/compare/' + p.outputs.compiled));
      });
    } else {
      chk('[実体] manifest.json が無い(事前生成が未実行)', false);
    }
  }

  console.log('\n' + (FAILS.length ? 'FAIL ' + FAILS.length + ' 件' : '全項目 PASS'));
  process.exit(FAILS.length ? 1 : 0);
})();
