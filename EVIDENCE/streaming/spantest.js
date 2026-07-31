// index.html から buildSpans / claimSpansFor を抜き出して性質検査する。
const fs = require('fs');
const html = fs.readFileSync(require('path').resolve(__dirname,'../..') + '/app/index.html','utf8');
const src = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];

// 対象の2関数だけを切り出す(DOM に触らない純ロジック)
function grab(name){
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('not found: ' + name);
  let d = 0, started = false;
  for (let j = i; j < src.length; j++){
    if (src[j] === '{'){ d++; started = true; }
    else if (src[j] === '}'){ d--; if (started && d === 0) return src.slice(i, j+1); }
  }
  throw new Error('unbalanced: ' + name);
}
const S = {brief:'', branches:[], spans:[], spanTaken:[], decisions:[]};
const MAX_CARDS = 5;
eval(grab('buildSpans'));
eval(grab('claimSpansFor'));

function randBrief(rnd){
  const words = ['モダン','温かみ','LP','うちの会社','高級感','若い人','いい感じ','1周年','ポートフォリオ','センス'];
  let s = '';
  const n = 4 + Math.floor(rnd()*6);
  for (let i=0;i<n;i++) s += words[Math.floor(rnd()*words.length)] + (rnd()<0.4?'の':'を') ;
  return s + 'つくって。';
}
function mulberry(a){return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;}}

let cases=0, zeroSpan=0, mismatch=0;
for (let seed=0; seed<4000; seed++){
  const rnd = mulberry(seed);
  const brief = randBrief(rnd);
  // 原文に実在する部分文字列だけを anchor にする(サーバ検証を通ったものと同じ条件)
  const nb = 1 + Math.floor(rnd()*5);
  const branches = [];
  for (let bi=0; bi<nb; bi++){
    const na = 1 + Math.floor(rnd()*3);
    const anchors = [];
    for (let k=0;k<na;k++){
      const st = Math.floor(rnd()*brief.length);
      const len = 1 + Math.floor(rnd()*8);
      const a = brief.slice(st, Math.min(brief.length, st+len));
      if (a.length) anchors.push(a);
    }
    if (!anchors.length) anchors.push(brief.slice(0,2));
    branches.push({question_point:'q'+bi, anchor_words:anchors,
                   options:[{label:'a'},{label:'b'}], default_if_unresolved:'a'});
  }
  cases++;

  // 逐次(ストリーミング)
  S.brief = brief; S.branches = []; S.spans = []; S.spanTaken = []; S.decisions = [];
  branches.forEach(b => { S.branches.push(b); S.decisions.push({status:null,oi:null}); claimSpansFor(S.branches.length-1); });
  const incr = S.branches.map((_,bi) => S.spans.some(sp => sp.bis.indexOf(bi) >= 0));
  if (incr.some(v => !v)) { zeroSpan++; if (zeroSpan<=3) console.log('ZERO-SPAN seed',seed,JSON.stringify(brief),JSON.stringify(branches.map(b=>b.anchor_words))); }

  // 一括(フォールバック経路)
  const bs = buildSpans(brief, branches);
  const batch = branches.map((_,bi) => bs.some(sp => sp.bis.indexOf(bi) >= 0));
  if (batch.some(v => !v)) mismatch++;

  // スパン同士が重ならないこと(相乗りを除く)
  const sorted = S.spans.slice().sort((a,b)=>a.start-b.start);
  for (let i=1;i<sorted.length;i++) if (sorted[i].start < sorted[i-1].end) throw new Error('overlap seed '+seed);
}
console.log('cases=%d  逐次でスパン0本の分岐が出たケース=%d  一括で0本=%d', cases, zeroSpan, mismatch);
console.log(zeroSpan===0 && mismatch===0 ? 'PASS: どの分岐も必ず1本以上のスパンを持つ(条項2c/5/6の前提)' : 'FAIL');
