#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旧プロンプト(git HEAD)の 0件率ベースライン。リポジトリのファイルには一切触らない。

server.py の合成関数と ClaudeRunner をそのまま使い、system プロンプトだけ差し替える。
使い方: python3 baseline.py <prompt_file> <brief_id> <n> <tag>
"""
import json, sys, time
sys.path.insert(0, "/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon")
import server as S

REPO = "/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon"
briefs = {b["id"]: b["text"] for b in json.load(open(REPO + "/data/briefs.json", encoding="utf-8"))}

pfile, bid, n, tag = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
brief = briefs[bid]
sysprompt = S.build_extraction_stream_system(open(pfile, encoding="utf-8").read())
runner = S.ClaudeRunner("claude", timeout_s=180, max_concurrency=2)
try:
    for i in range(n):
        t0 = time.monotonic()
        rec = runner.run(sysprompt, brief, "sonnet")
        row = {"tag": tag, "brief": bid, "run": i + 1, "cli_ok": rec["ok"],
               "wall_ms": rec["wall_ms"], "api_ms": rec["api_ms"]}
        if rec["ok"]:
            ex, why = S.extract_json_object(
                rec["result_text"], lambda o: all(k in o for k in S.EXTRACTION_REQUIRED_TOP))
            if ex is None:
                row.update({"json": False, "why": why, "branches": 0,
                            "head": rec["result_text"][:120]})
            else:
                payload, why2 = S.validate_extraction(brief, ex)
                if payload is None:
                    row.update({"json": True, "valid": False, "why": why2, "branches": 0})
                else:
                    row.update({"json": True, "valid": True,
                                "branches": len(payload["branches"]),
                                "raw": payload["branches_returned_by_model"],
                                "rejected": len(payload["rejected_branches"]),
                                "assessment": payload["residual_ambiguity_assessment"]})
        else:
            row["error"] = rec["error"]
        print(json.dumps(row, ensure_ascii=False), flush=True)
finally:
    runner.terminate_all()
    runner.cleanup()
