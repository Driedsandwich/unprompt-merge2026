#!/usr/bin/env python3
"""2026-07-30 「処理の内訳」のモデル表示を正準IDにする(サーバ側)を機械で押さえる。

サーバが claude CLI へ渡しているのはエイリアス("sonnet" / "haiku")である。
「実際にどのモデルが応答したか」は CLI の応答JSONの modelUsage のキーにしか無い。
このテストは、その値が timing.model_id として各エンドポイントの応答に載ることを見る。

  1) 純関数 model_id_from_cli / pick_model_id の境界
  2) /api/explode(一括)の timing.model_id
  3) /api/explode_stream(SSE)の done.timing.model_id
  4) /api/render / /api/compile の timing.model_id
  5) modelUsage が無い CLI(古い版・欠測)では None を返す
     = 「取れていないのに、それらしいIDをでっち上げる」ことをしない

claude は呼ばない(fake_claude.py が CLI の外形だけを真似る)。
使い方: python3 EVIDENCE/streaming/modelidtest.py
"""
import argparse
import json
import os
import sys
import tempfile
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


def make_state(tmpdir, render_model="haiku"):
    S.LOGS_DIR = Path(tmpdir)
    args = argparse.Namespace(
        port=0, host="127.0.0.1", model="sonnet", render_model=render_model,
        compile_model=None, effort="low", timeout=30,
        max_concurrency=4, claude_bin=FAKE, allow_api_key=False)
    S.STATE = S.ServerState(args)
    return S.STATE


def fake_env(**kv):
    """偽CLIへ渡す環境変数を差し替える。

    ClaudeRunner は起動時に os.environ を写し取って持つ(APIキー除去のため)。
    したがってテスト側は runner.env のほうを直接いじる必要がある。
    値 None は「その変数を消す」。
    """
    env = S.STATE.runner.env
    for k, v in kv.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v


def collect_stream(body):
    """handle_explode_stream を回して、送られたイベントを全部集める。"""
    events = []

    def emit(obj):
        if obj is None:          # keepalive(切断検知用)はイベントではないので読み飛ばす
            return True
        events.append(obj)
        return True

    S.handle_explode_stream(body, emit)
    return events


