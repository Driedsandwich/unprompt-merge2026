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
  POST /api/explode_stream  {brief}   → text/event-stream(SSE)
       /api/explode と同じ抽出を stream-json で走らせ、確定したものから逐次配信する。
       送信→初回カード表示までの体感時間を縮めるための経路(/api/explode は残す)。
         data: {"type":"meta",   residual_ambiguity_assessment, missing_materials, partial, elapsed_ms}
         data: {"type":"branch", index, branch:{...}, elapsed_ms}   ← anchor 検証を通った分岐のみ
         data: {"type":"done",   ok, branches, ..., timing, api_ms, first_branch_ms}
         data: {"type":"error",  error, hint}
       anchor のサーバ側検証は分岐単位で「配信前」に適用する(不合格の分岐は画面に出ない)。
       ブラウザは meta で内部準備、最初の branch で爆散を開始し、以後は到着順にカードを足す。
       ストリームが失敗したら旧 /api/explode へ自動フォールバックする(クライアント側)。
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
import select
import shutil
import signal
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
DEFAULT_RENDER_MODEL = "sonnet"     # /api/render(実測: haiku は effort low でも多弁で40秒級、sonnet は簡潔で速い)
DEFAULT_EFFORT = "low"              # --effort。実測でスリムスキーマと合わせて 110s→8.8s
DEFAULT_TIMEOUT_S = 120             # claude 呼び出し1本あたり(拘束)
DEFAULT_MAX_CONCURRENCY = 6         # 同時に走らせる claude 子プロセス数の上限
SLOT_WAIT_MARGIN_S = 60             # 実行枠の待ち行列で待てる追加秒数
# レンダ(ミニLP)は分岐5件×選択肢3で最大15本が同時に飛ぶ。全枠を占めると
# 爆散の取り直し(/api/explode)やコンパイルが待たされるので、レンダ専用の副上限を置き、
# レンダ以外のために常に RESERVED_NON_RENDER_SLOTS 枠を空けておく。
RENDER_CONCURRENCY_CAP = 3          # レンダが同時に使える上限(全枠の内数)
RESERVED_NON_RENDER_SLOTS = 2       # explode / compile のために常時空けておく枠数
TERM_GRACE_S = 3                    # 子プロセスに TERM を送ってから KILL するまで
KILL_GRACE_S = 2                    # KILL 後に回収(wait)を待つ上限
PUMP_JOIN_S = 2                     # 出力吸い出しスレッドの join 上限
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


