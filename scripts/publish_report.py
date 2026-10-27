"""Archive a successful current-day audit on seven of every eight days."""
import json
import os
import copy
import secrets
from datetime import date, datetime
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

REPOSITORY = "Jhenrique00/daily-log"
ZONE = ZoneInfo("America/Bahia")


def eligible(today, started):
    offset = (today - started).days
    return offset >= 0 and offset % 8 < 7


def prepare(root, today, expected_sha, run_id):
    config = json.loads((root / "automation.json").read_text(encoding="utf-8"))
    started = date.fromisoformat(config["publication_started_on"])
    if not eligible(today, started):
        return False, "Rest day in the 7-of-8 publication cycle."
    target = root / "data/latest-audit.json"
    if target.exists():
        previous = date.fromisoformat(json.loads(target.read_text(encoding="utf-8"))["publication_date"])
        if previous >= today:
            return False, "Today already has a report, or stored date is later."
    report = json.loads((root / "reports/metrics.json").read_text(encoding="utf-8"))
    observed = datetime.fromisoformat(report["observed_at"])
    if observed.tzinfo is None or observed.astimezone(ZONE).date() != today:
        raise ValueError("Report must belong to the current Bahia calendar day")
    if report["commit"] != expected_sha or str(report["run_id"]) != str(run_id):
        raise ValueError("Report provenance does not match this workflow run")
    if (report["status"] != "success" or report["errors"]
            or report["metrics_status"] != "available"
            or report["tests"]["exit_code"] != 0
            or report["inventory"]["errors"]
            or report["automated"] is not True
            or report["human_development"] is not False):
        raise ValueError("Only successful, explicitly automated online audits can be archived")
    record = {"publication_date": today.isoformat(), "timezone": "America/Bahia",
              "automated": True, "human_development": False,
              "description": "Machine-generated audit telemetry; not manual development.",
              "run_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}",
              "publication_target_percent": 87.5, "audit": report}
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return True, "Current-day verified report prepared."


def commit_batch(root, count=None):
    """Commit one measured report in transparent batches, not separate audits."""
    count = secrets.randbelow(15) + 1 if count is None else count
    if type(count) is not int or not 1 <= count <= 15:
        raise ValueError("Batch size must be between 1 and 15")
    target = root / "data/latest-audit.json"
    record = json.loads(target.read_text(encoding="utf-8"))
    files = record["audit"]["inventory"]["files"]
    fields = [(i, key, value) for i, item in enumerate(files) for key, value in item.items()]
    count = min(count, max(1, len(fields)))
    for part in range(1, count + 1):
        snapshot = copy.deepcopy(record)
        snapshot["publication"] = {"automatic_commits": count, "part": part,
                                   "complete": part == count,
                                   "manual_commits_counted": False,
                                   "strategy": "Random batching of one verified audit, not independent audits"}
        partial = {}
        for index, key, value in fields[:len(fields) * part // count]:
            partial.setdefault(index, {})[key] = value
        visible = list(partial.values())
        snapshot["audit"]["inventory"].update(files=visible, file_count=len(visible),
                                             total_bytes=sum(item.get("bytes", 0) for item in visible))
        target.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", "data/latest-audit.json"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m",
                        f"chore(automation): audit {record['publication_date']} batch {part}/{count}",
                        "-m", "Automatically partitioned telemetry from one audit. Not manual development."],
                       cwd=root, check=True)
    return count


def main():
    if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_EVENT_NAME") not in ("schedule", "workflow_dispatch")):
        raise ValueError("Publication is restricted to scheduled/manual main runs in daily-log")
    sha = os.environ["GITHUB_SHA"]
    if subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() != sha:
        raise ValueError("Checkout differs from the audited commit; retry with a new run")
    changed, message = prepare(Path.cwd(), datetime.now(ZONE).date(), sha, os.environ["GITHUB_RUN_ID"])
    print(message)
    if changed:
        count = commit_batch(Path.cwd())
        print(f"Prepared {count} automatic commits; manual activity is not counted.")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"publish={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()
