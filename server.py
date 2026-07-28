#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GYAKUMON — Intent Compiler ローカルサーバ(python3 標準ライブラリのみ)

起動:
    python3 server.py --port 8321 --model sonnet --render-model haiku

役割:
  1. app/ を http://127.0.0.1:<port>/ で静的配信(単一HTML・外部依存ゼロ)
  2. claude CLI ヘッドレス(`claude -p ... --output-format json`)を子プロセスとして呼ぶ
     API プロキシ。APIキー不要(Claude Code サブスクリプション認証)。

エンドポイント:
  POST /api/explode  {brief}
       → --model <model>       + prompts/extraction_product_v1.txt(スリムスキーマ)
       → {ok, branches[], residual_ambiguity_assessment, missing_materials[], timing}
         branches[] = {id, question_point, anchor_words[], options:[{label}], default_if_unresolved}
         downstream_impact / thumbnail_description / px200_rationale は存在しない(スリム化で削除)。
         anchor_words は「ブリーフ原文の連続部分文字列」であることをサーバ側で機械検証し、
         不合格の分岐は棄却してから返す(棄却理由は rejected_branches に残す)。
  POST /api/render   {brief, question_point, option:{label}, sibling_labels:[同じ判断点の他オプションのlabel...]}
       → --model <render_model> + prompts/render_v0.txt
       → {ok, tokens:{palette[3], heading_font, density, corner, tone_sample}, timing}
         対照性は sibling_labels(差別化すべき兄弟オプションのラベル群)を入力に含めることで
         担保する。レンダラーが「何から離れるべきか」を直接知る方式。
         旧フィールド(downstream_impact / option.thumbnail_description)が来ても無視する。
  POST /api/compile  {brief, decisions:[{question_point, anchor_words, status, chosen_label?, chosen_tokens?}]}
       → --model <model>       + prompts/compile_v0.txt
       → {ok, rationales:{question_point→1文}, timing}
         ブリーフ本文(MD/JSON)の組み立てはクライアント側の決定論処理。LLMは根拠文のみ。
  GET  /api/health   → {ok:true, ...}

規律(killer_test/run.py の流儀を踏襲):
  - 子プロセスの cwd は必ずリポジトリ外の一時ディレクトリ。CLAUDE.md / .claude 設定の
    祖先探索を遮断し、無関係な指示が抽出・生成へ注入されるのを防ぐ(設定汚染防止)。
  - プロンプトファイルは --system-prompt で system を「完全置換」して渡す(既定の
    Claude Code 用システムプロンプトを載せない)。--strict-mcp-config で MCP を遮断し、
    --effort low で思考量を絞る。実測: 同一ブリーフで 110s/8.5Ktok → 8.8s/543tok。
    ユーザープロンプトは対象データ(ブリーフ原文 / JSONペイロード)のみとする。
  - 出力スキーマはサーバ側の「出力規則」で上書き明記する(プロンプトファイルの文言に依存しない)。
  - 応答本文からのJSON抽出は波括弧対応の頑健抽出(コードフェンス・前置き混入に耐性)。
  - stdin は DEVNULL(親の stdin 継承によるハング防止)。タイムアウトは既定120秒。

証拠化:
  すべての claude 呼び出しを logs/session_<起動時刻>.jsonl へ
  {ts, endpoint, model, wall_ms, api_ms, ok} で追記する。

エラー規約:
  失敗時も HTTP 200 で {ok:false, error, hint} を返す(クライアントが画面に表示する)。
