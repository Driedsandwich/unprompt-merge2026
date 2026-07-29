#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GYAKUMON — 並置証明(SplitCompare)の事前生成パイプライン(python3 標準ライブラリのみ)

目的:
  デモ第二の驚き「元の一文 → 無難な別物」 vs 「コンパイル済みブリーフ → 選択が全て反映されたLP」を
  実生成物で用意する。ここで作る2つの HTML は、デモ当日にその場で生成するのではなく
  事前に生成して app/compare/ に置く(開示対象 — docs/DISCLOSURE.md #7)。

対照条件(拘束・公平性):
  RAW 側と COMPILED 側は、モデル・effort・タイムアウト・LP制作者 system の骨格を同一にする。
  違うのは「ユーザープロンプトとして何を渡すか」だけ:
    RAW      : ブリーフ一文(そのまま)
    COMPILED : 同じ一文を GYAKUMON に通して得た「コンパイル済みブリーフ MD」
  COMPILED 側の system にだけ 2 行の追加がある(視覚トークンの厳守 / 選択ラベルの
  HTMLコメント埋め込み)。RAW 側には対応する入力が存在しないため付けようがない。
  この非対称は manifest.json の prompts に全文で残す。

工程:
  1. /api/explode 相当   … ブリーフから判断点(branches)を抽出
  2. /api/render 相当    … 各判断点の第1オプションの視覚トークンを取得(並列)
  3. /api/compile 相当   … 各判断点の「意図」1文を取得
  4. コンパイル済みブリーフ MD を決定論的に組み立て(app/index.html の buildMarkdown と同形)
  5. RAW 側 LP を生成 / COMPILED 側 LP を生成
  6. 選択ラベルが COMPILED 側 HTML のコメントに埋まっているかを機械照合

出力:
  app/compare/raw.html
  app/compare/compiled.html
  app/compare/manifest.json   … ブリーフ・決定一覧・生成時刻・api_ms・使用プロンプト全文・照合結果

実行:
  python3 scripts/pregen_compare.py
  python3 scripts/pregen_compare.py --option-index -1   # 対照が弱いとき、各判断点の最終オプションで再生成
"""

import argparse
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# エンジンフラグ・一時cwd方式・JSON抽出・検証は server.py の実装を「そのまま」使う。
# コピーすると Gate1 で裁定済みの拘束から静かにずれるため、再実装しない。
import server  # noqa: E402

OUT_DIR = BASE_DIR / "app" / "compare"

DEMO_BRIEF = "モダンだけど温かみのあるLPを作って。うちの会社のやつ。"

# LP制作者 system の骨格(RAW / COMPILED 共通部分)
LP_SYSTEM_BASE = """あなたはLP制作者である。与えられた発注内容だけを根拠に、企業のランディングページを1枚作る。

## 出力規則

- 出力は単一の自己完結 HTML ドキュメントのみ。<!DOCTYPE html> で始め </html> で終える。
- CSS はすべて <style> タグ内にインラインで書く。外部CSS・外部フォント・外部画像・外部JSを一切参照しない。
  画像が必要な箇所は CSS のグラデーション・図形・絵文字・インライン SVG で表現する。
- コードフェンス(```)・前置き・後書き・説明文を一切書かない。1文字目が < であること。
- 日本語のLP。ヒーロー / 価値提案 / 特徴3点 / 会社について / CTA / フッター を含む縦1カラム構成。
- 全体で概ね 160 行以内に収める。冗長な繰り返しを書かない。
- 会社名や実績などブリーフに書かれていない事実を断定的に作らない。必要なら〈会社名〉のような
  プレースホルダを使う。
"""

LP_SYSTEM_COMPILED_EXTRA = """
## コンパイル済みブリーフの扱い(この実行に固有)

- 入力は GYAKUMON が出力した「コンパイル済みブリーフ」である。発注者が確定した判断点が
  明示されている。書かれている決定はすべて実装に反映せよ。解釈で薄めない。
- 「視覚トークン」に書かれたパレット(16進3色)・見出し書体(serif/sans/rounded)・
  密度(airy/normal/dense)・角(sharp/soft)は厳密に実装する。パレットの3色は
  [地色, 主要色, 強調色] の役割で使い、他の色相を勝手に足さない。
  密度 airy は余白を大きく行間を広く、dense は詰めて情報量を多く、
  角 sharp は border-radius:0、soft は大きめの border-radius とする。
- 「トーン例」の文体をコピーの基調にする。
- 各決定を反映した要素の直前に、次の形の HTML コメントを1つ置く(機械照合に使う):
  <!-- GYAKUMON-CHOICE: 判断点 = 選択ラベル -->
  判断点と選択ラベルはブリーフに書かれている文字列をそのまま使う。すべての決定について1回以上置く。
  <style> 内の CSS 規則に印を付ける場合は同じ本文を CSS コメント
  /* GYAKUMON-CHOICE: 判断点 = 選択ラベル */ の形で書く。
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def strip_fences(text):
    """コードフェンスや前置きが混ざっても HTML 本体だけを取り出す。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t).strip()
    # 先頭に地の文が混ざった場合は <!DOCTYPE か <html から拾う
    m = re.search(r"<!DOCTYPE\s+html", t, re.I) or re.search(r"<html", t, re.I)
    if m and m.start() > 0:
        t = t[m.start():]
    # 末尾に後書きが混ざった場合は </html> で切る
    m2 = re.search(r"</html\s*>", t, re.I)
    if m2:
        t = t[:m2.end()]
    return t.strip()


def load_system(path, builder):
    raw = path.read_text(encoding="utf-8")
    return builder(raw)


def step_explode(runner, brief, model):
    system_prompt = load_system(server.EXTRACTION_PROMPT_PATH, server.build_extraction_system)
    rec = runner.run(system_prompt, brief, model)
    if not rec["ok"]:
        raise RuntimeError("explode 失敗: %s / %s" % (rec["error"], rec["hint"]))

    def accept(o):
        return all(k in o for k in server.EXTRACTION_REQUIRED_TOP)

    ex, why = server.extract_json_object(rec["result_text"], accept)
    if ex is None:
        raise RuntimeError("explode のJSONを読めない: %s" % why)
    payload, why = server.validate_extraction(brief, ex)
    if payload is None:
        raise RuntimeError("explode の検証に失敗: %s" % why)
    if not payload["branches"]:
        raise RuntimeError("判断点が0件(棄却 %d 件)。ブリーフを見直す。"
                           % len(payload["rejected_branches"]))
    return payload, rec


def step_render_all(runner, brief, branches, picks, model):
    """各判断点の選択オプションについて視覚トークンを取る(並列。枠は runner が制御)。"""
    system_prompt = load_system(server.RENDER_PROMPT_PATH, server.build_render_system)
    results = [None] * len(branches)

    def work(i):
        b = branches[i]
        label = b["options"][picks[i]]["label"]
        siblings = [o["label"] for j, o in enumerate(b["options"]) if j != picks[i]]
        user_payload = json.dumps({
            "brief": brief,
            "question_point": b["question_point"],
            "option": {"label": label},
            "sibling_labels": siblings,
        }, ensure_ascii=False, indent=2)
        rec = runner.run(system_prompt, user_payload, model)
        if not rec["ok"]:
            results[i] = {"ok": False, "error": rec["error"], "api_ms": rec["api_ms"]}
            return

        def accept(o):
            src = o.get("tokens") if isinstance(o.get("tokens"), dict) else o
            return isinstance(src, dict) and "palette" in src and "tone_sample" in src

        obj, why = server.extract_json_object(rec["result_text"], accept)
        if obj is None:
            results[i] = {"ok": False, "error": "JSON抽出不能: %s" % why, "api_ms": rec["api_ms"]}
            return
        tokens, warn = server.validate_tokens(obj)
        if tokens is None:
            results[i] = {"ok": False, "error": "検証失敗: %s" % warn, "api_ms": rec["api_ms"]}
            return
        results[i] = {"ok": True, "tokens": tokens, "api_ms": rec["api_ms"]}

    threads = [threading.Thread(target=work, args=(i,)) for i in range(len(branches))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def step_compile(runner, brief, branches, picks, model):
    system_prompt = load_system(server.COMPILE_PROMPT_PATH, server.build_compile_system)
    decisions = []
    for i, b in enumerate(branches):
        decisions.append({
            "question_point": b["question_point"],
            "anchor_words": b["anchor_words"],
            "status": "decided",
            "chosen_label": b["options"][picks[i]]["label"],
        })
    user_payload = json.dumps({"brief": brief, "decisions": decisions},
                              ensure_ascii=False, indent=2)
    rec = runner.run(system_prompt, user_payload, model)
    qps = [d["question_point"] for d in decisions]
    if not rec["ok"]:
        return {}, rec, "compile 呼び出し失敗: %s" % rec["error"]

    def accept(o):
        if isinstance(o.get("rationales"), dict):
            return True
        return bool(o) and all(isinstance(v, str) for v in o.values()) and any(k in qps for k in o)

    obj, why = server.extract_json_object(rec["result_text"], accept)
    if obj is None:
        return {}, rec, "根拠文のJSONを読めない: %s" % why
    rationales, warn = server.validate_rationales(obj, qps)
    if rationales is None:
        return {}, rec, "根拠文の検証に失敗: %s" % warn
    return rationales, rec, None


def tokens_line(t):
    pal = t.get("palette") or []
    return "パレット %s、見出し=%s、密度=%s、角=%s" % (
        " / ".join(pal), t.get("heading_font", "-"), t.get("density", "-"), t.get("corner", "-"))


def build_compiled_brief_md(brief, payload, picks, renders, rationales):
    """app/index.html の buildMarkdown と同形の MD を決定論的に組み立てる。
    ブラウザ実測値(タイプ文字数・沈黙秒)はここでは持てないので、その2行は出さない。"""
    branches = payload["branches"]
    L = []
    L.append("# コンパイル済みブリーフ")
    L.append("")
    L.append("## 発注者が書いた唯一の文")
    L.append("")
    L.append("> " + brief.replace("\n", "\n> "))
    L.append("")
    L.append("- あなたがタイプした文字(最初の一文以降): 0")
    L.append("- あなたの選択: %d" % len(branches))
    L.append("")
    L.append("## 決めた判断点")
    L.append("")
    for i, b in enumerate(branches):
        label = b["options"][picks[i]]["label"]
        L.append("### " + b["question_point"])
        L.append("")
        L.append("- 選択: " + label)
        L.append("- 原文の根拠語: " + " ".join("「%s」" % a for a in b["anchor_words"]))
        r = renders[i]
        if r and r.get("ok"):
            L.append("- 視覚トークン: " + tokens_line(r["tokens"]))
            tone = r["tokens"].get("tone_sample")
            if tone:
                L.append("- トーン例: " + tone.replace("\n", " "))
        ra = rationales.get(b["question_point"])
        if ra:
            L.append("- 意図: " + ra)
        L.append("")
    L.append("## 残存曖昧度")
    L.append("")
    L.append(payload.get("residual_ambiguity_assessment") or "(評価なし)")
    L.append("")
    L.append("## 発注者からの提供が必要な材料")
    L.append("")
    if payload.get("missing_materials"):
        for m in payload["missing_materials"]:
            L.append("- " + m)
    else:
        L.append("- (なし)")
    L.append("")
    L.append("---")
    L.append("")
    L.append("このブリーフは、上の1文と %d 回の選択だけから GYAKUMON が機械的に組み立てた。"
             % len(branches))
    L.append("本文の文言は発注者の原文と選択ラベルに由来する。AIが生成したのは各「意図」の1文のみ。")
    return "\n".join(L)


def gen_lp(runner, system_prompt, user_prompt, model):
    rec = runner.run(system_prompt, user_prompt, model)
    if not rec["ok"]:
        raise RuntimeError("LP生成に失敗: %s / %s" % (rec["error"], rec["hint"]))
    html = strip_fences(rec["result_text"])
    if "<" not in html:
        raise RuntimeError("LP生成の応答が HTML に見えない(先頭: %r)" % html[:120])
    return html, rec


# HTMLコメント <!-- --> と、<style> 内で使われる CSSコメント /* */ の両方を拾う。
# 実測: モデルは <style> 内の規則に対しては CSS コメントで印を付ける(HTMLコメントは
# CSS ブロック内では機能しないので、これはモデル側が正しい)。片方だけ数えると
# 「反映されているのに未照合」という偽陰性が出る。
COMMENT_RE = re.compile(r"<!--(.*?)-->|/\*(.*?)\*/", re.S)


def verify_choice_comments(html, decisions):
    """選択ラベルが GYAKUMON-CHOICE コメントに埋まっているかを機械照合する。"""
    comments = [(a or b) for a, b in COMMENT_RE.findall(html)]
    comments = [c for c in comments if "GYAKUMON-CHOICE" in c]
    traces = []
    for d in decisions:
        hit = next((c.strip() for c in comments if d["chosen_label"] in c), None)
        traces.append({
            "question_point": d["question_point"],
            "chosen_label": d["chosen_label"],
            "found_in_comment": hit is not None,
            "comment": hit,
        })
    return {
        "gyakumon_choice_comments_total": len(comments),
        "traced": sum(1 for t in traces if t["found_in_comment"]),
        "of": len(decisions),
        "traces": traces,
    }


def color_signature(html):
    """HTML 中の 16進カラーを数え上げる(2枚の見た目差を機械的に示す簡易指標)。"""
    hexes = [h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}\b", html)]
    uniq = sorted(set(hexes))
    return {"hex_colors_unique": uniq, "hex_colors_count": len(hexes), "bytes": len(html.encode("utf-8"))}


def main():
    ap = argparse.ArgumentParser(description="並置証明(SplitCompare)の事前生成")
    ap.add_argument("--brief", default=DEMO_BRIEF, help="デモブリーフ(既定: 固定の一文)")
    ap.add_argument("--model", default="sonnet", help="全工程のモデル(既定: sonnet)")
    ap.add_argument("--effort", default=server.DEFAULT_EFFORT, help="claude --effort(既定: low)")
    ap.add_argument("--timeout", type=int, default=240, help="LP生成のタイムアウト秒(既定: 240)")
    ap.add_argument("--max-concurrency", type=int, default=6)
    ap.add_argument("--claude-bin", default="claude")
    ap.add_argument("--option-index", type=int, default=0,
                    help="各判断点で「決めた」ことにするオプションの位置(既定: 0=第1。-1で最終)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # LP生成は 2000トークン級になるので、タイムアウトは runner 生成時に長い方へ寄せる。
    runner = server.ClaudeRunner(args.claude_bin, args.timeout, args.max_concurrency,
                                 allow_api_key=False, effort=args.effort)
    started = now_iso()
    t_all = time.monotonic()
    timings = {}

    try:
        print("[1/5] explode …", flush=True)
        payload, rec_ex = step_explode(runner, args.brief, args.model)
        branches = payload["branches"]
        timings["explode"] = {"api_ms": rec_ex["api_ms"], "wall_ms": rec_ex["wall_ms"]}
        picks = []
        for b in branches:
            n = len(b["options"])
            idx = args.option_index if args.option_index >= 0 else n + args.option_index
            picks.append(max(0, min(n - 1, idx)))
        for i, b in enumerate(branches):
            print("      - %s → %s" % (b["question_point"], b["options"][picks[i]]["label"]), flush=True)

        print("[2/5] render(%d件・並列) …" % len(branches), flush=True)
        renders = step_render_all(runner, args.brief, branches, picks, args.model)
        timings["render"] = [{"api_ms": (r or {}).get("api_ms"), "ok": bool((r or {}).get("ok"))}
                             for r in renders]

        print("[3/5] compile(意図) …", flush=True)
        rationales, rec_cp, cp_err = step_compile(runner, args.brief, branches, picks, args.model)
        timings["compile"] = {"api_ms": rec_cp["api_ms"], "wall_ms": rec_cp["wall_ms"],
                              "error": cp_err}

        compiled_md = build_compiled_brief_md(args.brief, payload, picks, renders, rationales)
        (out_dir / "compiled_brief.md").write_text(compiled_md, encoding="utf-8")

        raw_system = LP_SYSTEM_BASE
        compiled_system = LP_SYSTEM_BASE + LP_SYSTEM_COMPILED_EXTRA

        print("[4/5] RAW 側 LP 生成 …", flush=True)
        raw_html, rec_raw = gen_lp(runner, raw_system, args.brief, args.model)
        timings["raw_lp"] = {"api_ms": rec_raw["api_ms"], "wall_ms": rec_raw["wall_ms"]}
        (out_dir / "raw.html").write_text(raw_html, encoding="utf-8")

        print("[5/5] COMPILED 側 LP 生成 …", flush=True)
        compiled_html, rec_cmp = gen_lp(runner, compiled_system, compiled_md, args.model)
        timings["compiled_lp"] = {"api_ms": rec_cmp["api_ms"], "wall_ms": rec_cmp["wall_ms"]}
        (out_dir / "compiled.html").write_text(compiled_html, encoding="utf-8")

        decisions = []
        for i, b in enumerate(branches):
            r = renders[i]
            decisions.append({
                "question_point": b["question_point"],
                "anchor_words": b["anchor_words"],
                "options": [o["label"] for o in b["options"]],
                "picked_index": picks[i],
                "chosen_label": b["options"][picks[i]]["label"],
                "tokens": r["tokens"] if (r and r.get("ok")) else None,
                "render_error": None if (r and r.get("ok")) else (r or {}).get("error"),
                "rationale": rationales.get(b["question_point"]),
            })

        manifest = {
            "format": "gyakumon.split_compare.v0",
            "generated_at": started,
            "finished_at": now_iso(),
            "total_wall_ms": round((time.monotonic() - t_all) * 1000),
            "pregenerated": True,
            "disclosure": ("並置比較の2枚は事前生成物である。デモ実行時にその場で生成していない。"
                           "RAW/COMPILED は同一モデル・同一 effort・同一 LP制作者 system 骨格で、"
                           "違いはユーザープロンプト(一文 vs コンパイル済みブリーフ)のみ。"),
            "engine": {
                "cli": args.claude_bin,
                "model": args.model,
                "effort": args.effort,
                "timeout_s": args.timeout,
                "flags": ["--system-prompt", "--strict-mcp-config", "--setting-sources project",
                          "--effort", "--model", "--output-format json", "-p --"],
                "cwd": "リポジトリ外の一時ディレクトリ(CLAUDE.md 注入遮断)",
                "auth": "Claude Code サブスクリプション(ANTHROPIC_API_KEY は子プロセス env から除去)",
            },
            "brief": args.brief,
            "option_index": args.option_index,
            "decisions": decisions,
            "residual_ambiguity_assessment": payload.get("residual_ambiguity_assessment"),
            "missing_materials": payload.get("missing_materials"),
            "rejected_branches": payload.get("rejected_branches"),
            "compiled_brief_md": compiled_md,
            "timings": timings,
            "verification": {
                "compiled": verify_choice_comments(compiled_html, decisions),
                "raw_signature": color_signature(raw_html),
                "compiled_signature": color_signature(compiled_html),
            },
            "prompts": {
                "lp_system_raw": raw_system,
                "lp_system_compiled": compiled_system,
                "lp_user_raw": args.brief,
                "lp_user_compiled": compiled_md,
                "extraction_prompt_file": str(server.EXTRACTION_PROMPT_PATH.relative_to(BASE_DIR)),
                "render_prompt_file": str(server.RENDER_PROMPT_PATH.relative_to(BASE_DIR)),
                "compile_prompt_file": str(server.COMPILE_PROMPT_PATH.relative_to(BASE_DIR)),
            },
            "outputs": {"raw": "raw.html", "compiled": "compiled.html",
                        "compiled_brief": "compiled_brief.md"},
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        v = manifest["verification"]["compiled"]
        print("")
        print("完了: %s" % out_dir)
        print("  選択の機械照合: %d/%d(GYAKUMON-CHOICE コメント %d 個)"
              % (v["traced"], v["of"], v["gyakumon_choice_comments_total"]))
        print("  raw.html      : %d bytes / 色 %d 種"
              % (manifest["verification"]["raw_signature"]["bytes"],
                 len(manifest["verification"]["raw_signature"]["hex_colors_unique"])))
        print("  compiled.html : %d bytes / 色 %d 種"
              % (manifest["verification"]["compiled_signature"]["bytes"],
                 len(manifest["verification"]["compiled_signature"]["hex_colors_unique"])))
        return 0
    finally:
        runner.cleanup()


if __name__ == "__main__":
    sys.exit(main())
