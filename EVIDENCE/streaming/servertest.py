#!/usr/bin/env python3
"""2026-07-29 Codex監査の採択指摘(M2 / M3 / N3)をサーバ側で押さえる。

claude は呼ばない(fake_claude.py が CLI の外形だけを真似る)。ここで見たいのは
実行枠の配分・子プロセスの回収・切断の記録であって、モデルの出力ではない。

  A) レンダ副上限: レンダが同時 render_cap 本までしか走らず、
     その最中でも explode / compile が枠待ちで止まらない(M2a)
  B) プロセス回収: ストリームを途中で閉じたら、claude と その孫プロセスが
     プロセスグループごと死に、吸い出しスレッドが畳まれてから枠が返る(M3)
  C) 切断検知: 既に切れている接続の /api/render では claude を起動しない(M2c)
  D) done 送信失敗: done を書き出せなかったら ok=false + client_gone=true(N3)

使い方: python3 EVIDENCE/streaming/servertest.py
"""
import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path("/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon")
sys.path.insert(0, str(REPO))
FAKE = str(REPO / "EVIDENCE" / "streaming" / "fake_claude.py")
BRIEF = "モダンだけど温かみのあるLPを作って。うちの会社のやつ。"

import server as S  # noqa: E402

FAILS = []


def chk(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def read_log(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 4:
                out.append({"kind": parts[0], "t": float(parts[1]), "pid": int(parts[2]),
                            "tag": parts[3]})
    return out


def max_overlap(events, tag):
    """START/END の並びから、同時に走っていた最大本数を出す。"""
    marks = []
    starts = {}
    for e in events:
        if e["tag"] != tag:
            continue
        if e["kind"] == "START":
            starts[e["pid"]] = e["t"]
            marks.append((e["t"], +1))
        elif e["kind"] == "END":
            marks.append((e["t"], -1))
    marks.sort()
    cur = best = 0
    for _t, d in marks:
        cur += d
        best = max(best, cur)
    return best


def make_state(tmpdir, max_concurrency=6, timeout=30):
    S.LOGS_DIR = Path(tmpdir)
    args = argparse.Namespace(
        port=0, host="127.0.0.1", model="sonnet", render_model="sonnet",
        compile_model=None, effort="low", timeout=timeout,
        max_concurrency=max_concurrency, claude_bin=FAKE, allow_api_key=False)
    S.STATE = S.ServerState(args)
    return S.STATE


def main():
    tmp = tempfile.mkdtemp(prefix="gyakumon_servertest_")
    os.environ["FAKE_BRIEF_ANCHOR"] = "LP"

    # ================= A) レンダ副上限(M2a) =================
    print("=== A) レンダ枠を絞り、explode/compile の枠を確保する(M2a) ===")
    flog = os.path.join(tmp, "fake_a.log")
    os.environ["FAKE_LOG"] = flog
    os.environ["FAKE_SLEEP"] = "1.0"
    os.environ.pop("FAKE_CHILD", None)
    runner = S.ClaudeRunner(FAKE, timeout_s=30, max_concurrency=6)
    chk("レンダ副上限が 3(全6枠のうち)", runner.render_cap == 3, "render_cap=%d" % runner.render_cap)

    render_payload = json.dumps({"brief": BRIEF, "sibling_labels": ["案B"]}, ensure_ascii=False)
    results = {}
    t_zero = time.monotonic()

    def do_render(i):
        runner.run("sys", render_payload, "sonnet", kind="render")

    def do_explode():
        time.sleep(0.25)                       # レンダが全部出そろってから割り込む
        t0 = time.monotonic()
        rec = runner.run("sys", BRIEF, "sonnet", kind="other")
        # rec["wall_ms"] は「枠を取ってから」の実行時間。差が枠待ち時間になる。
        results["explode_wait"] = (time.monotonic() - t0) - (rec["wall_ms"] or 0) / 1000.0
        results["explode_ok"] = rec["ok"]

    threads = [threading.Thread(target=do_render, args=(i,)) for i in range(8)]
    threads.append(threading.Thread(target=do_explode))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ev = read_log(flog)
    ov = max_overlap(ev, "render")
    chk("★レンダは同時 3 本を超えない", ov <= runner.render_cap, "max_overlap=%d" % ov)
    chk("レンダ8本は全部走った", sum(1 for e in ev if e["kind"] == "START" and e["tag"] == "render") == 8)
    chk("★レンダ渋滞の最中でも explode が枠待ちしない",
        results.get("explode_wait", 99) < 0.3, "枠待ち=%.3fs" % results.get("explode_wait", -1))
    chk("explode は成功している", results.get("explode_ok") is True)
    chk("全枠が返っている", runner.slots.qsize() == 6, "slots=%d" % runner.slots.qsize())
    chk("レンダ副上限も返っている(BoundedSemaphore が壊れていない)",
        runner.render_sema._value == runner.render_cap, "value=%s" % runner.render_sema._value)
    runner.cleanup()
    print("  (全体 %.1fs)" % (time.monotonic() - t_zero))

    # ================= B) 途中で閉じたときの回収(M3) =================
    print("\n=== B) ストリームを途中で閉じたら子も孫も回収する(M3) ===")
    flog = os.path.join(tmp, "fake_b.log")
    os.environ["FAKE_LOG"] = flog
    os.environ["FAKE_SLEEP"] = "20"          # result まで届かない長さ
    os.environ["FAKE_STREAM_GAP"] = "0.05"
    os.environ["FAKE_CHILD"] = "1"           # 孫プロセスを作らせる
    runner = S.ClaudeRunner(FAKE, timeout_s=60, max_concurrency=2)
    gen = runner.run_stream("sys", BRIEF, "sonnet")
    got_text = False
    for kind, _val in gen:
        if kind == "text":
            got_text = True
            break
    chk("前提: ストリームから本文が届いた", got_text)
    ev = read_log(flog)
    child_pids = [int(e["tag"]) for e in ev if e["kind"] == "CHILD"]
    parent_pids = [e["pid"] for e in ev if e["kind"] == "START"]
    chk("前提: 子(claude 役)と孫(sleep)が起きている",
        len(parent_pids) == 1 and len(child_pids) == 1, "parent=%s child=%s" % (parent_pids, child_pids))

    t0 = time.monotonic()
    gen.close()                               # クライアント切断に相当
    close_s = time.monotonic() - t0

    def alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    time.sleep(0.3)
    chk("★close で子プロセスが死ぬ", not alive(parent_pids[0]))
    chk("★孫プロセス(プロセスグループ)も道連れになる", not alive(child_pids[0]))
    chk("★close は待ち切れる(TERM→KILL の期限内)", close_s < TERM_LIMIT, "%.2fs" % close_s)
    chk("★実行枠が返っている", runner.slots.qsize() == 2, "slots=%d" % runner.slots.qsize())
    pumps = [t for t in threading.enumerate() if t.name.startswith("gyakumon-pump")]
    chk("★吸い出しスレッドが残っていない", len(pumps) == 0, [t.name for t in pumps])
    runner.cleanup()

    # ================= C) 切断済み接続では claude を起こさない(M2c) =================
    print("\n=== C) 既に切れている接続の /api/render では claude を起動しない(M2c) ===")
    flog = os.path.join(tmp, "fake_c.log")
    os.environ["FAKE_LOG"] = flog
    os.environ["FAKE_SLEEP"] = "1.0"
    os.environ.pop("FAKE_CHILD", None)
    state = make_state(tmp)
    httpd = S.Server(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    state.args.port = port          # Host ヘッダ検証は STATE.args.port を見る
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()

    body = json.dumps({"brief": BRIEF, "question_point": "判断点0",
                       "option": {"label": "案A"}, "sibling_labels": ["案B"]},
                      ensure_ascii=False).encode("utf-8")
    req = (b"POST /api/render HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n"
           b"Content-Type: application/json\r\nContent-Length: %d\r\n\r\n"
           % (port, len(body))) + body
    sock = socket.create_connection(("127.0.0.1", port))
    sock.sendall(req)
    sock.shutdown(socket.SHUT_WR)             # ブラウザが fetch を中断したときと同じ FIN
    time.sleep(1.2)
    ev = read_log(flog)
    chk("★切れている接続では claude を起動しない",
        sum(1 for e in ev if e["kind"] == "START") == 0, ev)
    sock.close()
    lines = []
    if os.path.exists(state.log.path):
        lines = [json.loads(l) for l in open(state.log.path, encoding="utf-8") if l.strip()]
    gone = [l for l in lines if l["endpoint"] == "/api/render"]
    chk("client_gone がセッションログに残る",
        len(gone) == 1 and gone[0]["ok"] is False and gone[0]["client_gone"] is True, gone)

    # 生きている接続なら通常どおり動く(検知が誤爆しないこと)
    sock2 = socket.create_connection(("127.0.0.1", port))
    sock2.sendall(req)
    sock2.settimeout(20)
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += sock2.recv(4096)
    head, _, rest = buf.partition(b"\r\n\r\n")
    length = int([h.split(b":")[1] for h in head.split(b"\r\n") if h.lower().startswith(b"content-length")][0])
    while len(rest) < length:
        rest += sock2.recv(4096)
    payload = json.loads(rest.decode("utf-8"))
    chk("生きている接続では従来どおり応答する", payload.get("ok") is True, payload.get("error"))
    ev = read_log(flog)
    chk("そのときは claude が起動している", sum(1 for e in ev if e["kind"] == "START") == 1)
    sock2.close()
    httpd.shutdown()
    httpd.server_close()

    # ================= D) done を届けられなかったら成功にしない(N3) =================
    print("\n=== D) done の送信失敗を成功として記録しない(N3) ===")
    flog = os.path.join(tmp, "fake_d.log")
    os.environ["FAKE_LOG"] = flog
    os.environ["FAKE_SLEEP"] = "0.2"
    make_state(tmp)
    sent = []

    def emit_ok(obj):
        sent.append(obj)
        return True

    ok, model, wall, api, fb, gone_flag = S.handle_explode_stream({"brief": BRIEF}, emit_ok)
    chk("前提: 通常経路は ok=true / client_gone=false", ok is True and gone_flag is False)
    chk("前提: done を送っている", any(o and o.get("type") == "done" for o in sent if o))

    sent2 = []

    def emit_fail_on_done(obj):
        sent2.append(obj)
        if obj is not None and obj.get("type") == "done":
            return False                      # 書き出しに失敗した(= クライアントが消えた)
        return True

    ok2, _m, _w, _a, _f, gone2 = S.handle_explode_stream({"brief": BRIEF}, emit_fail_on_done)
    chk("★done を届けられなければ ok=false", ok2 is False)
    chk("★その理由は client_gone として別に立つ", gone2 is True)
    chk("done 自体は組み立てられている(サーバ側の抽出は成功)",
        any(o and o.get("type") == "done" for o in sent2 if o))

    print("\n" + ("--- FAILED: " + " / ".join(FAILS) if FAILS
                  else "--- レンダ枠 / プロセス回収 / 切断検知 / done記録: すべて期待どおり"))
    return 1 if FAILS else 0


TERM_LIMIT = 6.0

if __name__ == "__main__":
    sys.exit(main())
