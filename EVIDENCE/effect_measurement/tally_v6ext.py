#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測定v6 外部3モデル判定の集計 (PREREGISTRATION.md 追補7 手続き2)

judgments/ext_v6/<model>_judge{1..3}_{metric}_v6.json をモデルごとに v4 と同じ規則で集計し、
sonnet 本走 (tally_v6.json) との一致 (方向・ブリーフ別勝敗・捏造の重なり) と
costs_v6ext.jsonl の実費合計を出す。出力: tally_v6ext.json + 標準出力の要約。
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXT = HERE / "judgments" / "ext_v6"
MAN = json.loads((HERE / "measure_manifest_v6.json").read_text(encoding="utf-8"))
BASE = json.loads((HERE / "tally_v6.json").read_text(encoding="utf-8"))
MODELS = ["deepseek-v4-flash", "glm-5.2", "kimi-k3"]
JUDGES = [1, 2, 3]

# sonnet 本走で確定した捏造4件の照合キーワード (対象箇所ベースの重なり判定の機械部分。
# 最終判定は fabrications 全文の目視とセットで行い、キーワードは見落とし防止の下限)
KNOWN_FABS = {}


def tally_model(short):
    data = {}
    for j in JUDGES:
        merged = {}
        for metric in ("rework", "fabrication"):
            p = EXT / f"{short}_judge{j}_{metric}_v6.json"
            if not p.exists():
                continue
            for bid, arts in json.loads(p.read_text(encoding="utf-8")).items():
                for art, slot in arts.items():
                    merged.setdefault(bid, {}).setdefault(art, {}).update(slot)
        data[j] = merged
    ids = sorted(MAN["pairs"])
    per_brief = {}
    rw_wins = {"compiled": 0, "raw": 0, "tie": 0}
    rw_sum = {"compiled": 0, "raw": 0}
    fb_sum = {"compiled": 0, "raw": 0}
    fb_arts = {"compiled": 0, "raw": 0}
    missing = 0
    fab_texts = {}
    for bid in ids:
        bm = MAN["pairs"][bid]["blind_map"]
        rw = {"compiled": [], "raw": []}
        fb = {"compiled": [], "raw": []}
        for j in JUDGES:
            d = data[j].get(bid, {})
            for art, cond in bm.items():
                slot = d.get(art, {})
                r, f = slot.get("rework"), slot.get("fabrications")
                if r is None or f is None:
                    missing += 1
                if r is not None:
                    rw[cond].append(len(r))
                if f is not None:
                    fb[cond].append(len(f))
                    for item in f:
                        fab_texts.setdefault((bid, cond), []).append(item.get("fact", ""))
        rec = {"rework_mean": {}, "fabrication_mean": {}}
        for cond in ("compiled", "raw"):
            rec["rework_mean"][cond] = (sum(rw[cond]) / len(rw[cond])) if rw[cond] else None
            rec["fabrication_mean"][cond] = (sum(fb[cond]) / len(fb[cond])) if fb[cond] else None
            rw_sum[cond] += sum(rw[cond])
            fb_sum[cond] += sum(fb[cond])
            fb_arts[cond] += len(fb[cond])
        c, r = rec["rework_mean"]["compiled"], rec["rework_mean"]["raw"]
        rec["rework_winner"] = None
        if c is not None and r is not None:
            rec["rework_winner"] = "compiled" if c < r else ("raw" if r < c else "tie")
            rw_wins[rec["rework_winner"]] += 1
        per_brief[bid] = rec
    n = len(ids)
    overlap = {}
    for (bid, cond), kws in KNOWN_FABS.items():
        texts = " / ".join(fab_texts.get((bid, cond), []))
        overlap[f"{bid}:{cond}"] = {
            "keywords": kws,
            "hit": any(k in texts for k in kws),
            "ext_facts": fab_texts.get((bid, cond), []),
        }
    return {
        "per_brief": per_brief,
        "missing_slots": missing,
        "summary": {
            "rework_wins": rw_wins,
            "rework_mean_per_artifact": {c: rw_sum[c] / (n * len(JUDGES)) for c in rw_sum},
            "fabrication_total": fb_sum,
        },
        "known_fab_overlap": overlap,
    }


def concordance(model_out):
    base_s = BASE["summary"]
    base_dir_rw = ("raw" if base_s["rework_mean_per_artifact"]["raw"]
                   < base_s["rework_mean_per_artifact"]["compiled"] else "compiled")
    base_dir_fb = ("compiled" if base_s["fabrication_total"]["compiled"]
                   > base_s["fabrication_total"]["raw"] else "raw")
    s = model_out["summary"]
    dir_rw = ("raw" if s["rework_mean_per_artifact"]["raw"]
              < s["rework_mean_per_artifact"]["compiled"] else "compiled")
    dir_fb = ("compiled" if s["fabrication_total"]["compiled"]
              > s["fabrication_total"]["raw"] else "raw")
    match = 0
    for bid, rec in model_out["per_brief"].items():
        if rec["rework_winner"] == BASE["per_brief"][bid]["rework_winner"]:
            match += 1
    return {
        "direction_rework_match": dir_rw == base_dir_rw,
        "direction_fabrication_match": dir_fb == base_dir_fb,
        "per_brief_winner_match": f"{match}/{len(model_out['per_brief'])}",
    }


def costs():
    per_model = {}
    total = 0.0
    calls = 0
    errors = 0
    if (EXT / "costs_v6ext.jsonl").exists():
        for line in (EXT / "costs_v6ext.jsonl").read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            short = rec["model"].split("/")[-1]
            m = per_model.setdefault(short, {"calls": 0, "errors": 0, "jpy": 0.0})
            if rec.get("error"):
                m["errors"] += 1
                errors += 1
                continue
            m["calls"] += 1
            calls += 1
            c = float(rec.get("x_cost_jpy") or 0)
            m["jpy"] += c
            total += c
    return {"per_model": {k: {**v, "jpy": round(v["jpy"], 2)} for k, v in per_model.items()},
            "billed_calls": calls, "errored_calls": errors, "total_jpy": round(total, 2)}


def main():
    out = {"format": "unprompt.effect_tally.v6ext", "models": {}, "costs": costs()}
    for short in MODELS:
        m = tally_model(short)
        m["concordance_vs_sonnet"] = concordance(m)
        out["models"][short] = m
    (HERE / "tally_v6ext.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print("== 測定v6 外部3モデル判定 集計 ==")
    for short in MODELS:
        m = out["models"][short]
        s, c = m["summary"], m["concordance_vs_sonnet"]
        print(f"[{short}] 欠測 {m['missing_slots']} slot")
        print("  指標1 平均/成果物: compiled %.2f / raw %.2f  勝敗 c%d/r%d/t%d"
              % (s["rework_mean_per_artifact"]["compiled"], s["rework_mean_per_artifact"]["raw"],
                 s["rework_wins"]["compiled"], s["rework_wins"]["raw"], s["rework_wins"]["tie"]))
        print("  指標2 捏造合計: compiled %d / raw %d"
              % (s["fabrication_total"]["compiled"], s["fabrication_total"]["raw"]))
        print("  一致: 方向(指標1) %s / 方向(指標2) %s / ブリーフ別勝敗 %s"
              % (c["direction_rework_match"], c["direction_fabrication_match"],
                 c["per_brief_winner_match"]))
        for k, v in m["known_fab_overlap"].items():
            print(f"  既知捏造 {k}: 検出 {v['hit']}")
    print("実費:", json.dumps(out["costs"], ensure_ascii=False))


if __name__ == "__main__":
    main()
