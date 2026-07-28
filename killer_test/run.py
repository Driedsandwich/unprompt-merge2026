#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GYAKUMON — キラーテスト・ランナー(ヘッドレスCLI版 / 主経路)

実行例:
    cd .../outputs/dev/gyakumon
    python3 killer_test/run.py --model sonnet
    python3 killer_test/run.py --model fable          # 比較用
    python3 killer_test/run.py --model sonnet --timeout 180

前提:
  - Claude Code サブスクリプションにログイン済みで、`claude -p` がAPIキーなしで動作すること。
  - python3 標準ライブラリのみ使用。npm/Node/外部パッケージ不要。
  - ブラウザ版 killer_test/index.html は「APIキーがある審査員向けの代替経路」。本スクリプトが主経路。

処理:
  1. ../data/briefs.json と ../prompts/extraction_v0.txt をスクリプト位置基準で読込
  2. 各ブリーフを逐次処理(レイテンシ実測を汚さないため並列にしない):
       claude -p <ブリーフ本文> --append-system-prompt <抽出プロンプト+出力規則(JSONのみ+スキーマ全文)>
                 --model <model> --output-format json   (タイムアウト180秒/本)
     cwd はリポジトリ外の一時ディレクトリ(CLAUDE.md / .claude 設定の祖先探索を遮断し、
     クリーンルーム指示が抽出呼び出しへ注入されるのを防ぐ)。
     注意: claude -p は素のAPI呼び出しではなく Claude Code エージェントのシステムプロンプト込みで
     動作する。ブラウザ版(system に直接渡す)とはエンジン条件が異なる(results JSON に注記)。
     CLIバージョンによる読込挙動差の検出のため、本実行前に1回素振りして cli_json を目視確認すること。
  3. CLI出力JSONの result フィールドから、波括弧対応で最初の完全なJSONオブジェクトを抽出
     (コードフェンス混入にも耐性)。パース失敗は1回だけ再実行、なお失敗ならエラー記録して次へ
  4. 機械判定はブラウザ版 index.html と同一基準:
       anchor_words 原文連続部分文字列(空文字・空配列は違反)/ branches<=5 / options 2〜3 /
       必須フィールド充足 / control_zero で branches>0 は「捏造疑い」フラグ(自動不合格にしない)
  5. レイテンシ: 壁時計 + CLI報告の duration_ms / duration_api_ms を全記録。
     8秒線は duration_api_ms 基準で判定(CLI起動オーバーヘッド分離のため)。壁時計は併記。
  6. 出力: EVIDENCE/killer_test/results_<UTC>.json(完全生データ)と SUMMARY_<UTC>.md(表+注記)。
     標準出力に進捗と最終サマリ。
  意味判定(有効分岐率70%、対照ペア妥当性)は管制塔が行う。本スクリプトは機械判定のみ。
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# ========= 定数 =========
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent                       # .../outputs/dev/gyakumon
BRIEFS_PATH = BASE_DIR / "data" / "briefs.json"
PROMPT_PATH = BASE_DIR / "prompts" / "extraction_v0.txt"
EVIDENCE_DIR = BASE_DIR / "EVIDENCE" / "killer_test"

LATENCY_LIMIT_MS = 8000        # 8秒線(duration_api_ms 基準)
DEFAULT_TIMEOUT_S = 180        # claude -p 1本あたりのタイムアウト
DEFAULT_MODEL = "sonnet"       # 製品想定 Sonnet 5。比較用に fable も可

# 抽出スキーマ(ブラウザ版 index.html の EXTRACTION_SCHEMA と同一。順序固定)
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "residual_ambiguity_assessment": {"type": "string", "description": "残存曖昧性の評価"},
        "missing_materials": {
            "type": "array", "items": {"type": "string"},
            "description": "選択では解決できず情報提供が必要な欠落"
        },
        "branches": {
            "type": "array", "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "question_point": {"type": "string"},
                    "anchor_words": {
                        "type": "array", "minItems": 1, "items": {"type": "string"},
                        "description": "原文の連続部分文字列をそのまま・可能な限り最長フレーズで"
                    },
                    "downstream_impact": {"type": "string"},
                    "options": {
                        "type": "array", "minItems": 2, "maxItems": 3,
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "thumbnail_description": {"type": "string"},
                                "px200_rationale": {"type": "string", "description": "200pxで判別できる根拠"}
                            },
                            "required": ["label", "thumbnail_description", "px200_rationale"]
                        }
                    },
                    "default_if_unresolved": {"type": "string"}
                },
                "required": ["question_point", "anchor_words", "downstream_impact",
                             "options", "default_if_unresolved"]
            }
        }
    },
    "required": ["residual_ambiguity_assessment", "missing_materials", "branches"]
}

