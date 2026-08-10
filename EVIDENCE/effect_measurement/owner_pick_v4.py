#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測定v4 発注者役の選択 (見本つき・PREREGISTRATION.md 追補4 工程3)

発注者役 = 独立エージェント (claude -p)。根拠は意図メモのみ。
提示文 (measure_v4_build.do_present: メモ+判断点+全選択肢の見本トークン) を渡し、
picks の JSON を受け取る。提示文・応答の全文を sessions/<id>/owner_pick_v4_log.json に保存。
v1〜v3 との整合: 発注者役は Fable 5 (--model fable)。全判断点を「決める」(委任なし・追補1の開示を継承)。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from measure_v4_build import IDS, SESS, do_present  # noqa: E402

INSTRUCT = """あなたは上記の意図メモの発注者本人である。各判断点について、メモの意図に最も合う選択肢を1つずつ選べ。
- 根拠はメモのみ。見本トークン (色・書体・密度・トーン例) がメモの好み・禁忌と合うかを必ず見る。
- ラベルの言葉づらだけで選ばず、見本がメモの美的意図と衝突しないかを確認する。
- 出力は次のJSONオブジェクトのみ (前置き・後書き・説明は禁止):
{"picks": [判断点0の選択肢番号, 判断点1の選択肢番号, ...], "notes": "選択の根拠メモ (2〜3文)"}"""


def pick_one(bid, model, timeout):
    present = do_present(bid)
    prompt = present + "\n\n---\n\n" + INSTRUCT
    r = subprocess.run(
        ["claude", "-p", "--model", model,
         "--settings", '{"permissions":{"defaultMode":"bypassPermissions"}}'],
        input=prompt, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"[{bid}] claude 失敗: {r.stderr[:300]}")
    txt = r.stdout.strip()
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError(f"[{bid}] JSONが見つからない: {txt[:200]}")
    obj = json.loads(m.group(0))
    picks = obj["picks"]
    (SESS / bid / "owner_pick_v4_log.json").write_text(json.dumps(
        {"presented": present, "instruction": INSTRUCT, "response_raw": txt,
         "picks": picks, "notes": obj.get("notes", ""), "owner_model": model},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return picks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="fable")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--ids", default=None)
    args = ap.parse_args()
    todo = args.ids.split(",") if args.ids else IDS
    results = {}
    for bid in todo:
        if (SESS / bid / "owner_pick_v4_log.json").exists():
            log = json.loads((SESS / bid / "owner_pick_v4_log.json").read_text(encoding="utf-8"))
            results[bid] = log["picks"]
            print(f"[{bid}] 済み — picks {log['picks']}")
            continue
        picks = pick_one(bid, args.model, args.timeout)
        results[bid] = picks
        print(f"[{bid}] picks {picks}")
    (HERE / "picks_v4.json").write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    print("全picks → picks_v4.json")


if __name__ == "__main__":
    main()
