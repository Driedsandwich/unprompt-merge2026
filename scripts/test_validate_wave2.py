"""Wave 2 検証テスト — 係留検証の退行確認(対照つき)+ 文外判断点の新規則。

対照の作り方: Wave 2 実装前の validate_branch / validate_extraction の実挙動を
scripts/fixture_validate_pre_wave2.json に固定してある(実装前に採取した実測)。
本テストは (A) その挙動が一字も変わっていないこと(新設の kind キー追加のみ許容)、
(B) 文外判断点の新規則が仕様どおり効くこと、の両方を検査する。

実行: python3 scripts/test_validate_wave2.py  (リポジトリ root から)
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server  # noqa: E402

FIXTURE = json.loads((ROOT / "scripts" / "fixture_validate_pre_wave2.json").read_text())
BRIEF = FIXTURE["brief"]


def bt(qp="読み手との距離感", origin="ポートフォリオは読み手が決まらないと文体が決まらない",
       options=None, **over):
    """beyond_text 分岐の素体。"""
    br = {"question_point": qp, "kind": "beyond_text", "anchor_words": [],
          "origin_rationale": origin,
          "options": options or [{"label": "採用担当向け"}, {"label": "同業向け"}],
          "default_if_unresolved": "採用担当向け"}
    br.update(over)
    return br


class TestAnchoredRegression(unittest.TestCase):
    """(A) 対照: 係留検証は Wave 2 前と同一挙動か。"""

    def test_each_case_same_verdict_and_reasons(self):
        for name, case in FIXTURE["cases"].items():
            expected = FIXTURE["expected"][name]
            got, reasons = server.validate_branch(BRIEF, dict(case), 0)
            with self.subTest(case=name):
                if expected["accepted"] is None:
                    self.assertIsNone(got, "以前は棄却だったのに通った")
                    self.assertEqual(reasons, expected["reasons"],
                                     "棄却理由の文言が変わった")
                else:
                    self.assertIsNotNone(got, "以前は合格だったのに棄却された")
                    # 旧フィールドは全て同値。新設は kind のみ許容(既定 anchored)。
                    for k, v in expected["accepted"].items():
                        self.assertEqual(got[k], v, "旧フィールド %s の値が変わった" % k)
                    self.assertEqual(set(got) - set(expected["accepted"]), {"kind"},
                                     "kind 以外のフィールドが増減した")
                    self.assertEqual(got["kind"], "anchored")

    def test_extraction_mixed_same(self):
        exp = FIXTURE["expected"]["extraction_mixed"]["payload"]
        ex = {"residual_ambiguity_assessment": "評価文", "missing_materials": ["ロゴ素材"],
              "branches": [dict(FIXTURE["cases"]["anchored_good"]),
                           dict(FIXTURE["cases"]["anchored_bad_anchor"])]}
        payload, why = server.validate_extraction(BRIEF, ex)
        self.assertIsNone(why)
        self.assertEqual(payload["rejected_branches"], exp["rejected_branches"])
        self.assertEqual(payload["branches_returned_by_model"],
                         exp["branches_returned_by_model"])
        self.assertEqual(len(payload["branches"]), len(exp["branches"]))
        for got, old in zip(payload["branches"], exp["branches"]):
            for k, v in old.items():
                self.assertEqual(got[k], v)
            self.assertEqual(set(got) - set(old), {"kind"})


class TestBeyondText(unittest.TestCase):
    """(B) 文外判断点の新規則。"""

    def test_accept_with_origin(self):
        got, reasons = server.validate_branch(BRIEF, bt(), 0)
        self.assertIsNone(reasons)
        self.assertEqual(got["kind"], "beyond_text")
        self.assertEqual(got["anchor_words"], [])
        self.assertTrue(got["origin_rationale"])

    def test_reject_without_origin(self):
        for missing in ({"origin_rationale": ""}, {"origin_rationale": "   "}):
            br = bt(**missing)
            got, reasons = server.validate_branch(BRIEF, br, 0)
            self.assertIsNone(got)
            self.assertTrue(any("origin_rationale" in r for r in reasons), reasons)
        br = bt()
        del br["origin_rationale"]
        got, reasons = server.validate_branch(BRIEF, br, 0)
        self.assertIsNone(got)

    def test_anchor_words_ignored_for_beyond_text(self):
        # 原文にない語を anchor に入れても beyond_text では棄却理由にならず、捨てられる
        got, reasons = server.validate_branch(BRIEF, bt(anchor_words=["原文にない語"]), 0)
        self.assertIsNone(reasons)
        self.assertEqual(got["anchor_words"], [])

    def test_unknown_kind_falls_back_to_anchored(self):
        br = dict(FIXTURE["cases"]["anchored_good"])
        br["kind"] = "novel_kind"
        got, reasons = server.validate_branch(BRIEF, br, 0)
        self.assertIsNone(reasons)
        self.assertEqual(got["kind"], "anchored")

    def test_cap_two_beyond_text(self):
        ex = {"residual_ambiguity_assessment": "", "missing_materials": [],
              "branches": [dict(FIXTURE["cases"]["anchored_good"]),
                           bt("距離感"), bt("季節感"), bt("場の空気")]}
        payload, why = server.validate_extraction(BRIEF, ex)
        self.assertIsNone(why)
        kinds = [b["kind"] for b in payload["branches"]]
        self.assertEqual(kinds.count("beyond_text"), 2)
        self.assertEqual(len(payload["branches"]), 3)
        self.assertTrue(any("文外判断点の上限2件" in r
                            for rej in payload["rejected_branches"]
                            for r in rej["reasons"]))

    def test_total_cap_five_still_holds(self):
        good = FIXTURE["cases"]["anchored_good"]
        ex = {"residual_ambiguity_assessment": "", "missing_materials": [],
              "branches": [dict(good) for _ in range(5)] + [bt()]}
        payload, why = server.validate_extraction(BRIEF, ex)
        self.assertIsNone(why)
        self.assertEqual(len(payload["branches"]), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
