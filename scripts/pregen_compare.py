#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GYAKUMON — 並置証明(SplitCompare)の事前生成パイプライン(python3 標準ライブラリのみ)

目的:
  デモ第二の驚き「元の一文 → 無難な別物」 vs 「コンパイル済みブリーフ → 選択が全て反映された成果物」を
  実生成物で用意する。ここで作る HTML は、デモ当日にその場で生成するのではなく
  事前に生成して app/compare/<brief_id>/ に置く(開示対象 — docs/DISCLOSURE.md #7)。

  ホーム画面の例文チップ5種(data/briefs.json の lp-warm / event-page / scout-mail /
  ec-product / portfolio と同一文)それぞれに1ペアを用意する。app/index.html は
  セッションの依頼文に一致するペアを表示し、一致がなければ lp-warm ペアへ落ちる。

対照条件(拘束・公平性):
  RAW 側と COMPILED 側は、モデル・effort・タイムアウト・制作者 system の骨格を同一にする。
  制作者 system には両側同一のデザイン憲章(prompts/downstream_maker_v1.txt)を含む
  (両側の品位の底上げが目的。左右差を演出するための注入ではない)。
  違うのは「ユーザープロンプトとして何を渡すか」だけ:
    RAW      : ブリーフ一文(そのまま)
    COMPILED : 同じ一文を GYAKUMON に通して得た「コンパイル済みブリーフ MD」
  COMPILED 側の system にだけ 2 項目の追加がある(視覚トークンの厳守 / 選択ラベルの
  コメント埋め込み)。RAW 側には対応する入力が存在しないため付けようがない。
  この非対称は manifest.json の prompts に全文で残す(開示 #8)。

成果物の種類:
  page 系(LP / 告知ページ / ポートフォリオ) … 自己完結 HTML のページそのものが成果物。
  text 系(スカウトメール / 商品説明文)      … 成果物は文面。HTML はそれを読ませる枠。
  枠の骨格(節の並び)は RAW / COMPILED で同一。

選択の組:
  「全部第1候補」は成果物の性格が出にくいので、判断点ごとに対照的な選択を人手で選び、
  BRIEF_SPECS[].picks にインデックスで焼き付ける(併せて expected_labels を持ち、
  爆散をやり直して選択肢の並びが変わった場合は警告を出す)。

工程(1ブリーフあたり):
  1. /api/explode 相当   … ブリーフから判断点(branches)を抽出(結果は explode.json にキャッシュ)
  2. /api/render 相当    … 選んだオプションの視覚トークンを取得(並列)
  3. /api/compile 相当   … 各判断点の「意図」1文を取得
  4. コンパイル済みブリーフ MD を決定論的に組み立て(app/index.html の buildMarkdown と同形)
  5. RAW 側を生成 / COMPILED 側を生成
  6. 選択ラベルが COMPILED 側 HTML のコメントに埋まっているかを機械照合

出力:
  app/compare/<brief_id>/raw.html
  app/compare/<brief_id>/compiled.html
  app/compare/<brief_id>/compiled_brief.md
  app/compare/<brief_id>/explode.json        … 爆散結果のキャッシュ(再現用)
  app/compare/manifest.json                  … 全ペア共通。brief全文・決定一覧・生成時刻・api_ms・
                                               使用プロンプト全文・照合結果

実行:
  python3 scripts/pregen_compare.py --explode-only --all      # 判断点と選択肢だけ先に見る
  python3 scripts/pregen_compare.py --brief-id lp-warm        # 1ペア生成(picks は焼き付け値)
  python3 scripts/pregen_compare.py --brief-id ec-product --picks 1,2,0
  python3 scripts/pregen_compare.py --all                     # 5ペアを順に生成
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

# 下流(成果物)制作者の共通デザイン憲章。RAW / COMPILED の両側に同一の全文を注入する。
# 目的は両側の品位の底上げであって左右差の演出ではない(非対称は従来どおり
# COMPILED_EXTRA_* の2項目のみ)。全文は manifest の prompts に残る。
MAKER_CHARTER_PATH = BASE_DIR / "prompts" / "downstream_maker_v1.txt"

# ---------------------------------------------------------------------------
# 制作者 system の骨格
# ---------------------------------------------------------------------------

# page 系(成果物 = ページそのもの)
PAGE_SYSTEM_TMPL = """あなたは{maker}である。与えられた発注内容だけを根拠に、{deliverable}を1枚作る。

## 出力規則

- 出力は単一の自己完結 HTML ドキュメントのみ。<!DOCTYPE html> で始め </html> で終える。
- CSS はすべて <style> タグ内にインラインで書く。外部CSS・外部フォント・外部画像・外部JSを一切参照しない。
  画像が必要な箇所は CSS のグラデーション・図形・絵文字・インライン SVG で表現する。
- コードフェンス(```)・前置き・後書き・説明文を一切書かない。1文字目が < であること。
- 日本語のページ。{structure}。
- 全体で概ね 160 行以内に収める。冗長な繰り返しを書かない。
- 発注内容に書かれていない事実(社名・実績・数値・日付・固有名)を断定的に作らない。
  必要なら{placeholder}のようなプレースホルダを使う。
"""

# text 系(成果物 = 文面。HTML はそれを読ませる枠)
TEXT_SYSTEM_TMPL = """あなたは{maker}である。与えられた発注内容だけを根拠に、{deliverable}を1本書く。

## 成果物の性質

- 成果物は「読み手に届ける文面」そのものである。HTML はその文面を画面で読ませるための枠にすぎない。
  枠の作り込みではなく、文面の中身(誰に何をどの順で言うか・語彙・文体)で勝負する。
- 本文はそのままコピーして使える日本語の文章にする。タグでしか意味が通じない書き方をしない。

## 出力規則

- 出力は単一の自己完結 HTML ドキュメントのみ。<!DOCTYPE html> で始め </html> で終える。
- CSS はすべて <style> タグ内にインラインで書く。外部CSS・外部フォント・外部画像・外部JSを一切参照しない。
- コードフェンス(```)・前置き・後書き・説明文を一切書かない。1文字目が < であること。
- 枠は横幅 720px 程度・中央寄せ・縦1カラムの文書とし、次の順で構成する: {structure}。
- 文面の分量は{volume}。全体で概ね 140 行以内に収める。
- 発注内容に書かれていない事実(社名・実績・数値・価格・日付・固有名)を断定的に作らない。
  必要なら{placeholder}のようなプレースホルダを使う。
"""

# COMPILED 側だけに足す2項目(開示 #8)
COMPILED_EXTRA_PAGE = """
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

COMPILED_EXTRA_TEXT = """
## コンパイル済みブリーフの扱い(この実行に固有)

- 入力は GYAKUMON が出力した「コンパイル済みブリーフ」である。発注者が確定した判断点が
  明示されている。書かれている決定はすべて文面に反映せよ。解釈で薄めない。
  決定が「誰に向けるか」「何を主張するか」「どの語り口か」を指しているなら、
  それが読んで分かる形で文面の中身を変える。無難な最大公約数の文面にしない。
- 「トーン例」の文体を本文の基調にする(そのまま引き写すのではなく、語彙と距離感を合わせる)。
- 「視覚トークン」のパレット(16進3色)は枠の [地色, 主要色, 強調色] として使い、
  他の色相を勝手に足さない。見出し書体(serif/sans/rounded)・密度(airy/normal/dense)・
  角(sharp/soft)も枠に反映する。密度 airy は行間と余白を大きく、dense は詰める。
- 各決定を反映した箇所の直前に、次の形の HTML コメントを1つ置く(機械照合に使う):
  <!-- GYAKUMON-CHOICE: 判断点 = 選択ラベル -->
  判断点と選択ラベルはブリーフに書かれている文字列をそのまま使う。すべての決定について1回以上置く。
  <style> 内の CSS 規則に印を付ける場合は同じ本文を CSS コメント
  /* GYAKUMON-CHOICE: 判断点 = 選択ラベル */ の形で書く。
"""

# ---------------------------------------------------------------------------
# ブリーフ定義(本文は data/briefs.json / ホームの例文チップと一字一句同一)
#   picks           : 判断点ごとに「決めた」ことにするオプションの位置。
#                     None のときは --picks か --option-index に従う。
#   expected_labels : picks を焼き付けた時点のラベル。爆散をやり直して並びが
#                     変わったら警告を出すためだけに持つ(生成は止めない)。
# ---------------------------------------------------------------------------
BRIEF_SPECS = [
    {
        "id": "lp-warm",
        "text": "モダンだけど温かみのあるLPを作って。うちの会社のやつ。",
        "kind": "page",
        "maker": "LP制作者",
        "deliverable": "企業のランディングページ",
        "structure": "ヒーロー / 価値提案 / 特徴3点 / 会社について / CTA / フッター を含む縦1カラム構成",
        "placeholder": "〈会社名〉",
        # 採用候補者向け × 手書きの温かみ × 大胆グラフィック × 世界観訴求。
        # RAW が落ちがちな「toB・ミニマル・実績訴求の無難な会社LP」から最も遠い組を選ぶ。
        "picks": [2, 1, 1, 1],
        "expected_labels": ["採用候補者", "手書き・柔らかい書体", "大胆グラフィック系", "世界観・共感訴求"],
    },
    {
        "id": "event-page",
        "text": "来月やる交流イベントの告知ページを作ってほしい。若い人にも刺さる感じで、申込みが増えるように。",
        "kind": "page",
        "maker": "イベント告知ページの制作者",
        "deliverable": "交流イベントの告知ページ",
        "structure": "イベント名の見出し / 日時・場所 / どんな会かの説明 / 見どころ3点 / "
                     "参加費と定員 / 申込みCTA / フッター を含む縦1カラム構成",
        "placeholder": "〈イベント名〉〈開催日〉〈会場〉",
        # 学生向け × 楽しさ一点 × 洗練トーン × 限定感 × 多セクション。
        # RAW は「若い人にも刺さる」を字面どおりなぞったカジュアル1枚ものになりやすいので、
        # 洗練と情報量の両方で離す。
        "picks": [0, 2, 1, 0, 1],
        "expected_labels": ["学生・10代20代", "純粋な楽しさ重視", "おしゃれ洗練",
                            "限定感・希少性訴求", "詳細多セクション構成"],
    },
    {
        "id": "portfolio",
        "text": "転職活動用に個人ポートフォリオサイトが欲しい。作品はいくつかあるんだけど、センスよくまとめて。",
        "kind": "page",
        "maker": "個人サイトの制作者",
        "deliverable": "転職活動用の個人ポートフォリオサイト(1ページ)",
        "structure": "名前と肩書きのヒーロー / 自己紹介 / 作品3点(タイトル・役割・一言) / "
                     "できること / 経歴サマリ / 連絡先CTA / フッター を含む縦1カラム構成",
        "placeholder": "〈氏名〉〈作品タイトル〉",
        # 「センスよく」を額面どおり受け取ると RAW はミニマルな作品ギャラリーになる。
        # 経営層向け × 数値実績 × ケーススタディ × 堅実トーン × 総合構成へ振り、
        # 同じ一文から別物が出ることを見せる。
        # 既知の弱点: 「堅実/信頼感」のレンダは暗いネイビー系トークンを返すため、
        # RAW 側も暗い配色に落ちやすい本ブリーフでは地色が接近する(5組中いちばん弱い差)。
        # 1回だけ [1,1,1,1,1](個性的/クリエイティブ)で再生成したが、見出しが Comic Sans に
        # なり判断点ごとのパレットが継ぎ接ぎになったため、こちらを採用のまま残した。
        "picks": [2, 2, 1, 2, 1],
        "expected_labels": ["経営層/クライアント", "実績/成果数値重視", "個別ケーススタディ型",
                            "堅実/信頼感", "経歴・スキルも含む総合構成"],
    },
    {
        "id": "scout-mail",
        "text": "エンジニアに送るスカウトメールの文面をお願い。うちっぽさが伝わって、返信したくなるやつ。",
        "kind": "text",
        "maker": "採用担当のライター",
        "deliverable": "エンジニア宛のスカウトメールの文面",
        "structure": "件名 / 宛名 / 本文(段落を分ける) / 結びと次の一歩 / 署名",
        "volume": "件名1行と本文 400〜600 字程度",
        "placeholder": "〈会社名〉〈候補者名〉〈担当者名〉",
        # 転職潜在層 × 文化・人柄 × カジュアル × プロダクト共感 × 個人経歴言及。
        # RAW は「即戦力へ丁寧語で待遇を並べる汎用テンプレ」に落ちやすいので、
        # 宛先・訴求・距離感の3点すべてで反対側へ振る。
        "picks": [2, 1, 1, 2, 1],
        "expected_labels": ["転職潜在層", "文化・人柄アピール", "カジュアル親近感",
                            "プロダクト共感訴求", "個人経歴言及型"],
    },
    {
        "id": "ec-product",
        "text": "ネットショップに載せるタンブラーの商品説明文を書いて。ちゃんと良さが伝わって、ポチりたくなるように。",
        "kind": "text",
        "maker": "ネットショップのコピーライター",
        "deliverable": "タンブラーの商品説明文",
        "structure": "商品名 / キャッチコピー1行 / 説明本文(段落を分ける) / 仕様の箇条書き / "
                     "購入ボタン(押せない飾り)",
        "volume": "キャッチ1行と本文 350〜550 字程度",
        "placeholder": "〈商品名〉〈容量〉〈価格〉",
        # 若年層・ギフト志向 × デザイン性 × 熱量高いセールス調 × 限定感・お得感。
        # 初回は逆側(高価格帯・上質調)へ振ったが、RAW 側が既に落ち着いた上質の文面を
        # 書いてきたため左右が接近した(地色 #f4f1ec / #f4f1ea)。1回だけ組を変えて再生成し、
        # 熱量側へ振った現在の組を採用した。経緯は PROCESS_LOG に記録。
        "picks": [0, 1, 0, 2],
        "expected_labels": ["若年層・ギフト志向", "デザイン性訴求", "熱量高いセールス調",
                            "限定感・お得感訴求"],
    },
]

SPEC_BY_ID = {s["id"]: s for s in BRIEF_SPECS}

# 爆散が「抽出せず成果物を書いてしまう」既知不具合(PROCESS_LOG / EVIDENCE/brief_as_data.patch)
# への事前生成側だけの回避。素の投入で失敗した回に限り <brief> で包んで再試行する。
# 製品経路(server.py)は未適用のままである。どちらの形で通ったかは manifest に残す。
BRIEF_WRAP_OPEN = "<brief>\n"
BRIEF_WRAP_CLOSE = "\n</brief>"


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


def build_maker_system(spec):
    """成果物の種類に応じた制作者 system(RAW / COMPILED 共通の骨格)。

    デザイン憲章(MAKER_CHARTER_PATH)は両側に同一の全文を足す。左右で違うのは
    従来どおり COMPILED_EXTRA_* の2項目だけであり、公平性の対照条件は変わらない。"""
    charter = MAKER_CHARTER_PATH.read_text(encoding="utf-8").strip() + "\n"
    if spec["kind"] == "page":
        base = PAGE_SYSTEM_TMPL.format(
            maker=spec["maker"], deliverable=spec["deliverable"],
            structure=spec["structure"], placeholder=spec["placeholder"])
        base = base + "\n" + charter
        return base, base + COMPILED_EXTRA_PAGE
    base = TEXT_SYSTEM_TMPL.format(
        maker=spec["maker"], deliverable=spec["deliverable"],
        structure=spec["structure"], volume=spec["volume"],
        placeholder=spec["placeholder"])
    base = base + "\n" + charter
    return base, base + COMPILED_EXTRA_TEXT


# ---------------------------------------------------------------------------
# 各工程
# ---------------------------------------------------------------------------

def step_explode(runner, brief, model, max_attempts=3):
    """爆散。素の投入で失敗した回に限り <brief> で包んで再試行する。

    戻り値: (payload, meta)  meta = {attempts, input_form, api_ms, wall_ms, failed_attempts}
    """
    system_prompt = load_system(server.EXTRACTION_PROMPT_PATH, server.build_extraction_system)
    errors = []
    for attempt in range(1, max_attempts + 1):
        wrapped = attempt > 1
        user_prompt = (BRIEF_WRAP_OPEN + brief + BRIEF_WRAP_CLOSE) if wrapped else brief
        rec = runner.run(system_prompt, user_prompt, model)
        if not rec["ok"]:
            errors.append("attempt%d: 呼び出し失敗 %s / %s" % (attempt, rec["error"], rec["hint"]))
            continue

        def accept(o):
            return all(k in o for k in server.EXTRACTION_REQUIRED_TOP)

        ex, why = server.extract_json_object(rec["result_text"], accept)
        if ex is None:
            errors.append("attempt%d: JSONを読めない(%s)" % (attempt, why))
            continue
        payload, why = server.validate_extraction(brief, ex)
        if payload is None:
            errors.append("attempt%d: 検証に失敗(%s)" % (attempt, why))
            continue
        if not payload["branches"]:
            errors.append("attempt%d: 判断点0件(棄却 %d 件)"
                          % (attempt, len(payload["rejected_branches"])))
            continue
        meta = {
            "attempts": attempt,
            "input_form": "wrapped_in_brief_tag" if wrapped else "raw_brief_text",
            "api_ms": rec["api_ms"], "wall_ms": rec["wall_ms"],
            "failed_attempts": errors,
        }
        return payload, meta
    raise RuntimeError("explode が %d 回とも失敗: %s" % (max_attempts, " / ".join(errors)))


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


def gen_deliverable(runner, system_prompt, user_prompt, model, max_attempts=2):
    """成果物1枚の生成。まれにモデルが HTML ではなく「材料をください」等の
    返信を書くことがある(デザイン憲章導入時の lp-warm RAW 側で実測1回)ため、
    HTML に見えない出力に限り同一プロンプトで最大 max_attempts 回まで引き直す。
    何回目で通ったか・失敗した回の先頭文字列は manifest に残す(隠さない)。"""
    errors = []
    for attempt in range(1, max_attempts + 1):
        rec = runner.run(system_prompt, user_prompt, model)
        if not rec["ok"]:
            errors.append("attempt%d: 呼び出し失敗 %s / %s" % (attempt, rec["error"], rec["hint"]))
            continue
        html = strip_fences(rec["result_text"])
        if "<" not in html:
            errors.append("attempt%d: HTMLに見えない(先頭: %r)" % (attempt, html[:120]))
            continue
        rec["gen_attempts"] = attempt
        rec["gen_failed_attempts"] = errors
        return html, rec
    raise RuntimeError("成果物生成に%d回失敗: %s" % (max_attempts, " / ".join(errors)))


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
    return {"hex_colors_unique": uniq, "hex_colors_count": len(hexes),
            "bytes": len(html.encode("utf-8"))}


def visible_text(html):
    """タグ・style・script を落とした可視テキスト(左右の文面差の簡易指標)。"""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&[a-zA-Z#0-9]+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def text_overlap(a_html, b_html, n=8):
    """可視テキストの n-gram 重なり(Jaccard)。1.0 に近いほど「同じ文章」。"""
    a, b = visible_text(a_html), visible_text(b_html)
    ga = {a[i:i + n] for i in range(max(0, len(a) - n + 1))}
    gb = {b[i:i + n] for i in range(max(0, len(b) - n + 1))}
    if not ga or not gb:
        return None
    inter = len(ga & gb)
    union = len(ga | gb)
    return {"ngram": n, "jaccard": round(inter / union, 4),
            "raw_chars": len(a), "compiled_chars": len(b)}


# ---------------------------------------------------------------------------
# manifest(全ペア共通・追記マージ)
# ---------------------------------------------------------------------------

MANIFEST_DISCLOSURE = (
    "並置比較の各ペア(左右2枚)は事前生成物である。デモ実行時にその場で生成していない。"
    "RAW/COMPILED は同一モデル・同一 effort・同一の制作者 system 骨格で、"
    "違いはユーザープロンプト(一文 vs コンパイル済みブリーフ)のみ。"
    "制作者 system には両側同一のデザイン憲章(prompts/downstream_maker_v1.txt)を含む。"
    "COMPILED 側の system にのみ2項目の追加がある(視覚トークンの厳守 / 選択ラベルのコメント埋め込み)。"
)


def load_manifest(path):
    if not path.exists():
        return None
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return m if isinstance(m, dict) and isinstance(m.get("pairs"), list) else None


def write_manifest(path, engine, pair_entries):
    """pairs を BRIEF_SPECS の順に並べて書き出す。"""
    order = {s["id"]: i for i, s in enumerate(BRIEF_SPECS)}
    pairs = sorted(pair_entries.values(), key=lambda p: order.get(p["brief_id"], 999))
    m = {
        "format": "gyakumon.split_compare.v1",
        "updated_at": now_iso(),
        "pregenerated": True,
        "disclosure": MANIFEST_DISCLOSURE,
        "engine": engine,
        "default_pair": "lp-warm",
        "pair_ids": [p["brief_id"] for p in pairs],
        "pairs": pairs,
    }
    path.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return m


# ---------------------------------------------------------------------------
# 1ブリーフ分の生成
# ---------------------------------------------------------------------------

def resolve_picks(spec, branches, cli_picks, option_index):
    """判断点ごとの選択位置を決める。優先順: --picks > spec['picks'] > --option-index。"""
    n_branches = len(branches)

    def clamp(i, n):
        return max(0, min(n - 1, i if i >= 0 else n + i))

    raw = None
    source = None
    if cli_picks:
        raw, source = cli_picks, "cli_picks"
    elif spec.get("picks"):
        raw, source = spec["picks"], "baked_contrast_picks"
    if raw is not None:
        if len(raw) != n_branches:
            print("      ! 警告: picks の件数 %d が判断点 %d と一致しない。足りない分は %d 番目で埋める。"
                  % (len(raw), n_branches, option_index), flush=True)
        picks = []
        for i, b in enumerate(branches):
            v = raw[i] if i < len(raw) else option_index
            picks.append(clamp(v, len(b["options"])))
        return picks, source
    return ([clamp(option_index, len(b["options"])) for b in branches],
            "option_index_%d" % option_index)


def check_expected_labels(spec, branches, picks):
    exp = spec.get("expected_labels")
    if not exp:
        return None
    got = [branches[i]["options"][picks[i]]["label"] for i in range(len(branches))]
    if got == exp:
        return {"match": True, "expected": exp, "got": got}
    print("      ! 警告: 焼き付けた期待ラベルと不一致。爆散結果が変わった可能性がある。", flush=True)
    print("        expected: %s" % exp, flush=True)
    print("        got     : %s" % got, flush=True)
    return {"match": False, "expected": exp, "got": got}


def run_one(runner, spec, args, out_root):
    brief = spec["text"]
    pair_dir = out_root / spec["id"]
    pair_dir.mkdir(parents=True, exist_ok=True)
    started = now_iso()
    t_all = time.monotonic()
    timings = {}

    cache = pair_dir / "explode.json"
    if cache.exists() and not args.refresh_explode:
        blob = json.loads(cache.read_text(encoding="utf-8"))
        payload, ex_meta = blob["payload"], blob["meta"]
        ex_meta["from_cache"] = True
        print("[1/5] explode … キャッシュ(%s)" % cache.name, flush=True)
    else:
        print("[1/5] explode …", flush=True)
        payload, ex_meta = step_explode(runner, brief, args.model)
        ex_meta["from_cache"] = False
        cache.write_text(json.dumps({"payload": payload, "meta": ex_meta,
                                     "brief": brief, "cached_at": now_iso()},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    branches = payload["branches"]
    timings["explode"] = {"api_ms": ex_meta.get("api_ms"), "wall_ms": ex_meta.get("wall_ms"),
                          "from_cache": ex_meta.get("from_cache")}

    picks, picks_source = resolve_picks(spec, branches, args.picks, args.option_index)
    for i, b in enumerate(branches):
        opts = " | ".join(("[%s]" % o["label"]) if j == picks[i] else o["label"]
                          for j, o in enumerate(b["options"]))
        print("      %d. %s → %s" % (i, b["question_point"], opts), flush=True)
    label_check = check_expected_labels(spec, branches, picks)

    if args.explode_only:
        return None

    print("[2/5] render(%d件・並列) …" % len(branches), flush=True)
    renders = step_render_all(runner, brief, branches, picks, args.model)
    timings["render"] = [{"api_ms": (r or {}).get("api_ms"), "ok": bool((r or {}).get("ok"))}
                         for r in renders]

    print("[3/5] compile(意図) …", flush=True)
    rationales, rec_cp, cp_err = step_compile(runner, brief, branches, picks, args.model)
    timings["compile"] = {"api_ms": rec_cp["api_ms"], "wall_ms": rec_cp["wall_ms"], "error": cp_err}

    compiled_md = build_compiled_brief_md(brief, payload, picks, renders, rationales)
    (pair_dir / "compiled_brief.md").write_text(compiled_md, encoding="utf-8")

    raw_system, compiled_system = build_maker_system(spec)

    print("[4/5] RAW 側生成 …", flush=True)
    raw_html, rec_raw = gen_deliverable(runner, raw_system, brief, args.model)
    timings["raw"] = {"api_ms": rec_raw["api_ms"], "wall_ms": rec_raw["wall_ms"],
                      "attempts": rec_raw.get("gen_attempts"),
                      "failed_attempts": rec_raw.get("gen_failed_attempts")}
    (pair_dir / "raw.html").write_text(raw_html, encoding="utf-8")

    print("[5/5] COMPILED 側生成 …", flush=True)
    compiled_html, rec_cmp = gen_deliverable(runner, compiled_system, compiled_md, args.model)
    timings["compiled"] = {"api_ms": rec_cmp["api_ms"], "wall_ms": rec_cmp["wall_ms"],
                          "attempts": rec_cmp.get("gen_attempts"),
                          "failed_attempts": rec_cmp.get("gen_failed_attempts")}
    (pair_dir / "compiled.html").write_text(compiled_html, encoding="utf-8")

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

    raw_sig = color_signature(raw_html)
    cmp_sig = color_signature(compiled_html)
    shared = sorted(set(raw_sig["hex_colors_unique"]) & set(cmp_sig["hex_colors_unique"]))

    entry = {
        "brief_id": spec["id"],
        "brief": brief,
        "deliverable_kind": spec["kind"],
        "deliverable": spec["deliverable"],
        "generated_at": started,
        "finished_at": now_iso(),
        "total_wall_ms": round((time.monotonic() - t_all) * 1000),
        "outputs": {"raw": "%s/raw.html" % spec["id"],
                    "compiled": "%s/compiled.html" % spec["id"],
                    "compiled_brief": "%s/compiled_brief.md" % spec["id"],
                    "explode_cache": "%s/explode.json" % spec["id"]},
        "picks_source": picks_source,
        "picked_indices": picks,
        "expected_label_check": label_check,
        "explode_meta": ex_meta,
        "decisions": decisions,
        "residual_ambiguity_assessment": payload.get("residual_ambiguity_assessment"),
        "missing_materials": payload.get("missing_materials"),
        "rejected_branches": payload.get("rejected_branches"),
        "compiled_brief_md": compiled_md,
        "timings": timings,
        "verification": {
            "compiled": verify_choice_comments(compiled_html, decisions),
            "raw_signature": raw_sig,
            "compiled_signature": cmp_sig,
            "shared_hex_colors": shared,
            "text_overlap": text_overlap(raw_html, compiled_html),
        },
        "prompts": {
            "maker_system_raw": raw_system,
            "maker_system_compiled": compiled_system,
            "user_raw": brief,
            "user_compiled": compiled_md,
            "maker_charter_file": str(MAKER_CHARTER_PATH.relative_to(BASE_DIR)),
            "extraction_prompt_file": str(server.EXTRACTION_PROMPT_PATH.relative_to(BASE_DIR)),
            "render_prompt_file": str(server.RENDER_PROMPT_PATH.relative_to(BASE_DIR)),
            "compile_prompt_file": str(server.COMPILE_PROMPT_PATH.relative_to(BASE_DIR)),
        },
    }

    v = entry["verification"]["compiled"]
    ov = entry["verification"]["text_overlap"] or {}
    print("      照合 %d/%d(コメント %d 個) / 色 左%d種 右%d種 共通%d種 / 文面重なり %s"
          % (v["traced"], v["of"], v["gyakumon_choice_comments_total"],
             len(raw_sig["hex_colors_unique"]), len(cmp_sig["hex_colors_unique"]),
             len(shared), ov.get("jaccard")), flush=True)
    return entry


def main():
    ap = argparse.ArgumentParser(description="並置証明(SplitCompare)の事前生成(複数ブリーフ)")
    ap.add_argument("--brief-id", action="append", default=None,
                    help="生成するブリーフID(複数指定可)。既定は全件")
    ap.add_argument("--all", action="store_true", help="定義済みの全ブリーフを順に生成")
    ap.add_argument("--model", default="sonnet", help="全工程のモデル(既定: sonnet)")
    ap.add_argument("--effort", default=server.DEFAULT_EFFORT, help="claude --effort(既定: low)")
    ap.add_argument("--timeout", type=int, default=240, help="1本あたりのタイムアウト秒(既定: 240)")
    ap.add_argument("--max-concurrency", type=int, default=6)
    ap.add_argument("--claude-bin", default="claude")
    ap.add_argument("--option-index", type=int, default=0,
                    help="picks 未指定時に使うオプション位置(既定: 0=第1。-1で最終)")
    ap.add_argument("--picks", default=None,
                    help="判断点ごとの選択位置をカンマ区切りで明示(例: 1,2,0)。"
                         "--brief-id 1件のときだけ有効")
    ap.add_argument("--explode-only", action="store_true",
                    help="爆散だけ実行して判断点と選択肢を表示(下流生成をしない)")
    ap.add_argument("--refresh-explode", action="store_true",
                    help="explode.json のキャッシュを無視して爆散をやり直す")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    ids = args.brief_id or [s["id"] for s in BRIEF_SPECS]
    if args.all:
        ids = [s["id"] for s in BRIEF_SPECS]
    unknown = [i for i in ids if i not in SPEC_BY_ID]
    if unknown:
        print("未知のブリーフID: %s(定義済み: %s)" % (unknown, list(SPEC_BY_ID)), file=sys.stderr)
        return 2
    if args.picks:
        if len(ids) != 1:
            print("--picks は --brief-id を1件だけ指定したときに使う", file=sys.stderr)
            return 2
        try:
            args.picks = [int(x) for x in args.picks.split(",") if x.strip() != ""]
        except ValueError:
            print("--picks は整数のカンマ区切り", file=sys.stderr)
            return 2

    out_root = Path(args.out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / "manifest.json"

    engine = {
        "cli": args.claude_bin,
        "model": args.model,
        "effort": args.effort,
        "timeout_s": args.timeout,
        "flags": ["--system-prompt", "--strict-mcp-config", "--setting-sources project",
                  "--effort", "--model", "--output-format json", "-p --"],
        "cwd": "リポジトリ外の一時ディレクトリ(CLAUDE.md 注入遮断)",
        "auth": "Claude Code サブスクリプション(ANTHROPIC_API_KEY は子プロセス env から除去)",
    }

    old = load_manifest(manifest_path)
    entries = {}
    if old:
        for p in old["pairs"]:
            if isinstance(p, dict) and p.get("brief_id"):
                entries[p["brief_id"]] = p

    runner = server.ClaudeRunner(args.claude_bin, args.timeout, args.max_concurrency,
                                 allow_api_key=False, effort=args.effort)
    failures = []
    try:
        for bid in ids:
            spec = SPEC_BY_ID[bid]
            print("\n=== %s ===\n%s" % (bid, spec["text"]), flush=True)
            try:
                entry = run_one(runner, spec, args, out_root)
            except Exception as e:  # 1本落ちても残りを続ける
                print("      ! 失敗: %s" % e, flush=True)
                failures.append((bid, str(e)))
                continue
            if entry is None:
                continue
            entries[bid] = entry
            write_manifest(manifest_path, engine, entries)

        if not args.explode_only:
            m = write_manifest(manifest_path, engine, entries)
            print("\n完了: %s(ペア %d 件)" % (out_root, len(m["pairs"])), flush=True)
            for p in m["pairs"]:
                v = p["verification"]["compiled"]
                print("  - %-12s 照合 %d/%d / 判断点 %d / %s"
                      % (p["brief_id"], v["traced"], v["of"], len(p["decisions"]),
                         p["deliverable_kind"]), flush=True)
        if failures:
            print("\n失敗 %d 件:" % len(failures), flush=True)
            for bid, e in failures:
                print("  - %s: %s" % (bid, e), flush=True)
            return 1
        return 0
    finally:
        runner.cleanup()


if __name__ == "__main__":
    sys.exit(main())
