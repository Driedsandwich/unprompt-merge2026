#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""選択セッションの構築 (AI発注者ペルソナ版・PREREGISTRATION.md 追補の工程2)

工程A (--explode): 一文 → 判断点と選択肢を抽出し sessions/<id>/explode.json に保存、
                  選択肢一覧を標準出力に出す (発注者役エージェントへの提示物)。
工程B (--picks) : 発注者役が意図メモに基づき決めた picks を受け取り、
                  render(視覚トークン)+compile(意図1文) を実行して
                  手渡しJSON (unprompt.compiled_brief.v0) を構築・保存する。
エンジン呼び出しは scripts/pregen_compare.py / server.py を import して継承 (再実装しない)。
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import server  # noqa: E402
import pregen_compare as pg  # noqa: E402

SESS = HERE / "sessions"

BRIEFS = {
    "m01-lp": "かっこいいけど信頼感もあるLPを作って。うちのサービス用。",
    "m02-event": "秋にやる社内勉強会の告知ページ、いい感じにして。",
    "m03-scout": "若手エンジニアに刺さるスカウトメール書いて。",
    "m04-ec": "この新商品の説明文、魅力的にお願い。",
    "m05-portfolio": "転職用のポートフォリオサイト、シンプルだけど印象に残る感じで。",
    "m06-news": "月イチの社内報の巻頭あいさつ、堅すぎない感じで。",
    "m07-recruit": "採用ページの会社紹介、飾らないけど熱意が伝わるように。",
    "m08-apology": "発送遅延のお詫びメール、誠実だけど重すぎないトーンで。",
    "m09-spec": "社内の経費精算をラクにする小さなツールの仕様メモを書いて。",
    "m10-invite": "昔の仲間を集める同窓会の案内、気軽に来たくなるやつ。",
}


def make_runner(args):
    return server.ClaudeRunner(args.claude_bin, args.timeout, args.max_concurrency,
                               allow_api_key=False, effort=args.effort)


def do_explode(runner, bid, model):
    brief = BRIEFS[bid]
    sdir = SESS / bid
    sdir.mkdir(parents=True, exist_ok=True)
    payload, rec = pg.step_explode(runner, brief, model)
    (sdir / "brief.txt").write_text(brief + "\n", encoding="utf-8")
    (sdir / "explode.json").write_text(json.dumps(
        {"brief": bid, "text": brief, "payload": payload,
         "api_ms": rec.get("duration_api_ms"), "at": pg.now_iso()},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n== {bid}: {brief}")
    for i, b in enumerate(payload["branches"]):
        opts = " / ".join(f"[{j}] {o['label']}" for j, o in enumerate(b["options"]))
        print(f"  判断点{i}: {b['question_point']} (係留語: {'・'.join(b['anchor_words'])})")
        print(f"    選択肢: {opts}")


def do_build(runner, bid, picks, model):
    sdir = SESS / bid
    ex = json.loads((sdir / "explode.json").read_text(encoding="utf-8"))
    brief = ex["text"]
    branches = ex["payload"]["branches"]
    if len(picks) != len(branches):
        raise SystemExit(f"picks数 {len(picks)} != 判断点数 {len(branches)}")
    renders = pg.step_render_all(runner, brief, branches, picks, model)
    bad = [i for i, r in enumerate(renders) if not r.get("ok")]
    if bad:
        raise SystemExit(f"render失敗: {bad}: {[renders[i].get('error') for i in bad]}")
    rationales, rec, err = pg.step_compile(runner, brief, branches, picks, model)
    if err:
        raise SystemExit(f"compile失敗: {err}")
    decisions = []
    for i, b in enumerate(branches):
        tokens = renders[i]["tokens"]
        decisions.append({
            "question_point": b["question_point"],
            "anchor_words": b["anchor_words"],
            "status": "decided",
            "chosen_label": b["options"][picks[i]]["label"],
            "visual_tokens": tokens,
            "tone_example": None,
            "intent": rationales.get(b["question_point"], ""),
        })
    handoff = {
        "format": "unprompt.compiled_brief.v0",
        "source_brief": brief,
        "compiled_at": pg.now_iso(),
        "decisions": decisions,
        "residual_ambiguity_assessment": ex["payload"].get("residual_ambiguity_assessment", ""),
        "missing_materials": ex["payload"].get("missing_materials", []),
    }
    (sdir / "handoff.json").write_text(json.dumps(handoff, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    (sdir / "choice_record.json").write_text(json.dumps(
        {"picks": picks,
         "labels": [branches[i]["options"][picks[i]]["label"] for i in range(len(picks))],
         "decided_at": pg.now_iso(), "owner": "AIペルソナ (意図メモ owner_memos.md 準拠)"},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  [{bid}] handoff.json 構築完了 ({len(decisions)}決定)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--explode", action="store_true")
    ap.add_argument("--picks", default=None, help="カンマ区切りインデックス")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--claude-bin", default="claude")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--max-concurrency", type=int, default=4)
    ap.add_argument("--effort", default="low")
    args = ap.parse_args()
    runner = make_runner(args)
    if args.explode:
        do_explode(runner, args.id, args.model)
    elif args.picks is not None:
        do_build(runner, args.id, [int(x) for x in args.picks.split(",")], args.model)
    else:
        raise SystemExit("--explode か --picks を指定")


if __name__ == "__main__":
    main()
