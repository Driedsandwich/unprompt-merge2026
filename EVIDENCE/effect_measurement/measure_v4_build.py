#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測定v4 構築ランナー (PREREGISTRATION.md 追補4)

工程 (サブコマンド):
  --explode-all   : 新エンジン(extraction_product_v2=文外判断点入り)で12本を爆散
                    → sessions/<id>/explode_v4.json (棄却・beyond_text数もそのまま保存)
  --render-all    : 全判断点×全選択肢の視覚トークンを事前レンダ
                    → sessions/<id>/options_render_v4.json (v2手続きの継承)
  --present --id  : 発注者役エージェントへの提示文 (メモ+判断点+見本トークン) を標準出力へ
  --build --id --picks 1,0,2,... : 見本つき選択の結果から handoff_v4.json を構築
                    (unprompt.compiled_brief.v1: kind / origin_rationale / generator_models)
  --artifacts     : compiled_v4 を12本生成。raw は v1 固定再利用 (m11/m12のみ新規生成)
                    → pairs_v4/<id>/{raw.html, compiled.html} + measure_manifest_v4.json
  --blind         : 単品提示用ブラインド → blind_v4/<id>/art_1.html, art_2.html
                    (割当は id+シードの決定論。対応表は manifest のみに保存)

エンジン呼び出しは server.py / scripts/pregen_compare.py を import して継承 (再実装しない)。
"""

import argparse
import hashlib
import json
import shutil
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import server  # noqa: E402
import pregen_compare as pg  # noqa: E402
from effect_measure import SPECS  # noqa: E402

SESS = HERE / "sessions"
PAIRS1 = HERE / "pairs"
PAIRS4 = HERE / "pairs_v4"
BLIND4 = HERE / "blind_v4"
MANIFEST = HERE / "measure_manifest_v4.json"

BRIEFS12 = {
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
    "m11-brand": "新しいコーヒー豆ブランドの世界観が伝わる紹介ページ。",
    "m12-faq": "問い合わせが多い返品まわりのFAQページ、探しやすく安心感のある感じ。",
}
IDS = sorted(BRIEFS12)


def make_runner(args):
    return server.ClaudeRunner(args.claude_bin, args.timeout, args.max_concurrency,
                               allow_api_key=False, effort=args.effort)


# ---------------------------------------------------------------- explode
def do_explode_all(runner, model):
    for bid in IDS:
        sdir = SESS / bid
        sdir.mkdir(parents=True, exist_ok=True)
        out = sdir / "explode_v4.json"
        if out.exists():
            print(f"[{bid}] explode_v4 済み — スキップ")
            continue
        brief = BRIEFS12[bid]
        payload, meta = pg.step_explode(runner, brief, model)
        (sdir / "brief.txt").write_text(brief + "\n", encoding="utf-8")
        out.write_text(json.dumps(
            {"brief": bid, "text": brief, "payload": payload, "meta": meta,
             "extraction_prompt": str(server.EXTRACTION_PROMPT_PATH.name),
             "at": pg.now_iso()}, ensure_ascii=False, indent=1), encoding="utf-8")
        kinds = [b.get("kind", "anchored") for b in payload["branches"]]
        print(f"[{bid}] 判断点{len(kinds)}件 (beyond_text {kinds.count('beyond_text')}件・"
              f"棄却{len(payload['rejected_branches'])}件)")


# ---------------------------------------------------------------- render options
def do_render_all(runner, model):
    for bid in IDS:
        sdir = SESS / bid
        out = sdir / "options_render_v4.json"
        if out.exists():
            print(f"[{bid}] options_render_v4 済み — スキップ")
            continue
        ex = json.loads((sdir / "explode_v4.json").read_text(encoding="utf-8"))
        brief, branches = ex["text"], ex["payload"]["branches"]
        acc = {i: {} for i in range(len(branches))}
        maxopt = max(len(b["options"]) for b in branches)
        for j in range(maxopt):
            picks = [min(j, len(b["options"]) - 1) for b in branches]
            renders = pg.step_render_all(runner, brief, branches, picks, model)
            for i, r in enumerate(renders):
                jj = picks[i]
                if jj not in acc[i]:
                    acc[i][jj] = {"label": branches[i]["options"][jj]["label"],
                                  "tokens": r.get("tokens") if r.get("ok") else None,
                                  "error": None if r.get("ok") else r.get("error")}
        bad = [(i, j) for i in acc for j in acc[i] if acc[i][j]["tokens"] is None]
        if bad:
            raise SystemExit(f"[{bid}] レンダ欠損 {bad} — 再実行する")
        out.write_text(json.dumps(
            {"options": {str(i): [acc[i][j] for j in sorted(acc[i])] for i in acc},
             "at": pg.now_iso()}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{bid}] options_render_v4 完了 ({sum(len(v) for v in acc.values())}レンダ)")


# ---------------------------------------------------------------- present
def memo_of(bid):
    txt = (HERE / "owner_memos.md").read_text(encoding="utf-8")
    blocks = txt.split("## ")
    hits = [b for b in blocks if b.startswith(bid)]
    if not hits:
        raise SystemExit(f"owner_memos.md に {bid} のメモが無い")
    return hits[-1].split("\n", 1)[1].strip()  # 追記が複数あれば最新を使う


def tokens_line(t):
    return "色%s・見出し%s・密度%s・角%s・トーン例「%s」" % (
        "/".join(t.get("palette", [])), t.get("heading_font", "-"),
        t.get("density", "-"), t.get("corner", "-"),
        str(t.get("tone_sample", "")).replace("\n", " "))


def do_present(bid):
    sdir = SESS / bid
    ex = json.loads((sdir / "explode_v4.json").read_text(encoding="utf-8"))
    opt = json.loads((sdir / "options_render_v4.json").read_text(encoding="utf-8"))["options"]
    L = []
    L.append("# 発注者役への提示 (%s)" % bid)
    L.append("")
    L.append("## あなた (発注者) の意図メモ")
    L.append(memo_of(bid))
    L.append("")
    L.append("## 依頼文")
    L.append(ex["text"])
    L.append("")
    L.append("## 判断点 (各1つ選ぶ。根拠はメモのみ)")
    for i, b in enumerate(ex["payload"]["branches"]):
        kind = b.get("kind", "anchored")
        head = "判断点%d: %s" % (i, b["question_point"])
        if kind == "beyond_text":
            head += " 【文には書かれていません — 由来: %s】" % b.get("origin_rationale", "")
        else:
            head += " (係留語: %s)" % "・".join(b["anchor_words"])
        L.append(head)
        for j, o in enumerate(opt[str(i)]):
            L.append("  [%d] %s — 見本: %s" % (j, o["label"], tokens_line(o["tokens"])))
    return "\n".join(L)


# ---------------------------------------------------------------- build handoff
def do_build(runner, bid, picks, model):
    sdir = SESS / bid
    ex = json.loads((sdir / "explode_v4.json").read_text(encoding="utf-8"))
    brief, branches = ex["text"], ex["payload"]["branches"]
    if len(picks) != len(branches):
        raise SystemExit(f"picks数 {len(picks)} != 判断点数 {len(branches)}")
    opt = json.loads((sdir / "options_render_v4.json").read_text(encoding="utf-8"))["options"]
    renders = []
    for i in range(len(branches)):
        t = opt[str(i)][picks[i]]["tokens"]
        if not t:
            raise SystemExit(f"branch{i} opt{picks[i]} のトークン欠損")
        renders.append(t)

    # compile: kind / origin_rationale を渡す (compile_v1 規則4)
    system_prompt = pg.load_system(server.COMPILE_PROMPT_PATH, server.build_compile_system)
    decisions_req = []
    for i, b in enumerate(branches):
        d = {"question_point": b["question_point"], "anchor_words": b["anchor_words"],
             "status": "decided", "chosen_label": b["options"][picks[i]]["label"]}
        if b.get("kind") == "beyond_text":
            d["kind"] = "beyond_text"
            d["origin_rationale"] = b.get("origin_rationale", "")
        decisions_req.append(d)
    rec = runner.run(system_prompt, json.dumps({"brief": brief, "decisions": decisions_req},
                                               ensure_ascii=False, indent=2), model)
    if not rec["ok"]:
        raise SystemExit("compile 失敗: %s" % rec["error"])
    qps = [d["question_point"] for d in decisions_req]

    def accept(o):
        if isinstance(o.get("rationales"), dict):
            return True
        return bool(o) and all(isinstance(v, str) for v in o.values()) and any(k in qps for k in o)

    obj, why = server.extract_json_object(rec["result_text"], accept)
    if obj is None:
        raise SystemExit("根拠文JSONを読めない: %s" % why)
    rationales, warn = server.validate_rationales(obj, qps)
    if rationales is None:
        raise SystemExit("根拠文の検証失敗: %s" % warn)

    decisions = []
    for i, b in enumerate(branches):
        d = {
            "question_point": b["question_point"],
            "kind": b.get("kind", "anchored"),
            "anchor_words": b["anchor_words"],
            "status": "decided",
            "chosen_label": b["options"][picks[i]]["label"],
            "visual_tokens": renders[i],
            "intent": rationales.get(b["question_point"], ""),
        }
        if b.get("kind") == "beyond_text":
            d["origin_rationale"] = b.get("origin_rationale", "")
        decisions.append(d)
    handoff = {
        "format": "unprompt.compiled_brief.v1",
        "source_brief": brief,
        "compiled_at": pg.now_iso(),
        "generator_models": {"extraction": None, "rationale": rec.get("model_id"),
                             "render": None},  # explode/render の観測IDは manifest 側に記録
        "decisions": decisions,
        "residual_ambiguity_assessment": ex["payload"].get("residual_ambiguity_assessment", ""),
        "missing_materials": ex["payload"].get("missing_materials", []),
    }
    (sdir / "handoff_v4.json").write_text(json.dumps(handoff, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    (sdir / "choice_record_v4.json").write_text(json.dumps(
        {"picks": picks,
         "labels": [branches[i]["options"][picks[i]]["label"] for i in range(len(picks))],
         "kinds": [branches[i].get("kind", "anchored") for i in range(len(picks))],
         "decided_at": pg.now_iso(),
         "owner": "AIペルソナ (意図メモ owner_memos.md 準拠・見本つき選択)"},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{bid}] handoff_v4.json 構築完了 ({len(decisions)}決定・"
          f"beyond_text {sum(1 for d in decisions if d['kind']=='beyond_text')}件)")


# ---------------------------------------------------------------- artifacts
def do_artifacts(runner, model):
    man = {"format": "unprompt.effect_measure.v4", "pairs": {}}
    if MANIFEST.exists():
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for bid in IDS:
        sdir = SESS / bid
        odir = PAIRS4 / bid
        odir.mkdir(parents=True, exist_ok=True)
        brief = (sdir / "brief.txt").read_text(encoding="utf-8").strip()
        handoff_raw = (sdir / "handoff_v4.json").read_text(encoding="utf-8").strip()
        raw_sys, compiled_sys = pg.build_maker_system(SPECS[bid])
        entry = man["pairs"].get(bid) or {"brief_id": bid, "brief": brief, "gen": {}}

        if not (odir / "compiled.html").exists():
            print(f"[{bid}] compiled_v4 生成中...", flush=True)
            html, rec = pg.gen_deliverable(runner, compiled_sys, handoff_raw, model)
            (odir / "compiled.html").write_text(html, encoding="utf-8")
            entry["gen"]["compiled"] = {
                "attempts": rec.get("gen_attempts"),
                "failed_attempts": rec.get("gen_failed_attempts"),
                "model_id_observed": rec.get("model_id")}
        if not (odir / "raw.html").exists():
            src = PAIRS1 / bid / "raw.html"
            if src.exists():
                shutil.copy(src, odir / "raw.html")
                entry["gen"]["raw"] = {"source": "pairs/(v1と同一物・固定再利用)"}
            else:
                print(f"[{bid}] raw 新規生成中 (v1に無いブリーフ)...", flush=True)
                html, rec = pg.gen_deliverable(runner, raw_sys, brief, model)
                (odir / "raw.html").write_text(html, encoding="utf-8")
                entry["gen"]["raw"] = {
                    "attempts": rec.get("gen_attempts"),
                    "failed_attempts": rec.get("gen_failed_attempts"),
                    "model_id_observed": rec.get("model_id")}
        entry["generated_at"] = pg.now_iso()
        entry["compiled_user"] = handoff_raw
        man["pairs"][bid] = entry
        MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{bid}] artifacts 完了")


# ---------------------------------------------------------------- blind
def art_order(bid):
    """単品提示の並び (決定論)。art_1/art_2 のどちらが raw かは manifest のみが知る。"""
    h = int(hashlib.sha256((bid + ":v4-single").encode()).hexdigest(), 16)
    return ("raw", "compiled") if h % 2 == 0 else ("compiled", "raw")


def do_blind():
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for bid in IDS:
        odir = PAIRS4 / bid
        b = BLIND4 / bid
        b.mkdir(parents=True, exist_ok=True)
        first, second = art_order(bid)
        shutil.copy(odir / (first + ".html"), b / "art_1.html")
        shutil.copy(odir / (second + ".html"), b / "art_2.html")
        (b / "brief.txt").write_text(man["pairs"][bid]["brief"] + "\n", encoding="utf-8")
        man["pairs"][bid]["blind_map"] = {"art_1": first, "art_2": second}
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print("blind_v4 構築完了 (対応表は manifest のみ)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--explode-all", action="store_true")
    ap.add_argument("--render-all", action="store_true")
    ap.add_argument("--present", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--artifacts", action="store_true")
    ap.add_argument("--blind", action="store_true")
    ap.add_argument("--id", default=None)
    ap.add_argument("--picks", default=None)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--claude-bin", default="claude")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--max-concurrency", type=int, default=4)
    ap.add_argument("--effort", default="low")
    args = ap.parse_args()
    if args.present:
        print(do_present(args.id))
        return
    if args.blind:
        do_blind()
        return
    runner = make_runner(args)
    if args.explode_all:
        do_explode_all(runner, args.model)
    elif args.render_all:
        do_render_all(runner, args.model)
    elif args.build:
        do_build(runner, args.id, [int(x) for x in args.picks.split(",")], args.model)
    elif args.artifacts:
        do_artifacts(runner, args.model)
    else:
        raise SystemExit("サブコマンドを指定 (--explode-all 等)")


if __name__ == "__main__":
    main()
