"""Read-only repository maintenance; standard library only."""
import argparse
import ast
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, unquote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

REPOSITORY = "Jhenrique00/daily-log"
ZONE = ZoneInfo("America/Bahia")


def get_json(url, token, opener=urlopen, sleep=time.sleep):
    request = Request(url, headers={"Authorization": f"Bearer {token}",
                                  "Accept": "application/vnd.github+json"})
    for attempt in range(3):
        try:
            with opener(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        logging.warning("API transient failure; retry %s/2", attempt + 1)
        sleep(2 ** attempt)


def collect_runs(token, start, getter=get_json):
    runs = []
    # The API caps filtered searches at 1,000 results. Refuse partial metrics.
    for page in range(1, 11):
        query = urlencode({"per_page": 100, "page": page,
                           "created": f">={start.isoformat()}T03:00:00Z"})
        data = getter(f"https://api.github.com/repos/{REPOSITORY}/actions/workflows/daily-log.yml/runs?{query}", token)
        if data["total_count"] >= 1000:
            raise ValueError("History exceeds API search cap; metrics unavailable")
        batch = data["workflow_runs"]
        runs.extend(batch)
        if len(batch) < 100:
            return runs
    raise ValueError("Incomplete workflow history")


def coverage(runs, today, started, window=30):
    start = max(started, today - timedelta(days=window))
    days = max(0, (today - start).days)
    successful = set()
    conclusions = {}
    for run in runs:
        day = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).astimezone(ZONE).date()
        if not start <= day < today or run["event"] not in ("schedule", "workflow_dispatch") or run["head_branch"] != "main":
            continue
        result = run.get("conclusion") or run["status"]
        conclusions[result] = conclusions.get(result, 0) + 1
        if result == "success":
            successful.add(day)
    missing = [(start + timedelta(days=n)).isoformat() for n in range(days)
               if start + timedelta(days=n) not in successful]
    return {"window_days": window, "from": start.isoformat(), "through": (today - timedelta(days=1)).isoformat(),
            "eligible_days": days, "successful_days": len(successful),
            "coverage_percent": round(100 * len(successful) / days, 2) if days else None,
            "indicative_target_percent": 85, "missing_days": missing, "run_conclusions": conclusions}


def inventory(root):
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    records, errors = [], []
    for name in filter(None, paths):
        path = root / name
        if path.is_symlink():
            errors.append(f"Unsupported symbolic link: {name}")
            continue
        data = path.read_bytes()
        records.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        try:
            if path.suffix == ".json":
                json.loads(data)
            if path.suffix == ".py":
                ast.parse(data, filename=name)
            if path.suffix == ".md":
                for target in re.findall(r"!?\[[^\]]*\]\(([^\s)]+)\)", data.decode()):
                    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                        continue
                    local = unquote(target.split("#")[0])
                    if not (path.parent / local).exists():
                        errors.append(f"Broken local link in {name}: {target}")
        except (ValueError, SyntaxError, UnicodeError) as exc:
            errors.append(f"Invalid {name}: {exc}")
    return {"files": records, "file_count": len(records),
            "total_bytes": sum(item["bytes"] for item in records), "errors": errors}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="Skip GitHub metrics explicitly")
    args = parser.parse_args(argv)
    root = Path.cwd()
    out = root / "reports"
    out.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(), logging.FileHandler(out / "audit.log", encoding="utf-8")], force=True)
    report = {"automated": True, "human_development": False,
              "observed_at": datetime.now(timezone.utc).isoformat(),
              "commit": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID"),
              "errors": [], "metrics_status": "unavailable"}
    try:
        if os.environ.get("GITHUB_REPOSITORY", REPOSITORY) != REPOSITORY:
            raise ValueError("Repository scope mismatch")
        logging.info("Validating tracked files, JSON, Python syntax and local Markdown links")
        report["inventory"] = inventory(root)
        report["errors"].extend(report["inventory"]["errors"])
        logging.info("Running regression tests")
        tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], capture_output=True, text=True, timeout=120)
        (out / "tests.log").write_text(tests.stdout + tests.stderr, encoding="utf-8")
        report["tests"] = {"exit_code": tests.returncode}
        if tests.returncode:
            report["errors"].append("Regression tests failed; see tests.log")
        if args.offline:
            report["metrics_status"] = "skipped_offline"
        else:
            config = json.loads((root / "automation.json").read_text())
            started = date.fromisoformat(config["monitoring_started_on"])
            today = datetime.now(ZONE).date()
            token = os.environ["GH_TOKEN"]
            runs = collect_runs(token, max(started, today - timedelta(days=30)))
            report["metrics"] = [coverage(runs, today, started, window) for window in (7, 30)]
            report["metrics_status"] = "available"
    except Exception as exc:
        logging.exception("Audit failed")
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    report["status"] = "failure" if report["errors"] else "success"
    (out / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = ["# Automated repository maintenance", "", f"Status: **{report['status']}**",
               "", "Automated checks only; not human development activity.",
               f"Metrics: {report['metrics_status']}. Today is excluded from coverage.", ""]
    for metric in report.get("metrics", []):
        value = metric["coverage_percent"]
        summary.append(f"- {metric['window_days']} days: {value if value is not None else 'N/A'}%; {metric['successful_days']}/{metric['eligible_days']} days. Indicative target: 85%.")
    summary.extend(["", "## Diagnostics", *[f"- {error}" for error in report["errors"]]])
    summary.append("\nSee metrics.json for file hashes, missing dates and workflow conclusions; tests.log and audit.log for diagnostics.\n")
    (out / "summary.md").write_text("\n".join(summary), encoding="utf-8")
    logging.info("Audit completed: %s", report["status"])
    return int(bool(report["errors"]))


if __name__ == "__main__":
    sys.exit(main())
