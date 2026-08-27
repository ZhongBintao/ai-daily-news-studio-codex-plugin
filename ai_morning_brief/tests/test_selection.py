import unittest
from pathlib import Path

from ai_morning_brief.aihot import load_fixture
from ai_morning_brief.selection import select_items


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "aihot_24h.json"


class SelectionTests(unittest.TestCase):
    def test_balances_categories_and_preserves_api_order(self):
        response = load_fixture(FIXTURE)
        result = select_items(response.items)
        self.assertEqual(result.mode, "normal")
        self.assertEqual(len(result.items), 8)
        self.assertEqual(result.items[0].item_id, "fixture-model-01")
        self.assertLessEqual(max(result.category_counts.values()), 2)
        self.assertNotIn("fixture-unselected-01", [item.item_id for item in result.items])

    def test_low_volume_is_short(self):
        response = load_fixture(FIXTURE)
        result = select_items(response.items[:5])
        self.assertEqual(result.mode, "short")
        self.assertEqual(len(result.items), 5)

    def test_under_three_is_failure(self):
        response = load_fixture(FIXTURE)
        result = select_items(response.items[:2])
        self.assertEqual(result.mode, "failure")
        self.assertIn("at least 3", result.reason or "")