REQUIRED_TOP = ["residual_ambiguity_assessment", "missing_materials", "branches"]
REQUIRED_BRANCH = ["question_point", "anchor_words", "downstream_impact", "options", "default_if_unresolved"]
REQUIRED_OPTION = ["label", "thumbnail_description", "px200_rationale"]

PASS_LINE_NOTE = (
    "合格線: 10本中8本で有効分岐率70%以上(意味判定は管制塔)+ anchor原文実在 + "
    "各ブリーフに対照ペア1組以上 + 8秒線(duration_api_ms <= 8000ms。壁時計とCLI総時間は"
    "起動オーバーヘッド分離評価のため併記)。対照(完全指定=control_zero)ブリーフで branches>0 は"
    "「捏造疑い」フラグのみで自動不合格にはしない(意味判定は管制塔)。"
)


# ========= プロンプト合成 =========
def build_prompt_prefix(extraction_prompt: str) -> str:
    """抽出プロンプト + 出力規則(JSONのみ+スキーマ全文)。
    --append-system-prompt で system 側へ渡す共通部(ブリーフ本文はユーザープロンプトとして別渡し)。"""
    # report_branches ツール前提の文言を「JSONのみ出力」へ適合(該当行がなければ無変更)
    adapted = extraction_prompt.replace(
        "出力は必ず report_branches ツール呼び出しのみで行う。地の文・前置き・後書きを書かない。",
        "出力は単一のJSONオブジェクトのみで行う。地の文・前置き・後書きを書かない。"
    )
    schema_text = json.dumps(EXTRACTION_SCHEMA, ensure_ascii=False, indent=2)
    output_rules = (
        "\n\n## 出力規則(この実行環境での上書き)\n\n"
        "この実行環境ではツール(report_branches)は使用できない。"
        "上記プロンプト中に report_branches ツール呼び出しへの言及が残っている場合、"
        "それはすべて次の規則に読み替える。\n\n"
        "- コードフェンス(```)・説明・前置き・後書きを一切付けず、単一のJSONオブジェクトのみを出力せよ。\n"
        "- そのJSONオブジェクトは次のJSONスキーマに厳密に従うこと(フィールド順もスキーマの順とする):\n\n"
        + schema_text +
        "\n\n- スキーマの required をすべて満たし、スキーマにないフィールドを追加しないこと。\n"
        "\n## 対象ブリーフ(原文)\n\n"
        "ユーザーメッセージとして与えられる本文全体がブリーフ原文である。これに対して抽出のみを行え。\n"
    )
    return adapted + output_rules


# ========= 応答本文からのJSON抽出(波括弧対応・頑健) =========
def extract_first_json_object(text: str):
    """本文から最初の完全なJSONオブジェクトを波括弧対応で抽出する。
    コードフェンス・前置き・後書きが混ざっていても、最初に閉じた '{...}' で
    json.loads が成功し、かつ REQUIRED_TOP の3キーをすべて持つものを返す。
    (外側JSONが壊れた際に、内側の branch/option オブジェクト単体を
    extraction として誤受理しないための条件。)見つからなければ (None, 理由文字列)。"""
    if not isinstance(text, str) or "{" not in text:
        return None, "本文に '{' が存在しない"
    n = len(text)
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        i = start
        while i < n:
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        try:
                            obj = json.loads(candidate)
                            # REQUIRED_TOP 3キー全存在を要求。内側の branch/option 単体の
                            # dict が先に成立しても捨てて走査を継続する。
                            if isinstance(obj, dict) and all(k in obj for k in REQUIRED_TOP):
                                return obj, None
                        except json.JSONDecodeError:
                            pass
                        break  # この開始位置は不成立。次の '{' から再走査
            i += 1
        start = text.find("{", start + 1)
    return None, "必須3キー(%s)を持つ完全なJSONオブジェクトを抽出できない" % ", ".join(REQUIRED_TOP)


