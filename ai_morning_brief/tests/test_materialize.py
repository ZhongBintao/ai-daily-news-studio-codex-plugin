import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ai_morning_brief.aihot import load_fixture
from ai_morning_brief.materialize import materialize
from ai_morning_brief.script import build_script
from ai_morning_brief.selection import select_items


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "aihot_24h.json"


class MaterializeTests(unittest.TestCase):
    def test_writes_authored_hyperframes_workspace(self):
        response = load_fixture(FIXTURE)
        script = build_script(select_items(response.items), run_date=date(2026, 8, 28))
        durations = {segment["id"]: 2.0 for segment in script["segments"]}
        cues = [{"start": 0.0, "end": 1.0, "text": "各位观众早上好"}]
        with tempfile.TemporaryDirectory() as directory:
            result = materialize(Path(directory), script, durations, cues)
            html = (Path(directory) / "hyperframes" / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("__SCENES__", html)
            self.assertIn("AI每日早报", html)
            self.assertIn("AI Daily News", html)
            self.assertIn("OpenAI 发布新一代推理模型", html)
            self.assertNotIn("08:00 / DAILY", html)
            self.assertNotIn("LIVE SIGNAL", html)
            self.assertNotIn("source-pill", html)
            self.assertNotIn("story-index", html)
            self.assertNotIn("class=\"progress\"", html)
            self.assertIn('id="nav-active-ai-models"', html)
            self.assertIn('class="top-nav"', html)
            self.assertIn("资讯概览", html)
            self.assertIn("模型发布", html)
            self.assertIn('class="point-grid count-', html)
            self.assertNotIn("story-lede", html)
            self.assertEqual(result["scene_count"], 11)
            project = json.loads((Path(directory) / "project.json").read_text(encoding="utf-8"))
            self.assertEqual(project["render_runtime"], "hyperframes")
