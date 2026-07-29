#!/usr/bin/env python3
"""ゼロ二重確認(2026-07-30)の決定的テスト。claude は呼ばない。

本番で ec-product(明らかに曖昧な依頼文)に「判断点なし」の0件が誤発動した。
対策は「branches 0件のときだけ、同一プロンプトで自動的にもう1回だけ引き直す」。
ここではモデルの出力を台本で固定し、分岐の有無ではなく制御の正しさを見る。

  A) /api/explode        0件 → 再抽出 → 2回目が非0なら採用(claude 呼び出しは2回)
  B) /api/explode        非0 なら再抽出しない(claude 呼び出しは1回)
  C) /api/explode        2回とも0 → zero_confirmed:true で0を返す
  D) /api/explode_stream 0件 → retry イベント → 2回目の分岐が index 0 から出る
  E) /api/explode_stream 非0 なら retry を送らない(既存挙動と同一)
  F) /api/explode_stream 2回とも0 → zero_confirmed:true + note、branch は0件
  G) /api/explode_stream 2回目が CLI エラー → 1回目の0件を done として返す(errorで潰さない)
  H) app/index.html の SSE ハンドラが未知イベント型 retry を読み飛ばす実装であること

使い方: python3 EVIDENCE/streaming/zerotest.py
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

REPO = Path("/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon")
sys.path.insert(0, str(REPO))

import server as S  # noqa: E402

BRIEF = "ネットショップに載せるタンブラーの商品説明文を書いて。ちゃんと良さが伝わって、ポチりたくなるように。"
FAILS = []


def chk(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def body_json(n, assessment):
    """n 件の分岐を持つ抽出JSON(anchor は必ず BRIEF の連続部分文字列)。"""
    anchors = ["タンブラーの商品説明文", "ちゃんと良さが伝わって", "ポチりたくなるように",
               "ネットショップに載せる", "商品説明文を書いて"]
    return json.dumps({
        "branches": [
            {"question_point": "判断点%d" % i,
             "anchor_words": [anchors[i]],
             "options": [{"label": "案A"}, {"label": "案B"}],
             "default_if_unresolved": "既定%d" % i}
            for i in range(n)
        ],
        "missing_materials": [],
        "residual_ambiguity_assessment": assessment,
    }, ensure_ascii=False)


class ScriptedRunner:
    """台本どおりに応答する ClaudeRunner の代役。

    script の各要素: ("ok", text) | ("cli_error", message)
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def _next(self):
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return item

    def run(self, system_prompt, user_prompt, model, kind="other"):
        kind_, payload = self._next()
        rec = {"ok": False, "wall_ms": 1000, "api_ms": 800, "duration_ms": 900,
               "result_text": None, "error": None, "hint": None, "exit_code": 0}
        if kind_ == "ok":
            rec["ok"] = True
            rec["result_text"] = payload
        else:
            rec["error"] = payload
            rec["hint"] = ""
        return rec

    def run_stream(self, system_prompt, user_prompt, model, idle_s=1.0):
        kind_, payload = self._next()
        if kind_ == "cli_error":
            yield ("error", {"error": payload, "hint": "", "wall_ms": 1000, "api_ms": None})
            return
        # 実物と同じく、本文を細切れで流す(増分パーサを通す)
        for i in range(0, len(payload), 40):
            yield ("text", payload[i:i + 40])
        yield ("result", {"ok": True, "wall_ms": 1000, "api_ms": 800,
                          "result_text": payload})


def make_state(tmpdir, script):
    S.LOGS_DIR = Path(tmpdir)
    args = argparse.Namespace(
        port=0, host="127.0.0.1", model="sonnet", render_model="sonnet",
        compile_model=None, effort="low", timeout=30,
        max_concurrency=6, claude_bin="/bin/false", allow_api_key=False)
    S.STATE = S.ServerState(args)
    runner = ScriptedRunner(script)
    S.STATE.runner.terminate_all()
    S.STATE.runner = runner
    return runner


def run_stream_capture(script, tmp):
    runner = make_state(tmp, script)
    events = []

    def emit(obj):
        if obj is not None:
            events.append(obj)
        return True

    ret = S.handle_explode_stream({"brief": BRIEF}, emit)
    return runner, events, ret


