#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測定v6 構築ランナー (PREREGISTRATION.md 追補7)

v4 から固定再利用: sessions/*/handoff_v4.json・brief・raw 成果物 (pairs_v4/*/raw.html)。
新規: compiled のみ 第3項+第1項明確化入り COMPILED_EXTRA (scripts/pregen_compare.py・コミット済み) で12本再生成。

工程:
  --artifacts : pairs_v6/<id>/{raw.html(コピー), compiled.html(新規)} + measure_manifest_v6.json
  --blind     : blind_v6/<id>/art_1.html, art_2.html (割当シード ":v6-single"・対応表は manifest のみ)
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import server  # noqa: E402
import pregen_compare as pg  # noqa: E402
from effect_measure import SPECS  # noqa: E402
from measure_v4_build import IDS, SESS, PAIRS4  # noqa: E402

PAIRS6 = HERE / "pairs_v6"
BLIND6 = HERE / "blind_v6"
MANIFEST = HERE / "measure_manifest_v6.json"


def do_artifacts(runner, model):
    man = {"format": "unprompt.effect_measure.v6", "pairs": {}}
    if MANIFEST.exists():
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for bid in IDS:
        sdir = SESS / bid
        odir = PAIRS6 / bid
        odir.mkdir(parents=True, exist_ok=True)
        brief = (sdir / "brief.txt").read_text(encoding="utf-8").strip()
        handoff_raw = (sdir / "handoff_v4.json").read_text(encoding="utf-8").strip()
        _, compiled_sys = pg.build_maker_system(SPECS[bid])
        # 実行前登録の要: 二律がシステム文に載っていることを生成前に検査する
        assert "創作せず、プレースホルダ" in compiled_sys and "丸投げせず" in compiled_sys \
            and "質問形" in compiled_sys and "年ぶり" in compiled_sys, \
            "第3項/第1項明確化が COMPILED_EXTRA に無い — pregen_compare.py の版を確認"
        entry = man["pairs"].get(bid) or {"brief_id": bid, "brief": brief, "gen": {}}
        if not (odir / "compiled.html").exists():
            print(f"[{bid}] compiled_v6 生成中...", flush=True)
            html, rec = pg.gen_deliverable(runner, compiled_sys, handoff_raw, model)
            (odir / "compiled.html").write_text(html, encoding="utf-8")
            entry["gen"]["compiled"] = {
                "attempts": rec.get("gen_attempts"),
                "failed_attempts": rec.get("gen_failed_attempts"),
                "model_id_observed": rec.get("model_id")}
        if not (odir / "raw.html").exists():
            shutil.copy(PAIRS4 / bid / "raw.html", odir / "raw.html")
            entry["gen"]["raw"] = {"source": "pairs_v4/(v4と同一物・固定再利用)"}
        entry["generated_at"] = pg.now_iso()
        entry["compiled_user"] = handoff_raw
        man["pairs"][bid] = entry
        MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{bid}] artifacts 完了")


def art_order(bid):
    h = int(hashlib.sha256((bid + ":v6-single").encode()).hexdigest(), 16)
    return ("raw", "compiled") if h % 2 == 0 else ("compiled", "raw")


def do_blind():
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for bid in IDS:
        odir = PAIRS6 / bid
        b = BLIND6 / bid
        b.mkdir(parents=True, exist_ok=True)
        first, second = art_order(bid)
        shutil.copy(odir / (first + ".html"), b / "art_1.html")
        shutil.copy(odir / (second + ".html"), b / "art_2.html")
        (b / "brief.txt").write_text(man["pairs"][bid]["brief"] + "\n", encoding="utf-8")
        man["pairs"][bid]["blind_map"] = {"art_1": first, "art_2": second}
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print("blind_v6 構築完了 (対応表は manifest のみ)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", action="store_true")
    ap.add_argument("--blind", action="store_true")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--claude-bin", default="claude")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--max-concurrency", type=int, default=4)
    ap.add_argument("--effort", default="low")
    args = ap.parse_args()
    if args.artifacts:
        runner = server.ClaudeRunner(args.claude_bin, args.timeout, args.max_concurrency,
                                     allow_api_key=False, effort=args.effort)
        do_artifacts(runner, args.model)
    if args.blind:
        do_blind()
    if not (args.artifacts or args.blind):
        raise SystemExit("--artifacts / --blind を指定")


if __name__ == "__main__":
    main()
