#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指標2 (捏造) の新旧規則併記 (PREREGISTRATION.md 追補7 変更点2の開示)

- v5 = 旧判定文で判定済み / v6 = 新判定文 (自己定義仕様の除外) で判定。
- 「旧規則→新規則」の機械近似 = m09-spec の全除外 (v5 の m09 項目が全て自己定義型で
  あることは sonnet 8件で全文確認済み・外部分は近似。追補7に開示)。
- 出力: 各版×判定系×規則ビューの compiled/raw 捏造合計 → tally_fab_rules.json
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sonnet_counts(ver, man):
    tot = {"all": {"compiled": 0, "raw": 0}, "excl_m09": {"compiled": 0, "raw": 0}}
    for j in (1, 2, 3):
        d = json.loads((HERE / "judgments" / f"judge{j}_{ver}.json").read_text(encoding="utf-8"))
        for bid in d:
            bm = man["pairs"][bid]["blind_map"]
            for art, slot in d[bid].items():
                n = len(slot.get("fabrications", []))
                cond = bm[art]
                tot["all"][cond] += n
                if bid != "m09-spec":
                    tot["excl_m09"][cond] += n
    return tot


def ext_counts(ver, man):
    ext = HERE / "judgments" / f"ext_{ver}"
    out = {}
    for f in ext.glob(f"*_fabrication_{ver}.json"):
        model = f.name.split("_judge")[0]
        m = out.setdefault(model, {"all": {"compiled": 0, "raw": 0},
                                   "excl_m09": {"compiled": 0, "raw": 0}})
        d = json.loads(f.read_text(encoding="utf-8"))
        for bid in d:
            bm = man["pairs"][bid]["blind_map"]
            for art, slot in d[bid].items():
                n = len(slot.get("fabrications", []))
                cond = bm[art]
                m["all"][cond] += n
                if bid != "m09-spec":
                    m["excl_m09"][cond] += n
    return out


def main():
    out = {"format": "unprompt.fab_rules_compare.v1", "note": "excl_m09 = 旧→新規則の機械近似 (追補7開示)"}
    for ver, prompt in (("v5", "旧判定文"), ("v6", "新判定文 (自己定義仕様の除外)")):
        man = json.loads((HERE / f"measure_manifest_{ver}.json").read_text(encoding="utf-8"))
        out[ver] = {"judge_prompt": prompt,
                    "sonnet": sonnet_counts(ver, man),
                    "external": ext_counts(ver, man)}
    (HERE / "tally_fab_rules.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
    for ver in ("v5", "v6"):
        v = out[ver]
        print(f"== {ver} ({v['judge_prompt']}) ==")
        s = v["sonnet"]
        print(f"  sonnet: 全体 c{s['all']['compiled']}/r{s['all']['raw']}"
              f" | m09除外 c{s['excl_m09']['compiled']}/r{s['excl_m09']['raw']}")
        for m, t in sorted(v["external"].items()):
            print(f"  {m}: 全体 c{t['all']['compiled']}/r{t['all']['raw']}"
                  f" | m09除外 c{t['excl_m09']['compiled']}/r{t['excl_m09']['raw']}")


if __name__ == "__main__":
    main()
