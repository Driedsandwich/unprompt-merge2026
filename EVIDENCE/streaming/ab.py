#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A/B: 現行スキーマ順(meta先) vs branches先。init/first_delta/branch1/result を実測。"""
import json, os, subprocess, sys, tempfile, time

REPO = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
sys.path.insert(0, REPO)
import server as S  # noqa

RAW = open(os.path.join(REPO, "prompts/extraction_product_v1.txt"), encoding="utf-8").read()


def build_branches_first(raw):
    """branches を先頭に置いたスキーマで出力規則を作る。"""
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
        "- そのJSONオブジェクトは次のJSONスキーマに厳密に従うこと(フィールド順もスキーマの順とする。"
        "branches を最初に書き、residual_ambiguity_assessment と missing_materials は最後に書く):\n\n"
        + json.dumps(schema, ensure_ascii=False, indent=2) +
        "\n\n- スキーマの required をすべて満たし、スキーマにないフィールドを追加しないこと。\n"
        "- anchor_words はサーバ側で「ブリーフ原文の連続部分文字列か」を機械検証する。"
        "一字でも異なる引用を含む分岐は棄却され、ユーザーには表示されない。原文からコピーした文字列だけを入れよ。\n"
        "\n## 対象ブリーフ(原文)\n\n"
        "ユーザーメッセージとして与えられる本文全体がブリーフ原文である。これに対して抽出のみを行え。\n")


def run(label, sysprompt, brief, model="sonnet"):
    wd = tempfile.mkdtemp(prefix="ab_")
    env = os.environ.copy()
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(k, None)
    cmd = ["claude", "--system-prompt", sysprompt, "--strict-mcp-config", "--setting-sources", "project",
           "--effort", "low", "--model", model,
           "--output-format", "stream-json", "--include-partial-messages", "--verbose",
           "-p", "--", brief]
    t0 = time.monotonic()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         bufsize=1, cwd=wd, stdin=subprocess.DEVNULL, env=env)
    ms = lambda: round((time.monotonic() - t0) * 1000)
    acc = ""
    marks = {}
    parser = S.StreamingExtractionParser() if hasattr(S, "StreamingExtractionParser") else None
    nbr = 0
    for line in p.stdout:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            marks["init"] = ms()
        elif t == "stream_event":
            e = ev.get("event") or {}
            if e.get("type") == "content_block_delta":
                txt = (e.get("delta") or {}).get("text") or ""
                if txt:
                    marks.setdefault("first_delta", ms())
                    acc += txt
                    if parser:
                        for kind, obj, _i in parser.feed(txt):
                            if kind == "meta":
                                marks.setdefault("meta", ms())
                            elif kind == "branch":
                                nbr += 1
                                marks["branch%d" % nbr] = ms()
        elif t == "result":
            marks["result"] = ms()
            marks["_api_ms"] = ev.get("duration_api_ms")
            marks["_ttft"] = ev.get("ttft_ms")
    p.wait()
    order = ["init", "first_delta", "meta"] + ["branch%d" % i for i in range(1, 8)] + ["result"]
    out = " ".join("%s=%s" % (k, marks[k]) for k in order if k in marks)
    print("%-16s %s api_ms=%s ttft=%s len=%d" % (label, out, marks.get("_api_ms"), marks.get("_ttft"), len(acc)),
          flush=True)
    return marks


BRIEFS = [
    "モダンだけど温かみのあるLPを作って。うちの会社のやつ。",
    "うちのカフェのInstagramプロフィールと固定投稿を、いい感じにしてほしい。開店1周年なので。",
]
A = S.build_extraction_system(RAW)
B = build_branches_first(RAW)
for b in BRIEFS:
    print("--- brief=%r" % b[:26], flush=True)
    run("A_meta_first", A, b)
    run("B_branch_first", B, b)
