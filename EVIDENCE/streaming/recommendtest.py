#!/usr/bin/env python3
"""2026-07-30 サーバ2点(/api/recommend と /api/health の model_ids)の決定的テスト。

claude は呼ばない(fake_claude.py が CLI の外形だけを真似る)。ここで見たいのは
「AIが選んだ添字をサーバがどこまで信用するか」であって、モデルの選び方の良し悪しではない。

  A) /api/recommend 正常系: picks がそのまま転記され、timing.model_id が載る
  B) /api/recommend picks の長さが判断点数と違う      → ok:false(再試行しない)
  C) /api/recommend picks の値が options の範囲外      → ok:false
  D) /api/recommend picks に整数でない値(文字列/真偽) → ok:false
  E) /api/recommend JSON不成立(地の文だけ)           → ok:false(hint に応答本文)
  F) /api/recommend 要求の不備(branches 空・不正 / brief 空)→ HTTP 400
  G) /api/recommend reason の正規化(空・60字超)
  H) /api/health の model_ids: 観測前は null、実行後に観測値が入る
  I) 要求検証・picks検証の純関数の境界

使い方: python3 EVIDENCE/streaming/recommendtest.py
"""
import argparse
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path("/Users/kishimotosatoshi/Documents/MERGE2026/MERGE2026_FABLE5_AUTONOMOUS_DELIBERATION_v4.0_20260728/outputs/dev/gyakumon")
sys.path.insert(0, str(REPO))
FAKE = str(REPO / "EVIDENCE" / "streaming" / "fake_claude.py")
BRIEF = "モダンだけど温かみのあるLPを作って。うちの会社のやつ。"

import server as S  # noqa: E402

# 判断点2件(選択肢は2件と3件)。範囲外の検証を「判断点ごとに違う上限」で見るため。
BRANCHES = [
    {"question_point": "誰に向けたLPか",
     "options": [{"label": "既存顧客"}, {"label": "新規客"}]},
    {"question_point": "温かみの出し方",
     "options": [{"label": "手書き"}, {"label": "写真"}, {"label": "配色"}]},
]

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
    """偽CLIへ渡す環境変数を差し替える(ClaudeRunner は自前の env を持っている)。"""
    env = S.STATE.runner.env
    for k, v in kv.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v


def recommend(brief=BRIEF, branches=None):
    """handle_recommend を直接呼ぶ。(out, model) を返す。"""
    out, _rec, model = S.handle_recommend(
        {"brief": brief, "branches": BRANCHES if branches is None else branches})
    return out, model


def http_json(port, method, path, obj=None, ctype="application/json"):
    data = None if obj is None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": ctype} if data is not None else {}
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                                 data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read().decode("utf-8"), e.code
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, {"raw": raw}