# ========= 機械判定(ブラウザ版 machineChecks と同一基準) =========
def machine_checks(brief_text: str, is_control: bool, ex, api_ms):
    c = {
        "missing_fields": [],
        "branches_count": 0,
        "branches_le5": True,
        "options_count_ok": True,
        "anchor_total": 0,
        "anchor_violations": 0,
        "latency_api_ms": api_ms,
        "latency_ok": api_ms is not None and api_ms <= LATENCY_LIMIT_MS,
        # api_ms が取得できなかった(CLI出力に duration_api_ms が無い)場合の区別用。
        # latency_ok=False(machine_pass も落ちる保守的挙動)は維持しつつ、
        # 「8秒超過」と「測定不能」を証拠上分離する。
        "latency_unmeasured": api_ms is None,
        "control_fabrication_warning": False,   # 対照(完全指定)なのに分岐が出た=捏造疑い(自動不合格にしない)
        "per_branch": []
    }
    if not isinstance(ex, dict):
        c["missing_fields"].append("(extraction全体が欠落)")
        c["schema_ok"] = False
        c["machine_pass"] = False
        return c
    for k in REQUIRED_TOP:
        if k not in ex or ex[k] is None:
            c["missing_fields"].append(k)
    if "missing_materials" in ex and ex["missing_materials"] is not None and not isinstance(ex["missing_materials"], list):
        c["missing_fields"].append("missing_materials(配列でない)")
    if "branches" in ex and ex["branches"] is not None and not isinstance(ex["branches"], list):
        c["missing_fields"].append("branches(配列でない)")
    if "residual_ambiguity_assessment" in ex and ex["residual_ambiguity_assessment"] is not None \
            and not isinstance(ex["residual_ambiguity_assessment"], str):
        c["missing_fields"].append("residual_ambiguity_assessment(文字列でない)")

    branches = ex.get("branches") if isinstance(ex.get("branches"), list) else []
    c["branches_count"] = len(branches)
    c["branches_le5"] = len(branches) <= 5
    if is_control and len(branches) > 0:
        c["control_fabrication_warning"] = True

    for bi, br in enumerate(branches):
        pb = {"index": bi, "question_point": "", "anchors": [], "options_count": 0,
              "options_ok": True, "missing": []}
        if isinstance(br, dict):
            for k in REQUIRED_BRANCH:
                if k not in br or br[k] is None:
                    pb["missing"].append(k)
            pb["question_point"] = br.get("question_point") if isinstance(br.get("question_point"), str) else "(欠落)"
            anchors = br.get("anchor_words") if isinstance(br.get("anchor_words"), list) else []
            if len(anchors) == 0:
                # anchor ゼロの分岐は原文根拠なし=違反(空虚な合格を防ぐ)
                c["anchor_violations"] += 1
                pb["missing"].append("anchor_words(空)")
            for a in anchors:
                s = str(a)
                # 空文字・空白のみは常に部分一致してしまうため違反扱い
                found = len(s.strip()) > 0 and (s in brief_text)  # 連続部分文字列として一字一句
                pb["anchors"].append({"text": s, "found": found})
                c["anchor_total"] += 1
                if not found:
                    c["anchor_violations"] += 1
            opts = br.get("options") if isinstance(br.get("options"), list) else []
            pb["options_count"] = len(opts)
            pb["options_ok"] = 2 <= len(opts) <= 3
            if not pb["options_ok"]:
                c["options_count_ok"] = False
            for oi, op in enumerate(opts):
                if not isinstance(op, dict):
                    pb["missing"].append("options[%d]" % oi)
                    continue
                for k in REQUIRED_OPTION:
                    if k not in op or op[k] is None:
                        pb["missing"].append("options[%d].%s" % (oi, k))
        else:
            pb["missing"].append("(branch自体が不正)")
        if pb["missing"]:
            c["missing_fields"].extend("branches[%d].%s" % (bi, m) for m in pb["missing"])
        c["per_branch"].append(pb)

    c["schema_ok"] = len(c["missing_fields"]) == 0
    c["machine_pass"] = (c["schema_ok"] and c["branches_le5"] and c["options_count_ok"]
                         and c["anchor_violations"] == 0 and c["latency_ok"])
    return c


