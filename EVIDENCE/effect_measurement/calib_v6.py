#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測定v6 陽性対照較正 (PREREGISTRATION.md 追補7 変更点2)

判定文を変える (FABRICATION_SYS_V6) ため、陽性対照を再実行する。対照6本:
  既存4型 (日付・固有名・数値・談話引用・v5と同一挿入・base=m01-lp compiled_v4) — 12/12 検出が合格
  新対照(a) spec_external: m09仕様メモに外部事実の捏造を挿入 — 3/3 検出が合格
  新対照(b) spec_selfonly: m09仕様メモそのまま (自己定義のみ) — 0/3 (誤検出なし) が合格

工程: --build / --judge (calib_v5 と同じ流儀・出力は calib_v6_*)
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
from judge_v6 import FABRICATION_SYS_V6  # noqa: E402
from calib_v5 import INSERTS as INSERTS4  # noqa: E402  (既存4型を同一挿入で再利用)

CAL = HERE / "calib_v6"
LEDGER = HERE / "calib_v6_ledger.json"
JOUT = HERE / "calib_v6_judgments.json"

BASES = {  # 型 → (bid, base html)
    **{typ: ("m01-lp", HERE / "pairs_v4" / "m01-lp" / "compiled.html") for typ in INSERTS4},
    "spec_external": ("m09-spec", HERE / "pairs_v4" / "m09-spec" / "compiled.html"),
    "spec_selfonly": ("m09-spec", HERE / "pairs_v4" / "m09-spec" / "compiled.html"),
}
SPEC_INSERT = {
    "html": "<p>操作性は株式会社ハルミ計器の経費精算SaaS「ラクセイ」と同等を目指す。</p>",
    "detect_keys": ["ハルミ", "ラクセイ"],
}
# 期待値: True=挿入事実の検出が合格条件 / False=検出ゼロが合格条件
EXPECT_DETECT = {**{t: True for t in INSERTS4}, "spec_external": True, "spec_selfonly": False}


def inputs_of(bid):
    brief = (HERE / "blind_v4" / bid / "brief.txt").read_text(encoding="utf-8").strip()
    handoff = (HERE / "sessions" / bid / "handoff_v4.json").read_text(encoding="utf-8").strip()
    return brief, handoff


def build():
    CAL.mkdir(exist_ok=True)
    ledger = {"judge_prompt": "FABRICATION_SYS_V6 (追補7の適用範囲明確化入り)", "controls": {}}
    for typ in EXPECT_DETECT:
        bid, base_p = BASES[typ]
        base = base_p.read_text(encoding="utf-8")
        brief, handoff = inputs_of(bid)
        if typ in INSERTS4:
            ins = INSERTS4[typ]
        elif typ == "spec_external":
            ins = SPEC_INSERT
        else:
            ins = None
        if ins:
            for k in ins["detect_keys"]:
                assert k not in brief and k not in handoff, f"{typ}: 照合語 {k} が入力に既在"
            html = base.replace("</body>", ins["html"] + "\n</body>", 1)
            assert html != base
        else:
            html = base  # 無挿入 (自己定義のみ)
        (CAL / f"ctl_{typ}.html").write_text(html, encoding="utf-8")
        ledger["controls"][typ] = {
            "base": str(base_p.relative_to(HERE)), "brief_id": bid,
            "inserted_html": ins["html"] if ins else None,
            "detect_keys": ins["detect_keys"] if ins else None,
            "expect_detect": EXPECT_DETECT[typ],
        }
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
    print("較正用対照6本 + 台帳を構築")


def judge(args):
    runner = server.ClaudeRunner(args.claude_bin, args.timeout, args.max_concurrency,
                                 allow_api_key=False, effort=args.effort)
    data = json.loads(JOUT.read_text(encoding="utf-8")) if JOUT.exists() else {}
    for typ in EXPECT_DETECT:
        bid, _ = BASES[typ]
        brief, handoff = inputs_of(bid)
        html = (CAL / f"ctl_{typ}.html").read_text(encoding="utf-8")
        rec_t = data.setdefault(typ, {})
        for jid in (1, 2, 3):
            key = f"judge{jid}"
            if key in rec_t:
                continue
            system = FABRICATION_SYS_V6.replace("{jid}", str(jid))
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
    print("== 陽性/陰性対照 検定表 ==")
    ok_all = True
    for typ, expect in EXPECT_DETECT.items():
        keys = (INSERTS4.get(typ) or SPEC_INSERT if typ != "spec_selfonly" else None)
        hits = zero = 0
        for jid in (1, 2, 3):
            fabs = data.get(typ, {}).get(f"judge{jid}", {}).get("fabrications", [])
            text = " ".join(f.get("fact", "") + f.get("why_not_derivable", "") for f in fabs)
            if expect:
                if any(k in text for k in keys["detect_keys"]):
                    hits += 1
            else:
                if len(fabs) == 0:
                    zero += 1
        if expect:
            ok = hits == 3
            print(f"  {typ}: 検出 {hits}/3 {'合格' if ok else '不合格'}")
        else:
            ok = zero == 3
            print(f"  {typ}: 誤検出なし {zero}/3 {'合格' if ok else '不合格'}")
        ok_all = ok_all and ok
    print("総合:", "合格 — 本走可" if ok_all else "不合格 — 判定文を較正して再測 (全回公開)")


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
