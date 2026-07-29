#!/usr/bin/env python3
"""claude CLI の代役(servertest.py 専用)。

実行枠・プロセス回収・切断検知の検証で claude を実際に呼ぶ必要はなく、
呼ぶと課金と数十秒の待ちが乗る。ここでは CLI の外形(--output-format json /
stream-json の出力形)だけを真似て、時間と副作用を制御できるようにする。

環境変数:
  FAKE_LOG        1行1イベントの記録先(START/END/CHILD)
  FAKE_SLEEP      出力前に眠る秒数(既定 1.0)
  FAKE_CHILD      1 なら孫プロセス(sleep 120)を作る(プロセスグループ回収の検証用)
  FAKE_STREAM_GAP stream-json のイベント間隔(既定 0.05)
  FAKE_BRIEF_ANCHOR  分岐の anchor_words に使う文字列(原文の部分文字列であること)
"""
import json
import os
import subprocess
import sys
import time

LOG = os.environ.get("FAKE_LOG")
SLEEP = float(os.environ.get("FAKE_SLEEP", "1.0"))
GAP = float(os.environ.get("FAKE_STREAM_GAP", "0.05"))
ANCHOR = os.environ.get("FAKE_BRIEF_ANCHOR", "LP")


def log(kind, extra=""):
    if not LOG:
        return
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s\t%.4f\t%d\t%s\n" % (kind, time.monotonic(), os.getpid(), extra))
        f.flush()


def main():
    argv = sys.argv[1:]
    prompt = argv[-1] if argv else ""
    fmt = "json"
    if "--output-format" in argv:
        fmt = argv[argv.index("--output-format") + 1]
    kind = "render" if "sibling_labels" in prompt else "other"
    log("START", kind)

    child = None
    if os.environ.get("FAKE_CHILD") == "1":
        child = subprocess.Popen(["sleep", "120"])
        log("CHILD", str(child.pid))

    body = {
        "residual_ambiguity_assessment": "偽の抽出器である。",
        "missing_materials": [],
        "branches": [
            {"question_point": "判断点%d" % i,
             "anchor_words": [ANCHOR],
             "options": [{"label": "案A"}, {"label": "案B"}],
             "default_if_unresolved": "既定%d" % i}
            for i in range(2)
        ],
    }
    if kind == "render":
        body = {"palette": ["#112233", "#445566", "#778899"], "heading_font": "sans",
                "density": "normal", "corner": "soft", "tone_sample": "見出し。一文。"}
    text = json.dumps(body, ensure_ascii=False)

    if fmt == "stream-json":
        # branches 先スキーマの到着順を真似て、少しずつ吐く
        step = max(1, len(text) // 8)
        for i in range(0, len(text), step):
            ev = {"type": "stream_event",
                  "event": {"type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": text[i:i + step]}}}
            sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            time.sleep(GAP)
        time.sleep(SLEEP)
        sys.stdout.write(json.dumps({"type": "result", "result": text, "is_error": False,
                                     "duration_ms": 1000, "duration_api_ms": 800},
                                    ensure_ascii=False) + "\n")
        sys.stdout.flush()
    else:
        time.sleep(SLEEP)
        sys.stdout.write(json.dumps({"type": "result", "result": text, "is_error": False,
                                     "duration_ms": 1000, "duration_api_ms": 800},
                                    ensure_ascii=False))
        sys.stdout.flush()

    log("END", kind)
    if child is not None:
        child.wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