# ========= claude -p 1回実行 =========
def run_claude_once(claude_bin: str, system_prompt: str, user_prompt: str,
                    model: str, timeout_s: int, workdir: str):
    """1回の claude -p 実行。attempt レコード(生データ込み)を返す。

    - 抽出プロンプトは --append-system-prompt で system 側へ渡す(ブラウザ版の
      system 渡しに条件を寄せる)。ユーザープロンプトはブリーフ本文のみ。
    - cwd はリポジトリ外の一時ディレクトリ(workdir)。CLAUDE.md / .claude 設定の
      祖先探索を遮断し、無関係な指示の注入を防ぐ。
    - stdin は DEVNULL(親の stdin 継承による CLI の入力待ちハングを防ぐ)。
    """
    attempt = {
        "timestamp_start": datetime.now(timezone.utc).isoformat(),
        "wall_ms": None,             # 壁時計(subprocess起動〜終了。CLI起動オーバーヘッド込み)
        "cli_exit_code": None,
        "cli_stdout": None,          # 生stdout全文
        "cli_stderr": None,
        "cli_json": None,            # --output-format json のパース結果全体
        "duration_ms": None,         # CLI報告の総時間
        "duration_api_ms": None,     # CLI報告のAPI時間(8秒線の判定基準)
        "result_text": None,         # result フィールド(応答本文)
        "extraction": None,          # 本文から抽出したJSONオブジェクト
        "error": None                # {"kind": ..., "message": ...}
    }
    cmd = [claude_bin, "-p", user_prompt,
           "--append-system-prompt", system_prompt,
           "--model", model, "--output-format", "json"]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout_s, cwd=workdir,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        attempt["wall_ms"] = round((time.monotonic() - t0) * 1000)
        attempt["cli_stdout"] = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
        attempt["cli_stderr"] = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode("utf-8", "replace")
        attempt["error"] = {"kind": "timeout",
                            "message": "タイムアウト(%d秒)。打ち切って次へ。" % timeout_s}
        return attempt
    except FileNotFoundError:
        attempt["wall_ms"] = round((time.monotonic() - t0) * 1000)
        attempt["error"] = {"kind": "cli_not_found",
                            "message": "claude コマンドが見つからない(%r)。Claude Code のインストール/PATHを確認。" % claude_bin}
        return attempt

    attempt["wall_ms"] = round((time.monotonic() - t0) * 1000)
    attempt["cli_exit_code"] = proc.returncode
    attempt["cli_stdout"] = proc.stdout
    attempt["cli_stderr"] = proc.stderr

    # CLI出力(--output-format json)のパース
    try:
        cli_json = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        attempt["error"] = {"kind": "cli_json_parse",
                            "message": "CLI出力(--output-format json)がJSONとしてパースできない"
                                       + ("(exit=%s)" % proc.returncode)}
        return attempt
    attempt["cli_json"] = cli_json
    attempt["duration_ms"] = cli_json.get("duration_ms")
    attempt["duration_api_ms"] = cli_json.get("duration_api_ms")

    if proc.returncode != 0 or cli_json.get("is_error"):
        attempt["error"] = {"kind": "cli_error",
                            "message": "claude CLI がエラーを返した(exit=%s, is_error=%s)"
                                       % (proc.returncode, cli_json.get("is_error"))}
        return attempt

    result_text = cli_json.get("result")
    attempt["result_text"] = result_text
    if not isinstance(result_text, str) or not result_text.strip():
        attempt["error"] = {"kind": "result_json_parse", "message": "result フィールドが空または文字列でない"}
        return attempt

    extraction, why = extract_first_json_object(result_text)
    if extraction is None:
        attempt["error"] = {"kind": "result_json_parse", "message": "本文からのJSON抽出失敗: " + why}
        return attempt
    attempt["extraction"] = extraction
    return attempt