"""

import argparse
import json
import mimetypes
import os
import posixpath
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ========= 定数・パス =========
BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR / "app"
PROMPTS_DIR = BASE_DIR / "prompts"
LOGS_DIR = BASE_DIR / "logs"

EXTRACTION_PROMPT_PATH = PROMPTS_DIR / "extraction_product_v1.txt"
RENDER_PROMPT_PATH = PROMPTS_DIR / "render_v0.txt"
COMPILE_PROMPT_PATH = PROMPTS_DIR / "compile_v0.txt"

DEFAULT_PORT = 8321
DEFAULT_HOST = "127.0.0.1"          # localhost のみバインド(拘束)
DEFAULT_MODEL = "sonnet"            # /api/explode, /api/compile
DEFAULT_RENDER_MODEL = "haiku"      # /api/render
DEFAULT_EFFORT = "low"              # --effort。実測でスリムスキーマと合わせて 110s→8.8s
DEFAULT_TIMEOUT_S = 120             # claude 呼び出し1本あたり(拘束)
DEFAULT_MAX_CONCURRENCY = 6         # 同時に走らせる claude 子プロセス数の上限
SLOT_WAIT_MARGIN_S = 60             # 実行枠の待ち行列で待てる追加秒数
MAX_BODY_BYTES = 512 * 1024         # リクエストボディ上限
MAX_BRANCHES = 5                    # カードは最大5枚(UI仕様)

TEXT_MIME_CHARSET = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

FONT_ALIASES = {
    "serif": "serif", "mincho": "serif", "明朝": "serif", "serif-font": "serif",
    "sans": "sans", "sans-serif": "sans", "sansserif": "sans", "gothic": "sans", "ゴシック": "sans",
    "rounded": "rounded", "round": "rounded", "丸ゴシック": "rounded", "rounded-sans": "rounded",
}
DENSITY_ALIASES = {
    "airy": "airy", "sparse": "airy", "light": "airy",
    "normal": "normal", "medium": "normal", "default": "normal",
    "dense": "dense", "heavy": "dense", "packed": "dense",
}
CORNER_ALIASES = {
    "sharp": "sharp", "square": "sharp", "angular": "sharp",
    "soft": "soft", "rounded": "soft", "round": "soft",
}

TONE_SAMPLE_MAX = 40


# ========= スキーマ(出力規則としてサーバ側で明記・上書き) =========
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "residual_ambiguity_assessment": {"type": "string", "description": "残存曖昧性の評価"},
        "missing_materials": {
            "type": "array", "items": {"type": "string"},
            "description": "選択では解決できず情報提供が必要な欠落"
        },
        "branches": {
            "type": "array", "maxItems": MAX_BRANCHES,
            "items": {
                "type": "object",
                "properties": {
                    "question_point": {"type": "string"},
                    "anchor_words": {
                        "type": "array", "minItems": 1, "items": {"type": "string"},
                        "description": "原文の連続部分文字列をそのまま・可能な限り最長フレーズで"
                    },
                    "options": {
                        "type": "array", "minItems": 2, "maxItems": 3,
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "解釈名(12字以内)"}
                            },
                            "required": ["label"]
                        }
                    },
                    "default_if_unresolved": {"type": "string"}
                },
                "required": ["question_point", "anchor_words",
                             "options", "default_if_unresolved"]
            }
        }
    },
    "required": ["residual_ambiguity_assessment", "missing_materials", "branches"]
}

RENDER_SCHEMA = {
    "type": "object",
    "properties": {
        "palette": {
            "type": "array", "minItems": 3, "maxItems": 3,
            "items": {"type": "string", "description": "#RRGGBB 形式。役割順 [地色, 主要色, 強調色]"}
        },
        "heading_font": {"enum": ["serif", "sans", "rounded"]},
        "density": {"enum": ["airy", "normal", "dense"]},
        "corner": {"enum": ["sharp", "soft"]},
        "tone_sample": {"type": "string", "description": "このオプションの世界観の見出し+一文。合計40字以内"}
    },
    "required": ["palette", "heading_font", "density", "corner", "tone_sample"]
}

COMPILE_SCHEMA = {
    "type": "object",
    "properties": {
        "rationales": {
            "type": "object",
            "description": "キーは与えられた各 question_point の文字列そのまま。値はその判断の根拠1文。"
        }
    },
    "required": ["rationales"]
}

EXTRACTION_REQUIRED_TOP = ["residual_ambiguity_assessment", "missing_materials", "branches"]


# ========= プロンプト合成 =========
def build_extraction_system(extraction_prompt: str) -> str:
    """抽出プロンプト + 出力規則(単一JSONのみ + スキーマ全文)。run.py と同一方針。

    prompts/extraction_product_v1.txt(スリムスキーマ)を前提とする。
    旧 extraction_v0.txt を --extraction-prompt 相当で差し込んだ場合に備え、
    report_branches ツール前提の文言だけは読み替える。"""
    adapted = extraction_prompt.replace(
        "出力は必ず report_branches ツール呼び出しのみで行う。地の文・前置き・後書きを書かない。",
        "出力は単一のJSONオブジェクトのみで行う。地の文・前置き・後書きを書かない。"
    )
    schema_text = json.dumps(EXTRACTION_SCHEMA, ensure_ascii=False, indent=2)
    rules = (
        "\n\n## 出力規則(この実行環境での上書き)\n\n"
        "- コードフェンス(```)・説明・前置き・後書きを一切付けず、単一のJSONオブジェクトのみを出力せよ。\n"
        "- 思考・分析・検討過程を書かない。即座に結論のJSONだけを書く。\n"
        "- そのJSONオブジェクトは次のJSONスキーマに厳密に従うこと(フィールド順もスキーマの順とする):\n\n"
        + schema_text +
        "\n\n- スキーマの required をすべて満たし、スキーマにないフィールドを追加しないこと。\n"
        "- anchor_words はサーバ側で「ブリーフ原文の連続部分文字列か」を機械検証する。"
        "一字でも異なる引用(言い換え・要約・表記正規化・空白の付け外し)を含む分岐は棄却され、"
        "ユーザーには表示されない。原文からコピーした文字列だけを入れよ。\n"
        "\n## 対象ブリーフ(原文)\n\n"
        "ユーザーメッセージとして与えられる本文全体がブリーフ原文である。これに対して抽出のみを行え。\n"
    )
    return adapted + rules


def build_render_system(render_prompt: str) -> str:
    schema_text = json.dumps(RENDER_SCHEMA, ensure_ascii=False, indent=2)
    rules = (
        "\n\n## 出力規則(この実行環境での上書き)\n\n"
        "- コードフェンス(```)・説明・前置き・後書きを一切付けず、単一のJSONオブジェクトのみを出力せよ。\n"
        "- そのJSONオブジェクトは次のJSONスキーマに厳密に従うこと(フィールド順もスキーマの順とする):\n\n"
        + schema_text +
        "\n\n- 列挙値は英小文字リテラルのみ。palette は3要素・すべて \"#RRGGBB\" 形式の16進6桁。\n"
        "- tone_sample は合計40字以内(超過分はサーバ側で切り詰められる)。\n"
        "- スキーマにないフィールドを追加しないこと。null を入れないこと。\n"
        "- 思考・分析・検討過程を書かない。即座に結論のJSONだけを書く。\n"
        "\n## 入力\n\n"
        "ユーザーメッセージとして単一のJSONオブジェクトが与えられる。"
        "brief(ブリーフ原文)・question_point(判断点)・option(対象オプションの label)・"
        "sibling_labels(同じ判断点に並ぶ他オプションの label 群)を読み、"
        "その option 1件分のトークンだけを返せ。"
        "sibling_labels は「離れるべき方向」を示す。それらが取りそうな値域を避けよ。\n"
    )
    return render_prompt + rules


def build_compile_system(compile_prompt: str) -> str:
    schema_text = json.dumps(COMPILE_SCHEMA, ensure_ascii=False, indent=2)
    rules = (
        "\n\n## 出力規則(この実行環境での上書き)\n\n"
        "- コードフェンス(```)・説明・前置き・後書きを一切付けず、単一のJSONオブジェクトのみを出力せよ。\n"
        "- そのJSONオブジェクトは次のJSONスキーマに厳密に従うこと:\n\n"
        + schema_text +
        "\n\n- rationales のキーは、入力 decisions の各 question_point の文字列を"
        "一字一句そのまま用いること(要約・言い換え・番号付けは失格)。\n"
        "- 値は日本語1文(句点で終わる1文のみ)。箇条書き・複数文・見出しを書かない。\n"
        "- status が \"decided\" の判断点は「選ばれた解釈が下流の成果物をどう規定するか」を、"
        "\"delegated\" の判断点は「委任により制作者側の裁量に委ねられた範囲」を、それぞれ1文で述べる。\n"
        "- 成果物本文(コピー、構成案、デザイン案)を書いてはならない。根拠文のみを返す。"
        "ブリーフ本文の組み立てはクライアント側の決定論処理が行う。\n"
        "- スキーマにないフィールドを追加しないこと。\n"
        "\n## 入力\n\n"
        "ユーザーメッセージとして単一のJSONオブジェクトが与えられる。"
        "brief(ブリーフ原文)と decisions(各判断点の確定/委任の記録)を読み、rationales だけを返せ。\n"
    )
    return compile_prompt + rules


# ========= 応答本文からのJSON抽出(波括弧対応・頑健。run.py と同方式) =========
def extract_json_object(text, accept):
    """本文から最初の「accept(obj) が真になる」完全なJSONオブジェクトを波括弧対応で抽出する。
    コードフェンス・前置き・後書きが混ざっていても拾える。内側の部分オブジェクトを
    誤受理しないよう、受理条件は呼び出し側が accept で与える。
    戻り値: (obj, None) / (None, 理由文字列)"""
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
                            if isinstance(obj, dict) and accept(obj):
                                return obj, None
                        except json.JSONDecodeError:
                            pass
                        break  # この開始位置は不成立。次の '{' から再走査
            i += 1
        start = text.find("{", start + 1)
    return None, "期待した形のJSONオブジェクトを抽出できない"


# ========= claude CLI 実行器(実行枠プール付き) =========
class ClaudeRunner:
    """claude -p をスレッドセーフに呼ぶ実行器。

    - 同時実行数を max_concurrency に制限する(超過分はキューで待つ)。
    - 各実行枠は専用の一時ディレクトリ(リポジトリ外)を cwd として持つ。
      枠ごとに分けるのは、並列実行時に同一 cwd のセッション状態が競合しないようにするため。
    - 子プロセス env から Anthropic APIキーを除去する(サブスクリプション認証を主経路に固定)。
      --allow-api-key 指定時のみ除去しない。
    """

    def __init__(self, claude_bin, timeout_s, max_concurrency, allow_api_key=False,
                 effort=DEFAULT_EFFORT):
        self.claude_bin = claude_bin
        self.timeout_s = timeout_s
        self.max_concurrency = max_concurrency
        self.allow_api_key = allow_api_key
        self.effort = effort
        self.base_dir = tempfile.mkdtemp(prefix="gyakumon_server_")
        self.slots = queue.Queue()
        for i in range(max_concurrency):
            d = os.path.join(self.base_dir, "slot_%d" % i)
            os.makedirs(d, exist_ok=True)
            self.slots.put(d)
        self.env = os.environ.copy()
        self.stripped_env_keys = []
        if not allow_api_key:
            for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
                if k in self.env:
                    del self.env[k]
                    self.stripped_env_keys.append(k)

    def cleanup(self):
        shutil.rmtree(self.base_dir, ignore_errors=True)

    def run(self, system_prompt, user_prompt, model):
        """1回の claude -p 実行。結果 dict を返す(例外を投げない)。

        戻り値: {ok, wall_ms, api_ms, duration_ms, result_text, error, hint, exit_code}
        """
        rec = {"ok": False, "wall_ms": None, "api_ms": None, "duration_ms": None,
               "result_text": None, "error": None, "hint": None, "exit_code": None}
        wait_deadline = self.timeout_s + SLOT_WAIT_MARGIN_S
        t_wait = time.monotonic()
        try:
            workdir = self.slots.get(timeout=wait_deadline)
        except queue.Empty:
            rec["wall_ms"] = round((time.monotonic() - t_wait) * 1000)
            rec["error"] = "サーバが混雑している(同時実行 %d 枠がすべて埋まったまま %d 秒経過)" % (
                self.max_concurrency, wait_deadline)
            rec["hint"] = "少し待って再試行するか、--max-concurrency を上げて再起動する。"
            return rec

        # フラグ注入対策(拘束): user_prompt はユーザー入力(ブリーフ原文)そのものであり得るため、
        # "-" で始まる本文が claude CLI(commander)のオプションとして解釈されないよう、
        # オプション終端子 "--" の後ろに最後の位置引数として置く。
        # 検証済み: claude 2.1.220 で `claude --model ... --output-format json -p -- "--settings=..."` が
        # 本文をプロンプトとして扱い、json 出力も維持される。
        #
        # --system-prompt(--append-system-prompt ではない): 既定の Claude Code 用
        #   システムプロンプトを「完全置換」する。抽出器はエージェントではないので、
        #   ツール利用・作業手順・環境説明を読ませる必要がない。
        # --strict-mcp-config: --mcp-config を与えていないので MCP サーバを一切載せない。
        # --effort: 思考量の上限。抽出/レンダは分類タスクなので low で足りる。
        # 実測(同一ブリーフ): 既定 110s/8.5Ktok → この3点 + スリムスキーマで 8.8s/543tok。
        cmd = [self.claude_bin,
               "--system-prompt", system_prompt,
               "--strict-mcp-config",
               "--effort", self.effort,
               "--model", model, "--output-format", "json",
               "-p", "--", user_prompt]
        t0 = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=self.timeout_s, cwd=workdir,
                                  stdin=subprocess.DEVNULL, env=self.env)
        except subprocess.TimeoutExpired:
            rec["wall_ms"] = round((time.monotonic() - t0) * 1000)
            rec["error"] = "claude 呼び出しがタイムアウトした(%d秒)" % self.timeout_s
            rec["hint"] = "ネットワークとモデル指定を確認し、再送する。--timeout で延長できる。"
            return rec
        except FileNotFoundError:
            rec["wall_ms"] = round((time.monotonic() - t0) * 1000)
            rec["error"] = "claude コマンドが見つからない(%r)" % self.claude_bin
            rec["hint"] = "Claude Code のインストールと PATH、または --claude-bin を確認する。"
            return rec
        except OSError as e:
            rec["wall_ms"] = round((time.monotonic() - t0) * 1000)
            rec["error"] = "claude の起動に失敗した: %s" % e
            rec["hint"] = "実行権限とディスク空きを確認する。"
            return rec
        finally:
            self.slots.put(workdir)

        rec["wall_ms"] = round((time.monotonic() - t0) * 1000)
        rec["exit_code"] = proc.returncode

        try:
            cli_json = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            rec["error"] = "claude CLI の出力(--output-format json)をパースできない(exit=%s)" % proc.returncode
            rec["hint"] = ("`claude -p \"ping\" --output-format json` を手で実行して "
                           "CLI が正常かログイン済みかを確認する。stderr: "
                           + (proc.stderr or "")[:300])
            return rec

        if isinstance(cli_json, dict):
            rec["duration_ms"] = cli_json.get("duration_ms")
            rec["api_ms"] = cli_json.get("duration_api_ms")

        if proc.returncode != 0 or (isinstance(cli_json, dict) and cli_json.get("is_error")):
            rec["error"] = "claude CLI がエラーを返した(exit=%s, is_error=%s)" % (
                proc.returncode, cli_json.get("is_error") if isinstance(cli_json, dict) else "?")
            rec["hint"] = (str(cli_json.get("result"))[:300] if isinstance(cli_json, dict) and cli_json.get("result")
                           else "Claude Code のログイン状態と利用上限を確認する。")
            return rec

        result_text = cli_json.get("result") if isinstance(cli_json, dict) else None
        if not isinstance(result_text, str) or not result_text.strip():
            rec["error"] = "claude の応答本文(result)が空である"
            rec["hint"] = "同じ入力で再送する。繰り返す場合はモデル指定を確認する。"
            return rec

        rec["result_text"] = result_text
        rec["ok"] = True
        return rec


# ========= 検証: 抽出結果(anchor 機械検証を含む) =========
def _nonempty_str(v):
    return isinstance(v, str) and v.strip() != ""


def validate_extraction(brief_text, ex):
    """抽出結果を検証し、(payload, None) か (None, 理由) を返す。
    anchor_words が原文の連続部分文字列でない分岐は棄却する(拘束)。"""
    if not isinstance(ex, dict):
        return None, "抽出結果がオブジェクトでない"

    assessment = ex.get("residual_ambiguity_assessment")
    assessment = assessment if isinstance(assessment, str) else ""
    materials = ex.get("missing_materials")
    materials = [str(m) for m in materials if _nonempty_str(m)] if isinstance(materials, list) else []

    raw_branches = ex.get("branches") if isinstance(ex.get("branches"), list) else []
    accepted, rejected = [], []

    for idx, br in enumerate(raw_branches):
        reasons = []
        if not isinstance(br, dict):
            rejected.append({"index": idx, "question_point": "", "reasons": ["分岐がオブジェクトでない"]})
            continue

        qp = br.get("question_point")
        if not _nonempty_str(qp):
            reasons.append("question_point が空")

        anchors_raw = br.get("anchor_words") if isinstance(br.get("anchor_words"), list) else []
        anchors, bad_anchors = [], []
        for a in anchors_raw:
            s = a if isinstance(a, str) else str(a)
            # 空文字・空白のみは常に部分一致してしまうため違反扱い(run.py と同基準)
            if s.strip() == "" or (s not in brief_text):
                bad_anchors.append(s)
            else:
                anchors.append(s)
        if not anchors_raw:
            reasons.append("anchor_words が空(原文根拠なし)")
        if bad_anchors:
            reasons.append("anchor_words が原文の連続部分文字列でない: " +
                           " / ".join(repr(x)[:60] for x in bad_anchors[:3]))

        # スリムスキーマ: option は label のみが必須。thumbnail_description /
        # px200_rationale はスキーマから外したので、来ても要求しない(来たら捨てる)。
        opts_raw = br.get("options") if isinstance(br.get("options"), list) else []
        options = []
        for op in opts_raw:
            if isinstance(op, str):
                # label だけを裸の文字列で返した場合の救済
                if _nonempty_str(op):
                    options.append({"label": op.strip()})
                continue
            if not isinstance(op, dict):
                continue
            label = op.get("label")
            if not _nonempty_str(label):
                continue
            options.append({"label": label.strip()})
        if not (2 <= len(options) <= 3):
            reasons.append("options が2〜3件でない(有効 %d 件)" % len(options))

        if reasons:
            rejected.append({"index": idx,
                             "question_point": qp if isinstance(qp, str) else "",
                             "reasons": reasons})
            continue

        accepted.append({
            "id": "b%d" % idx,
            "question_point": qp.strip(),
            "anchor_words": anchors,
            "options": options,
            "default_if_unresolved": (br.get("default_if_unresolved").strip()
                                      if _nonempty_str(br.get("default_if_unresolved")) else "")
        })

    # 影響の大きい順に並んでいる前提で先頭から最大5件(UI仕様: カードは最大5枚)
    if len(accepted) > MAX_BRANCHES:
        for extra in accepted[MAX_BRANCHES:]:
            rejected.append({"index": -1, "question_point": extra["question_point"],
                             "reasons": ["上限5件を超過したため切り捨て"]})
        accepted = accepted[:MAX_BRANCHES]

    payload = {
        "branches": accepted,
        "residual_ambiguity_assessment": assessment,
        "missing_materials": materials,
        "rejected_branches": rejected,           # 証拠用(棄却の可視化)
        "branches_returned_by_model": len(raw_branches),
    }
    return payload, None


# ========= 検証: レンダトークン =========
def _norm_hex(v):
    if not isinstance(v, str):
        return None
    m = HEX_RE.match(v.strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h.lower()


TONE_STOP_CHARS = "。！？!?"                 # ここで切ると1文として完結する(その文字は残す)
TONE_SOFT_CHARS = "、，,・/／|｜ 　"          # 次善の境界(その文字は落とす)


def truncate_tone(text, limit):
    """tone_sample を limit 字へ切り詰める。文の途中でぶつ切りにするとミニレンダと
    MD出力の「トーン例」に欠けた文が出るため、句点 → 読点・区切り の順で境界を探す。
    境界が前半すぎる(limit の半分より手前)場合は情報が失われすぎるので単純切り詰めに戻す。"""
    head = text[:limit]
    for i in range(len(head) - 1, -1, -1):
        if head[i] in TONE_STOP_CHARS:
            if i + 1 >= limit // 2:
                return head[:i + 1]
            break
    for i in range(len(head) - 1, -1, -1):
        if head[i] in TONE_SOFT_CHARS:
            if i >= limit // 2:
                cut = head[:i].rstrip()
                if cut:
                    return cut
            break
    return head


def validate_tokens(obj):
    """レンダトークンを検証・正規化する。(tokens, warnings) か (None, 理由) を返す。"""
    if not isinstance(obj, dict):
        return None, "トークンがオブジェクトでない"
    src = obj.get("tokens") if isinstance(obj.get("tokens"), dict) else obj
    warnings = []

    palette_raw = src.get("palette")
    if not isinstance(palette_raw, list):
        return None, "palette が配列でない"
    palette = []
    for c in palette_raw:
        h = _norm_hex(c)
        if h:
            palette.append(h)
    if len(palette) < 3:
        return None, "palette に有効な #RRGGBB が3色ない(有効 %d 色)" % len(palette)
    if len(palette) > 3:
        warnings.append("palette が4色以上だったため先頭3色を採用した")
        palette = palette[:3]

    def pick(value, aliases, field):
        if not isinstance(value, str):
            return None
        key = value.strip().lower()
        return aliases.get(key)

    heading_font = pick(src.get("heading_font"), FONT_ALIASES, "heading_font")
    if heading_font is None:
        return None, "heading_font が serif/sans/rounded のいずれでもない(%r)" % src.get("heading_font")
    density = pick(src.get("density"), DENSITY_ALIASES, "density")
    if density is None:
        return None, "density が airy/normal/dense のいずれでもない(%r)" % src.get("density")
    corner = pick(src.get("corner"), CORNER_ALIASES, "corner")
    if corner is None:
        return None, "corner が sharp/soft のいずれでもない(%r)" % src.get("corner")

    tone = src.get("tone_sample")
    if not _nonempty_str(tone):
        return None, "tone_sample が空"
    tone = " ".join(tone.split()) if "\n" in tone else tone.strip()
    if len(tone) > TONE_SAMPLE_MAX:
        warnings.append("tone_sample が%d字を超えたため句読点境界で切り詰めた" % TONE_SAMPLE_MAX)
        tone = truncate_tone(tone, TONE_SAMPLE_MAX)

    tokens = {"palette": palette, "heading_font": heading_font,
              "density": density, "corner": corner, "tone_sample": tone}
    return tokens, warnings


# ========= 検証: コンパイル根拠文 =========
def validate_rationales(obj, question_points):
    """rationales を検証・正規化する。(rationales, warnings) か (None, 理由) を返す。"""
    if not isinstance(obj, dict):
        return None, "応答がオブジェクトでない"
    src = obj.get("rationales") if isinstance(obj.get("rationales"), dict) else obj
    if not isinstance(src, dict):
        return None, "rationales がオブジェクトでない"

    warnings = []
    out = {}
    # 完全一致を優先し、外れたキーは順序で補完する(モデルがキーを言い換えた場合の救済)
    leftovers = [(k, v) for k, v in src.items() if k not in question_points and _nonempty_str(v)]
    for qp in question_points:
        v = src.get(qp)
        if _nonempty_str(v):
            out[qp] = " ".join(str(v).split())
    if len(out) < len(question_points) and leftovers:
        for qp in question_points:
            if qp in out:
                continue
            if not leftovers:
                break
            k, v = leftovers.pop(0)
            out[qp] = " ".join(str(v).split())
            warnings.append("キー不一致のため順序で対応付けた: %r → %r" % (k[:40], qp[:40]))
    missing = [qp for qp in question_points if qp not in out]
    if len(out) == 0:
        return None, "どの question_point にも根拠文が返ってこなかった"
    if missing:
        warnings.append("根拠文が欠けた判断点が %d 件ある" % len(missing))
    return out, warnings


# ========= セッションログ(証拠化) =========
class SessionLog:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def append(self, endpoint, model, wall_ms, api_ms, ok):
        line = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
            "model": model,
            "wall_ms": wall_ms,
            "api_ms": api_ms,
            "ok": bool(ok),
        }, ensure_ascii=False)
        try:
            with self.lock:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    f.flush()
        except OSError as e:
            print("警告: セッションログ書込失敗: %s" % e, file=sys.stderr, flush=True)


# ========= サーバ状態(グローバル1個) =========
class ServerState:
    def __init__(self, args):
        self.args = args
        self.model = args.model
        self.render_model = args.render_model
        self.compile_model = args.compile_model or args.model
        self.runner = ClaudeRunner(args.claude_bin, args.timeout, args.max_concurrency,
                                   allow_api_key=args.allow_api_key,
                                   effort=args.effort)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        self.log = SessionLog(LOGS_DIR / ("session_%s.jsonl" % ts))
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.counters = {"explode": 0, "render": 0, "compile": 0, "errors": 0}
        self.counter_lock = threading.Lock()
        # プロンプトは起動時に1回読む(存在しないものは None のまま。該当APIで説明的エラーを返す)
        self.prompts = {}
        self.prompt_errors = {}
        self._load_prompt("explode", EXTRACTION_PROMPT_PATH, build_extraction_system)
        self._load_prompt("render", RENDER_PROMPT_PATH, build_render_system)
        self._load_prompt("compile", COMPILE_PROMPT_PATH, build_compile_system)

    def _load_prompt(self, key, path, builder):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            self.prompts[key] = None
            self.prompt_errors[key] = "プロンプト %s を読めない: %s" % (path, e)
            return
        if not raw.strip():
            self.prompts[key] = None
            self.prompt_errors[key] = "プロンプト %s が空である" % path
            return
        self.prompts[key] = builder(raw)

    def bump(self, key, ok):
        with self.counter_lock:
            if key in self.counters:
                self.counters[key] += 1
            if not ok:
                self.counters["errors"] += 1


STATE = None  # main で設定


# ========= エンドポイント実装 =========
def err(message, hint=""):
    return {"ok": False, "error": message, "hint": hint}


def call_claude(endpoint, system_prompt, user_prompt, model):
    """claude 実行 + セッションログ追記。(rec, timing) を返す。"""
    rec = STATE.runner.run(system_prompt, user_prompt, model)
    timing = {"wall_ms": rec["wall_ms"], "api_ms": rec["api_ms"]}
    return rec, timing


def handle_explode(body):
    brief = body.get("brief")
    if not _nonempty_str(brief):
        return err("brief が空である", "ブリーフ本文を1文以上入力する。"), None, STATE.model
    system_prompt = STATE.prompts.get("explode")
    if system_prompt is None:
        return err(STATE.prompt_errors.get("explode", "抽出プロンプトが読めない"),
                   "prompts/extraction_product_v1.txt を確認してサーバを再起動する。"), None, STATE.model

    model = STATE.model
    rec, timing = call_claude("/api/explode", system_prompt, brief, model)
    if not rec["ok"]:
        out = err(rec["error"], rec["hint"] or "")
        out["timing"] = timing
        return out, rec, model

    def accept(o):
        return all(k in o for k in EXTRACTION_REQUIRED_TOP)

    ex, why = extract_json_object(rec["result_text"], accept)
    if ex is None:
        out = err("抽出結果のJSONを読み取れなかった(%s)" % why,
                  "同じブリーフでもう一度送信する。繰り返す場合は --model を確認する。")
        out["timing"] = timing
        return out, rec, model

    payload, why = validate_extraction(brief, ex)
    if payload is None:
        out = err("抽出結果の検証に失敗した(%s)" % why, "同じブリーフでもう一度送信する。")
        out["timing"] = timing
        return out, rec, model

    if not payload["branches"]:
        # 分岐0件は「完全指定に近いブリーフ」では正当な結果。棄却が原因の0件と区別できるよう
        # note を添えて ok:true で返す(クライアントが文言を出し分ける)。
        payload["note"] = ("判断点は抽出されなかった(モデル出力 %d 件 / 検証で棄却 %d 件)"
                           % (payload["branches_returned_by_model"], len(payload["rejected_branches"])))

    out = {"ok": True}
    out.update(payload)
    out["timing"] = timing
    return out, rec, model


def handle_render(body):
    """{brief, question_point, option:{label}, sibling_labels:[...]} を受ける。

    対照性は sibling_labels(同じ判断点に並ぶ他オプションのラベル群)をモデルへ渡すことで
    担保する。レンダラーが「離れるべき方向」を直接知るので、中庸な値へ収束しにくい。
    旧契約のフィールド(downstream_impact, option.thumbnail_description)が来ても無視する。
    """
    brief = body.get("brief")
    question_point = body.get("question_point")
    option = body.get("option")
    model = STATE.render_model

    if not _nonempty_str(brief):
        return err("brief が空である", "ブリーフ原文を添えて送る。"), None, model
    if not _nonempty_str(question_point):
        return err("question_point が空である", "対象の判断点を添えて送る。"), None, model
    # option は {label} が必須。文字列で来た場合も label として受ける。
    if isinstance(option, str):
        option = {"label": option}
    if not isinstance(option, dict) or not _nonempty_str(option.get("label")):
        return err("option.label が必要である",
                   "抽出結果のオプションの label をそのまま渡す。"), None, model

    siblings_raw = body.get("sibling_labels")
    label = option["label"].strip()
    siblings = []
    if isinstance(siblings_raw, list):
        for s in siblings_raw:
            t = s.strip() if isinstance(s, str) else ""
            if t and t != label and t not in siblings:
                siblings.append(t)

    system_prompt = STATE.prompts.get("render")
    if system_prompt is None:
        return err(STATE.prompt_errors.get("render", "レンダプロンプトが読めない"),
                   "prompts/render_v0.txt を確認してサーバを再起動する。"), None, model

    user_payload = json.dumps({
        "brief": brief,
        "question_point": question_point,
        "option": {"label": label},
        "sibling_labels": siblings,
    }, ensure_ascii=False, indent=2)

    rec, timing = call_claude("/api/render", system_prompt, user_payload, model)
    if not rec["ok"]:
        out = err(rec["error"], rec["hint"] or "")
        out["timing"] = timing
        return out, rec, model

    def accept(o):
        src = o.get("tokens") if isinstance(o.get("tokens"), dict) else o
        return isinstance(src, dict) and "palette" in src and "tone_sample" in src

    obj, why = extract_json_object(rec["result_text"], accept)
    if obj is None:
        out = err("レンダトークンのJSONを読み取れなかった(%s)" % why, "このオプションだけ再レンダする。")
        out["timing"] = timing
        return out, rec, model

    tokens, warnings = validate_tokens(obj)
    if tokens is None:
        out = err("レンダトークンの検証に失敗した(%s)" % warnings, "このオプションだけ再レンダする。")
        out["timing"] = timing
        return out, rec, model

    out = {"ok": True, "tokens": tokens, "timing": timing}
    if warnings:
        out["warnings"] = warnings
    return out, rec, model


def handle_compile(body):
    brief = body.get("brief")
    decisions = body.get("decisions")
    model = STATE.compile_model

    if not _nonempty_str(brief):
        return err("brief が空である", "ブリーフ原文を添えて送る。"), None, model
    if not isinstance(decisions, list) or not decisions:
        return err("decisions が空である", "確定/委任した判断点を1件以上添えて送る。"), None, model

    clean = []
    for d in decisions:
        if not isinstance(d, dict) or not _nonempty_str(d.get("question_point")):
            continue
        status = d.get("status")
        status = status if status in ("decided", "delegated") else "delegated"
        # anchor_words は配列でなければ捨てる。文字列で来ると1文字ずつのリストに
        # 分解されて("高級感" → ["高","級","感"])黙ってプロンプトへ入ってしまう。
        aw = d.get("anchor_words")
        item = {"question_point": d["question_point"],
                "anchor_words": [a for a in aw if _nonempty_str(a)] if isinstance(aw, list) else [],
                "status": status}
        if _nonempty_str(d.get("chosen_label")):
            item["chosen_label"] = d["chosen_label"]
        if isinstance(d.get("chosen_tokens"), dict):
            item["chosen_tokens"] = d["chosen_tokens"]
        clean.append(item)
    if not clean:
        return err("有効な decisions が1件もない", "question_point を含む判断点を渡す。"), None, model

    system_prompt = STATE.prompts.get("compile")
    if system_prompt is None:
        return err(STATE.prompt_errors.get("compile", "コンパイルプロンプトが読めない"),
                   "prompts/compile_v0.txt を確認してサーバを再起動する。"), None, model

    user_payload = json.dumps({"brief": brief, "decisions": clean}, ensure_ascii=False, indent=2)
    rec, timing = call_claude("/api/compile", system_prompt, user_payload, model)
    if not rec["ok"]:
        out = err(rec["error"], rec["hint"] or "")
        out["timing"] = timing
        return out, rec, model

    qps = [d["question_point"] for d in clean]

    def accept(o):
        if isinstance(o.get("rationales"), dict):
            return True
        # rationales ラッパーなしで question_point → 文 のマップを返した場合も受理
        return bool(o) and all(isinstance(v, str) for v in o.values()) and any(k in qps for k in o)

    obj, why = extract_json_object(rec["result_text"], accept)
    if obj is None:
        out = err("根拠文のJSONを読み取れなかった(%s)" % why, "もう一度コンパイルを実行する。")
        out["timing"] = timing
        return out, rec, model

    rationales, warnings = validate_rationales(obj, qps)
    if rationales is None:
        out = err("根拠文の検証に失敗した(%s)" % warnings, "もう一度コンパイルを実行する。")
        out["timing"] = timing
        return out, rec, model

    out = {"ok": True, "rationales": rationales, "timing": timing}
    if warnings:
        out["warnings"] = warnings
    return out, rec, model


ROUTES = {
    "/api/explode": ("explode", handle_explode),
    "/api/render": ("render", handle_render),
    "/api/compile": ("compile", handle_compile),
}


# ========= HTTP ハンドラ =========
class Handler(BaseHTTPRequestHandler):
    server_version = "GYAKUMON/0.1"
    protocol_version = "HTTP/1.1"

    # --- 共通 ---
    def log_message(self, fmt, *args):
        # 既定の stderr ログは冗長。要点だけ標準出力へ出す(_access で明示的に出す)。
        pass

    def _access(self, method, path, status, note=""):
        print("%s %s %s %s" % (datetime.now().strftime("%H:%M:%S"), method, path,
                               ("%d %s" % (status, note)).strip()), flush=True)

    def _send_bytes(self, status, content_type, data, extra_headers=None):
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # クライアントが切断(タブを閉じた等)。サーバは継続する。

    def _send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", data)

    # --- ローカル専用ガード(クロスサイトからのドライブバイ呼び出し遮断) ---
    LOOPBACK_NAMES = ("127.0.0.1", "localhost", "::1", "[::1]")

    def _host_ok(self):
        """Host ヘッダがループバック:自ポートであることを確認する。
        127.0.0.1 バインドでも、悪意あるページからの fetch や DNS リバインディングで
        claude 子プロセスを起動させられる(応答が読めなくても副作用は成立する)ため、
        API はここで Host を検証して 403 で落とす。"""
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return False
        port = STATE.args.port
        allowed = set()
        for name in self.LOOPBACK_NAMES:
            allowed.add(name)
            allowed.add("%s:%d" % (name, port))
        bind = (STATE.args.host or "").strip().lower()
        if bind and bind not in ("0.0.0.0", "::", ""):
            allowed.add(bind)
            allowed.add("%s:%d" % (bind, port))
        return host in allowed

    def _guard_api(self):
        """API 共通ガード。通過なら True、拒否済みなら False。"""
        if not self._host_ok():
            self._send_bytes(403, "text/plain; charset=utf-8",
                             "403 forbidden (Host)\n".encode("utf-8"))
            self._access(self.command, urllib.parse.urlsplit(self.path).path, 403, "bad-host")
            return False
        return True

    def _content_type_ok(self):
        """POST は application/json のみ受ける。text/plain 等の CORS セーフリスト型を
        拒むことで、プリフライトを伴わないクロスサイト POST 経路を消す
        (本サーバは OPTIONS を実装していないのでプリフライトは自然に失敗する)。"""
        ctype = (self.headers.get("Content-Type") or "").strip().lower()
        return ctype.split(";")[0].strip() == "application/json"

    def _read_body(self):
        """ボディを必ず読み切る(keep-alive の同期ずれ防止)。(obj, error) を返す。"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "Content-Length が不正である"
        if length < 0:
            return None, "Content-Length が不正である"
        if length > MAX_BODY_BYTES:
            # 読み捨ててから拒否
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            return None, "リクエストが大きすぎる(上限 %d バイト)" % MAX_BODY_BYTES
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return None, "リクエストボディが空である"
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return None, "リクエストボディがJSONとしてパースできない: %s" % e
        if not isinstance(obj, dict):
            return None, "リクエストボディがJSONオブジェクトでない"
        return obj, None

    # --- GET / HEAD ---
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/api/") and not self._guard_api():
            return
        if path == "/api/health":
            payload = {
                "ok": True,
                "started_at": STATE.started_at,
                "model": STATE.model,
                "render_model": STATE.render_model,
                "compile_model": STATE.compile_model,
                "effort": STATE.args.effort,
                "max_concurrency": STATE.args.max_concurrency,
                "timeout_s": STATE.args.timeout,
                "session_log": str(STATE.log.path),
                "prompts_ready": {k: (v is not None) for k, v in STATE.prompts.items()},
                "counters": dict(STATE.counters),
            }
            self._send_json(payload)
            self._access("GET", path, 200)
            return
        if path.startswith("/api/"):
            self._send_json(err("GET は未対応のエンドポイントである(%s)" % path,
                                "POST /api/explode | /api/render | /api/compile を使う。"))
            self._access("GET", path, 200, "unknown-api")
            return
        self._serve_static(path)

    def _serve_static(self, path):
        if path == "/" or path == "":
            path = "/index.html"
        # パス正規化(ディレクトリトラバーサル遮断)
        rel = posixpath.normpath(urllib.parse.unquote(path)).lstrip("/")
        target = (APP_DIR / rel).resolve()
        try:
            app_root = APP_DIR.resolve()
        except OSError:
            app_root = APP_DIR
        if target != app_root and app_root not in target.parents:
            self._send_bytes(403, "text/plain; charset=utf-8", "403 forbidden\n".encode("utf-8"))
            self._access("GET", path, 403)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            if rel in ("index.html", ""):
                msg = ("GYAKUMON server は起動しているが app/index.html が存在しない。\n"
                       "期待するパス: %s\n" % (APP_DIR / "index.html"))
                self._send_bytes(503, "text/plain; charset=utf-8", msg.encode("utf-8"))
                self._access("GET", path, 503, "app-missing")
                return
            self._send_bytes(404, "text/plain; charset=utf-8", "404 not found\n".encode("utf-8"))
            self._access("GET", path, 404)
            return
        try:
            data = target.read_bytes()
        except OSError as e:
            self._send_bytes(500, "text/plain; charset=utf-8", ("500 %s\n" % e).encode("utf-8"))
            self._access("GET", path, 500)
            return
        ext = target.suffix.lower()
        ctype = TEXT_MIME_CHARSET.get(ext) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send_bytes(200, ctype, data)
        self._access("GET", path, 200)

    # --- POST ---
    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        body, berr = self._read_body()   # 常に読み切ってから分岐する(keep-alive の同期を保つ)
        # ボディを読み切った後にローカル専用ガードを適用する。claude 子プロセスは起動しない。
        if not self._guard_api():
            return
        if not self._content_type_ok():
            self._send_bytes(403, "text/plain; charset=utf-8",
                             "403 forbidden (Content-Type)\n".encode("utf-8"))
            self._access("POST", path, 403, "bad-content-type")
            return
        route = ROUTES.get(path)
        if route is None:
            self._send_json(err("未対応のエンドポイントである(%s)" % path,
                                "POST /api/explode | /api/render | /api/compile を使う。"))
            self._access("POST", path, 200, "unknown-api")
            return
        name, fn = route
        if berr:
            self._send_json(err(berr, "Content-Type: application/json でJSONオブジェクトを送る。"))
            STATE.bump(name, False)
            self._access("POST", path, 200, "bad-request")
            return

        t0 = time.monotonic()
        try:
            out, rec, model = fn(body)
        except Exception as e:  # ハンドラ内の想定外例外もHTTP 200のエラー契約で返す
            out = err("サーバ内部エラー: %s: %s" % (type(e).__name__, e),
                      "サーバの標準出力を確認する。")
            rec, model = None, "-"
            import traceback
            traceback.print_exc()

        wall_ms = rec["wall_ms"] if rec else round((time.monotonic() - t0) * 1000)
        api_ms = rec["api_ms"] if rec else None
        STATE.log.append(path, model, wall_ms, api_ms, bool(out.get("ok")))
        STATE.bump(name, bool(out.get("ok")))
        self._send_json(out)
        self._access("POST", path, 200,
                     "%s wall=%sms api=%sms" % ("ok" if out.get("ok") else "NG", wall_ms, api_ms))


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ========= main =========
def main():
    global STATE
    ap = argparse.ArgumentParser(description="GYAKUMON ローカルサーバ(claude CLI ヘッドレス)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="待受ポート(既定: %d)" % DEFAULT_PORT)
    ap.add_argument("--host", default=DEFAULT_HOST, help="待受アドレス(既定: 127.0.0.1。localhost以外は非推奨)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="/api/explode と /api/compile のモデル(既定: sonnet)")
    ap.add_argument("--render-model", default=DEFAULT_RENDER_MODEL, help="/api/render のモデル(既定: haiku)")
    ap.add_argument("--compile-model", default=None, help="/api/compile を別モデルにする場合(既定: --model と同じ)")
    ap.add_argument("--effort", default=DEFAULT_EFFORT,
                    help="claude の --effort(既定: %s。抽出/レンダは分類タスクなので low で足りる)"
                         % DEFAULT_EFFORT)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="claude 1呼び出しのタイムアウト秒(既定: 120)")
    ap.add_argument("--max-concurrency", type=int, default=DEFAULT_MAX_CONCURRENCY,
                    help="claude 子プロセスの同時実行上限(既定: 6。超過はキュー)")
    ap.add_argument("--claude-bin", default="claude", help="claude CLI のパス(既定: PATH上の claude)")
    ap.add_argument("--allow-api-key", action="store_true",
                    help="子プロセスへ ANTHROPIC_API_KEY を渡す(既定は除去。サブスクリプション認証が主経路)")
    args = ap.parse_args()

    if args.max_concurrency < 1:
        print("エラー: --max-concurrency は1以上である。", file=sys.stderr)
        return 2

    STATE = ServerState(args)

    try:
        httpd = Server((args.host, args.port), Handler)
    except OSError as e:
        print("エラー: %s:%d を待ち受けできない: %s" % (args.host, args.port, e), file=sys.stderr)
        print("ヒント: 既に起動済みのサーバがいないか確認する(lsof -i :%d)。別ポートは --port。" % args.port,
              file=sys.stderr)
        STATE.runner.cleanup()
        return 1

    url = "http://%s:%d/" % ("127.0.0.1" if args.host in ("0.0.0.0", "") else args.host, args.port)
    print("")
    print("  GYAKUMON — Intent Compiler")
    print("  ブラウザで開く: %s" % url)
    print("")
    print("  モデル: explode/compile=%s, render=%s" % (STATE.model, STATE.render_model)
          + ("" if STATE.compile_model == STATE.model else " (compile=%s)" % STATE.compile_model))
    print("  claude: %s / effort=%s / タイムアウト %d秒 / 同時実行上限 %d"
          % (args.claude_bin, args.effort, args.timeout, args.max_concurrency))
    print("  system は --system-prompt で完全置換 / --strict-mcp-config で MCP 遮断")
    print("  子プロセス作業Dir: %s(リポジトリ外・CLAUDE.md 注入遮断)" % STATE.runner.base_dir)
    print("  セッションログ: %s" % STATE.log.path)
    if STATE.runner.stripped_env_keys:
        print("  注記: 子プロセス env から %s を除去した(サブスクリプション認証を使う)"
              % ", ".join(STATE.runner.stripped_env_keys))
    if not APP_DIR.is_file() and not (APP_DIR / "index.html").is_file():
        print("  警告: %s が見つからない(APIのみ稼働)" % (APP_DIR / "index.html"))
    for key, e in STATE.prompt_errors.items():
        print("  警告: /api/%s が使えない — %s" % (key, e))
    print("  停止: Ctrl+C")
    print("", flush=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n停止する。", flush=True)
    finally:
        httpd.server_close()
        STATE.runner.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
