#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指示書効果測定 — A/B生成ランナー (PREREGISTRATION.md の工程3)

前提:
  - 発注者が実アプリで選択した手渡しJSONが sessions/<id>/handoff.json にある。
  - 一文が sessions/<id>/brief.txt にある。
処理 (1ブリーフ):
  A: user prompt = 一文そのまま           / system = 骨格+憲章 (RAW側)
  B: user prompt = 手渡しJSONそのまま     / system = 骨格+憲章+コンパイル済み2項 (COMPILED側)
  → pairs/<id>/raw.html, compiled.html, manifest 追記。
公平条件は scripts/pregen_compare.py の拘束を import で継承 (再実装しない)。

実行:
  python3 EVIDENCE/effect_measurement/effect_measure.py --id m01-lp
  python3 EVIDENCE/effect_measurement/effect_measure.py --all
"""

import argparse
import hashlib
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
PAIRS = HERE / "pairs"
MANIFEST = HERE / "measure_manifest.json"

# 候補12本のspec (確定10本はPREREGISTRATION.mdに転記して固定)
SPECS = {
    "m01-lp": dict(kind="page", maker="LP制作者", deliverable="サービスのランディングページ",
        structure="ヒーロー / 価値提案 / 特徴3点 / 利用の流れ / CTA / フッター を含む縦1カラム構成",
        placeholder="〈サービス名〉"),
    "m02-event": dict(kind="page", maker="社内イベント告知ページの制作者", deliverable="社内勉強会の告知ページ",
        structure="タイトル / 日時・場所 / 内容の説明 / 見どころ / 参加方法 の縦1カラム構成",
        placeholder="〈開催日〉〈会場〉"),
    "m03-scout": dict(kind="text", maker="採用担当のライター", deliverable="若手エンジニア宛のスカウトメールの文面",
        structure="件名 / 宛名 / 本文(段落を分ける) / 結びと次の一歩 / 署名",
        volume="件名1行と本文 400〜600 字程度", placeholder="〈会社名〉〈候補者名〉"),
    "m04-ec": dict(kind="text", maker="ネットショップのコピーライター", deliverable="新商品の説明文",
        structure="キャッチコピー / リード文 / 特徴の説明 / 仕様・注意 / 締めの一言",
        volume="全体で 300〜500 字程度", placeholder="〈商品名〉"),
    "m05-portfolio": dict(kind="page", maker="個人サイトの制作者", deliverable="転職活動用の個人ポートフォリオサイト(1ページ)",
        structure="名前と肩書きのヒーロー / 自己紹介 / 作品3点 / スキル / 連絡先 の縦1カラム構成",
        placeholder="〈氏名〉〈作品タイトル〉"),
    "m06-news": dict(kind="text", maker="社内報の編集者", deliverable="社内報の巻頭あいさつ文",
        structure="呼びかけ / 近況 / 今月の話題 / 締めの一言",
        volume="全体で 300〜450 字程度", placeholder="〈会社名〉〈執筆者名〉"),
    "m07-recruit": dict(kind="page", maker="採用ページの制作者", deliverable="採用ページの会社紹介セクション",
        structure="見出し / 会社の紹介 / 働く人の声 / 大事にしていること / 応募への導線 の縦1カラム構成",
        placeholder="〈会社名〉"),
    "m08-apology": dict(kind="text", maker="カスタマーサポートのライター", deliverable="発送遅延のお詫びメールの文面",
        structure="件名 / 宛名 / お詫びと状況説明 / 今後の対応 / 結び",
        volume="件名1行と本文 300〜450 字程度", placeholder="〈お客様名〉〈商品名〉〈新しいお届け予定〉"),
    "m09-spec": dict(kind="text", maker="社内ツールの企画担当", deliverable="経費精算を楽にする小さな社内ツールの仕様メモ",
        structure="目的 / 対象ユーザー / 主要機能(箇条書き) / 画面イメージの言葉での説明 / 使わないと決めたもの",
        volume="全体で 400〜600 字程度", placeholder="〈会社名〉"),
    "m10-invite": dict(kind="text", maker="幹事役のライター", deliverable="同窓会の案内文",
        structure="呼びかけ / 開催概要(日時・場所) / どんな会にしたいか / 出欠の連絡方法 / 締め",
        volume="全体で 250〜400 字程度", placeholder="〈開催日〉〈会場〉〈幹事名〉"),
    "m11-brand": dict(kind="page", maker="ブランドサイトの制作者", deliverable="コーヒー豆ブランドの紹介ページ",
        structure="ブランド名のヒーロー / ブランドの物語 / 豆へのこだわり / ラインナップ / 購入導線 の縦1カラム構成",
        placeholder="〈ブランド名〉"),
    "m12-faq": dict(kind="page", maker="サポートサイトの制作者", deliverable="返品まわりのFAQページ",
        structure="見出しと安心の一言 / よくある質問5問(質問と答え) / 解決しないときの連絡導線 の縦1カラム構成",
        placeholder="〈ショップ名〉"),
}


def load_manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"format": "unprompt.effect_measure.v0", "pairs": {}}


def blind_side(brief_id):
    """ブラインド提示の左右割当 (決定論: idのハッシュ偶奇。評価前に人が見ない)。"""
    return "AB" if int(hashlib.sha256(brief_id.encode()).hexdigest(), 16) % 2 == 0 else "BA"


def run_one(runner, bid, model):
    spec = SPECS[bid]
    sdir = SESS / bid
    brief = (sdir / "brief.txt").read_text(encoding="utf-8").strip()
    handoff_raw = (sdir / "handoff.json").read_text(encoding="utf-8").strip()
    handoff = json.loads(handoff_raw)  # 破損検知
    raw_sys, compiled_sys = pg.build_maker_system(spec)

    odir = PAIRS / bid
    odir.mkdir(parents=True, exist_ok=True)
    entry = {"brief_id": bid, "brief": brief, "spec": spec, "generated_at": pg.now_iso(),
             "model": model, "blind_order": blind_side(bid),
             "handoff_format": handoff.get("format"), "gen": {}}

    for side, system_prompt, user_prompt, fname in (
            ("raw", raw_sys, brief, "raw.html"),
            ("compiled", compiled_sys, handoff_raw, "compiled.html")):
        print(f"  [{bid}] {side} 生成中...", flush=True)
        html, rec = pg.gen_deliverable(runner, system_prompt, user_prompt, model)
        (odir / fname).write_text(html, encoding="utf-8")
        entry["gen"][side] = {
            "api_ms": rec.get("duration_api_ms"), "wall_ms": rec.get("wall_ms"),
            "attempts": rec.get("gen_attempts"), "failed_attempts": rec.get("gen_failed_attempts"),
            "model_id_observed": rec.get("model_id"),
        }
    entry["prompts"] = {"raw_system": raw_sys, "compiled_system": compiled_sys,
                        "raw_user": brief, "compiled_user": handoff_raw}
    m = load_manifest()
    m["pairs"][bid] = entry
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  [{bid}] 完了 → {odir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--claude-bin", default="claude")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--max-concurrency", type=int, default=4)
    ap.add_argument("--effort", default="low")
    args = ap.parse_args()

    ids = [args.id] if args.id else None
    if args.all:
        ids = [d.name for d in sorted(SESS.iterdir())
               if d.is_dir() and (d / "handoff.json").exists()]
    if not ids:
        print("使い方: --id m01-lp または --all (sessions/ に brief.txt と handoff.json を置く)")
        sys.exit(1)
    runner = server.ClaudeRunner(args.claude_bin, args.timeout, args.max_concurrency,
                                 allow_api_key=False, effort=args.effort)
    for bid in ids:
        if bid not in SPECS:
            print(f"  [{bid}] SPECS に未定義 — スキップ"); continue
        run_one(runner, bid, args.model)


if __name__ == "__main__":
    main()
