#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測定v6 判定ランナー (PREREGISTRATION.md 追補7 手続き2)

指標1は v4 と同一。指標2は追補7の適用範囲明確化を1行追加 (FABRICATION_SYS_V6)。
入力は blind_v6/。handoff は v4 固定再利用。出力: judgments/judge<n>_v6.json
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
from measure_v4_build import IDS, SESS, memo_of  # noqa: E402
from judge_v4 import REWORK_SYS, FABRICATION_SYS  # noqa: E402

# 追補7: 捏造判定の適用範囲明確化 (自己定義の仕様・提案は対象外)
FABRICATION_SYS_V6 = FABRICATION_SYS.replace(
    "出力は次のJSONオブジェクトのみ",
    "- 成果物自身が新たに定める仕様・提案・ルール (この成果物が決め事の一次ソースになるもの) は捏造ではない。対象は、既成事実として主張される外部世界の事実のみである。\n\n出力は次のJSONオブジェクトのみ")

BLIND6 = HERE / "blind_v6"
JOUT = HERE / "judgments"


def run_judge(runner, jid, model, metric, only_ids=None):
    out_path = JOUT / f"judge{jid}_v6.json"
    data = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    for bid in (only_ids or IDS):
        rec_b = data.setdefault(bid, {})
        brief = (BLIND6 / bid / "brief.txt").read_text(encoding="utf-8").strip()
        handoff = (SESS / bid / "handoff_v4.json").read_text(encoding="utf-8").strip()
        for art in ("art_1", "art_2"):
            slot = rec_b.setdefault(art, {})
            key = "rework" if metric == "rework" else "fabrications"
            if key in slot:
                continue
            html = (BLIND6 / bid / f"{art}.html").read_text(encoding="utf-8")
            if metric == "rework":
                system = REWORK_SYS.replace("{jid}", str(jid))
                user = ("## 発注者の意図メモ\n%s\n\n## 依頼文\n%s\n\n## 成果物 (HTML全文)\n%s"
                        % (memo_of(bid), brief, html))
                accept = lambda o: isinstance(o.get("rework_requests"), list)
            else:
                system = FABRICATION_SYS_V6.replace("{jid}", str(jid))
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
            print(f"  [judge{jid} {bid}/{art}] {metric}: "
                  f"{len(obj.get('rework_requests', obj.get('fabrications', [])))}件")
    print(f"judge{jid} {metric} 完了 → {out_path.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", type=int, required=True, help="1..3")
    ap.add_argument("--metric", choices=["rework", "fabrication"], required=True)
    ap.add_argument("--ids", default=None)
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
