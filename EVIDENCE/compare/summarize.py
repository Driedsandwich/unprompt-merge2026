#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事前生成ペアの左右差を機械で要約する(自己評価の材料。判定そのものは人間/担当が行う)。

出す値はすべて HTML ソースから機械的に取れるものに限る:
  - body の背景色 / 本文色(CSS 宣言の最初の一致)
  - 使われている16進色の集合と、左右の共通色数
  - font-family の宣言(serif / sans / rounded 系の判別材料)
  - border-radius の最大値(角の硬さ)
  - 可視テキストの先頭(見出しが何を名乗っているか)と総文字数
  - 可視テキストの 8-gram Jaccard(文面が同じか)

実行: python3 EVIDENCE/compare/summarize.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
COMPARE = ROOT / "app" / "compare"


def visible_text(html):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&[a-zA-Z#0-9]+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def jaccard(a, b, n=8):
    ga = {a[i:i + n] for i in range(max(0, len(a) - n + 1))}
    gb = {b[i:i + n] for i in range(max(0, len(b) - n + 1))}
    if not ga or not gb:
        return None
    return round(len(ga & gb) / len(ga | gb), 4)


def css_vars(html):
    """:root などで定義された CSS 変数を拾う(地色が var(--bg) の形で書かれるため)。"""
    out = {}
    for block in re.findall(r"\{([^}]*)\}", html, re.S):
        for name, val in re.findall(r"(--[\w-]+)\s*:\s*([^;]+)", block):
            out.setdefault(name, val.strip())
    return out


def body_bg(html):
    m = re.search(r"\bbody\s*\{([^}]*)\}", html, re.S | re.I)
    if not m:
        return None
    b = re.search(r"background(?:-color)?\s*:\s*([^;]+)", m.group(1), re.I)
    if not b:
        return None
    val = b.group(1).strip()
    v = css_vars(html)
    for _ in range(3):   # var(--a, var(--b)) の入れ子は浅いので3回で足りる
        m2 = re.search(r"var\((--[\w-]+)[^)]*\)", val)
        if not m2 or m2.group(1) not in v:
            break
        val = val.replace(m2.group(0), v[m2.group(1)])
    return val[:60]


def fonts(html):
    fam = re.findall(r"font-family\s*:\s*([^;}]+)", html, re.I)
    out = []
    for f in fam:
        f = re.sub(r"\s+", " ", f).strip()
        if f not in out:
            out.append(f[:70])
    return out[:4]


def radii(html):
    vals = []
    for v in re.findall(r"border-radius\s*:\s*([0-9.]+)(px|rem|em|%)", html, re.I):
        n = float(v[0])
        vals.append(n * 16 if v[1] in ("rem", "em") else n)
    return {"max_px_like": max(vals) if vals else 0, "count": len(vals)}


def summarize(path):
    html = path.read_text(encoding="utf-8")
    vt = visible_text(html)
    hexes = [h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}\b", html)]
    return {
        "bytes": len(html.encode("utf-8")),
        "lines": html.count("\n") + 1,
        "body_bg": body_bg(html),
        "hex_unique": sorted(set(hexes)),
        "fonts": fonts(html),
        "radius": radii(html),
        "text_chars": len(vt),
        "text_head": vt[:110],
        "_vt": vt,
    }


def main():
    mp = COMPARE / "manifest.json"
    if not mp.exists():
        print("manifest.json が無い", file=sys.stderr)
        return 2
    m = json.loads(mp.read_text(encoding="utf-8"))
    for p in m["pairs"]:
        r = summarize(COMPARE / p["outputs"]["raw"])
        c = summarize(COMPARE / p["outputs"]["compiled"])
        shared = sorted(set(r["hex_unique"]) & set(c["hex_unique"]))
        print("=" * 78)
        print("%s (%s) — %s" % (p["brief_id"], p["deliverable_kind"], p["deliverable"]))
        print("  依頼文: %s" % p["brief"])
        print("  決定  : %s" % " / ".join(d["chosen_label"] for d in p["decisions"]))
        print("  照合  : %d/%d" % (p["verification"]["compiled"]["traced"],
                                   p["verification"]["compiled"]["of"]))
        print("  -- 左(一文だけ) --")
        print("     地色 %s / 色 %d種 / 角 max %.0f / 書体 %s"
              % (r["body_bg"], len(r["hex_unique"]), r["radius"]["max_px_like"], r["fonts"][:2]))
        print("     %d字: %s" % (r["text_chars"], r["text_head"]))
        print("  -- 右(指示書) --")
        print("     地色 %s / 色 %d種 / 角 max %.0f / 書体 %s"
              % (c["body_bg"], len(c["hex_unique"]), c["radius"]["max_px_like"], c["fonts"][:2]))
        print("     %d字: %s" % (c["text_chars"], c["text_head"]))
        print("  -- 差 --")
        print("     共通色 %d種 %s / 文面 8-gram Jaccard %s / 文字数比 %.2f"
              % (len(shared), shared[:6], jaccard(r["_vt"], c["_vt"]),
                 (c["text_chars"] / r["text_chars"]) if r["text_chars"] else 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
