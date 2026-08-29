import unittest
from datetime import date
from pathlib import Path

from ai_morning_brief.aihot import load_fixture
from ai_morning_brief.script import build_fact_ledger, build_script, validate_script
from ai_morning_brief.selection import select_items


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "aihot_24h.json"


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.response = load_fixture(FIXTURE)
        self.selection = select_items(self.response.items)
        self.script = build_script(self.selection, run_date=date(2026, 8, 28))

    def test_script_is_source_grounded(self):
        items = {item.item_id: item for item in self.response.items}
        self.assertEqual(validate_script(self.script, items), [])
        ledger = build_fact_ledger(self.script, items)
        self.assertEqual(len(ledger["records"]), 8)
        self.assertTrue(all(record["claims"] for record in ledger["records"]))

    def test_intro_and_outro_are_not_news_claims(self):
        kinds = [segment["kind"] for segment in self.script["segments"]]
        self.assertEqual(kinds[0], "intro")
        self.assertEqual(kinds[1], "overview")
        self.assertEqual(kinds[-1], "outro")
        self.assertEqual(kinds.count("news"), 8)
        self.assertEqual(
            self.script["segments"][0]["broadcast_text"],
            "各位观众早上好，今天是8月28日，星期五，欢迎收看今天的AI早报，下面是详细报道",
        )
        self.assertEqual(self.script["segments"][-1]["broadcast_text"], "今天的AI资讯播送完了，我们明天见")
        overview = self.script["segments"][1]
        self.assertEqual(overview["broadcast_text"], "首先来看今日资讯概览，请看屏幕上的主要内容。")
        self.assertEqual(overview["minimum_duration_seconds"], 12.0)
        self.assertEqual(sum(len(group["items"]) for group in overview["screen_groups"]), 8)
        self.assertNotIn("AIHOT", self.script["segments"][0]["broadcast_text"])
        self.assertNotIn("AIHOT", self.script["segments"][-1]["broadcast_text"])

    def test_tampered_fragment_is_rejected(self):
        items = {item.item_id: item for item in self.response.items}
        tampered = {**self.script, "segments": [dict(segment) for segment in self.script["segments"]]}
        tampered["segments"][2]["source_fragments"] = [{"source_field": "summary", "source_text": "这是没有出处的数字 999。"}]
        errors = validate_script(tampered, items)
        self.assertTrue(errors)
