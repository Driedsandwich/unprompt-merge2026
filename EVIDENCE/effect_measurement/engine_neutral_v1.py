#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E1: 生成側のエンジン中立性 (PREREGISTRATION.md 追補8)

製品プロンプトとサーバ側検証器は不変更のまま、runner だけを ai& API へ差し替えて
爆散 (step_explode)・render (step_render_all)・根拠文 (step_compile) の通過率を測る。
AiandRunner は server.ClaudeRunner.run() と同一の戻り値契約を持つ。

出力: engine_neutral/e1_results.json (生出力・検証結果) + engine_neutral/costs_e1.jsonl
"""

import json
import subprocess
import sys
import threading
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
import pregen_compare as pg  # noqa: E402
from measure_v4_build import BRIEFS12, IDS  # noqa: E402

OUT = HERE / "engine_neutral"
COSTS = OUT / "costs_e1.jsonl"
API = "https://api.aiand.com/v1/chat/completions"
FLASH = "deepseek-ai/deepseek-v4-flash"
SPOT_MODELS = ["zai-org/glm-5.2", "moonshotai/kimi-k3"]
SPOT_IDS = ["m01-lp", "m07-recruit", "m12-faq"]


class AiandRunner:
    """server.ClaudeRunner.run() と同一契約の ai& 版 (生成用途: reasoning none)。"""

    def __init__(self, timeout=300):
        self.timeout = timeout
        self._lock = threading.Lock()
        self.key = subprocess.run(
            ["security", "find-generic-password", "-s", "aiand-api", "-w"],
            capture_output=True, text=True, check=True).stdout.strip()

    def _log(self, rec):
        with self._lock:
            with COSTS.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def run(self, system_prompt, user_prompt, model, kind="other"):
        rec = {"ok": False, "wall_ms": None, "api_ms": None, "duration_ms": None,
               "model_id": None, "result_text": None, "error": None, "hint": None,
               "exit_code": None}
        body = json.dumps({
            "model": model, "reasoning_effort": "none", "max_tokens": 8000,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(API, data=body, method="POST", headers={
            "Authorization": "Bearer " + self.key,
            "Content-Type": "application/json",
            "X-Aiand-Metrics": "true",
            "User-Agent": "unprompt-engine-neutral/1.0",
        })
        t0 = time.monotonic()
        cost = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "model": model,
                "kind": kind, "sys_head": system_prompt[:40]}
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    heads = {k.lower(): v for k, v in resp.headers.items()}
                ms = int((time.monotonic() - t0) * 1000)
                usage = data.get("usage", {})
                cost.update({"x_cost_jpy": heads.get("x-cost"),
                             "prompt_tokens": usage.get("prompt_tokens"),
                             "completion_tokens": usage.get("completion_tokens"),
                             "finish_reason": data["choices"][0].get("finish_reason"),
                             "wall_ms": ms})
                self._log(cost)
                rec.update({"ok": True, "wall_ms": ms, "api_ms": ms,
                            "model_id": data.get("model"),
                            "result_text": data["choices"][0]["message"].get("content") or ""})
                if data["choices"][0].get("finish_reason") == "length":
                    rec.update({"ok": False, "error": "出力打ち切り (max_tokens)",
                                "hint": "max_tokens を上げて再実行"})
                return rec
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    time.sleep(float(e.headers.get("Retry-After") or (2 ** attempt)))
                    continue
                cost["error"] = f"HTTP {e.code}"
                self._log(cost)
                rec.update({"error": f"HTTP {e.code}: {e.read().decode('utf-8')[:150]}",
                            "hint": "4xxは無課金", "exit_code": e.code})
                return rec
            except Exception as e:
                time.sleep(2 ** attempt)
                last = repr(e)[:150]
        cost["error"] = f"5回失敗: {last}"
        self._log(cost)
        rec.update({"error": cost["error"], "hint": "接続/タイムアウト"})
        return rec


def try_explode(runner, bid, model, results):
    brief = BRIEFS12[bid]
    key = f"{model.split('/')[-1]}:{bid}"
    slot = results["explode"].setdefault(key, {})
    if "final_pass" in slot:
        return slot
    try:
        payload, meta = pg.step_explode(runner, brief, model)
        slot.update({"final_pass": True, "attempts": meta["attempts"],
                     "first_attempt_pass": meta["attempts"] == 1,
                     "branches": len(payload["branches"]),
                     "beyond_text": sum(1 for b in payload["branches"]
                                        if b.get("kind") == "beyond_text"),
                     "rejected_branches": len(payload["rejected_branches"]),
                     "failed_attempts": meta["failed_attempts"],
                     "payload": payload})
    except RuntimeError as e:
        slot.update({"final_pass": False, "first_attempt_pass": False,
                     "attempts": 3, "error": str(e)})
    return slot


def main():
    OUT.mkdir(exist_ok=True)
    rpath = OUT / "e1_results.json"
    results = json.loads(rpath.read_text(encoding="utf-8")) if rpath.exists() else \
        {"explode": {}, "render": {}, "compile": {}}
    runner = AiandRunner()

    # 工程A: flash 全量 + スポット2モデル×3ブリーフ
    for bid in IDS:
        s = try_explode(runner, bid, FLASH, results)
        print(f"[A {bid} flash] pass={s['final_pass']} attempts={s.get('attempts')} "
              f"branches={s.get('branches')} rejected={s.get('rejected_branches')}")
        rpath.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    for model in SPOT_MODELS:
        for bid in SPOT_IDS:
            s = try_explode(runner, bid, model, results)
            print(f"[A {bid} {model.split('/')[-1]}] pass={s['final_pass']} "
                  f"attempts={s.get('attempts')}")
            rpath.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    # 工程B/C: flash の explode 成功分に対して picks=0
    for bid in IDS:
        a = results["explode"].get(f"deepseek-v4-flash:{bid}", {})
        if not a.get("final_pass"):
            continue
        branches = a["payload"]["branches"]
        picks = [0] * len(branches)
        brief = BRIEFS12[bid]
        if bid not in results["render"]:
            renders = pg.step_render_all(runner, brief, branches, picks, FLASH)
            results["render"][bid] = [
                {"ok": r["ok"], "error": r.get("error")} for r in renders]
            ok = sum(1 for r in renders if r["ok"])
            print(f"[B {bid}] render {ok}/{len(renders)}")
            rpath.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        if bid not in results["compile"]:
            obj, rec, err = pg.step_compile(runner, brief, branches, picks, FLASH)
            if err:
                results["compile"][bid] = {"ok": False, "error": err}
            else:
                qps = [b["question_point"] for b in branches]
                rationales, warn = server.validate_rationales(obj, qps)
                results["compile"][bid] = {"ok": rationales is not None,
                                           "warn": warn,
                                           "n_rationales": len(rationales or {})}
            print(f"[C {bid}] compile ok={results['compile'][bid]['ok']}")
            rpath.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    # 集計
    ex = results["explode"]
    for label, keys in (("flash 12本", [k for k in ex if k.startswith("deepseek")]),
                        ("glm spot", [k for k in ex if k.startswith("glm")]),
                        ("kimi spot", [k for k in ex if k.startswith("kimi")])):
        fp = sum(1 for k in keys if ex[k]["final_pass"])
        f1 = sum(1 for k in keys if ex[k].get("first_attempt_pass"))
        print(f"工程A {label}: 最終 {fp}/{len(keys)} 初回 {f1}/{len(keys)}")
    rn = [x for v in results["render"].values() for x in v]
    print(f"工程B render (flash): {sum(1 for x in rn if x['ok'])}/{len(rn)}")
    cp = results["compile"].values()
    print(f"工程C compile (flash): {sum(1 for x in cp if x['ok'])}/{len(list(results['compile']))}")
    cost = sum(float(json.loads(l).get("x_cost_jpy") or 0)
               for l in COSTS.read_text(encoding="utf-8").splitlines())
    print(f"実費 x-cost 合計: ¥{cost:.2f}")


if __name__ == "__main__":
    main()