def main():
    tmp = tempfile.mkdtemp(prefix="gyakumon_recommendtest_")
    os.environ["FAKE_BRIEF_ANCHOR"] = "LP"
    os.environ["FAKE_SLEEP"] = "0.05"
    os.environ["FAKE_STREAM_GAP"] = "0.005"
    os.environ.pop("FAKE_CHILD", None)
    os.environ.pop("FAKE_NO_MODEL_USAGE", None)
    os.environ.pop("FAKE_RECOMMEND_PICKS", None)
    os.environ.pop("FAKE_RECOMMEND_RAW", None)
    os.environ.pop("FAKE_RECOMMEND_REASON", None)
    os.environ["FAKE_MODEL_ID"] = "claude-sonnet-5"

    state = make_state(tmp)
    chk("前提: 推奨プロンプトが読めている", state.prompts.get("recommend") is not None,
        state.prompt_errors.get("recommend", ""))

    # ================= A) 正常系 =================
    print("=== A) 正常系: picks の転記と timing ===")
    fake_env(FAKE_RECOMMEND_PICKS="[1,2]", FAKE_RECOMMEND_REASON="新規向けに配色で温かみを出す。")
    out, model = recommend()
    chk("★ok:true で picks が返る", out.get("ok") is True, out.get("error"))
    chk("★picks はモデルの出力をそのまま転記する", out.get("picks") == [1, 2], out.get("picks"))
    chk("reason が載る", out.get("reason") == "新規向けに配色で温かみを出す。", out.get("reason"))
    chk("picks の長さは判断点数と同じ", len(out.get("picks") or []) == len(BRANCHES))
    chk("★timing.model_id に正準IDが載る",
        out["timing"].get("model_id") == "claude-sonnet-5",
        json.dumps(out["timing"], ensure_ascii=False))
    chk("timing.wall_ms / api_ms は数値",
        isinstance(out["timing"]["wall_ms"], int) and isinstance(out["timing"]["api_ms"], int),
        json.dumps(out["timing"], ensure_ascii=False))
    chk("モデルは compile と同じエイリアス", model == S.STATE.compile_model == "sonnet", model)
    chk("成果物本文は返らない(picks / reason / timing のみ)",
        set(out.keys()) <= {"ok", "picks", "reason", "timing", "warnings"}, list(out.keys()))

    # ================= B) 長さ不一致 =================
    print("\n=== B) picks の長さが判断点数と違う ===")
    fake_env(FAKE_RECOMMEND_PICKS="[0]")
    out, _m = recommend()
    chk("★ok:false になる", out.get("ok") is False, out)
    chk("error に長さ不一致と書く", "長さ" in (out.get("error") or ""), out.get("error"))
    chk("hint にモデルの picks を載せる", "[0]" in (out.get("hint") or ""), out.get("hint"))
    chk("失敗でも timing は返る", isinstance(out.get("timing"), dict), out.get("timing"))
    chk("picks は返さない", "picks" not in out, list(out.keys()))

    fake_env(FAKE_RECOMMEND_PICKS="[0,1,2]")
    out, _m = recommend()
    chk("多すぎても ok:false", out.get("ok") is False, out.get("error"))

    # ================= C) 範囲外 =================
    print("\n=== C) picks の値が options の範囲外 ===")
    fake_env(FAKE_RECOMMEND_PICKS="[0,3]")            # 2件目の選択肢は3件(0..2)
    out, _m = recommend()
    chk("★上限超過は ok:false", out.get("ok") is False, out)
    chk("error に範囲と書く", "範囲" in (out.get("error") or ""), out.get("error"))
    fake_env(FAKE_RECOMMEND_PICKS="[-1,0]")
    out, _m = recommend()
    chk("★負の添字も ok:false", out.get("ok") is False, out.get("error"))
    fake_env(FAKE_RECOMMEND_PICKS="[2,0]")            # 1件目の選択肢は2件(0..1)
    out, _m = recommend()
    chk("★判断点ごとの上限で判定する", out.get("ok") is False, out.get("error"))
    fake_env(FAKE_RECOMMEND_PICKS="[1,2]")
    out, _m = recommend()
    chk("境界値(各判断点の最後の添字)は通る", out.get("ok") is True, out.get("error"))

    # ================= D) 整数でない値 =================
    print("\n=== D) picks に整数でない値 ===")
    fake_env(FAKE_RECOMMEND_PICKS='[0,"1"]')
    out, _m = recommend()
    chk("★数字の文字列は ok:false(黙って直さない)", out.get("ok") is False, out)
    fake_env(FAKE_RECOMMEND_PICKS="[true,0]")
    out, _m = recommend()
    chk("★真偽値は ok:false(bool は整数として扱わない)", out.get("ok") is False, out.get("error"))
    fake_env(FAKE_RECOMMEND_PICKS="[0.0,0]")
    out, _m = recommend()
    chk("★小数は ok:false", out.get("ok") is False, out.get("error"))
    fake_env(FAKE_RECOMMEND_PICKS='"0,1"')
    out, _m = recommend()
    chk("★picks が配列でなければ ok:false", out.get("ok") is False, out.get("error"))

    # ================= E) JSON不成立 =================
    print("\n=== E) JSON にならない応答 ===")
    fake_env(FAKE_RECOMMEND_PICKS=None, FAKE_RECOMMEND_RAW="1")
    out, _m = recommend()
    chk("★ok:false になる", out.get("ok") is False, out)
    chk("error に読み取れなかったと書く", "読み取れなかった" in (out.get("error") or ""), out.get("error"))
    chk("★hint に実際の応答本文を載せる", "承知した" in (out.get("hint") or ""), out.get("hint"))
    fake_env(FAKE_RECOMMEND_RAW=None)

    # ================= F) 要求の不備 → 400 =================
    print("\n=== F) 要求の不備は HTTP 400 ===")
    for label, branches in (("branches が空配列", []),
                            ("branches が無い(None)", None),
                            ("branches が配列でない", {"a": 1}),
                            ("要素がオブジェクトでない", ["案A"]),
                            ("question_point が空", [{"question_point": "", "options": ["A", "B"]}]),
                            ("options が配列でない", [{"question_point": "Q", "options": "A"}]),
                            ("options が空", [{"question_point": "Q", "options": []}]),
                            ("options にラベルが無い", [{"question_point": "Q",
                                                        "options": [{"x": 1}, {"x": 2}]}])):
        out, _rec, _m = S.handle_recommend({"brief": BRIEF, "branches": branches})
        chk("★400 になる: " + label,
            out.get("ok") is False and out.get("_http_status") == 400, out.get("error"))
    out, _rec, _m = S.handle_recommend({"brief": "  ", "branches": BRANCHES})
    chk("★brief 空も 400", out.get("ok") is False and out.get("_http_status") == 400, out.get("error"))

    ev_before = os.path.exists(str(S.STATE.log.path))
    chk("400 のときは claude を呼んでいない(timing が null)", out.get("timing") is None, out)

    # ================= G) reason の正規化 =================
    print("\n=== G) reason の正規化 ===")
    fake_env(FAKE_RECOMMEND_PICKS="[0,0]", FAKE_RECOMMEND_REASON="")
    out, _m = recommend()
    chk("reason が空でも picks は通す", out.get("ok") is True and out.get("picks") == [0, 0], out)
    chk("空 reason は warnings に残す", any("reason" in w for w in out.get("warnings") or []),
        out.get("warnings"))
    long_reason = "あ" * 80
    fake_env(FAKE_RECOMMEND_REASON=long_reason)
    out, _m = recommend()
    chk("★60字超は切り詰める",
        out.get("ok") is True and len(out.get("reason") or "") <= S.RECOMMEND_REASON_MAX,
        len(out.get("reason") or ""))
    chk("切り詰めを warnings に残す", any("切り詰め" in w for w in out.get("warnings") or []),
        out.get("warnings"))
    fake_env(FAKE_RECOMMEND_REASON="改行と\n空白が  混ざった理由。")
    out, _m = recommend()
    chk("空白は1つに畳む", out.get("reason") == "改行と 空白が 混ざった理由。", out.get("reason"))
    fake_env(FAKE_RECOMMEND_REASON=None)

    # ================= H) /api/health の model_ids =================
    print("\n=== H) /api/health の model_ids(観測前は null) ===")
    make_state(tmp, render_model="haiku")             # 観測ゼロの状態から始める
    httpd = S.Server(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    S.STATE.args.port = port
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        st, h0 = http_json(port, "GET", "/api/health")
        chk("前提: health が 200 で返る", st == 200 and h0.get("ok") is True, st)
        chk("★model_ids は使うエイリアスを列挙する",
            set((h0.get("model_ids") or {}).keys()) == {"sonnet", "haiku"}, h0.get("model_ids"))
        chk("★観測前はすべて null",
            all(v is None for v in (h0.get("model_ids") or {}).values()), h0.get("model_ids"))
        chk("エイリアス自体は従来どおり別に返る",
            h0.get("model") == "sonnet" and h0.get("render_model") == "haiku"
            and h0.get("compile_model") == "sonnet", h0)

        fake_env(FAKE_MODEL_ID="claude-sonnet-5", FAKE_RECOMMEND_PICKS="[1,0]",
                 FAKE_RECOMMEND_REASON="既存顧客に手書きで寄せる。")
        st, r = http_json(port, "POST", "/api/recommend", {"brief": BRIEF, "branches": BRANCHES})
        chk("★HTTP 経由でも正常系は 200 / ok:true", st == 200 and r.get("ok") is True, (st, r))
        chk("HTTP 応答の picks", r.get("picks") == [1, 0], r.get("picks"))
        chk("内部キー _http_status は応答に混ざらない", "_http_status" not in r, list(r.keys()))

        st, h1 = http_json(port, "GET", "/api/health")
        chk("★実行後は観測した正準IDが入る",
            (h1.get("model_ids") or {}).get("sonnet") == "claude-sonnet-5", h1.get("model_ids"))
        chk("★まだ走っていないエイリアスは null のまま",
            (h1.get("model_ids") or {}).get("haiku") is None, h1.get("model_ids"))
        chk("recommend のカウンタが増える", (h1.get("counters") or {}).get("recommend") == 1,
            h1.get("counters"))

        # レンダを1本回すと render_model 側のエイリアスも観測値で埋まる
        fake_env(FAKE_MODEL_ID="claude-haiku-4-5")
        rout, _rec, _rm = S.handle_render({"brief": BRIEF, "question_point": "誰に向けたLPか",
                                           "option": {"label": "既存顧客"},
                                           "sibling_labels": ["新規客"]})
        chk("前提: レンダが成功している", rout.get("ok") is True, rout.get("error"))
        st, h2 = http_json(port, "GET", "/api/health")
        chk("★エイリアスごとに別のIDを持てる",
            (h2.get("model_ids") or {}).get("haiku") == "claude-haiku-4-5"
            and (h2.get("model_ids") or {}).get("sonnet") == "claude-sonnet-5",
            h2.get("model_ids"))

        # modelUsage を返さない実行では、既に観測できた値を消さない(嘘も作らない)
        fake_env(FAKE_NO_MODEL_USAGE="1")
        out3, _m3 = recommend()
        chk("前提: その実行の timing.model_id は null",
            out3.get("ok") is True and out3["timing"].get("model_id") is None, out3.get("timing"))
        st, h3 = http_json(port, "GET", "/api/health")
        chk("★観測できなかった実行は既存の観測値を消さない",
            (h3.get("model_ids") or {}).get("sonnet") == "claude-sonnet-5", h3.get("model_ids"))
        fake_env(FAKE_NO_MODEL_USAGE=None)

        # 要求不備は HTTP でも 400(ok:false のJSONを本文に持つ)
        st, r4 = http_json(port, "POST", "/api/recommend", {"brief": BRIEF, "branches": []})
        chk("★HTTP でも branches 空は 400", st == 400 and r4.get("ok") is False, (st, r4))
        chk("400 の本文も {ok,error,hint} 契約",
            all(k in r4 for k in ("ok", "error", "hint")), list(r4.keys()))
        st, r5 = http_json(port, "POST", "/api/recommend",
                           {"brief": BRIEF, "branches": BRANCHES}, ctype="text/plain")
        chk("Content-Type ガードは従来どおり効く", st == 403, st)
    finally:
        httpd.shutdown()
        httpd.server_close()
    chk("セッションログは書かれている", ev_before or os.path.exists(str(S.STATE.log.path)))

    # ================= I) 純関数の境界 =================
    print("\n=== I) 純関数の境界 ===")
    nb = S.normalize_recommend_branches
    clean, bad = nb([{"question_point": " Q ", "options": ["A", {"label": " B "}, 3, {"x": 1}]}])
    chk("ラベルは文字列でも {label} でも受け、前後空白を落とす",
        bad is None and clean == [{"question_point": "Q", "options": ["A", "B"]}], clean)
    chk("1件でも不正なら全体を拒否する(黙って間引かない)",
        nb([{"question_point": "Q", "options": ["A"]}, {"question_point": "", "options": ["A"]}])[0]
        is None)
    chk("空配列・None・辞書は拒否",
        nb([])[0] is None and nb(None)[0] is None and nb({})[0] is None)

    vp = S.validate_picks
    one = [{"question_point": "Q", "options": ["A", "B"]}]
    chk("正常: (picks, reason, warnings)",
        vp({"picks": [1], "reason": "理由。"}, one)[:2] == ([1], "理由。"))
    chk("picks 欠落は不合格", vp({"reason": "x"}, one)[0] is None)
    chk("bool は整数として通さない", vp({"picks": [True], "reason": "x"}, one)[0] is None)
    chk("応答がオブジェクトでなければ不合格", vp(["picks"], one)[0] is None)
    chk("空の判断点リストなら空 picks が通る", vp({"picks": [], "reason": "x"}, [])[0] == [])

    print("\n" + ("--- FAILED: " + " / ".join(FAILS) if FAILS
                  else "--- 推奨エンジンの検証 / health の model_ids: すべて期待どおり"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
