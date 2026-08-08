#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2: 全判断点×全選択肢の視覚トークン (見本相当) を事前レンダする。
出力: sessions/<id>/options_render.json = {branch_index: [ {label, tokens}... ]}
選択セッションではこのトークンを提示し、確定時も同じ値を焼き付ける (再レンダしない)。"""

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
IDS = ["m01-lp", "m02-event", "m03-scout", "m04-ec", "m05-portfolio",
       "m06-news", "m07-recruit", "m08-apology", "m09-spec", "m10-invite"]


def main():
    runner = server.ClaudeRunner("claude", 180, 6, allow_api_key=False, effort="low")
    for bid in IDS:
        sdir = SESS / bid
        out = sdir / "options_render.json"
        if out.exists():
            print(f"[{bid}] 済み — スキップ"); continue
        ex = json.loads((sdir / "explode.json").read_text(encoding="utf-8"))
        brief, branches = ex["text"], ex["payload"]["branches"]
        result = {}
        maxopt = max(len(b["options"]) for b in branches)
        # j番目の選択肢を全branchで同時にレンダ (無い branch は 0 に落として後で捨てる)
        acc = {i: {} for i in range(len(branches))}
        for j in range(maxopt):
            picks = [min(j, len(b["options"]) - 1) for b in branches]
            renders = pg.step_render_all(runner, brief, branches, picks, "sonnet")
            for i, r in enumerate(renders):
                jj = picks[i]
                if jj in acc[i]:
                    continue
                if not r.get("ok"):
                    print(f"[{bid}] branch{i} opt{jj} render失敗: {r.get('error')}")
                    continue
                acc[i][jj] = r["tokens"]
        for i, b in enumerate(branches):
            result[str(i)] = [
                {"label": o["label"], "tokens": acc[i].get(j)}
                for j, o in enumerate(b["options"])]
        missing = sum(1 for i in acc for j in range(len(branches[i]["options"])) if j not in acc[i])
        out.write_text(json.dumps({"brief": bid, "rendered_at": pg.now_iso(),
                                   "options": result}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"[{bid}] options_render.json 保存 (欠損 {missing})")


if __name__ == "__main__":
    main()
