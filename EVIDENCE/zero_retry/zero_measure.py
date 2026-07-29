#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ゼロ二重確認の実測。live server の /api/explode_stream を叩き、1回ぶんの結果を1行JSONで吐く。

使い方: python3 zero_measure.py <port> <brief_id> <n>

注意(読み間違い防止): このクライアントは 4096 バイト単位で read するため、
出力 JSON の first_branch_ms / retry_ms / done_ms は「クライアントが読み出した時刻」で
あって到着時刻ではない(小さな SSE レコードはバッファに溜まってからまとめて出てくる)。
逐次到着そのものを測るなら EVIDENCE/streaming/sse_client.py(1バイトずつ読む)を使う。
サーバ実測は done の timing / first_branch_ms と logs/session_*.jsonl を見ること。
"""
import json, sys, time, urllib.request, pathlib

REPO = "/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon"
briefs = {b["id"]: b["text"] for b in json.load(open(REPO + "/data/briefs.json", encoding="utf-8"))}

port, bid, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
brief = briefs[bid]

for i in range(n):
    req = urllib.request.Request("http://127.0.0.1:%s/api/explode_stream" % port,
                                 data=json.dumps({"brief": brief}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.monotonic()
    buf = b""
    first_branch = None
    retry = None
    done = None
    err = None
    nbr = 0
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            while True:
                chunk = r.read(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n\n" in buf:
                    rec, buf = buf.split(b"\n\n", 1)
                    ms = round((time.monotonic() - t0) * 1000)
                    line = rec.decode("utf-8", "replace").strip()
                    if not line.startswith("data: "):
                        continue
                    obj = json.loads(line[6:])
                    t = obj.get("type")
                    if t == "branch":
                        nbr += 1
                        if first_branch is None:
                            first_branch = ms
                    elif t == "retry":
                        retry = ms
                    elif t == "done":
                        done = (obj, ms)
                    elif t == "error":
                        err = (obj, ms)
    except Exception as e:
        err = ({"error": "%s: %s" % (type(e).__name__, e)}, round((time.monotonic() - t0) * 1000))

    row = {"brief": bid, "run": i + 1}
    if done:
        o, ms = done
        row.update({
            "branches": len(o.get("branches", [])),
            "qps": [b["question_point"] for b in o.get("branches", [])],
            "zero_retry": o.get("zero_retry", False),
            "zero_confirmed": o.get("zero_confirmed", False),
            "attempts": o.get("attempts"),
            "note": o.get("note"),
            "assessment": o.get("residual_ambiguity_assessment"),
            "rejected": len(o.get("rejected_branches", [])),
            "raw": o.get("branches_returned_by_model"),
            "first_branch_ms": first_branch, "retry_ms": retry, "done_ms": ms,
            "timing": o.get("timing"),
        })
    if err:
        row["error"] = err[0]
    print(json.dumps(row, ensure_ascii=False), flush=True)
