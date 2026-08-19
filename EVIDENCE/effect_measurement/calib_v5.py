#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測定v5 陽性対照較正 (PREREGISTRATION.md 追補6 変更点2)

既知の捏造4型 (日付・固有名・数値・談話引用) を1件ずつ機械挿入した較正用成果物を作り、
sonnet 判定3体 (judge_v4 と同一の捏造判定システム文) が検出できるかを測る。

工程:
  --build : calib_v5/fab_<type>.html を4本生成 + 較正台帳 calib_v5_ledger.json
  --judge : 4本×判定3体=12判定を実行 → calib_v5_judgments.json + 検出表
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import server  # noqa: E402
from judge_v4 import FABRICATION_SYS  # noqa: E402

BASE_BID = "m01-lp"
BASE_HTML = HERE / "pairs_v4" / BASE_BID / "compiled.html"
CAL = HERE / "calib_v5"
LEDGER = HERE / "calib_v5_ledger.json"
JOUT = HERE / "calib_v5_judgments.json"

# 挿入する既知捏造 (m01-lp のブリーフ・handoff_v4 のどちらからも導出できないことを
# --build 時に機械確認する)。detect_keys は検出判定に使う最小の照合語。
INSERTS = {
    "date": {
        "html": "<p>2019年4月の創業以来、私たちは同じ姿勢で開発を続けています。</p>",
        "detect_keys": ["2019"],
    },
    "proper_noun": {
        "html": "<p>株式会社ミナモ電装をはじめとする製造業のお客様にご利用いただいています。</p>",
        "detect_keys": ["ミナモ電装", "ミナモ"],
    },
    "number": {
        "html": "<p>導入企業は現在1,247社を数えます。</p>",
        "detect_keys": ["1,247", "1247"],
    },
    "quote": {
        "html": "<p>「驚くほど手離れが良かった」— 導入企業のご担当者様</p>",
        "detect_keys": ["手離れ"],
    },
}


def build():
    CAL.mkdir(exist_ok=True)
    base = BASE_HTML.read_text(encoding="utf-8")
    brief = (HERE / "blind_v4" / BASE_BID / "brief.txt").read_text(encoding="utf-8")
    handoff = (HERE / "sessions" / BASE_BID / "handoff_v4.json").read_text(encoding="utf-8")
    ledger = {"base": str(BASE_HTML.relative_to(HERE)), "brief_id": BASE_BID,
              "insert_position": "</body> 直前に1段落", "inserts": {}}
    assert "</body>" in base, "ベースHTMLに </body> が無い"
    for typ, ins in INSERTS.items():
        # 導出不能の機械確認: 照合語が brief にも handoff にも現れない
        for k in ins["detect_keys"]:
            assert k not in brief and k not in handoff, f"{typ}: 照合語 {k} が入力に既在 — 挿入文を替える"
        html = base.replace("</body>", ins["html"] + "\n</body>", 1)
        assert html != base
        (CAL / f"fab_{typ}.html").write_text(html, encoding="utf-8")
        ledger["inserts"][typ] = {"inserted_html": ins["html"],
                                  "detect_keys": ins["detect_keys"],
                                  "not_derivable_checked": True}
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
    print("較正用成果物4本 + 台帳を構築 (base=%s)" % ledger["base"])


def judge(args):
    runner = server.ClaudeRunner(args.claude_bin, args.timeout, args.max_concurrency,
                                 allow_api_key=False, effort=args.effort)
    brief = (HERE / "blind_v4" / BASE_BID / "brief.txt").read_text(encoding="utf-8").strip()
    handoff = (HERE / "sessions" / BASE_BID / "handoff_v4.json").read_text(encoding="utf-8").strip()
    data = json.loads(JOUT.read_text(encoding="utf-8")) if JOUT.exists() else {}
    for typ in INSERTS:
        html = (CAL / f"fab_{typ}.html").read_text(encoding="utf-8")
        rec_t = data.setdefault(typ, {})
        for jid in (1, 2, 3):
            key = f"judge{jid}"
            if key in rec_t:
                continue
            system = FABRICATION_SYS.replace("{jid}", str(jid))
            user = ("## 依頼文\n%s\n\n## 手渡しJSON (参考資料)\n%s\n\n## 成果物 (HTML全文)\n%s"
                    % (brief, handoff, html))
            rec = runner.run(system, user, args.model)
            if not rec["ok"]:
                print(f"  [{typ}/j{jid}] 失敗: {rec['error']} — スキップ(再実行可)")
                continue
            obj, why = server.extract_json_object(
                rec["result_text"], lambda o: isinstance(o.get("fabrications"), list))
            if obj is None:
                print(f"  [{typ}/j{jid}] JSON不読 ({why}) — スキップ(再実行可)")
                continue
            rec_t[key] = {"fabrications": obj["fabrications"], "model_id": rec.get("model_id")}
            JOUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  [{typ}/j{jid}] {len(obj['fabrications'])}件")
    # 検出表
    print("== 陽性対照 検出表 (挿入事実を fabrications が言及したか) ==")
    total = 0
    for typ, ins in INSERTS.items():
        hits = 0
        for jid in (1, 2, 3):
            facts = " ".join(f.get("fact", "") + f.get("why_not_derivable", "")
                             for f in data.get(typ, {}).get(f"judge{jid}", {}).get("fabrications", []))
            if any(k in facts for k in ins["detect_keys"]):
                hits += 1
        total += hits
        print(f"  {typ}: {hits}/3")
    print(f"  合計: {total}/12")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--claude-bin", default="claude")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--max-concurrency", type=int, default=4)
    ap.add_argument("--effort", default="low")
    args = ap.parse_args()
    if args.build:
        build()
    if args.judge:
        judge(args)
    if not (args.build or args.judge):
        raise SystemExit("--build / --judge を指定")


if __name__ == "__main__":
    main()