def build_extraction_stream_system(extraction_prompt: str) -> str:
    """/api/explode_stream 専用。build_extraction_system と同内容だが branches を先に書かせる。

    理由(実測): スキーマ順どおりに書くモデルに対し、meta 2項(約200字)を先に書かせると
    その分だけ最初の分岐の確定が遅れる。同一ブリーフ・同一モデルで
      meta先   : first_delta 6.5s → branch1 9.4s(init 2.6s)
      branches先: first_delta 5.2s → branch1 8.1s(init 4.0s)
    となり、init を差し引いた「モデル時間」では 6.8s → 4.2s に短縮した。
    抽出内容そのものへの影響はない(meta 2項は分岐の要約ではなく独立した評価であり、
    先に書くか後に書くかで分岐の選び方は変わらない)。

    2026-07-29 追補: prompts/extraction_product_v1.txt 側のスキーマ例も
    branches → missing_materials → residual_ambiguity_assessment に揃えた。
    それ以前は「プロンプト本体の例は meta 先・この上書き規則は branches 先」という
    矛盾した2つの順序指示を1つのシステムプロンプトに同居させていた。
    ここで組み立てるスキーマの順もその追補に合わせてある。
    一括版 /api/explode(build_extraction_system)は EXTRACTION_SCHEMA をそのまま出すので
    上書き規則側の順序は meta 先のままだが、一括経路は全文を最後に一度だけ解釈するため
    順序に依存しない(フォールバックの挙動は変わらない)。
    """
    props = EXTRACTION_SCHEMA["properties"]
    schema = {
        "type": "object",
        "properties": {
            "branches": props["branches"],
            "missing_materials": props["missing_materials"],
            "residual_ambiguity_assessment": props["residual_ambiguity_assessment"],
        },
        "required": ["branches", "missing_materials", "residual_ambiguity_assessment"],
    }
    adapted = extraction_prompt.replace(
        "出力は必ず report_branches ツール呼び出しのみで行う。地の文・前置き・後書きを書かない。",
        "出力は単一のJSONオブジェクトのみで行う。地の文・前置き・後書きを書かない。"
    )
    rules = (
        "\n\n## 出力規則(この実行環境での上書き)\n\n"
        "- コードフェンス(```)・説明・前置き・後書きを一切付けず、単一のJSONオブジェクトのみを出力せよ。\n"
        "- 思考・分析・検討過程を書かない。即座に結論のJSONだけを書く。\n"
        "- そのJSONオブジェクトは次のJSONスキーマに厳密に従うこと。"
        "フィールド順もスキーマの順とし、branches を最初に書く。"
        "missing_materials と residual_ambiguity_assessment は branches を書き終えた後に書く:\n\n"
        + json.dumps(schema, ensure_ascii=False, indent=2) +
        "\n\n- スキーマの required をすべて満たし、スキーマにないフィールドを追加しないこと。\n"
        "- branches の各要素は1つ書き終えるごとに完結させ、後から書き直さないこと"
        "(サーバは1件書き終わるたびに検証して画面へ送る)。\n"
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


# ========= 増分パーサ(生成中テキストから meta / 各分岐を確定次第取り出す) =========
def _find_branches_array(s):
    """トップレベルオブジェクト直下の "branches" 配列を探す。

    戻り値: (オブジェクト開始 '{' の位置, キー文字列の開始位置, 配列の '[' の位置)。
    未確定なら (-1, -1, -1)。オブジェクト開始位置も返すのは、meta 部分
    (= その '{' から "branches" キーの手前まで)を切り出すのに必要だからである。
    文字列内のエスケープと波括弧・角括弧の対応を追い、
      - od: '{' の深さ / ad: '[' の深さ
      - トップレベル(od==1 かつ ad==0)でだけキーとして解釈する
      - キーと値の間に ':' があることを要求する
    ので、missing_materials の要素に "branches" という文字列が来ても誤検出しない。

    候補の開始位置は「最初の '{'」だけに賭けない。前置きの地の文に '{' が
    混ざっていた場合、そこから読むと構造がずれて永久に見つからなくなるので、
    そのオブジェクトが branches を持たずに閉じたら次の '{' から読み直す
    (extract_json_object と同じ方針)。
    """
    start = s.find("{")
    while start >= 0:
        key_pos, arr = _scan_for_branches(s, start)
        if arr >= 0:
            return start, key_pos, arr
        if key_pos == -2:
            # 入力がまだ途中で切れている。次のチャンクを待つ(候補を進めない)。
            return -1, -1, -1
        start = s.find("{", start + 1)
    return -1, -1, -1


def _scan_for_branches(s, start):
    """s[start] から1オブジェクトぶん走査する。

    戻り値: (キー位置, '[' 位置)  … 見つかった
            (-1, -1)             … このオブジェクトは branches を持たずに閉じた
            (-2, -1)             … 入力が途中で終わった(判断保留)
    """
    n = len(s)
    od = ad = 0
    in_str = esc = False
    expect_key = False
    want_value = False
    key_from = -1
    key_name = None
    key_pos = -1
    i = start
    while i < n:
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
                if expect_key and od == 1 and ad == 0:
                    key_name = s[key_from + 1:i]
                    key_pos = key_from
                    expect_key = False
        else:
            if c == '"':
                in_str = True
                key_from = i
            elif c == "{":
                od += 1
                if od == 1 and ad == 0:
                    expect_key = True
                want_value = False
            elif c == "}":
                od -= 1
                if od <= 0:
                    return -1, -1        # branches を持たずに閉じた → 次の候補へ
            elif c == "[":
                if want_value and od == 1 and ad == 0 and key_name == "branches":
                    return key_pos, i
                ad += 1
                want_value = False
            elif c == "]":
                ad -= 1
            elif c == ":":
                if od == 1 and ad == 0:
                    want_value = True
            elif c == ",":
                if od == 1 and ad == 0:
                    expect_key = True
                    want_value = False
                    key_name = None
        i += 1
    return -2, -1                        # 入力が途中で終わった → 判断保留


def _next_complete_object(s, pos):
    """s[pos:] から配列要素の走査を進める。

    戻り値: ("object", start, end) / ("end", idx, idx) / (None, pos, pos)
      - "object": s[start:end+1] が対応の取れた1オブジェクト
      - "end"   : 配列の閉じ ']' に到達した
      - None    : まだ確定していない(次のチャンクを待つ)
    """
    n = len(s)
    i = pos
    while i < n and s[i] not in "{]":
        i += 1
    if i >= n:
        return None, i, i          # 空白・カンマだけ。走査位置は進めてよい
    if s[i] == "]":
        return "end", i, i
    # ここから1オブジェクトの対応取り
    od = 0
    in_str = esc = False
    j = i
    while j < n:
        c = s[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                od += 1
            elif c == "}":
                od -= 1
                if od == 0:
                    return "object", i, j
        j += 1
    return None, i, i              # 未完。次のチャンクで同じ位置から読み直す


class StreamingExtractionParser:
    """生成中の抽出JSONを増分で解釈する。

    feed(chunk) は、そのチャンクで新たに確定した事象のリストを返す:
      ("meta", {"residual_ambiguity_assessment": str, "missing_materials": [str], "partial": bool})
      ("branch", {分岐オブジェクト(モデル出力のまま。検証は呼び出し側)}, raw_index)
      ("branches_end", None, None)

    確定の定義:
      meta   … トップレベル "branches" キーに到達した時点。スキーマ順(assessment →
               missing_materials → branches)ではこの時点で前2項が閉じている。
               前置き部分を "}" で閉じて JSON として解釈できたら partial=False。
               branches が先に来るスキーマでは partial=True の空 meta を出す
               (本文は done イベントの全体JSONが権威)。
      branch … branches 配列内の1オブジェクトの波括弧が閉じた時点。
    """

    def __init__(self):
        self.buf = ""
        self.obj_start = -1
        self.arr_start = -1
        self.scan = 0
        self.meta_emitted = False
        self.array_ended = False
        self.raw_index = 0

    def feed(self, chunk):
        events = []
        if not chunk:
            return events
        self.buf += chunk

        if self.arr_start < 0:
            obj_start, key_pos, arr = _find_branches_array(self.buf)
            if arr < 0:
                return events
            self.obj_start = obj_start
            self.arr_start = arr
            self.scan = arr + 1
            if not self.meta_emitted:
                self.meta_emitted = True
                events.append(("meta", self._parse_head(key_pos), None))

        if self.array_ended:
            return events

        while True:
            kind, a, b = _next_complete_object(self.buf, self.scan)
            if kind is None:
                self.scan = a
                break
            if kind == "end":
                self.scan = a + 1
                self.array_ended = True
                events.append(("branches_end", None, None))
                break
            self.scan = b + 1
            try:
                obj = json.loads(self.buf[a:b + 1])
            except json.JSONDecodeError:
                # 対応は取れたが JSON として不正(まず起きない)。この要素だけ捨てて先へ進む。
                self.raw_index += 1
                continue
            idx = self.raw_index
            self.raw_index += 1
            events.append(("branch", obj, idx))
        return events

    def _parse_head(self, key_pos):
        """"branches" キーより手前(= meta 部分)を単体のJSONとして解釈する。"""
        blank = {"residual_ambiguity_assessment": "", "missing_materials": [], "partial": True}
        if self.obj_start < 0 or key_pos <= self.obj_start:
            return blank
        head = self.buf[self.obj_start:key_pos].rstrip()
        if head.endswith(","):
            head = head[:-1]
        try:
            obj = json.loads(head + "}")
        except json.JSONDecodeError:
            return blank
        if not isinstance(obj, dict) or "residual_ambiguity_assessment" not in obj:
            return blank
        mats = obj.get("missing_materials")
        return {
            "residual_ambiguity_assessment": (obj.get("residual_ambiguity_assessment")
                                              if isinstance(obj.get("residual_ambiguity_assessment"), str) else ""),
            "missing_materials": ([str(m) for m in mats if _nonempty_str(m)]
                                  if isinstance(mats, list) else []),
            "partial": False,
        }


# ========= claude CLI 実行器(実行枠プール付き) =========
class ClaudeRunner:
    """claude -p をスレッドセーフに呼ぶ実行器。

    - 同時実行数を max_concurrency に制限する(超過分はキューで待つ)。
    - さらに kind="render" には副上限(render_cap)を課す。レンダは1画面で最大15本
      飛ぶので、これが無いと全枠を占め、爆散の取り直しやコンパイルが枠待ちで
      止まる(実測で「リロード後の再送が待たされる」経路がここ)。
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
        # レンダ専用の副上限。全枠が RESERVED_NON_RENDER_SLOTS 以下しかない構成でも
        # 1本は通す(それ以上絞ると画面が何も出せない)。
        self.render_cap = max(1, min(RENDER_CONCURRENCY_CAP,
                                     max_concurrency - RESERVED_NON_RENDER_SLOTS))
        self.render_sema = threading.BoundedSemaphore(self.render_cap)
        # 走っているストリーミング子プロセス。start_new_session で親のプロセスグループから
        # 外している以上、Ctrl+C はもう子へ届かない。停止時にここを見て自分で始末する。
        self._live = set()
        self._live_lock = threading.Lock()
        self.env = os.environ.copy()
        self.stripped_env_keys = []
        if not allow_api_key:
            for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
                if k in self.env:
                    del self.env[k]
                    self.stripped_env_keys.append(k)

    def cleanup(self):
        self.terminate_all()
        shutil.rmtree(self.base_dir, ignore_errors=True)

    def terminate_all(self):
        """停止時に、走っている claude 子プロセスをグループごと始末する。"""
        with self._live_lock:
            procs = list(self._live)
        for p in procs:
            self._reap(p, None)

    # ---- 実行枠の取得/返却(レンダの副上限つき) ----
    def _acquire_render_token(self, kind, deadline):
        """kind="render" のときだけ副上限を取る。取れたら True。"""
        if kind != "render":
            return True
        return self.render_sema.acquire(timeout=max(0.0, deadline - time.monotonic()))

    def _release_render_token(self, kind):
        if kind != "render":
            return
        try:
            self.render_sema.release()
        except ValueError:
            pass

    def _busy_rec(self, rec, t_wait, kind):
        rec["wall_ms"] = round((time.monotonic() - t_wait) * 1000)
        if kind == "render":
            rec["error"] = ("サーバが混雑している(レンダ枠 %d がすべて埋まったまま待ち切れなかった)"
                            % self.render_cap)
        else:
            rec["error"] = "サーバが混雑している(同時実行 %d 枠がすべて埋まったまま経過)" % self.max_concurrency
        rec["hint"] = "少し待って再試行するか、--max-concurrency を上げて再起動する。"
        return rec

    def _reap(self, proc, threads):
        """子プロセスを確実に終わらせ、回収し、出力吸い出しスレッドも畳む。

        - 起動時に start_new_session=True でプロセスグループを分けているので、
          claude が孫プロセスを持っていてもグループごと止められる。
        - TERM → 期限付き wait → KILL → wait の順。kill しっぱなしでゾンビを残さない。
        - パイプを閉じてから pump スレッドを join する(閉じると読み側が例外で抜ける)。
        """
        if proc is None:
            return
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    proc.terminate()
                except OSError:
                    pass
            try:
                proc.wait(timeout=TERM_GRACE_S)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    try:
                        proc.kill()
                    except OSError:
                        pass
                try:
                    proc.wait(timeout=KILL_GRACE_S)
                except subprocess.TimeoutExpired:
                    print("警告: claude 子プロセス(pid=%s)を回収できなかった" % proc.pid,
                          file=sys.stderr, flush=True)
        else:
            try:
                proc.wait(timeout=KILL_GRACE_S)   # 既に終了 → ゾンビを回収するだけ
            except subprocess.TimeoutExpired:
                pass
        for s in (proc.stdout, proc.stderr):
            try:
                if s:
                    s.close()
            except OSError:
                pass
        for t in (threads or []):
            if t is not None:
                t.join(timeout=PUMP_JOIN_S)
                if t.is_alive():
                    print("警告: 出力吸い出しスレッドが %.0f 秒で終わらなかった" % PUMP_JOIN_S,
                          file=sys.stderr, flush=True)
        with self._live_lock:
            self._live.discard(proc)

    def run(self, system_prompt, user_prompt, model, kind="other"):
        """1回の claude -p 実行。結果 dict を返す(例外を投げない)。

        戻り値: {ok, wall_ms, api_ms, duration_ms, result_text, error, hint, exit_code}
        kind="render" は副上限(render_cap)の対象。
        """
        rec = {"ok": False, "wall_ms": None, "api_ms": None, "duration_ms": None,
               "result_text": None, "error": None, "hint": None, "exit_code": None}
        wait_deadline = self.timeout_s + SLOT_WAIT_MARGIN_S
        t_wait = time.monotonic()
        deadline = t_wait + wait_deadline
        if not self._acquire_render_token(kind, deadline):
            return self._busy_rec(rec, t_wait, kind)
        try:
            workdir = self.slots.get(timeout=max(0.05, deadline - time.monotonic()))
        except queue.Empty:
            self._release_render_token(kind)
            return self._busy_rec(rec, t_wait, kind)

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
               "--setting-sources", "project",
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
            self._release_render_token(kind)

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

    def run_stream(self, system_prompt, user_prompt, model, idle_s=1.0):
        """claude -p を --output-format stream-json で起動し、逐次イベントを yield する生成器。

        yield されるもの(いずれも2要素タプル):
          ("text",   str)   モデル本文の増分(content_block_delta の text_delta)
          ("idle",   None)  idle_s 秒何も来なかった(呼び出し側のハートビート用)
          ("result", dict)  CLI の最終 result イベント(duration_api_ms 等)
          ("error",  dict)  失敗。run() と同じ {error, hint, wall_ms, ...} 形式
        最後は必ず ("result", …) か ("error", …) のどちらか1回で終わる。

        run() と同じ拘束(cwd はリポジトリ外の実行枠 / --system-prompt で完全置換 /
        --strict-mcp-config / --effort / stdin は使わない / user_prompt は "--" の後ろ)を保つ。
        追加フラグは --output-format stream-json --include-partial-messages --verbose のみ。
        (--verbose は -p + stream-json の組で CLI が要求する。)
        """
        rec = {"ok": False, "wall_ms": None, "api_ms": None, "duration_ms": None,
               "result_text": None, "error": None, "hint": None, "exit_code": None}
        wait_deadline = self.timeout_s + SLOT_WAIT_MARGIN_S
        t_wait = time.monotonic()
        try:
            workdir = self.slots.get(timeout=wait_deadline)
        except queue.Empty:
            yield ("error", self._busy_rec(rec, t_wait, "explode_stream"))
            return

        cmd = [self.claude_bin,
               "--system-prompt", system_prompt,
               "--strict-mcp-config",
               "--setting-sources", "project",
               "--effort", self.effort,
               "--model", model,
               "--output-format", "stream-json", "--include-partial-messages", "--verbose",
               "-p", "--", user_prompt]

        t0 = time.monotonic()
        proc = None
        t_out = t_err = None
        try:
            try:
                # start_new_session=True: 子を独立したプロセスグループにする。
                # クライアント切断や打ち切りのとき、claude が持つ孫プロセスごと
                # killpg で確実に止めるための前提(kill しっぱなしにしない。M3)。
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, bufsize=1, cwd=workdir,
                                        stdin=subprocess.DEVNULL, env=self.env,
                                        start_new_session=True)
            except FileNotFoundError:
                rec["wall_ms"] = round((time.monotonic() - t0) * 1000)
                rec["error"] = "claude コマンドが見つからない(%r)" % self.claude_bin
                rec["hint"] = "Claude Code のインストールと PATH、または --claude-bin を確認する。"
                yield ("error", rec)
                return
            except OSError as e:
                rec["wall_ms"] = round((time.monotonic() - t0) * 1000)
                rec["error"] = "claude の起動に失敗した: %s" % e
                rec["hint"] = "実行権限とディスク空きを確認する。"
                yield ("error", rec)
                return
            with self._live_lock:
                self._live.add(proc)

            # stdout は行単位でキューへ。stderr は別スレッドで吸い出す(パイプ満杯によるデッドロック防止)。
            q = queue.Queue()
            errbuf = []

            def pump_out():
                try:
                    for line in proc.stdout:
                        q.put(("line", line))
                except (ValueError, OSError):
                    pass
                q.put(("eof", None))

            def pump_err():
                try:
                    for line in proc.stderr:
                        if len(errbuf) < 40:
                            errbuf.append(line)
                except (ValueError, OSError):
                    pass

            t_out = threading.Thread(target=pump_out, daemon=True, name="gyakumon-pump-out")
            t_err = threading.Thread(target=pump_err, daemon=True, name="gyakumon-pump-err")
            t_out.start()
            t_err.start()

            cli_json = None
            saw_eof = False
            while not saw_eof:
                if time.monotonic() - t0 > self.timeout_s:
                    rec["wall_ms"] = round((time.monotonic() - t0) * 1000)
                    rec["error"] = "claude 呼び出しがタイムアウトした(%d秒)" % self.timeout_s
                    rec["hint"] = "ネットワークとモデル指定を確認し、再送する。--timeout で延長できる。"
                    yield ("error", rec)
                    return
                try:
                    kind, line = q.get(timeout=idle_s)
                except queue.Empty:
                    yield ("idle", None)
                    continue
                if kind == "eof":
                    saw_eof = True
                    break
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue                      # CLI が出す非JSON行(まず無い)は捨てる
                if not isinstance(ev, dict):
                    continue
                etype = ev.get("type")
                if etype == "stream_event":
                    inner = ev.get("event") or {}
                    if inner.get("type") == "content_block_delta":
                        delta = inner.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            txt = delta.get("text")
                            if isinstance(txt, str) and txt:
                                yield ("text", txt)
                elif etype == "result":
                    cli_json = ev

            proc.wait(timeout=5)
            rec["wall_ms"] = round((time.monotonic() - t0) * 1000)
            rec["exit_code"] = proc.returncode

            if cli_json is None:
                rec["error"] = "claude CLI が result イベントを返さなかった(exit=%s)" % proc.returncode
                rec["hint"] = ("`claude -p \"ping\" --output-format json` を手で実行して CLI が正常か"
                               "ログイン済みかを確認する。stderr: " + ("".join(errbuf))[:300])
                yield ("error", rec)
                return

            rec["duration_ms"] = cli_json.get("duration_ms")
            rec["api_ms"] = cli_json.get("duration_api_ms")
            if proc.returncode != 0 or cli_json.get("is_error"):
                rec["error"] = "claude CLI がエラーを返した(exit=%s, is_error=%s)" % (
                    proc.returncode, cli_json.get("is_error"))
                rec["hint"] = (str(cli_json.get("result"))[:300] if cli_json.get("result")
                               else "Claude Code のログイン状態と利用上限を確認する。")
                yield ("error", rec)
                return

            rec["result_text"] = cli_json.get("result")
            rec["ok"] = True
            yield ("result", rec)
        except subprocess.TimeoutExpired:
            rec["wall_ms"] = round((time.monotonic() - t0) * 1000)
            rec["error"] = "claude の終了待ちがタイムアウトした"
            rec["hint"] = "再送する。"
            yield ("error", rec)
        finally:
            # 生成器が途中で閉じられた(クライアント切断)場合もここを通る。
            # 実行枠は「子プロセスを回収し、吸い出しスレッドを畳んでから」返す。
            # 先に返すと、まだ CPU とネットワークを使っている claude が枠外で走り続け、
            # 次のリクエストと二重に走る(M3)。
            self._reap(proc, (t_out, t_err))
            self.slots.put(workdir)


# ========= 検証: 抽出結果(anchor 機械検証を含む) =========
def _nonempty_str(v):
    return isinstance(v, str) and v.strip() != ""


def validate_branch(brief_text, br, idx):
    """分岐1件を検証・正規化する。(branch, None) か (None, 理由リスト) を返す。

    /api/explode(一括)と /api/explode_stream(逐次)の両方がこの1実装だけを使う。
    分岐単位で完結する検証しかここに置かない(上限5件の切り捨ては呼び出し側の責務)。
    """
    if not isinstance(br, dict):
        return None, ["分岐がオブジェクトでない"]

    reasons = []
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
        return None, reasons

    return {
        "id": "b%d" % idx,
        "question_point": qp.strip(),
        "anchor_words": anchors,
        "options": options,
        "default_if_unresolved": (br.get("default_if_unresolved").strip()
                                  if _nonempty_str(br.get("default_if_unresolved")) else "")
    }, None


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
        ok_branch, reasons = validate_branch(brief_text, br, idx)
        if ok_branch is None:
            qp = br.get("question_point") if isinstance(br, dict) else ""
            rejected.append({"index": idx,
                             "question_point": qp if isinstance(qp, str) else "",
                             "reasons": reasons})
            continue
        accepted.append(ok_branch)

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

    def append(self, endpoint, model, wall_ms, api_ms, ok, first_branch_ms=None,
               client_gone=None):
        """1リクエスト1行。first_branch_ms はストリーミング爆散のみ持つ

        (送信から最初の分岐カードをクライアントへ送り出すまでのサーバ実測ms)。
        収録動画のレイテンシ表示と突き合わせるための証拠列なので、
        持たない経路では欠測を明示するために null を書く(キーは常に出す)。

        client_gone: クライアントへ届け切れなかった(切断)ことを ok と別に記録する。
        ok=false の理由が「モデルの失敗」なのか「届かなかった」なのかを
        後から区別できるようにするための列である(N3)。
        """
        line = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
            "model": model,
            "wall_ms": wall_ms,
            "api_ms": api_ms,
            "first_branch_ms": first_branch_ms,
            "ok": bool(ok),
            "client_gone": bool(client_gone) if client_gone is not None else None,
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
        self.counters = {"explode": 0, "explode_stream": 0, "render": 0, "compile": 0, "errors": 0}
        self.counter_lock = threading.Lock()
        # プロンプトは起動時に1回読む(存在しないものは None のまま。該当APIで説明的エラーを返す)
        self.prompts = {}
        self.prompt_errors = {}
        self._load_prompt("explode", EXTRACTION_PROMPT_PATH, build_extraction_system)
        self._load_prompt("explode_stream", EXTRACTION_PROMPT_PATH, build_extraction_stream_system)
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


def _sum_ms(vals):
    """None 混じりの ms 値を合計する。1つも数値がなければ None。

    ゼロ二重確認で2回 claude を回したとき、timing を「合計の実測」にするために使う。
    片方が欠測(CLI が duration_api_ms を返さなかった等)でも、取れた分は捨てない。
    """
    nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return round(sum(nums)) if nums else None


def call_claude(endpoint, system_prompt, user_prompt, model):
    """claude 実行 + セッションログ追記。(rec, timing) を返す。

    kind はエンドポイントから決める。/api/render だけレンダ副上限の対象にして、
    爆散(取り直しを含む)とコンパイル用の実行枠を必ず空けておく。
    """
    kind = "render" if endpoint == "/api/render" else "other"
    rec = STATE.runner.run(system_prompt, user_prompt, model, kind=kind)
    timing = {"wall_ms": rec["wall_ms"], "api_ms": rec["api_ms"]}
    return rec, timing


def handle_explode(body):
    """一括抽出。分岐0件のときだけ「ゼロ二重確認」で1回だけ引き直す。

    ゼロ二重確認(2026-07-30 追加):
      本番で ec-product(明らかに曖昧な依頼文)に対し 0 件が誤発動した。
      0 件はサンプリング揺らぎで起こりうる偽陰性であり、かつ 0 件のときだけは
      「ユーザーに何も返さない」という最悪の結果になる。そこで branches が 0 件だった
      場合に限り、同一プロンプトで自動的にもう1回だけ再サンプリングする。
      2回目が非0ならそれを採用し、両方0なら zero_confirmed:true を付けて 0 を返す。
      対照ブリーフ(完全指定)の 0 件は、この二重確認を通っても 0 のままである
      = 「聞くことがないブリーフには聞かない」という誠実性は落とさない。
      追加コストは 0 件のときだけの +1 回。
    """
    brief = body.get("brief")
    if not _nonempty_str(brief):
        return err("brief が空である", "ブリーフ本文を1文以上入力する。"), None, STATE.model
    system_prompt = STATE.prompts.get("explode")
    if system_prompt is None:
        return err(STATE.prompt_errors.get("explode", "抽出プロンプトが読めない"),
                   "prompts/extraction_product_v1.txt を確認してサーバを再起動する。"), None, STATE.model

    model = STATE.model

    def accept(o):
        return all(k in o for k in EXTRACTION_REQUIRED_TOP)

    def one_attempt():
        """1回分。(payload|None, err_out|None, rec, timing) を返す。"""
        rec, timing = call_claude("/api/explode", system_prompt, brief, model)
        if not rec["ok"]:
            out = err(rec["error"], rec["hint"] or "")
            out["timing"] = timing
            return None, out, rec, timing
        ex, why = extract_json_object(rec["result_text"], accept)
        if ex is None:
            out = err("抽出結果のJSONを読み取れなかった(%s)" % why,
                      "同じブリーフでもう一度送信する。繰り返す場合は --model を確認する。")
            out["timing"] = timing
            return None, out, rec, timing
        payload, why = validate_extraction(brief, ex)
        if payload is None:
            out = err("抽出結果の検証に失敗した(%s)" % why, "同じブリーフでもう一度送信する。")
            out["timing"] = timing
            return None, out, rec, timing
        return payload, None, rec, timing

    payload, out_err, rec, timing = one_attempt()
    if payload is None:
        return out_err, rec, model

    attempts = [{"branches": len(payload["branches"]),
                 "branches_returned_by_model": payload["branches_returned_by_model"],
                 "rejected": len(payload["rejected_branches"]),
                 "wall_ms": timing["wall_ms"], "api_ms": timing["api_ms"]}]
    zero_confirmed = False

    if not payload["branches"]:
        payload2, _out_err2, rec2, timing2 = one_attempt()
        # 2回目が失敗(CLIエラー/JSON不成立)なら1回目の0件をそのまま返す。
        # 「1回目は成立していた」という事実を、2回目の事故で潰さない。
        if payload2 is not None:
            attempts.append({"branches": len(payload2["branches"]),
                             "branches_returned_by_model": payload2["branches_returned_by_model"],
                             "rejected": len(payload2["rejected_branches"]),
                             "wall_ms": timing2["wall_ms"], "api_ms": timing2["api_ms"]})
            if payload2["branches"]:
                payload, rec = payload2, rec2          # 2回目を採用(偽陰性を救った)
            else:
                zero_confirmed = True                  # 2回とも0 = 本当に0件
        else:
            attempts.append({"branches": None, "error": True,
                             "wall_ms": timing2["wall_ms"], "api_ms": timing2["api_ms"]})
        timing = {"wall_ms": _sum_ms(a.get("wall_ms") for a in attempts),
                  "api_ms": _sum_ms(a.get("api_ms") for a in attempts)}

    if not payload["branches"]:
        # 分岐0件は「完全指定に近いブリーフ」では正当な結果。棄却が原因の0件と区別できるよう
        # note を添えて ok:true で返す(クライアントが文言を出し分ける)。
        payload["note"] = ("判断点は抽出されなかった(モデル出力 %d 件 / 検証で棄却 %d 件%s)"
                           % (payload["branches_returned_by_model"], len(payload["rejected_branches"]),
                              " / 二重確認済み" if zero_confirmed else ""))

    out = {"ok": True}
    out.update(payload)
    if len(attempts) > 1:
        out["zero_retry"] = True
        out["attempts"] = attempts
    if zero_confirmed:
        out["zero_confirmed"] = True
    out["timing"] = timing
    return out, rec, model


def handle_explode_stream(body, emit):
    """/api/explode_stream の本体。確定したものから emit(dict) で逐次送り出す。

    emit は1イベント分の dict を受け取り、SSE 1レコードとして書き出して flush する
    (HTTP の詳細はハンドラ側。ここは「何をいつ送るか」だけを決める)。
    emit が False を返したらクライアントが切断したとみなして打ち切る。

    送るイベント:
      {"type":"meta",   residual_ambiguity_assessment, missing_materials, partial, elapsed_ms}
      {"type":"branch", index, branch:{...}, elapsed_ms}   ← 検証を通った分岐のみ
      {"type":"retry",  reason:"branches_zero", attempt:2, elapsed_ms}  ← ゼロ二重確認の再抽出開始
      {"type":"done",   ok:true, branches, residual_ambiguity_assessment, missing_materials,
                        rejected_branches, branches_returned_by_model, note?,
                        zero_retry?, zero_confirmed?, attempts?,
                        timing:{wall_ms, api_ms}, api_ms, first_branch_ms}
      {"type":"error",  error, hint, timing}

    戻り値: (ok, model, wall_ms, api_ms, first_branch_ms, client_gone) — アクセス/セッションログ用。
    first_branch_ms は最初の分岐カードを送り出すまでのサーバ実測ms(1枚も出せなければ None)。
    ok は「done イベントをクライアントへ届け切れた」ことを指す(N3)。
    done を作れても書き出しに失敗した場合は ok=False, client_gone=True になる。
    サーバ側で全分岐を確定できたのに届かなかった、という状態を成功として数えない。

    ゼロ二重確認(2026-07-30 追加)
    ------------------------------------------------------------------
    本番で ec-product(明らかに曖昧な依頼文)に 0 件が誤発動した。0 件は
    サンプリング揺らぎで起こる偽陰性でありうるうえ、0 件のときだけは
    「ユーザーに何も返さない」という最悪の結果になる。そこで1回目のストリームが
    分岐0件で終わったときに限り、同一プロンプトでもう1回だけ引き直す。
      - 2回目が非0 → それを採用する(偽陰性を救う)
      - 両方0     → zero_confirmed:true を付けて0を返す
        (完全指定の対照ブリーフでは0のままであり、「聞くことがないなら聞かない」
         という誠実性は落とさない)
    0件のときは branch イベントを1件も出していないので、2回目の index を 0 から
    振り直しても画面と矛盾しない。追加コストは0件のときだけの +1 回。

    retry は既存クライアントが知らないイベント型である。app/index.html の SSE
    ハンドラは type が meta / branch / done / error のいずれでもないオブジェクトを
    何もせず読み飛ばす実装であることを確認したうえで採用した(app は無改造で動く)。
    再抽出中も run_stream の idle からハートビート(SSEコメント)が出続ける。
    """
    model = STATE.model
    t0 = time.monotonic()
    ms = lambda: round((time.monotonic() - t0) * 1000)
    # 早期 return でもセッションログに欠測として書けるよう、最初に定義しておく。
    first_branch_ms = None

    brief = body.get("brief")
    if not _nonempty_str(brief):
        emit({"type": "error", "error": "brief が空である", "hint": "ブリーフ本文を1文以上入力する。"})
        return False, model, ms(), None, first_branch_ms, False
    system_prompt = STATE.prompts.get("explode_stream")
    if system_prompt is None:
        emit({"type": "error",
              "error": STATE.prompt_errors.get("explode_stream", "抽出プロンプトが読めない"),
              "hint": "prompts/extraction_product_v1.txt を確認してサーバを再起動する。"})
        return False, model, ms(), None, first_branch_ms, False

    def run_attempt():
        """1回分のストリーム抽出。(st, fail) を返す。

        st   … {"accepted","rejected","raw_seen","meta","final_rec"}
        fail … None なら正常終了。失敗時は {"kind": "gone"|"error"|"noresult", "val": ...}。
               error イベントの送出は呼び出し側が決める(2回目が事故ったときに
               1回目の成立していた0件を error で潰さないため)。
        """
        nonlocal first_branch_ms
        parser = StreamingExtractionParser()
        st = {"accepted": [], "rejected": [], "raw_seen": 0, "final_rec": None,
              "meta": {"residual_ambiguity_assessment": "", "missing_materials": []}}

        def push_branch(obj, raw_idx):
            """1分岐を検証し、通ったものだけを送る。戻り値: 送ったら True。"""
            nonlocal first_branch_ms
            br, reasons = validate_branch(brief, obj, raw_idx)
            if br is None:
                qp = obj.get("question_point") if isinstance(obj, dict) else ""
                st["rejected"].append({"index": raw_idx,
                                       "question_point": qp if isinstance(qp, str) else "",
                                       "reasons": reasons})
                return True
            if len(st["accepted"]) >= MAX_BRANCHES:
                st["rejected"].append({"index": raw_idx, "question_point": br["question_point"],
                                       "reasons": ["上限%d件を超過したため切り捨て" % MAX_BRANCHES]})
                return True
            st["accepted"].append(br)
            if first_branch_ms is None:
                first_branch_ms = ms()
            return emit({"type": "branch", "index": len(st["accepted"]) - 1, "branch": br,
                         "elapsed_ms": ms()}) is not False

        alive = True
        # 生成器は必ず close する(finally)。途中で break したときに claude 子プロセスの
        # 後始末(run_stream の finally)が走る時点を参照カウントに委ねない。
        stream = STATE.runner.run_stream(system_prompt, brief, model)
        try:
            for kind, val in stream:
                if kind == "idle":
                    # 生成中であることをコネクション上で示す(SSE コメント行。クライアントは無視する)
                    if emit(None) is False:
                        alive = False
                        break
                    continue
                if kind == "text":
                    for ev_kind, obj, raw_idx in parser.feed(val):
                        if ev_kind == "meta":
                            st["meta"] = {"residual_ambiguity_assessment": obj["residual_ambiguity_assessment"],
                                          "missing_materials": obj["missing_materials"]}
                            if emit({"type": "meta", "partial": obj["partial"],
                                     "residual_ambiguity_assessment": obj["residual_ambiguity_assessment"],
                                     "missing_materials": obj["missing_materials"],
                                     "elapsed_ms": ms()}) is False:
                                alive = False
                                break
                        elif ev_kind == "branch":
                            st["raw_seen"] = max(st["raw_seen"], raw_idx + 1)
                            if not push_branch(obj, raw_idx):
                                alive = False
                                break
                    if not alive:
                        break
                    continue
                if kind == "error":
                    return st, {"kind": "error", "val": val}
                if kind == "result":
                    st["final_rec"] = val
        finally:
            stream.close()

        if not alive:
            # クライアント切断。子プロセスは run_stream の finally で始末済み。
            return st, {"kind": "gone"}

        if st["final_rec"] is None:
            return st, {"kind": "noresult"}

        # 完了時に全文をもう一度厳密に解釈し、これを権威とする。
        # 増分パーサが取りこぼした分岐(まず起きないが)を done の前に追送し、
        # 「画面に出たカード」と「最終JSON」が必ず一致する状態にする。
        payload = None
        if isinstance(st["final_rec"].get("result_text"), str):
            ex, _why = extract_json_object(st["final_rec"]["result_text"],
                                           lambda o: all(k in o for k in EXTRACTION_REQUIRED_TOP))
            if ex is not None:
                payload, _why2 = validate_extraction(brief, ex)

        if payload is not None:
            st["meta"] = {"residual_ambiguity_assessment": payload["residual_ambiguity_assessment"],
                          "missing_materials": payload["missing_materials"]}
            st["raw_seen"] = max(st["raw_seen"], payload["branches_returned_by_model"])
            known = {b["id"] for b in st["accepted"]}
            for br in payload["branches"]:
                if br["id"] in known or len(st["accepted"]) >= MAX_BRANCHES:
                    continue
                st["accepted"].append(br)
                if first_branch_ms is None:
                    first_branch_ms = ms()
                if emit({"type": "branch", "index": len(st["accepted"]) - 1, "branch": br,
                         "elapsed_ms": ms(), "late": True}) is False:
                    return st, {"kind": "gone"}
            # 棄却理由は全文側のほうが完全(増分側は打ち切りで欠けうる)
            if len(payload["rejected_branches"]) >= len(st["rejected"]):
                st["rejected"] = payload["rejected_branches"]
        return st, None

    def emit_fail(st, fail):
        """失敗を error イベントとして送り、handle_explode_stream の戻り値を作る。"""
        if fail["kind"] == "gone":
            return False, model, ms(), (st["final_rec"] or {}).get("api_ms"), first_branch_ms, True
        if fail["kind"] == "error":
            val = fail["val"]
            emit({"type": "error", "error": val["error"], "hint": val["hint"] or "",
                  "timing": {"wall_ms": val["wall_ms"], "api_ms": val["api_ms"]}})
            return False, model, val["wall_ms"] or ms(), val["api_ms"], first_branch_ms, False
        emit({"type": "error", "error": "ストリームが result を返さずに終了した",
              "hint": "同じブリーフでもう一度送信する。"})
        return False, model, ms(), None, first_branch_ms, False

    def stat(st, fail):
        rec = st["final_rec"] or {}
        return {"branches": len(st["accepted"]), "branches_returned_by_model": st["raw_seen"],
                "rejected": len(st["rejected"]), "wall_ms": rec.get("wall_ms"),
                "api_ms": rec.get("api_ms"),
                "failed": (fail["kind"] if fail else None)}

    st, fail = run_attempt()
    if fail is not None:
        return emit_fail(st, fail)

    attempts = [stat(st, None)]
    zero_confirmed = False

    if not st["accepted"]:
        # ---- ゼロ二重確認: 0件のときだけ、もう1回だけ引き直す ----
        if emit({"type": "retry", "reason": "branches_zero", "attempt": 2,
                 "elapsed_ms": ms()}) is False:
            return False, model, (st["final_rec"] or {}).get("wall_ms") or ms(), \
                   (st["final_rec"] or {}).get("api_ms"), first_branch_ms, True
        st2, fail2 = run_attempt()
        attempts.append(stat(st2, fail2))
        if fail2 is None:
            if st2["accepted"]:
                st = st2                     # 2回目が非0 → 偽陰性を救った
            else:
                zero_confirmed = True
                # 残存曖昧性の所見は2回目を優先し、空なら1回目を残す。
                if st2["meta"]["residual_ambiguity_assessment"]:
                    st = st2
                elif st2["rejected"]:
                    st["rejected"] = st2["rejected"]
        elif fail2["kind"] == "gone":
            return emit_fail(st2, fail2)     # 切断は done を送れない
        # 2回目が error / noresult のときは、成立していた1回目の0件をそのまま done にする
        # (「2回目の事故」でユーザーへ出す答えを差し替えない)。

    accepted = st["accepted"]
    rejected = st["rejected"]
    raw_seen = st["raw_seen"]
    meta_sent = st["meta"]

    out = {
        "type": "done",
        "ok": True,
        "branches": accepted,
        "residual_ambiguity_assessment": meta_sent["residual_ambiguity_assessment"],
        "missing_materials": meta_sent["missing_materials"],
        "rejected_branches": rejected,
        "branches_returned_by_model": raw_seen,
        "timing": {"wall_ms": _sum_ms(a.get("wall_ms") for a in attempts),
                   "api_ms": _sum_ms(a.get("api_ms") for a in attempts)},
        "api_ms": _sum_ms(a.get("api_ms") for a in attempts),
        "first_branch_ms": first_branch_ms,
        "elapsed_ms": ms(),
    }
    if len(attempts) > 1:
        out["zero_retry"] = True
        out["attempts"] = attempts
    if zero_confirmed:
        out["zero_confirmed"] = True
    if not accepted:
        out["note"] = ("判断点は抽出されなかった(モデル出力 %d 件 / 検証で棄却 %d 件%s)"
                       % (raw_seen, len(rejected), " / 二重確認済み" if zero_confirmed else ""))
    # done を「送ったつもり」で成功にしない。書き出しに失敗したら ok=False + client_gone(N3)。
    # クライアント側も done 未着を成功にしない(一括で取り直して照合する。M1)ので、
    # ここで嘘の成功を記録すると、ログと画面の食い違いだけが残る。
    delivered = emit(out) is not False
    # wall/api はゼロ二重確認で2回回した場合の合計(1回で終われば従来と同じ値)。
    return (delivered, model, out["timing"]["wall_ms"], out["timing"]["api_ms"],
            first_branch_ms, not delivered)


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

    def _client_gone(self):
        """接続が既に切れているかを、確認できる範囲で確かめる(M2c)。

        ブラウザがタブを閉じる/リロードすると fetch は中断され、TCP は FIN を送る。
        その場合ソケットは「読める」状態になり、覗くと 0 バイト(EOF)が返る。
        レンダのように「開始すると 5〜15 秒サーバの実行枠を占める」処理は、
        始める前にここを見て、誰も読まない応答のために枠を潰さないようにする。
        断定できるのは EOF が見えたときだけである(見えない=生存の保証ではない)。
        """
        try:
            sock = self.connection
            r, _w, _x = select.select([sock], [], [], 0)
            if not r:
                return False
            data = sock.recv(1, socket.MSG_PEEK)
            return not data
        except (OSError, ValueError):
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
                "render_concurrency": STATE.runner.render_cap,
                "timeout_s": STATE.args.timeout,
                "session_log": str(STATE.log.path),
                "prompts_ready": {k: (v is not None) for k, v in STATE.prompts.items()},
                "counters": dict(STATE.counters),
                # ---- 「処理の内訳」パネル(app/index.html)の固定情報 ----
                # 画面に「ローカル実行」「APIキー不使用」「127.0.0.1 のみ」と書くだけなら
                # それは主張であって証拠ではない。実際に効いている設定をそのまま返し、
                # クライアントは受け取った値を表示するだけにする(文言を持たせない)。
                "engine": "claude-code-cli",
                "claude_bin": STATE.args.claude_bin,
                "api_key_stripped": (not STATE.args.allow_api_key),
                "bind_host": STATE.args.host,
                "bind_port": STATE.args.port,
                "prompts_dir": PROMPTS_DIR.name + "/",
            }
            self._send_json(payload)
            self._access("GET", path, 200)
            return
        if path.startswith("/api/"):
            self._send_json(err("GET は未対応のエンドポイントである(%s)" % path,
                                "POST /api/explode | /api/explode_stream | /api/render | /api/compile を使う。"))
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
        if path == "/api/explode_stream":
            if berr:
                self._send_json(err(berr, "Content-Type: application/json でJSONオブジェクトを送る。"))
                STATE.bump("explode_stream", False)
                self._access("POST", path, 200, "bad-request")
                return
            self._serve_explode_stream(path, body)
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

        # レンダは1画面で最大15本飛び、1本あたり数秒〜十数秒サーバの実行枠を占める。
        # 既に切れている接続のために claude を起動しない(M2c)。
        # 送信側は pagehide / beforeunload で AbortController により切る(M2b と対)。
        if name == "render" and self._client_gone():
            self.close_connection = True
            STATE.log.append(path, STATE.render_model, 0, None, False, client_gone=True)
            STATE.bump(name, False)
            self._access("POST", path, 499, "client-gone (render skipped)")
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


    # --- SSE(POST /api/explode_stream) ---
    def _serve_explode_stream(self, path, body):
        """text/event-stream で逐次配信する。

        Content-Length を付けられないので Connection: close で終端を示す
        (BaseHTTPRequestHandler は chunked を自前で組む必要があり、close のほうが簡単で確実)。
        X-Accel-Buffering: no はリバースプロキシ越しでも即時 flush させるための保険。
        """
        t_start = time.monotonic()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True
            self._access("POST", path, 200, "sse client gone")
            return
        self.close_connection = True

        broken = {"v": False}

        def emit(obj):
            """1イベントを書き出して即 flush。obj が None ならハートビート(SSEコメント)。
            クライアント切断時は False を返す(以後の送信は行わない)。"""
            if broken["v"]:
                return False
            if obj is None:
                data = b": keepalive\n\n"
            else:
                data = ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")
            try:
                self.wfile.write(data)
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                broken["v"] = True
                return False

        ok, model, wall_ms, api_ms, first_branch_ms, gone = False, "-", None, None, None, False
        try:
            (ok, model, wall_ms, api_ms,
             first_branch_ms, gone) = handle_explode_stream(body, emit)
        except Exception as e:
            import traceback
            traceback.print_exc()
            emit({"type": "error", "error": "サーバ内部エラー: %s: %s" % (type(e).__name__, e),
                  "hint": "サーバの標準出力を確認する。"})
            wall_ms = round((time.monotonic() - t_start) * 1000)

        if wall_ms is None:
            wall_ms = round((time.monotonic() - t_start) * 1000)
        client_gone = bool(gone or broken["v"])
        STATE.log.append(path, model, wall_ms, api_ms, bool(ok),
                         first_branch_ms=first_branch_ms, client_gone=client_gone)
        STATE.bump("explode_stream", bool(ok))
        self._access("POST", path, 200,
                     "%s wall=%sms api=%sms first_branch=%sms%s" % (
                         "ok" if ok else "NG", wall_ms, api_ms, first_branch_ms,
                         " client-gone" if client_gone else ""))


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
    print("  claude: %s / effort=%s / タイムアウト %d秒 / 同時実行上限 %d(うちレンダは同時 %d まで)"
          % (args.claude_bin, args.effort, args.timeout, args.max_concurrency,
             STATE.runner.render_cap))
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
