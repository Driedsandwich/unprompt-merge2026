#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""U1: 均一性試験 (PREREGISTRATION.md 追補9)

288生成 (12ブリーフ×2条件×[flash/glm×5反復 + kimi-k2.7-code/kimi-k3×1]) を
AiandRunner (engine_neutral_v1) + pg.gen_deliverable (既存の生成規則そのまま) で行い、
機械指標 (構造CV・判断点マーカー保存率・トークン遵守・禁則出現) を測る。

工程: --generate (再開安全) / --metrics
出力: engine_uniformity/gen/<model>/<bid>/<cond>_r<n>.html・u1_metrics.json・costs_u1.jsonl
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import pregen_compare as pg  # noqa: E402
from effect_measure import SPECS  # noqa: E402
from measure_v4_build import BRIEFS12, IDS, SESS  # noqa: E402
import engine_neutral_v1 as en  # noqa: E402

OUT = HERE / "engine_uniformity"
GEN = OUT / "gen"
COSTS = OUT / "costs_u1.jsonl"
REP_MODELS = {"deepseek-ai/deepseek-v4-flash": 5, "zai-org/glm-5.2": 5}
VER_MODELS = {"moonshotai/kimi-k2.7-code": 1, "moonshotai/kimi-k3": 1}


def gen_all(only=None):
    en.COSTS = COSTS  # 実費記録をU1側のファイルへ束ねる
    runner = en.AiandRunner()
    plan = {**REP_MODELS, **VER_MODELS}
    if only:
        plan = {m: r for m, r in plan.items() if m.split("/")[-1] in only}
    for model, reps in plan.items():
        short = model.split("/")[-1]
        for bid in IDS:
            brief = BRIEFS12[bid]
            handoff = (SESS / bid / "handoff_v4.json").read_text(encoding="utf-8").strip()
            raw_sys, compiled_sys = pg.build_maker_system(SPECS[bid])
            for cond, system, user in (("raw", raw_sys, brief),
                                       ("compiled", compiled_sys, handoff)):
                for r in range(1, reps + 1):
                    p = GEN / short / bid / f"{cond}_r{r}.html"
                    if p.exists():
                        continue
                    p.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        html, rec = pg.gen_deliverable(runner, system, user, model)
                    except Exception as e:
                        print(f"  [{short} {bid} {cond} r{r}] 失敗: {e} — スキップ(再実行可)")
                        continue
                    p.write_text(html, encoding="utf-8")
                    print(f"  [{short} {bid} {cond} r{r}] {len(html)}B")


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
YEARS_RE = re.compile(r"[一二三四五六七八九十0-9]+年(ぶり|目|以上)|創業[一二三四五六七八九十0-9]+年")
MARKER_RE = re.compile(r"GYAKUMON-CHOICE:\s*([^=]+?)\s*=")


def strip_tags(html):
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", re.sub(r"<(style|script)[\s\S]*?</\1>", "", html)))


def struct_of(html):
    return {"headings": len(re.findall(r"<h[1-6][\s>]", html)),
            "sections": len(re.findall(r"<section[\s>]", html)),
            "chars": len(strip_tags(html))}


def cv(values):
    m = statistics.mean(values)
    if m == 0:
        return None
    return (statistics.pstdev(values) / m)


def jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 1.0


def palette_hexes(bid):
    h = json.loads((SESS / bid / "handoff_v4.json").read_text(encoding="utf-8"))
    hexes = set()
    for d in h["decisions"]:
        for c in (d.get("visual_tokens") or {}).get("palette", []):
            hexes.add(c.lower())
    return hexes


