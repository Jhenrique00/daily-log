import io
import json
import logging
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts.audit import collect_runs, coverage, get_json, inventory, main


def run(day="2026-10-26T12:00:00Z", result="success", event="schedule", branch="main"):
    return {"created_at": day, "conclusion": result, "event": event,
            "head_branch": branch, "status": "completed"}


class CoverageTests(unittest.TestCase):
    def test_duplicate_runs_count_once_and_missing_days_remain(self):
        result = coverage([run(), run(), run(result="failure")], date(2026, 10, 28), date(2026, 10, 25))
        self.assertEqual(result["successful_days"], 1)
        self.assertEqual(result["coverage_percent"], 33.33)
        self.assertEqual(result["missing_days"], ["2026-10-25", "2026-10-27"])

    def test_today_push_and_other_branches_are_excluded(self):
        runs = [run("2026-10-28T12:00:00Z"), run(event="push"), run(branch="feature"), run(result="failure")]
        self.assertEqual(coverage(runs, date(2026, 10, 28), date(2026, 10, 25))["successful_days"], 0)

    def test_bahia_midnight_boundary(self):
        result = coverage([run("2026-10-27T02:59:59Z")], date(2026, 10, 27), date(2026, 10, 26))
        self.assertEqual(result["coverage_percent"], 100)

    def test_no_history_is_not_claimed_as_success(self):
        result = coverage([], date(2026, 10, 25), date(2026, 10, 25))
        self.assertIsNone(result["coverage_percent"])
        self.assertEqual(result["eligible_days"], 0)

    def test_rolling_window(self):
        result = coverage([run("2026-10-01T12:00:00Z")], date(2026, 10, 28), date(2026, 10, 1), 7)
        self.assertEqual(result["eligible_days"], 7)
        self.assertEqual(result["successful_days"], 0)


class ApiTests(unittest.TestCase):
    def test_pagination(self):
        calls = []
        def getter(url, token):
            calls.append(url)
            return {"total_count": 101, "workflow_runs": [run()] * (100 if len(calls) == 1 else 1)}
        self.assertEqual(len(collect_runs("unused", date(2026, 10, 25), getter)), 101)
        self.assertIn("page=2", calls[1])

    def test_refuses_truncated_results(self):
        with self.assertRaises(ValueError):
            collect_runs("unused", date(2026, 10, 25), lambda *_: {"total_count": 1000})

    def test_retries_transient_network_failure(self):
        calls = []
        def opener(*args, **kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise URLError("temporary")
            return io.StringIO('{"ok": true}')
        self.assertEqual(get_json("https://api.github.com/test", "unused", opener, lambda _: None), {"ok": True})
        self.assertEqual(len(calls), 3)

    def test_auth_errors_fail_without_retry(self):
        def opener(*args, **kwargs):
            raise HTTPError("https://api.github.com/test", 401, "unauthorized", {}, None)
        with self.assertRaises(HTTPError):
            get_json("https://api.github.com/test", "unused", opener, lambda _: self.fail("unexpected retry"))

    def test_retry_exhaustion_fails(self):
        def opener(*args, **kwargs):
            raise URLError("offline")
        with self.assertRaises(URLError):
            get_json("https://api.github.com/test", "unused", opener, lambda _: None)


class RepositoryTests(unittest.TestCase):
    def test_detects_invalid_data_syntax_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.json").write_text("{")
            (root / "bad.py").write_text("if:")
            (root / "README.md").write_text("[missing](missing.md) [web](https://example.com)")
            with patch("scripts.audit.subprocess.check_output", return_value=b"bad.json\0bad.py\0README.md\0"):
                result = inventory(root)
            self.assertEqual(len(result["errors"]), 3)
            self.assertEqual(result["file_count"], 3)
            self.assertEqual(len(result["files"][0]["sha256"]), 64)

    def test_failure_still_writes_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.audit.Path.cwd", return_value=Path(tmp)), patch.dict("os.environ", {"GITHUB_REPOSITORY": "wrong/repo"}):
                self.assertEqual(main([]), 1)
            result = json.loads((Path(tmp) / "reports/metrics.json").read_text())
            self.assertEqual(result["status"], "failure")
            self.assertEqual(result["metrics_status"], "unavailable")
            self.assertTrue((Path(tmp) / "reports/summary.md").exists())
            logging.shutdown()


if __name__ == "__main__":
    unittest.main()