def main():
    tmp = tempfile.mkdtemp(prefix="gyakumon_zerotest_")

    # ================= A) 一括: 0件 → 再抽出 → 2回目採用 =================
    print("=== A) /api/explode 0件 → 自動でもう1回 → 2回目が非0なら採用 ===")
    runner = make_state(tmp, [("ok", body_json(0, "十分に特定されている")),
                              ("ok", body_json(3, "曖昧である"))])
    out, rec, model = S.handle_explode({"brief": BRIEF})
    chk("★2回目の非0を採用する", len(out.get("branches", [])) == 3, "branches=%d" % len(out.get("branches", [])))
    chk("★claude は2回だけ呼ばれる", runner.calls == 2, "calls=%d" % runner.calls)
    chk("zero_retry の印が立つ", out.get("zero_retry") is True)
    chk("zero_confirmed は立たない", "zero_confirmed" not in out)
    chk("attempts に両方の実測が残る",
        isinstance(out.get("attempts"), list) and len(out["attempts"]) == 2
        and out["attempts"][0]["branches"] == 0 and out["attempts"][1]["branches"] == 3,
        out.get("attempts"))
    chk("★timing は2回分の合計(+1回分だけ増える)",
        out["timing"]["wall_ms"] == 2000 and out["timing"]["api_ms"] == 1600, out["timing"])
    chk("採用した所見が2回目のもの", out.get("residual_ambiguity_assessment") == "曖昧である")

    # ================= B) 一括: 非0 なら引き直さない =================
    print("\n=== B) /api/explode 非0 なら再抽出しない(既存経路のコスト不変) ===")
    runner = make_state(tmp, [("ok", body_json(4, "曖昧である")),
                              ("ok", body_json(0, "呼ばれてはいけない"))])
    out, rec, model = S.handle_explode({"brief": BRIEF})
    chk("★claude は1回しか呼ばれない", runner.calls == 1, "calls=%d" % runner.calls)
    chk("分岐は4件", len(out.get("branches", [])) == 4)
    chk("zero_retry は付かない", "zero_retry" not in out)
    chk("timing は1回分のまま", out["timing"] == {"wall_ms": 1000, "api_ms": 800}, out["timing"])

    # ================= C) 一括: 両方0 → zero_confirmed =================
    print("\n=== C) /api/explode 2回とも0 → 0件を返す(対照ブリーフの誠実性) ===")
    runner = make_state(tmp, [("ok", body_json(0, "完全に指定されている")),
                              ("ok", body_json(0, "完全に指定されている"))])
    out, rec, model = S.handle_explode({"brief": BRIEF})
    chk("★0件のまま返す", out.get("ok") is True and out.get("branches") == [])
    chk("★zero_confirmed:true が付く", out.get("zero_confirmed") is True)
    chk("claude は2回", runner.calls == 2, "calls=%d" % runner.calls)
    chk("note に二重確認済みと書く", "二重確認済み" in out.get("note", ""), out.get("note"))

    # ================= D) ストリーム: 0件 → retry → 2回目採用 =================
    print("\n=== D) /api/explode_stream 0件 → retry イベント → 2回目を採用 ===")
    runner, events, ret = run_stream_capture(
        [("ok", body_json(0, "十分に特定されている")),
         ("ok", body_json(3, "曖昧である"))], tmp)
    types = [e["type"] for e in events]
    done = [e for e in events if e["type"] == "done"]
    branches = [e for e in events if e["type"] == "branch"]
    retries = [e for e in events if e["type"] == "retry"]
    chk("★claude は2回だけ", runner.calls == 2, "calls=%d" % runner.calls)
    chk("★retry イベントを1つ送る", len(retries) == 1, retries)
    chk("retry は理由を名乗る",
        retries and retries[0].get("reason") == "branches_zero" and retries[0].get("attempt") == 2)
    chk("★retry は最初の branch より前", types.index("retry") < types.index("branch"), types)
    chk("★2回目の branch が index 0 から出る",
        [b["index"] for b in branches] == [0, 1, 2], [b["index"] for b in branches])
    chk("done は3件", done and len(done[0]["branches"]) == 3)
    chk("done に zero_retry の印", done and done[0].get("zero_retry") is True)
    chk("done に note は付かない", done and "note" not in done[0])
    chk("★done の timing は2回分の合計",
        done and done[0]["timing"] == {"wall_ms": 2000, "api_ms": 1600}, done and done[0]["timing"])
    chk("戻り値 ok=True / client_gone=False", ret[0] is True and ret[5] is False, ret)
    chk("戻り値の wall/api も合計", ret[2] == 2000 and ret[3] == 1600, ret)

    # ================= E) ストリーム: 非0 なら retry なし =================
    print("\n=== E) /api/explode_stream 非0 なら retry を送らない ===")
    runner, events, ret = run_stream_capture(
        [("ok", body_json(2, "曖昧である")),
         ("ok", body_json(5, "呼ばれてはいけない"))], tmp)
    chk("★claude は1回だけ", runner.calls == 1, "calls=%d" % runner.calls)
    chk("★retry イベントを送らない", not [e for e in events if e["type"] == "retry"])
    done = [e for e in events if e["type"] == "done"]
    chk("done は2件", done and len(done[0]["branches"]) == 2)
    chk("zero_retry も zero_confirmed も付かない",
        done and "zero_retry" not in done[0] and "zero_confirmed" not in done[0])
    chk("timing は1回分のまま", done and done[0]["timing"] == {"wall_ms": 1000, "api_ms": 800})

    # ================= F) ストリーム: 両方0 =================
    print("\n=== F) /api/explode_stream 2回とも0 → 0件を返す ===")
    runner, events, ret = run_stream_capture(
        [("ok", body_json(0, "完全に指定されている")),
         ("ok", body_json(0, "完全に指定されている"))], tmp)
    done = [e for e in events if e["type"] == "done"]
    chk("★branch イベントは1件も出ない", not [e for e in events if e["type"] == "branch"])
    chk("★done は0件 + zero_confirmed",
        done and done[0]["branches"] == [] and done[0].get("zero_confirmed") is True)
    chk("note に二重確認済み", done and "二重確認済み" in done[0].get("note", ""), done and done[0].get("note"))
    chk("所見(0件の理由)は残る",
        done and done[0]["residual_ambiguity_assessment"] == "完全に指定されている")
    chk("戻り値 ok=True", ret[0] is True)

    # ================= G) ストリーム: 2回目が事故 =================
    print("\n=== G) /api/explode_stream 2回目が CLI エラー → 1回目の0件を done で返す ===")
    runner, events, ret = run_stream_capture(
        [("ok", body_json(0, "完全に指定されている")),
         ("cli_error", "claude CLI がエラーを返した")], tmp)
    done = [e for e in events if e["type"] == "done"]
    errs = [e for e in events if e["type"] == "error"]
    chk("★error イベントで潰さない", not errs, errs)
    chk("★1回目の0件が done として届く", done and done[0]["branches"] == [])
    chk("zero_confirmed は立てない(2回目は確認になっていない)",
        done and "zero_confirmed" not in done[0])
    chk("attempts に2回目の失敗が残る",
        done and done[0]["attempts"][1].get("failed") == "error", done and done[0].get("attempts"))
    chk("戻り値 ok=True", ret[0] is True)

    # ================= H) 既存クライアントが retry を無視する =================
    print("\n=== H) app/index.html は未知イベント型を読み飛ばす(app 無改造で動く根拠) ===")
    html = (REPO / "app" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"const handle = \(obj\) => \{(.*?)\n  \};", html, re.S)
    chk("SSE ハンドラ本体を特定できる", m is not None)
    if m:
        known = set(re.findall(r"obj\.type === '(\w+)'", m.group(1)))
        chk("★分岐しているのは meta/branch/done/error だけ",
            known == {"meta", "branch", "done", "error"}, sorted(known))
        chk("★else 節も throw もない(未知の型は素通り)",
            "else" not in m.group(1) and "throw" not in m.group(1))
        chk("retry を特別扱いする記述はない", "retry" not in m.group(1))

    print("\n--- %s" % ("ゼロ二重確認: すべて期待どおり" if not FAILS
                        else "FAILED: " + ", ".join(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