def metrics():
    res = {"format": "unprompt.uniformity.u1", "briefs": {}, "summary": {}}
    rep_shorts = [m.split("/")[-1] for m in REP_MODELS]
    ver_shorts = [m.split("/")[-1] for m in VER_MODELS]
    cv_wins = {"compiled": 0, "raw": 0, "tie": 0}
    marker_jacs, ver_marker, ver_struct = [], [], []
    tok_hit = tok_all = 0
    forb = {"compiled": {"email": 0, "years": 0, "n": 0}, "raw": {"email": 0, "years": 0, "n": 0}}
    for bid in IDS:
        b = {"cv": {}, "marker_jaccard": {}, "token_rate": {}}
        pal = palette_hexes(bid)
        is_page = SPECS[bid]["kind"] == "page"
        for short in rep_shorts:
            for cond in ("raw", "compiled"):
                files = sorted((GEN / short / bid).glob(f"{cond}_r*.html"))
                htmls = [f.read_text(encoding="utf-8") for f in files]
                for h in htmls:
                    forb[cond]["n"] += 1
                    forb[cond]["email"] += bool(EMAIL_RE.search(h))
                    forb[cond]["years"] += bool(YEARS_RE.search(h))
                structs = [struct_of(h) for h in htmls]
                cvs = [c for c in (cv([s[k] for s in structs])
                                   for k in ("headings", "sections", "chars")) if c is not None]
                b["cv"][f"{short}:{cond}"] = round(statistics.mean(cvs), 4) if cvs else None
                if cond == "compiled":
                    sets = [set(MARKER_RE.findall(h)) for h in htmls]
                    jacs = [jaccard(sets[i], sets[j])
                            for i in range(len(sets)) for j in range(i + 1, len(sets))]
                    b["marker_jaccard"][short] = round(statistics.mean(jacs), 3) if jacs else None
                    marker_jacs += jacs
                    if is_page and pal:
                        for h in htmls:
                            style = "".join(re.findall(r"<style[\s\S]*?</style>", h)).lower()
                            tok_hit += sum(1 for c in pal if c in style)
                            tok_all += len(pal)
        # CV 勝敗 (反復2エンジンの平均で比較)
        cc = [v for k, v in b["cv"].items() if k.endswith(":compiled") and v is not None]
        rr = [v for k, v in b["cv"].items() if k.endswith(":raw") and v is not None]
        if cc and rr:
            c, r = statistics.mean(cc), statistics.mean(rr)
            b["cv_winner"] = "compiled" if c < r else ("raw" if r < c else "tie")
            cv_wins[b["cv_winner"]] += 1
        # 版間 (k2.7-code → k3)
        old, new = ver_shorts
        po = GEN / old / bid / "compiled_r1.html"
        pn = GEN / new / bid / "compiled_r1.html"
        if po.exists() and pn.exists():
            ho, hn = po.read_text(encoding="utf-8"), pn.read_text(encoding="utf-8")
            j = jaccard(set(MARKER_RE.findall(ho)), set(MARKER_RE.findall(hn)))
            b["version_marker_jaccard"] = round(j, 3)
            ver_marker.append(j)
        ro = GEN / old / bid / "raw_r1.html"
        rn = GEN / new / bid / "raw_r1.html"
        if ro.exists() and rn.exists():
            so, sn = struct_of(ro.read_text(encoding="utf-8")), struct_of(rn.read_text(encoding="utf-8"))
            diffs = [abs(so[k] - sn[k]) / max(so[k], sn[k]) for k in so if max(so[k], sn[k]) > 0]
            b["version_raw_struct_drift"] = round(statistics.mean(diffs), 3) if diffs else None
            if b["version_raw_struct_drift"] is not None:
                ver_struct.append(b["version_raw_struct_drift"])
        res["briefs"][bid] = b
    res["summary"] = {
        "cv_wins": cv_wins,
        "marker_jaccard_mean": round(statistics.mean(marker_jacs), 3) if marker_jacs else None,
        "token_adherence": f"{tok_hit}/{tok_all}",
        "version_marker_jaccard_mean": round(statistics.mean(ver_marker), 3) if ver_marker else None,
        "version_raw_struct_drift_mean": round(statistics.mean(ver_struct), 3) if ver_struct else None,
        "forbidden": forb,
    }
    (OUT / "u1_metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    s = res["summary"]
    print("== U1 均一性 集計 ==")
    print("主指標 構造CV勝敗 (compiledが小=勝ち):", s["cv_wins"])
    print("判断点マーカー反復一致 (jaccard平均):", s["marker_jaccard_mean"])
    print("視覚トークン遵守:", s["token_adherence"])
    print("版間 k2.7→k3: compiledマーカー保存", s["version_marker_jaccard_mean"],
          "/ raw構造ドリフト", s["version_raw_struct_drift_mean"])
    print("禁則:", json.dumps(s["forbidden"], ensure_ascii=False))
    cost = sum(float(json.loads(l).get("x_cost_jpy") or 0)
               for l in COSTS.read_text(encoding="utf-8").splitlines() if l.strip())
    print(f"実費 x-cost 合計: ¥{cost:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--metrics", action="store_true")
    ap.add_argument("--models", default=None, help="カンマ区切りの短名で絞る (並列実行用)")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    if a.generate:
        gen_all(a.models.split(",") if a.models else None)
    if a.metrics:
        metrics()
    if not (a.generate or a.metrics):
        raise SystemExit("--generate / --metrics を指定")


if __name__ == "__main__":
    main()