def main():
    tmp = tempfile.mkdtemp(prefix="gyakumon_modelidtest_")
    os.environ["FAKE_BRIEF_ANCHOR"] = "LP"
    os.environ["FAKE_SLEEP"] = "0.05"
    os.environ["FAKE_STREAM_GAP"] = "0.005"
    os.environ.pop("FAKE_CHILD", None)
    os.environ.pop("FAKE_NO_MODEL_USAGE", None)
    os.environ["FAKE_MODEL_ID"] = "claude-sonnet-5"

    # ================= 1) 純関数 =================
    print("=== 1) modelUsage の読み取り(純関数) ===")
    f = S.model_id_from_cli
    chk("★キーが正準IDとして取れる",
        f({"modelUsage": {"claude-sonnet-5": {"outputTokens": 4,
                                              "canonicalModel": "claude-sonnet-5"}}})
        == "claude-sonnet-5")
    chk("canonicalModel が無くてもキーを使う",
        f({"modelUsage": {"claude-haiku-4-5": {}}}) == "claude-haiku-4-5")
    chk("★複数載ったら出力トークンが多いほうを主とする",
        f({"modelUsage": {"a": {"outputTokens": 1}, "b": {"outputTokens": 9}}}) == "b")
    chk("modelUsage が無ければ None", f({"duration_api_ms": 10}) is None)
    chk("空・型違い・None でも落ちずに None",
        f({"modelUsage": {}}) is None and f({"modelUsage": "x"}) is None and f(None) is None)
    chk("pick_model_id は最初に取れた値", S.pick_model_id([None, "", "claude-sonnet-5", "z"])
        == "claude-sonnet-5")
    chk("1つも無ければ None", S.pick_model_id([None, None, ""]) is None)

    make_state(tmp)

    # ================= 2) /api/explode =================
    print("\n=== 2) /api/explode(一括)の timing.model_id ===")
    out, rec, model = S.handle_explode({"brief": BRIEF})
    chk("前提: 抽出が成功している", out.get("ok") is True, out.get("error"))
    chk("サーバが CLI へ渡すのはエイリアス", model == "sonnet")
    chk("★timing に model_id が載る", out["timing"].get("model_id") == "claude-sonnet-5",
        json.dumps(out["timing"], ensure_ascii=False))
    chk("wall/api も従来どおり数値", isinstance(out["timing"]["wall_ms"], int)
        and isinstance(out["timing"]["api_ms"], int))
    chk("★エイリアスと正準IDは別物(だから出す意味がある)",
        out["timing"]["model_id"] != model)

    # ================= 3) /api/explode_stream =================
    print("\n=== 3) /api/explode_stream(SSE)の done.timing.model_id ===")
    events = collect_stream({"brief": BRIEF})
    done = [e for e in events if e.get("type") == "done"]
    chk("前提: done が1つ届く", len(done) == 1, [e.get("type") for e in events])
    chk("★done の timing に model_id が載る",
        done and done[0]["timing"].get("model_id") == "claude-sonnet-5",
        json.dumps(done[0]["timing"], ensure_ascii=False) if done else "")

    # ================= 4) /api/render, /api/compile =================
    print("\n=== 4) /api/render / /api/compile の timing.model_id ===")
    fake_env(FAKE_MODEL_ID="claude-haiku-4-5")             # 見本の生成は別モデル
    rout, _rec, rmodel = S.handle_render({
        "brief": BRIEF, "question_point": "LPの目的",
        "option": {"label": "問い合わせ"}, "sibling_labels": ["購入"]})
    chk("前提: レンダが成功している", rout.get("ok") is True, rout.get("error"))
    chk("レンダのエイリアスは render_model", rmodel == "haiku")
    chk("★レンダの timing にレンダ側の正準IDが載る",
        rout["timing"].get("model_id") == "claude-haiku-4-5",
        json.dumps(rout["timing"], ensure_ascii=False))

    fake_env(FAKE_MODEL_ID="claude-sonnet-5")
    cout, _crec, cmodel = S.handle_compile({
        "brief": BRIEF,
        "decisions": [{"question_point": "判断点0", "anchor_words": ["LP"],
                       "status": "delegated"}]})
    chk("前提: コンパイルが応答している", "timing" in cout, cout.get("error"))
    chk("★コンパイルの timing にも model_id が載る",
        cout["timing"].get("model_id") == "claude-sonnet-5",
        json.dumps(cout["timing"], ensure_ascii=False))
    chk("コンパイルのエイリアスは既定で model と同じ", cmodel == "sonnet")

    # ================= 5) 取れないときは None =================
    print("\n=== 5) modelUsage を返さない CLI では None(でっち上げない) ===")
    fake_env(FAKE_NO_MODEL_USAGE="1")
    out2, _rec2, _m2 = S.handle_explode({"brief": BRIEF})
    chk("前提: 抽出自体は成功する", out2.get("ok") is True)
    chk("★model_id は None(エイリアスで埋めない)", out2["timing"].get("model_id") is None,
        json.dumps(out2["timing"], ensure_ascii=False))
    events2 = collect_stream({"brief": BRIEF})
    done2 = [e for e in events2 if e.get("type") == "done"]
    chk("★ストリームでも None", done2 and done2[0]["timing"].get("model_id") is None,
        json.dumps(done2[0]["timing"], ensure_ascii=False) if done2 else "")
    fake_env(FAKE_NO_MODEL_USAGE=None)

    print("\n" + ("--- FAILED: " + " / ".join(FAILS) if FAILS
                  else "--- モデル正準IDの受け渡し: すべて期待どおり"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
