#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測定v4 判定ランナー (PREREGISTRATION.md 追補4 工程6)

指標1 (やり直し回数・メモあり): 判定者が発注者メモを根拠に、成果物単品への
  「差し戻したい点」を列挙する (0件可・対象箇所と理由必須)。
指標2 (捏造・メモなし): 「ブリーフからも手渡しJSONからも導出できない具体的事実」を列挙。
  導出基準は両条件同一 (brief+handoff の和集合)。プレースホルダ〈〉と一般常識は捏造でない。

判定者は独立エージェント3体 (sonnet)。成果物は blind_v4/ の単品 (条件ラベルなし)。
提示順は id ごとに art_1 → art_2 (割当自体が決定論シャッフル済み)。
出力: judgments/judge<n>_v4.json (rework / fabrications の全文)。
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
from measure_v4_build import IDS, memo_of  # noqa: E402

SESS = HERE / "sessions"
BLIND4 = HERE / "blind_v4"
JOUT = HERE / "judgments"

REWORK_SYS = """あなたは制作物の検収を行う発注者の代理人 (判定者{jid}) である。
発注者の意図メモと依頼文を根拠に、提示された成果物ひとつを検収し、
「発注者として差し戻したい点」を列挙する。

規則:
- 根拠はメモと依頼文のみ。あなた自身の好みを持ち込まない。
- 各項目は「対象箇所 (成果物のどこか)」と「理由 (メモ・依頼文のどの意図に反するか)」を必ず書く。
- 直せば受け入れられる具体的な指摘だけを書く。抽象的な感想 (「全体的に弱い」等) は書かない。
- 問題がなければ空配列でよい。件数を稼ぐことも遠慮することもしない。
- プレースホルダ (〈会社名〉等) は仕組み上の仮置きであり、それ自体は差し戻し対象にしない。

出力は次のJSONオブジェクトのみ (前置き・後書き禁止):
{"rework_requests": [{"target": "対象箇所", "reason": "理由"}]}"""

FABRICATION_SYS = """あなたは事実検証の判定者{jid}である。提示された成果物ひとつについて、
「依頼文からも手渡しJSON (参考資料) からも導出できない具体的事実」を列挙する。

規則:
- 対象は具体的事実のみ: 日付・時刻・期間、固有名 (人名・社名・製品名・地名)、数値 (価格・件数・年数・割合)、実績・受賞、談話やレビューの引用。
- 依頼文または手渡しJSONに書かれている事実、そこから直接導出できる事実は捏造ではない。
- プレースホルダ (〈会社名〉〈開催日〉等の山括弧) は捏造ではない (埋める前提の仮置き)。
- 成果物の種類から当然に決まる一般構造 (見出しがある・ボタンがある等) や一般常識は対象外。
- デザイン上の創作 (配色・レイアウト・架空でない一般的な文言) は対象外。文面上の「事実の主張」だけを見る。
- 該当がなければ空配列。件数を稼がない。

出力は次のJSONオブジェクトのみ (前置き・後書き禁止):
{"fabrications": [{"fact": "成果物中の記述 (短い引用)", "why_not_derivable": "導出できない理由"}]}"""


def run_judge(runner, jid, model, metric, only_ids=None):
    out_path = JOUT / f"judge{jid}_v4.json"
    data = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    for bid in (only_ids or IDS):
        rec_b = data.setdefault(bid, {})
        brief = (BLIND4 / bid / "brief.txt").read_text(encoding="utf-8").strip()
        handoff = (SESS / bid / "handoff_v4.json").read_text(encoding="utf-8").strip()
        for art in ("art_1", "art_2"):
            slot = rec_b.setdefault(art, {})
            key = "rework" if metric == "rework" else "fabrications"
            if key in slot:
                continue
            html = (BLIND4 / bid / f"{art}.html").read_text(encoding="utf-8")
            if metric == "rework":
                system = REWORK_SYS.replace("{jid}", str(jid))
                user = ("## 発注者の意図メモ\n%s\n\n## 依頼文\n%s\n\n## 成果物 (HTML全文)\n%s"
                        % (memo_of(bid), brief, html))
                accept = lambda o: isinstance(o.get("rework_requests"), list)
            else:
                system = FABRICATION_SYS.replace("{jid}", str(jid))
                user = ("## 依頼文\n%s\n\n## 手渡しJSON (参考資料)\n%s\n\n## 成果物 (HTML全文)\n%s"
                        % (brief, handoff, html))
                accept = lambda o: isinstance(o.get("fabrications"), list)
            rec = runner.run(system, user, model)
            if not rec["ok"]:
                print(f"  [{bid}/{art}] {metric} 呼び出し失敗: {rec['error']} — スキップ(再実行可)")
                continue
            obj, why = server.extract_json_object(rec["result_text"], accept)
            if obj is None:
                print(f"  [{bid}/{art}] {metric} JSON不読 ({why}) — スキップ(再実行可)")
                continue
            if metric == "rework":
                slot["rework"] = obj["rework_requests"]
            else:
                slot["fabrications"] = obj["fabrications"]
            slot.setdefault("model_id", rec.get("model_id"))
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            n = len(slot.get("rework", slot.get("fabrications", [])))
            print(f"  [judge{jid} {bid}/{art}] {metric}: "
                  f"{len(obj.get('rework_requests', obj.get('fabrications', [])))}件")
    print(f"judge{jid} {metric} 完了 → {out_path.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", type=int, required=True, help="1..3")
    ap.add_argument("--metric", choices=["rework", "fabrication"], required=True)
    ap.add_argument("--ids", default=None, help="カンマ区切り (省略時は全12本)")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--claude-bin", default="claude")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--max-concurrency", type=int, default=4)
    ap.add_argument("--effort", default="low")
    args = ap.parse_args()
    JOUT.mkdir(exist_ok=True)
    runner = server.ClaudeRunner(args.claude_bin, args.timeout, args.max_concurrency,
                                 allow_api_key=False, effort=args.effort)
    only = args.ids.split(",") if args.ids else None
    run_judge(runner, args.judge, args.model, args.metric, only)


if __name__ == "__main__":
    main()
