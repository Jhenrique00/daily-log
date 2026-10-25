import copy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from scripts.publish_report import eligible, prepare

START = date(2026, 10, 25)


class PublicationTests(unittest.TestCase):
    def test_exact_seven_days_per_eight_day_cycle(self):
        for offset in range(24):
            self.assertEqual(sum(eligible(START + timedelta(days=offset + n), START)
                                 for n in range(8)), 7)
        self.assertFalse(eligible(START - timedelta(days=1), START))

    def test_rolling_thirty_days_between_85_and_90_percent(self):
        for offset in range(8):
            count = sum(eligible(START + timedelta(days=offset + n), START) for n in range(30))
            self.assertGreaterEqual(count / 30, .85)
            self.assertLessEqual(count / 30, .90)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "automation.json").write_text(json.dumps({"publication_started_on": START.isoformat()}))
        (self.root / "reports").mkdir()
        self.report = {"observed_at": "2026-10-25T12:00:00+00:00", "commit": "abc", "run_id": "42",
                       "status": "success", "errors": [], "metrics_status": "available",
                       "tests": {"exit_code": 0}, "inventory": {"errors": []},
                       "automated": True, "human_development": False}

    def save(self, report=None):
        (self.root / "reports/metrics.json").write_text(json.dumps(report or self.report))

    def test_report_is_written_once_and_keeps_evidence(self):
        self.save()
        self.assertTrue(prepare(self.root, START, "abc", "42")[0])
        path = self.root / "data/latest-audit.json"
        original = path.read_bytes()
        self.assertEqual(json.loads(original)["audit"], self.report)
        self.assertFalse(prepare(self.root, START, "abc", "42")[0])
        self.assertEqual(path.read_bytes(), original)

    def test_rest_day_creates_no_file(self):
        self.assertFalse(prepare(self.root, START + timedelta(days=7), "abc", "42")[0])
        self.assertFalse((self.root / "data").exists())

    def test_rejects_failure_offline_foreign_and_stale_evidence(self):
        changes = [({"status": "failure"}), {"errors": ["failure"]},
                   {"metrics_status": "skipped_offline"}, {"tests": {"exit_code": 1}},
                   {"inventory": {"errors": ["broken file"]}}, {"commit": "other"},
                   {"run_id": "other"}, {"observed_at": "2026-10-25T02:59:00+00:00"},
                   {"observed_at": "2026-10-26T12:00:00+00:00"},
                   {"observed_at": "2026-10-25T12:00:00"}, {"human_development": True}]
        for change in changes:
            with self.subTest(change=change):
                candidate = copy.deepcopy(self.report)
                candidate.update(change)
                self.save(candidate)
                with self.assertRaises(ValueError):
                    prepare(self.root, START, "abc", "42")
                self.assertFalse((self.root / "data/latest-audit.json").exists())


if __name__ == "__main__":
    unittest.main()
