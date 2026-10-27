import copy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import patch

from scripts.publish_report import eligible, prepare, commit_batch

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


class BatchTests(unittest.TestCase):
    def test_batches_preserve_report_and_ignore_manual_commits(self):
        for count in (1, 7, 15):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                def git(*args):
                    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
                git("init", "-q")
                git("config", "user.name", "Test")
                git("config", "user.email", "test@example.invalid")
                (root / "manual.txt").write_text("manual work")
                git("add", ".")
                git("commit", "-qm", "manual contribution")
                (root / "data").mkdir()
                files = [{"path": f"file-{n}", "bytes": n, "sha256": str(n)} for n in range(10)]
                report = {"publication_date": "2026-10-27", "automated": True,
                          "human_development": False, "audit": {
                              "inventory": {"files": files, "file_count": 10,
                                            "total_bytes": sum(range(10)), "errors": []}}}
                target = root / "data/latest-audit.json"
                target.write_text(json.dumps(report))
                with patch("scripts.publish_report.secrets.randbelow", return_value=count - 1):
                    self.assertEqual(commit_batch(root), count)
                self.assertEqual(int(git("rev-list", "--count", "HEAD")), count + 1)
                final = json.loads(target.read_text())
                self.assertEqual(final["audit"], report["audit"])
                self.assertTrue(final["publication"]["complete"])
                self.assertFalse(final["publication"]["manual_commits_counted"])
                self.assertEqual(git("status", "--porcelain"), "")
                commits = git("rev-list", "--reverse", f"HEAD~{count}..HEAD").splitlines()
                previous_files = 0
                for part, sha in enumerate(commits, 1):
                    snapshot = json.loads(git("show", f"{sha}:data/latest-audit.json"))
                    self.assertEqual(snapshot["publication"]["complete"], part == count)
                    measured_fields = sum(len(item) for item in snapshot["audit"]["inventory"]["files"])
                    self.assertGreater(measured_fields, previous_files)
                    previous_files = measured_fields

    def test_invalid_counts_rejected_before_writing(self):
        for count in (0, 16, -1, True, 1.5):
            with self.assertRaises(ValueError):
                commit_batch(Path("does-not-exist"), count)


if __name__ == "__main__":
    unittest.main()
