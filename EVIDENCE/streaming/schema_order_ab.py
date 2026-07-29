#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スキーマ順 A/B(2026-07-29)。

A(before) = 修正前の prompts/extraction_product_v1.txt(スキーマ例が meta 先)
            + 修正前の上書き規則(branches, residual_ambiguity_assessment, missing_materials)
B(after)  = 修正後のプロンプトファイル(スキーマ例も branches 先)
            + 現行 build_extraction_stream_system

server.py の StreamingExtractionParser / validate_branch をそのまま使うので、
ここで測る first_branch_ms は /api/explode_stream が返す値と同じ定義
(送信 → 最初の「検証を通った分岐」を送り出せる時刻)。

同一ブリーフで A→B / B→A を交互に回して、機械側のドリフト(claude CLI の
初期化時間は実測で 4〜10秒ぶれる)が片方の腕に偏らないようにする。
"""
import json, os, statistics, subprocess, sys, time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
import server as S  # noqa: E402

NEW_RAW = open(os.path.join(REPO, "prompts/extraction_product_v1.txt"), encoding="utf-8").read()
OLD_RAW = subprocess.run(["git", "show", "HEAD:prompts/extraction_product_v1.txt"],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout


def build_before(raw):
    """修正前の build_extraction_stream_system と同一の合成(meta 2項の順だけ旧)。"""
    props = S.EXTRACTION_SCHEMA["properties"]
    schema = {
        "type": "object",
        "properties": {
            "branches": props["branches"],
            "residual_ambiguity_assessment": props["residual_ambiguity_assessment"],
            "missing_materials": props["missing_materials"],
        },
        "required": ["branches", "residual_ambiguity_assessment", "missing_materials"],
    }
    adapted = raw.replace(
        "出力は必ず report_branches ツール呼び出しのみで行う。地の文・前置き・後書きを書かない。",
        "出力は単一のJSONオブジェクトのみで行う。地の文・前置き・後書きを書かない。")
    return adapted + (
        "\n\n## 出力規則(この実行環境での上書き)\n\n"
        "- コードフェンス(```)・説明・前置き・後書きを一切付けず、単一のJSONオブジェクトのみを出力せよ。\n"
        "- 思考・分析・検討過程を書かない。即座に結論のJSONだけを書く。\n"
        "- そのJSONオブジェクトは次のJSONスキーマに厳密に従うこと。"
        "フィールド順もスキーマの順とし、branches を最初に書く。"
        "residual_ambiguity_assessment と missing_materials は branches を書き終えた後に書く:\n\n"
        + json.dumps(schema, ensure_ascii=False, indent=2) +
        "\n\n- スキーマの required をすべて満たし、スキーマにないフィールドを追加しないこと。\n"
        "- branches の各要素は1つ書き終えるごとに完結させ、後から書き直さないこと"
        "(サーバは1件書き終わるたびに検証して画面へ送る)。\n"
        "- anchor_words はサーバ側で「ブリーフ原文の連続部分文字列か」を機械検証する。"
        "一字でも異なる引用(言い換え・要約・表記正規化・空白の付け外し)を含む分岐は棄却され、"
        "ユーザーには表示されない。原文からコピーした文字列だけを入れよ。\n"
        "\n## 対象ブリーフ(原文)\n\n"
        "ユーザーメッセージとして与えられる本文全体がブリーフ原文である。これに対して抽出のみを行え。\n")


ARMS = {
    "A_before": build_before(OLD_RAW),
    "B_after": S.build_extraction_stream_system(NEW_RAW),
}


def one_run(runner, system_prompt, brief, model):
    """1回の run_stream を実測。戻り値: (first_branch_ms, first_delta_ms, nbranches, api_ms)"""
    parser = S.StreamingExtractionParser()
    t0 = time.monotonic()
    ms = lambda: round((time.monotonic() - t0) * 1000)
    first_delta = first_branch = None
    n = 0
    api_ms = None
    stream = runner.run_stream(system_prompt, brief, model)
    try:
        for kind, val in stream:
            if kind == "text":
                if first_delta is None:
                    first_delta = ms()
                for ev, obj, idx in parser.feed(val):
                    if ev == "branch":
                        br, _why = S.validate_branch(brief, obj, idx)
                        if br is not None:
                            n += 1
                            if first_branch is None:
                                first_branch = ms()
            elif kind == "result":
                api_ms = val.get("api_ms")
            elif kind == "error":
                return None, first_delta, 0, None
    finally:
        stream.close()
    return first_branch, first_delta, n, api_ms


def main():
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    ids = sys.argv[2].split(",") if len(sys.argv) > 2 else ["lp-warm", "cafe-insta", "portfolio"]
    briefs = {b["id"]: b["text"] for b in json.load(open(os.path.join(REPO, "data/briefs.json"), encoding="utf-8"))}
    runner = S.ClaudeRunner("claude", 120, 1, effort="low")
    model = "sonnet"
    rows = []
    print("A/B: A_before(旧プロンプト・スキーマ例 meta先) vs B_after(新プロンプト・スキーマ例 branches先)")
    print("model=%s effort=low 逐次実行(同時実行1)\n" % model)
    try:
        for r in range(reps):
            for bid in ids:
                order = ["A_before", "B_after"] if (r + ids.index(bid)) % 2 == 0 else ["B_after", "A_before"]
                for arm in order:
                    fb, fd, n, api = one_run(runner, ARMS[arm], briefs[bid], model)
                    rows.append({"rep": r, "brief": bid, "arm": arm,
                                 "first_branch_ms": fb, "first_delta_ms": fd,
                                 "branches": n, "api_ms": api})
                    print("rep%d %-12s %-9s first_branch=%-7s first_delta=%-7s branches=%d api_ms=%s"
                          % (r, bid, arm, fb, fd, n, api), flush=True)
    finally:
        runner.cleanup()

    print("\n--- 集計(first_branch_ms) ---")
    for arm in ("A_before", "B_after"):
        v = [x["first_branch_ms"] for x in rows if x["arm"] == arm and x["first_branch_ms"] is not None]
        d = [x["first_delta_ms"] for x in rows if x["arm"] == arm and x["first_delta_ms"] is not None]
        if not v:
            continue
        print("%-9s n=%d  median=%dms  min=%d max=%d   | first_delta median=%dms  "
              "| モデル時間(first_branch - first_delta) median=%dms"
              % (arm, len(v), statistics.median(v), min(v), max(v), statistics.median(d),
                 statistics.median([x["first_branch_ms"] - x["first_delta_ms"] for x in rows
                                    if x["arm"] == arm and x["first_branch_ms"] is not None])))
    out = os.path.join(REPO, "EVIDENCE/streaming/schema_order_ab.jsonl")
    with open(out, "a", encoding="utf-8") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print("\n生ログ追記: %s" % out)


if __name__ == "__main__":
    main()
