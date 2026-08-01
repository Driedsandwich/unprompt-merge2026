#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2: 見本つき選択の handoff_v2.json から compiled_v3 を生成し、
raw は v1 と同一物を再利用 (raw条件は選択に依存しないため・対照の固定)。
blind_v3/ は左右順のシードを変えて再ブラインドする。"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import server  # noqa: E402
import pregen_compare as pg  # noqa: E402
from effect_measure import SPECS  # noqa: E402

SESS = HERE / "sessions"
PAIRS1 = HERE / "pairs"
PAIRS2 = HERE / "pairs_v3"
BLIND2 = HERE / "blind_v3"
MANIFEST = HERE / "measure_manifest_v3.json"


def blind_side(bid):
    return "AB" if int(hashlib.sha256((bid + ":v3").encode()).hexdigest(), 16) % 2 == 0 else "BA"


def main():
    runner = server.ClaudeRunner("claude", 180, 4, allow_api_key=False, effort="low")
    man = {"format": "unprompt.effect_measure.v3", "pairs": {}}
    for bid in sorted(SPECS):
        sdir = SESS / bid
        h = sdir / "handoff_v2.json"
        if not h.exists():
            continue
        handoff_raw = h.read_text(encoding="utf-8").strip()
        brief = (sdir / "brief.txt").read_text(encoding="utf-8").strip()
        _, compiled_sys = pg.build_maker_system(SPECS[bid])
        odir = PAIRS2 / bid
        odir.mkdir(parents=True, exist_ok=True)
        print(f"[{bid}] compiled_v3 生成中...", flush=True)
        html, rec = pg.gen_deliverable(runner, compiled_sys, handoff_raw, "sonnet")
        (odir / "compiled.html").write_text(html, encoding="utf-8")
        shutil.copy(PAIRS1 / bid / "raw.html", odir / "raw.html")  # v1のrawを固定再利用
        order = blind_side(bid)
        man["pairs"][bid] = {
            "brief_id": bid, "brief": brief, "generated_at": pg.now_iso(),
            "blind_order": order, "raw_source": "pairs/(v1と同一物)",
            "gen": {"compiled": {"attempts": rec.get("gen_attempts"),
                                 "failed_attempts": rec.get("gen_failed_attempts")}},
            "compiled_user": handoff_raw,
        }
        b = BLIND2 / bid
        b.mkdir(parents=True, exist_ok=True)
        left, right = ("raw.html", "compiled.html") if order == "AB" else ("compiled.html", "raw.html")
        shutil.copy(odir / left, b / "left.html")
        shutil.copy(odir / right, b / "right.html")
        (b / "brief.txt").write_text(brief + "\n", encoding="utf-8")
        print(f"[{bid}] 完了")
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print("manifest_v2:", len(man["pairs"]), "pairs")


if __name__ == "__main__":
    main()
