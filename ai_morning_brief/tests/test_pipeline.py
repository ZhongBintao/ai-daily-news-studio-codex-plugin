import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ai_morning_brief.pipeline import run_pipeline


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "aihot_24h.json"


class PipelineTests(unittest.TestCase):
    def test_prepare_only_is_offline_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "outputs"
            first = run_pipeline(run_date=date(2026, 8, 28), output_root=root, fixture=FIXTURE, prepare_only=True)
            self.assertEqual(first["status"], "prepared")
            run_dir = root / "2026-08-28"
            self.assertTrue((run_dir / "artifacts" / "source_snapshot.json").is_file())
            self.assertTrue((run_dir / "artifacts" / "narration_plan.json").is_file())
            second = run_pipeline(run_date=date(2026, 8, 28), output_root=root, fixture=FIXTURE, prepare_only=True)
            self.assertEqual(second["status"], "prepared")
            report = json.loads((run_dir / "run_report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["no_secrets_in_artifacts"])