def run_brief(brief, prompt_prefix, claude_bin, model, timeout_s, workdir):
    """1ブリーフ処理。パース失敗(cli_json_parse / result_json_parse)は1回だけ再実行。"""
    attempts = []
    attempt = run_claude_once(claude_bin, prompt_prefix, brief["text"], model, timeout_s, workdir)
    attempts.append(attempt)
    if attempt["error"] and attempt["error"]["kind"] in ("cli_json_parse", "result_json_parse"):
        print("    パース失敗(%s)。1回だけ再実行する。" % attempt["error"]["kind"], flush=True)
        attempt = run_claude_once(claude_bin, prompt_prefix, brief["text"], model, timeout_s, workdir)
        attempts.append(attempt)

    final = attempts[-1]
    checks = None
    if final["extraction"] is not None:
        checks = machine_checks(brief["text"], brief["is_control"],
                                final["extraction"], final["duration_api_ms"])
    return {
        "brief_id": brief["id"],
        "brief_type": brief["type"],
        "brief_is_control": brief["is_control"],
        "brief_text": brief["text"],
        "model": model,
        "attempts": attempts,               # 全試行の生データ(生stdout・生応答本文込み)
        "retried": len(attempts) > 1,
        "wall_ms": final["wall_ms"],
        "duration_ms": final["duration_ms"],
        "duration_api_ms": final["duration_api_ms"],
        "extraction": final["extraction"],
        "machine_checks": checks,
        "error": final["error"]
    }


