#!/usr/bin/env node
/* 2026-07-30 第8FB: 引出線の「平行重なり」解消(planTethers)を境界値で押さえる。
   線が重なって1本に見えると「意味が重複している」と誤読されるため、
   (1) 同じカードへ入る垂線は入口 x を8px以上離す
   (2) x範囲が重なる水平の棚は高さを4px以上離す
   を純関数 planTethers が保証する。DOMシムは使わない(関数だけを抜いて叩く)。
   使い方: node EVIDENCE/streaming/domtest10.js */
'use strict';
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'index.html'), 'utf8');
const m = html.match(/function planTethers\(items\)\{[\s\S]*?\n\}/);
if (!m){ console.log('NG   planTethers が index.html に見つからない'); process.exit(1); }
const planTethers = new Function('return ' + m[0])();

let OK = 0, NG = 0;
function chk(label, cond, extra){
  if (cond){ OK++; console.log('OK   ' + label); }
  else { NG++; console.log('NG   ' + label + (extra ? '  ' + extra : '')); }
}
function item(o){
  return Object.assign({ x1: 0, y1: 100, x2: 0, y2: 400, xMin: 0, xMax: 800,
                         bi: 0, ord: 0, spStart: 0, firstOfSp: true }, o);
}

console.log('=== 1) 同一カードへの入口レーン ===');
{
  // 2語(x1=300,304)が同じカード(bi=0)へ。素の x2 はどちらも 302 に潰れる想定
  const out = planTethers([
    item({ ord: 0, spStart: 10, x1: 300, x2: 302, bi: 0, xMin: 260, xMax: 700 }),
    item({ ord: 1, spStart: 40, x1: 304, x2: 302, bi: 0, xMin: 260, xMax: 700 }),
  ]);
  const xs = out.map(p => p.x2).sort((a, b) => a - b);
  chk('★入口が8px以上離れる', xs[1] - xs[0] >= 8, JSON.stringify(xs));
  const left = out.find(p => p.spStart === 10), right = out.find(p => p.spStart === 40);
  chk('★左の語ほど左の口(順序は座標で決まる)', left.x2 < right.x2);
}
{
  // 3本が同じ口に潰れても全て離れる
  const out = planTethers([0, 1, 2].map(i =>
    item({ ord: i, spStart: i * 7, x1: 400 + i * 2, x2: 401, bi: 2, xMin: 380, xMax: 820 })));
  const xs = out.map(p => p.x2).sort((a, b) => a - b);
  chk('★3本でも隣接ペアが全て8px以上', (xs[1] - xs[0] >= 8) && (xs[2] - xs[1] >= 8), JSON.stringify(xs));
  chk('★xMax を超えない', xs[2] <= 820);
}
{
  // 別カードなら触らない
  const out = planTethers([
    item({ ord: 0, x1: 300, x2: 302, bi: 0 }),
    item({ ord: 1, x1: 304, x2: 302, bi: 1 }),
  ]);
  chk('★別カードの入口は動かさない', out.every(p => p.x2 === 302));
}

console.log('\n=== 2) 棚の高さレーン ===');
{
  // 同じ行(y1=100)から左右のカードへ。x範囲が重なる2本の棚が同じ高さに来る想定
  const a = item({ ord: 0, x1: 300, x2: 500, bi: 0 });   // 棚 y=124(knee=24)
  const b = item({ ord: 1, x1: 350, x2: 550, bi: 1 });   // 素なら同じく y=124
  const out = planTethers([a, b]);
  const ya = out.find(p => p.ord === 0).shelfY, yb = out.find(p => p.ord === 1).shelfY;
  chk('★重なる棚は4px以上離れる', Math.abs(ya - yb) >= 4, ya + ' / ' + yb);
  chk('★先に引かれた線が元の高さを取る', ya === 124, String(ya));
}
{
  // x範囲が重ならなければ同じ高さでよい(離す理由がない)
  const out = planTethers([
    item({ ord: 0, x1: 100, x2: 200, bi: 0 }),
    item({ ord: 1, x1: 500, x2: 600, bi: 1 }),
  ]);
  chk('★離れた棚は同じ高さのまま', out[0].shelfY === out[1].shelfY);
}
{
  // 棚はカード上辺より6px以上手前で止まる(押し下げすぎない)
  const items = [];
  for (let i = 0; i < 12; i++){
    items.push(item({ ord: i, spStart: i, x1: 300 + i, x2: 500 + i, bi: i, y2: 190 }));
  }
  const out = planTethers(items);
  chk('★連鎖しても棚が y2-6 を超えない', out.every(p => p.shelfY <= 190 - 6));
}

console.log('\n=== 3) 直落としと決定論 ===');
{
  const out = planTethers([item({ ord: 0, x1: 400, x2: 403 })]);
  chk('★|dx|<8 は棚を持たない(shelfY=null)', out[0].shelfY === null);
}
{
  const src = [
    item({ ord: 0, spStart: 3, x1: 300, x2: 302, bi: 0 }),
    item({ ord: 1, spStart: 9, x1: 304, x2: 302, bi: 0 }),
    item({ ord: 2, spStart: 5, x1: 350, x2: 550, bi: 1 }),
  ];
  const o1 = JSON.stringify(planTethers(src.map(x => Object.assign({}, x))));
  const o2 = JSON.stringify(planTethers(src.map(x => Object.assign({}, x))));
  chk('★同じ入力なら同じ出力(乱数・時刻を使わない)', o1 === o2);
}
{
  // 入力オブジェクトを破壊しない(drawTethers 側の再利用を壊さない)
  const src = item({ ord: 0, x1: 300, x2: 500, bi: 0 });
  planTethers([src]);
  chk('★入力の x2 を書き換えない(コピーに対して計画する)', src.x2 === 500 && !('shelfY' in src));
}

console.log('\n--- 引出線の経路計画: ' + (NG === 0 ? 'すべて期待どおり' : NG + '件の失敗'));
process.exit(NG === 0 ? 0 : 1);
