#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測定v6 集計 (PREREGISTRATION.md 追補7)

judgments/judge{1..3}_v4.json を manifest の blind_map で復号し、
指標1 (やり直し件数: 少ない方が勝ち) と指標2 (捏造件数/成果物) を集計する。
出力: tally_v6.json (全数値) + 標準出力の要約。
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAN = json.loads((HERE / "measure_manifest_v6.json").read_text(encoding="utf-8"))
JUDGES = [1, 2, 3]

def load(j):
    return json.loads((HERE / "judgments" / f"judge{j}_v6.json").read_text(encoding="utf-8"))

def main():
    data = {j: load(j) for j in JUDGES}
    ids = sorted(MAN["pairs"])
    out = {"format": "unprompt.effect_tally.v6", "per_brief": {}, "summary": {}}
    rw_wins = {"compiled": 0, "raw": 0, "tie": 0}
    rw_sum = {"compiled": 0, "raw": 0}
    fb_sum = {"compiled": 0, "raw": 0}
    fb_arts = {"compiled": 0, "raw": 0}

    for bid in ids:
        bm = MAN["pairs"][bid]["blind_map"]          # {"art_1": "raw"|"compiled", ...}
        rec = {"blind_map": bm, "judges": {}, "rework_mean": {}, "fabrication_mean": {}}
        rw = {"compiled": [], "raw": []}
        fb = {"compiled": [], "raw": []}
        for j in JUDGES:
            d = data[j].get(bid, {})
            jr = {}
            for art, cond in bm.items():
                slot = d.get(art, {})
                r = slot.get("rework")
                f = slot.get("fabrications")
                jr[cond] = {"rework_n": (len(r) if r is not None else None),
                            "fabrication_n": (len(f) if f is not None else None)}
                if r is not None:
                    rw[cond].append(len(r))
                if f is not None:
                    fb[cond].append(len(f))
            rec["judges"][f"judge{j}"] = jr
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
        out["per_brief"][bid] = rec

    n = len(ids)
    out["summary"] = {
        "briefs": n,
        "rework_wins": rw_wins,
        "rework_total": rw_sum,
        "rework_mean_per_artifact": {c: rw_sum[c] / (n * len(JUDGES)) for c in rw_sum},
        "fabrication_total": fb_sum,
        "fabrication_rate_per_artifact": {c: (fb_sum[c] / fb_arts[c]) if fb_arts[c] else None
                                          for c in fb_sum},
        "prediction_1_rework": "compiled<=raw が過半か: compiled勝ち+引き分け = %d / %d"
                               % (rw_wins["compiled"] + rw_wins["tie"], n),
        "prediction_2_fabrication": "raw > compiled か: raw %d 件 vs compiled %d 件"
                                    % (fb_sum["raw"], fb_sum["compiled"]),
    }
    (HERE / "tally_v6.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    s = out["summary"]
    print("== 測定v6 集計 (n=%d×判定3体) ==" % n)
    print("指標1 やり直し件数: compiled勝ち %d / raw勝ち %d / 引き分け %d"
          % (rw_wins["compiled"], rw_wins["raw"], rw_wins["tie"]))
    print("  平均件数/成果物: compiled %.2f / raw %.2f"
          % (s["rework_mean_per_artifact"]["compiled"], s["rework_mean_per_artifact"]["raw"]))
    print("指標2 捏造件数: compiled %d / raw %d (率/成果物: %.2f / %.2f)"
          % (fb_sum["compiled"], fb_sum["raw"],
             s["fabrication_rate_per_artifact"]["compiled"] or 0,
             s["fabrication_rate_per_artifact"]["raw"] or 0))
    print("予測1:", s["prediction_1_rework"])
    print("予測2:", s["prediction_2_fabrication"])


if __name__ == "__main__":
    main()