# ========= 出力 =========
def write_results_json(path, model, prompt_prefix, extraction_prompt_raw, results, timeout_s, workdir):
    data = {
        "tool": "gyakumon-killer-test-runner-headless-cli",
        "version": "cli-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "claude -p (Claude Code subscription headless CLI)",
        "engine_note": (
            "エンジン差の注記: claude -p は素のAPI呼び出しではなく、Claude Code エージェントの"
            "システムプロンプト込みで動作する。抽出プロンプトは --append-system-prompt で"
            "system 側へ追加しており、ブラウザ版(extraction_v0.txt を API の system に直接渡し"
            "tool_choice で report_branches を強制)とは測定条件が異なる。"
            "cwd はリポジトリ外の一時ディレクトリで、CLAUDE.md / .claude 設定の祖先探索による"
            "無関係な指示の注入を遮断している。"
        ),
        "command_template": ("claude -p <brief_text> --append-system-prompt <prompt_prefix_full> "
                             "--model %s --output-format json" % model),
        "cwd": workdir,
        "model": model,
        "timeout_s_per_brief": timeout_s,
        "latency_limit_ms": LATENCY_LIMIT_MS,
        "latency_basis": "duration_api_ms(CLI起動オーバーヘッド分離のため。壁時計 wall_ms とCLI総時間 duration_ms を併記)",
        "pass_line_note": PASS_LINE_NOTE,
        "prompt_file": str(PROMPT_PATH),
        "briefs_file": str(BRIEFS_PATH),
        "extraction_prompt_raw": extraction_prompt_raw,   # extraction_v0.txt 原文
        "prompt_prefix_full": prompt_prefix,              # 適合済みプロンプト+出力規則+スキーマ全文(--append-system-prompt で system 側へ)
        "full_prompt_composition": ("system: prompt_prefix_full を --append-system-prompt で追加 / "
                                    "user: 各ブリーフの brief_text のみ"),
        "extraction_schema": EXTRACTION_SCHEMA,
        "results": results
    }
    # 非アトミックな上書きで既存証拠が壊れないよう、一時ファイル経由で os.replace する
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def write_summary_md(path, model, results, ts):
    lines = []
    lines.append("# GYAKUMON キラーテスト SUMMARY(ヘッドレスCLI版)")
    lines.append("")
    lines.append("- 実行時刻(UTC): %s / モデル: `%s` / エンジン: `claude -p --output-format json`" % (ts, model))
    lines.append("- 8秒線は **duration_api_ms** 基準(CLI起動オーバーヘッド分離のため)。壁時計 wall_ms と CLI総時間 duration_ms を併記。")
    lines.append("")
    lines.append("| ブリーフ | type | 分岐数 | anchor違反 | api_ms | duration_ms | 壁時計ms | 機械判定 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    n_pass = n_err = n_lat_ok = n_fab = viol_total = 0
    for r in results:
        c = r["machine_checks"]
        if r["error"]:
            n_err += 1
            lines.append("| %s | %s | — | — | %s | %s | %s | エラー(%s) |" % (
                r["brief_id"], r["brief_type"],
                r["duration_api_ms"] if r["duration_api_ms"] is not None else "—",
                r["duration_ms"] if r["duration_ms"] is not None else "—",
                r["wall_ms"] if r["wall_ms"] is not None else "—",
                r["error"]["kind"]))
            continue
        if c["machine_pass"]:
            n_pass += 1
        if c["latency_ok"]:
            n_lat_ok += 1
        if c["control_fabrication_warning"]:
            n_fab += 1
        viol_total += c["anchor_violations"]
        verdict = "合格" if c["machine_pass"] else "違反あり"
        notes = []
        if not c["schema_ok"]:
            notes.append("必須欠落%d" % len(c["missing_fields"]))
        if not c["branches_le5"]:
            notes.append("分岐>5")
        if not c["options_count_ok"]:
            notes.append("options数違反")
        if not c["latency_ok"]:
            notes.append("api_ms欠落(8秒線判定不能)" if c.get("latency_unmeasured") else "8秒超")
        if c["control_fabrication_warning"]:
            notes.append("対照なのに分岐=捏造疑い")
        if r["retried"]:
            notes.append("再実行1回")
        lines.append("| %s | %s | %d | %d / %d | %s | %s | %s | %s%s |" % (
            r["brief_id"], r["brief_type"],
            c["branches_count"], c["anchor_violations"], c["anchor_total"],
            r["duration_api_ms"] if r["duration_api_ms"] is not None else "—",
            r["duration_ms"] if r["duration_ms"] is not None else "—",
            r["wall_ms"] if r["wall_ms"] is not None else "—",
            verdict, ("(%s)" % "・".join(notes)) if notes else ""))
    lines.append("")
    lines.append("**集計(機械判定のみ)**: 実行 %d 本 | 機械判定パス %d 本 | 8秒線クリア %d 本 | "
                 "anchor違反合計 %d | 捏造疑いフラグ %d 本 | エラー %d 本" % (
                     len(results), n_pass, n_lat_ok, viol_total, n_fab, n_err))
    lines.append("")
    lines.append("## 合格線の注記")
    lines.append("")
    lines.append("- " + PASS_LINE_NOTE)
    lines.append("- 「有効分岐率70%(10本中8本)」「対照ペアの妥当性」は意味判定であり管制塔が行う。本表は機械判定のみ。")
    lines.append("- control_zero ブリーフの branches>0 は「捏造疑い」フラグであり自動不合格ではない(意味判定は管制塔)。")
    lines.append("- 壁時計msにはCLI起動・認証等のオーバーヘッドが含まれるため、8秒線の一次判定には用いない。")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ========= main =========
def main():
    ap = argparse.ArgumentParser(description="GYAKUMON キラーテスト(claude -p ヘッドレスCLI版)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="claude -p の --model(既定: sonnet。比較用に fable 等)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="1ブリーフあたりのタイムアウト秒(既定: 180)")
    ap.add_argument("--claude-bin", default="claude", help="claude CLI のパス(既定: PATH上の claude)")
    args = ap.parse_args()

    # 1. アセット読込(スクリプト位置基準)
    try:
        extraction_prompt_raw = PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as e:
        print("エラー: プロンプト読込失敗 (%s): %s" % (PROMPT_PATH, e), file=sys.stderr)
        return 1
    try:
        raw_briefs = json.loads(BRIEFS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print("エラー: ブリーフ読込失敗 (%s): %s" % (BRIEFS_PATH, e), file=sys.stderr)
        return 1

    # ブラウザ版 index.html の normalizeBriefs と同一の正規化・判定
    # (ラッパーオブジェクト {briefs|items|data:[...]} 許容 / 非dict要素スキップ /
    #  control:true・fully_specified:true・is_control:true・type:"control*"・expected_branches:0)
    if isinstance(raw_briefs, list):
        raw_list = raw_briefs
    elif isinstance(raw_briefs, dict):
        raw_list = raw_briefs.get("briefs") or raw_briefs.get("items") or raw_briefs.get("data")
    else:
        raw_list = None
    briefs = []
    for i, raw in enumerate(raw_list if isinstance(raw_list, list) else []):
        if isinstance(raw, str):
            raw = {"text": raw}
        if not isinstance(raw, dict):
            continue  # 数値等の非dict要素はスキップ(ブラウザ版はテキスト空扱いで除外)
        text = raw.get("text") or raw.get("body") or raw.get("brief") or raw.get("content") or ""
        if not text:
            continue
        btype = raw.get("type")
        eb = raw.get("expected_branches")
        is_control = (
            raw.get("control") is True
            or raw.get("fully_specified") is True
            or raw.get("is_control") is True
            or (isinstance(btype, str) and btype.startswith("control"))   # 'control', 'control_zero' 等
            or (not isinstance(eb, bool) and isinstance(eb, (int, float)) and eb == 0)  # JS の === 0 相当
        )
        briefs.append({
            "id": str(raw.get("id") or raw.get("name") or "brief_%02d" % (i + 1)),
            "type": str(btype) if isinstance(btype, str) else "",
            "is_control": is_control,
            "text": str(text)
        })
    if not briefs:
        print("エラー: briefs.json にブリーフが見つからない。", file=sys.stderr)
        return 1

    prompt_prefix = build_prompt_prefix(extraction_prompt_raw)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    results_path = EVIDENCE_DIR / ("results_%s.json" % ts)
    summary_path = EVIDENCE_DIR / ("SUMMARY_%s.md" % ts)

    # claude -p の作業ディレクトリ: リポジトリ外の空一時ディレクトリ。
    # CLAUDE.md / .claude 設定の祖先探索を断ち、クリーンルーム指示の注入による
    # 抽出品質・latency 実測の汚染を防ぐ。
    workdir = tempfile.mkdtemp(prefix="gyakumon_killer_cli_")

    print("GYAKUMON キラーテスト(ヘッドレスCLI版) 開始")
    print("  モデル: %s / タイムアウト: %d秒/本 / ブリーフ: %d 本" % (args.model, args.timeout, len(briefs)))
    print("  プロンプト: %s(%d 文字 + 出力規則。--append-system-prompt で system 側へ)" % (PROMPT_PATH, len(extraction_prompt_raw)))
    print("  claude -p 作業Dir: %s(リポジトリ外・CLAUDE.md注入遮断)" % workdir)
    print("  出力先: %s" % EVIDENCE_DIR)
    print("", flush=True)

    # 2. 逐次実行
    results = []
    for i, b in enumerate(briefs):
        print("[%d/%d] %s (%s) 実行中…" % (i + 1, len(briefs), b["id"], b["type"]), flush=True)
        r = run_brief(b, prompt_prefix, args.claude_bin, args.model, args.timeout, workdir)
        results.append(r)
        if r["error"]:
            print("    エラー: %s — %s" % (r["error"]["kind"], r["error"]["message"]), flush=True)
        else:
            c = r["machine_checks"]
            print("    分岐 %d / anchor違反 %d/%d / api %sms / 壁時計 %sms / 機械判定 %s%s" % (
                c["branches_count"], c["anchor_violations"], c["anchor_total"],
                r["duration_api_ms"], r["wall_ms"],
                "合格" if c["machine_pass"] else "違反あり",
                " / 捏造疑い(対照なのに分岐)" if c["control_fabrication_warning"] else ""), flush=True)
        # 途中経過も毎回書き出す(途中中断でも生データが残るように)
        write_results_json(results_path, args.model, prompt_prefix, extraction_prompt_raw, results, args.timeout, workdir)

    # 3. 出力
    write_results_json(results_path, args.model, prompt_prefix, extraction_prompt_raw, results, args.timeout, workdir)
    write_summary_md(summary_path, args.model, results, ts)

    n_pass = sum(1 for r in results if r["machine_checks"] and r["machine_checks"]["machine_pass"])
    n_lat = sum(1 for r in results if r["machine_checks"] and r["machine_checks"]["latency_ok"])
    n_err = sum(1 for r in results if r["error"])
    n_fab = sum(1 for r in results if r["machine_checks"] and r["machine_checks"]["control_fabrication_warning"])
    viol = sum(r["machine_checks"]["anchor_violations"] for r in results if r["machine_checks"])
    print("")
    print("完了: %d 本 | 機械判定パス %d | 8秒線(api_ms)クリア %d | anchor違反合計 %d | 捏造疑い %d | エラー %d" % (
        len(results), n_pass, n_lat, viol, n_fab, n_err))
    print("生データ: %s" % results_path)
    print("サマリ:   %s" % summary_path)
    print("注: 有効分岐率70%・対照ペア妥当性は管制塔の意味判定。本スクリプトは機械判定のみ。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
