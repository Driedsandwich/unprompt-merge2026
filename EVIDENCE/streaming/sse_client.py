#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSE 受信の実測クライアント(ブラウザ相当)。到着ごとに経過msを刻む。"""
import json, sys, time, urllib.request

port = sys.argv[1] if len(sys.argv) > 1 else "8399"
brief = sys.argv[2] if len(sys.argv) > 2 else "モダンだけど温かみのあるLPを作って。うちの会社のやつ。"

req = urllib.request.Request("http://127.0.0.1:%s/api/explode_stream" % port,
                             data=json.dumps({"brief": brief}).encode("utf-8"),
                             headers={"Content-Type": "application/json"}, method="POST")
t0 = time.monotonic()
buf = b""
marks = []
first_branch = None
nbr = 0
with urllib.request.urlopen(req, timeout=180) as r:
    print("HTTP %s  Content-Type=%s" % (r.status, r.headers.get("Content-Type")))
    while True:
        chunk = r.read(1)          # 1バイトずつ読んで「本当に逐次届いているか」を確かめる
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            rec, buf = buf.split(b"\n\n", 1)
            ms = round((time.monotonic() - t0) * 1000)
            line = rec.decode("utf-8", "replace").strip()
            if line.startswith(":"):
                marks.append(("keepalive", ms))
                continue
            if not line.startswith("data: "):
                continue
            obj = json.loads(line[6:])
            t = obj.get("type")
            if t == "branch":
                nbr += 1
                if first_branch is None:
                    first_branch = ms
                marks.append(("branch%d[%s]" % (nbr, obj["branch"]["question_point"][:14]), ms))
            elif t == "done":
                marks.append(("done", ms))
                print("done: branches=%d rejected=%d api_ms=%s first_branch_ms=%s wall_ms=%s" % (
                    len(obj["branches"]), len(obj["rejected_branches"]), obj["api_ms"],
                    obj["first_branch_ms"], obj["timing"]["wall_ms"]))
                for b in obj["branches"]:
                    print("   - %s | anchors=%s | opts=%s" % (
                        b["question_point"][:34], b["anchor_words"], [o["label"] for o in b["options"]]))
                if obj.get("rejected_branches"):
                    print("   rejected: %s" % json.dumps(obj["rejected_branches"], ensure_ascii=False)[:300])
            elif t == "meta":
                marks.append(("meta(partial=%s)" % obj.get("partial"), ms))
            elif t == "error":
                marks.append(("error", ms))
                print("ERROR: %s / %s" % (obj.get("error"), obj.get("hint")))
print("--- 受信タイムライン(クライアント視点・送信からの経過ms) ---")
for k, v in marks:
    print("  %-34s %6d ms" % (k, v))
if first_branch is not None:
    print("初回カード表示可能まで: %d ms  (目標 8000ms %s)" % (
        first_branch, "達成" if first_branch <= 8000 else "未達"))
