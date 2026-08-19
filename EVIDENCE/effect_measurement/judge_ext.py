#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測定v4 追加走: 複数モデル判定ランナー (PREREGISTRATION.md 追補5)

判定文・入力の組み立ては judge_v4.py と同一 (システム文は judge_v4 から import し
単一ソースを保つ)。判定器だけを ai& API (OpenAI互換) の非Claude系モデルへ差し替える。
reasoning_effort は全呼び出し "high" を明示 (モデルごとに既定が異なるため)。

出力:
  judgments/ext/<model短名>_judge<n>_v4.json  — 判定全文 (v4 と同じ入れ子形)
  judgments/ext/costs_v4ext.jsonl             — 全呼び出しの実費記録 (x-cost・トークン内訳)

APIキーは macOS キーチェーン (service=aiand-api) から取得し、値は出力しない。
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import server  # noqa: E402
from measure_v4_build import IDS, memo_of  # noqa: E402
from judge_v4 import REWORK_SYS, FABRICATION_SYS  # noqa: E402

SESS = HERE / "sessions"
API = "https://api.aiand.com/v1/chat/completions"
# --suffix で v4/v5 を切り替える (main で束縛)。handoff は両版とも v4 固定再利用 (追補6)
BLIND = None
EXT = None
COSTS = None


FAB_SYS = FABRICATION_SYS


def bind_paths(suffix):
    global BLIND, EXT, COSTS, FAB_SYS
    BLIND = HERE / f"blind_{suffix}"
    EXT = HERE / "judgments" / ("ext" if suffix == "v4" else f"ext_{suffix}")
    COSTS = EXT / f"costs_{suffix}ext.jsonl"
    if suffix == "v6":  # 追補7: 捏造判定の適用範囲明確化 (単一ソース = judge_v6)
        from judge_v6 import FABRICATION_SYS_V6
        FAB_SYS = FABRICATION_SYS_V6


def api_key():
    return subprocess.run(
        ["security", "find-generic-password", "-s", "aiand-api", "-w"],
        capture_output=True, text=True, check=True).stdout.strip()


def call_api(key, model, system, user, max_tokens, timeout):
    body = json.dumps({
        "model": model,
        "reasoning_effort": "high",
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(API, data=body, method="POST", headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "X-Aiand-Metrics": "true",
        # urllib 既定UA (Python-urllib/3.x) は Cloudflare に 403 (1010) で遮断される実測
        "User-Agent": "unprompt-judge-ext/1.0",
    })
    last_err = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                heads = {k.lower(): v for k, v in resp.headers.items()}
                return data, heads, None
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            # 4xx は課金されない仕様。429/5xx のみ退避して再試行
            if e.code == 429 or e.code >= 500:
                wait = float(e.headers.get("Retry-After") or (2 ** attempt))
                time.sleep(wait)
                continue
            return None, None, f"HTTP {e.code}: {e.read().decode('utf-8')[:200]}"
        except Exception as e:  # タイムアウト・接続断
            last_err = repr(e)[:200]
            time.sleep(2 ** attempt)
    return None, None, f"5回失敗: {last_err}"


def build_messages(metric, jid, bid, art):
    brief = (BLIND / bid / "brief.txt").read_text(encoding="utf-8").strip()
    html = (BLIND / bid / f"{art}.html").read_text(encoding="utf-8")
    if metric == "rework":
        system = REWORK_SYS.replace("{jid}", str(jid))
        user = ("## 発注者の意図メモ\n%s\n\n## 依頼文\n%s\n\n## 成果物 (HTML全文)\n%s"
                % (memo_of(bid), brief, html))
        accept = lambda o: isinstance(o.get("rework_requests"), list)
    else:
        handoff = (SESS / bid / "handoff_v4.json").read_text(encoding="utf-8").strip()
        system = FAB_SYS.replace("{jid}", str(jid))
        user = ("## 依頼文\n%s\n\n## 手渡しJSON (参考資料)\n%s\n\n## 成果物 (HTML全文)\n%s"
                % (brief, handoff, html))
        accept = lambda o: isinstance(o.get("fabrications"), list)
    return system, user, accept


def log_cost(rec):
    with COSTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="ai& の完全モデルID")
    ap.add_argument("--judge", type=int, required=True, help="1..3")
    ap.add_argument("--metric", choices=["rework", "fabrication"], required=True)
    ap.add_argument("--ids", default=None, help="カンマ区切り (省略時は全12本)")
    ap.add_argument("--limit", type=int, default=None, help="新規呼び出し数の上限 (較正走用)")
    ap.add_argument("--max-tokens", type=int, default=6000)
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--suffix", choices=["v4", "v5", "v6"], default="v4", help="blind/出力の版")
    args = ap.parse_args()

    bind_paths(args.suffix)
    EXT.mkdir(parents=True, exist_ok=True)
    short = args.model.split("/")[-1]
    # 指標ごとに別ファイル。rework/fabrication を同一ファイルに並行書き込みすると
    # 後勝ちで片方が消える事故を実際に起こした (2026-08-19・216判定を再実行した)
    out_path = EXT / f"{short}_judge{args.judge}_{args.metric}_{args.suffix}.json"
    data = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    key = api_key()
    done = 0
    for bid in (args.ids.split(",") if args.ids else IDS):
        rec_b = data.setdefault(bid, {})
        for art in ("art_1", "art_2"):
            slot = rec_b.setdefault(art, {})
            store_key = "rework" if args.metric == "rework" else "fabrications"
            if store_key in slot:
                continue
            # limit は成功・失敗を問わず「試行数」で数える (失敗連発時の暴走防止)
            if args.limit is not None and done >= args.limit:
                print(f"limit {args.limit} 到達 — 停止 (再実行で続き)")
                return
            system, user, accept = build_messages(args.metric, args.judge, bid, art)
            t0 = time.time()
            resp, heads, err = call_api(key, args.model, system, user,
                                        args.max_tokens, args.timeout)
            done += 1
            cost_rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "model": args.model, "judge": args.judge,
                        "metric": args.metric, "bid": bid, "art": art,
                        "wall_s": round(time.time() - t0, 1)}
            if err:
                cost_rec["error"] = err
                log_cost(cost_rec)
                print(f"  [{bid}/{art}] 呼び出し失敗: {err} — スキップ(再実行可)")
                continue
            usage = resp.get("usage", {})
            cost_rec.update({
                "x_cost_jpy": heads.get("x-cost"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                "finish_reason": resp["choices"][0].get("finish_reason"),
                "request_id": heads.get("x-request-id"),
            })
            log_cost(cost_rec)
            if resp["choices"][0].get("finish_reason") == "length":
                print(f"  [{bid}/{art}] 出力打ち切り (max_tokens={args.max_tokens}) — スキップ(要再実行)")
                continue
            content = resp["choices"][0]["message"].get("content") or ""
            obj, why = server.extract_json_object(content, accept)
            if obj is None:
                print(f"  [{bid}/{art}] JSON不読 ({why}) — スキップ(再実行可)")
                continue
            slot[store_key] = obj["rework_requests"] if args.metric == "rework" else obj["fabrications"]
            slot.setdefault("model_id", resp.get("model"))
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                encoding="utf-8")
            n = len(slot[store_key])
            print(f"  [{short} j{args.judge} {bid}/{art}] {args.metric}: {n}件 "
                  f"¥{heads.get('x-cost')} ({cost_rec['wall_s']}s)")
    print(f"{short} judge{args.judge} {args.metric} 完了 → {out_path.name}")


if __name__ == "__main__":
    main()
