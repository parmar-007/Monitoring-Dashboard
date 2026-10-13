"""
Reads job status files from the PVC and works out each job's status per day.

A job's status for a day comes from its latest run that day. With no run on
file, the registry (jobs.yaml) decides whether that is expected (NO_RUN),
not yet due (PENDING) or a problem (MISSING).
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

SUCCESS = "SUCCESS"
FAILED = "FAILED"
RUNNING = "RUNNING"
STUCK = "STUCK"  # RUNNING for longer than max_runtime - pod likely killed
MISSING = "MISSING"  # scheduled, past its deadline, no run on file
PENDING = "PENDING"  # scheduled, deadline not reached yet
NO_RUN = "NO_RUN"  # not scheduled that day
UNKNOWN = "UNKNOWN"  # status file with a status we don't recognise

PROBLEMS = {FAILED, STUCK, MISSING, UNKNOWN}

_STATUS_ALIASES = {
    "SUCCESS": SUCCESS,
    "SUCCEEDED": SUCCESS,
    "COMPLETED": SUCCESS,
    "OK": SUCCESS,
    "FAILED": FAILED,
    "FAILURE": FAILED,
    "ERROR": FAILED,
    "RUNNING": RUNNING,
    "STARTED": RUNNING,
    "IN_PROGRESS": RUNNING,
}

JOB_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class JobDef:
    name: str
    description: str = ""
    schedule: str = "daily"  # daily | weekdays | "mon,wed,fri" | none
    expected_by: time | None = None  # when the run should have finished; None = end of day
    max_runtime: timedelta = timedelta(hours=1)
    registered: bool = True

    def runs_on(self, d):
        s = self.schedule.strip().lower()
        if s == "daily":
            return True
        if s == "weekdays":
            return d.weekday() < 5
        if s in ("", "none"):
            return False
        return WEEKDAYS[d.weekday()] in {part.strip()[:3] for part in s.split(",")}


def _validate_schedule(name, schedule):
    s = schedule.strip().lower()
    if s in ("daily", "weekdays", "", "none"):
        return
    bad = [p for p in s.split(",") if p.strip()[:3] not in WEEKDAYS]
    if bad:
        raise ValueError(
            f"jobs.yaml: job {name!r} has schedule {schedule!r}; "
            "use daily, weekdays, none, or a list like 'mon,wed,fri'"
        )


def load_registry(path):
    path = Path(path)
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text()) or {}
    defaults = doc.get("defaults") or {}
    jobs = []
    for entry in doc.get("jobs") or []:
        merged = {**defaults, **entry}
        name = str(merged["name"])
        if not JOB_NAME_RE.match(name):
            raise ValueError(f"jobs.yaml: invalid job name {name!r}")
        schedule = str(merged.get("schedule", "daily"))
        _validate_schedule(name, schedule)
        expected_by = merged.get("expected_by")
        jobs.append(
            JobDef(
                name=name,
                description=str(merged.get("description", "")),
                schedule=schedule,
                expected_by=time.fromisoformat(str(expected_by)) if expected_by else None,
                max_runtime=timedelta(minutes=int(merged.get("max_runtime_minutes", 60))),
            )
        )
    return jobs


def discover_jobs(settings):
    """Registered jobs plus any job folder on the PVC that isn't registered yet."""
    jobs = load_registry(settings.jobs_file)
    known = {j.name for j in jobs}
    if settings.status_dir.is_dir():
        for folder in sorted(settings.status_dir.iterdir()):
            if folder.is_dir() and folder.name not in known and JOB_NAME_RE.match(folder.name):
                jobs.append(JobDef(name=folder.name, schedule="none", registered=False))
    return jobs


def _parse_ts(value, run_date, tz):
    if not value:
        return None
    try:
        value = str(value)
        if len(value) <= 8:  # legacy "09:00:00"
            ts = datetime.combine(run_date, time.fromisoformat(value))
        else:
            ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=tz)


def normalize_run(raw, run_date, tz, source):
    """Map both the new (job_status.py) and the original JSON layout onto one shape."""
    error = raw.get("error")
    if not error and (raw.get("error_code") or raw.get("error_message")):
        error = {"type": raw.get("error_code") or None, "message": raw.get("error_message") or ""}

    raw_status = str(raw.get("status", "")).strip().upper()
    status = _STATUS_ALIASES.get(raw_status, UNKNOWN)
    if status == UNKNOWN and not error:
        error = {"type": "UnknownStatus", "message": f"Unrecognised status {raw_status or '(empty)'!r}"}

    known = {
        "schema_version", "job", "application", "execution_id", "run_date", "execution_date",
        "status", "started_at", "start_time", "finished_at", "end_time", "duration_seconds",
        "host", "records", "total_records", "output_files", "metrics", "error", "error_code",
        "error_message", "log_tail",
    }
    # Unknown top-level keys from older writers are shown as metrics rather than dropped.
    metrics = {**{k: v for k, v in raw.items() if k not in known}, **(raw.get("metrics") or {})}

    return {
        "execution_id": raw.get("execution_id"),
        "status": status,
        "started_at": _parse_ts(raw.get("started_at") or raw.get("start_time"), run_date, tz),
        "finished_at": _parse_ts(raw.get("finished_at") or raw.get("end_time"), run_date, tz),
        "duration_seconds": raw.get("duration_seconds"),
        "host": raw.get("host"),
        "records": raw.get("records", raw.get("total_records")),
        "output_files": raw.get("output_files") or [],
        "metrics": metrics,
        "error": error,
        "log_tail": raw.get("log_tail") or [],
        "source_file": source,
    }


def read_runs(job_dir, run_date, tz, files=None):
    """All runs of one job on one day, oldest first."""
    if files is None:
        files = sorted(Path(job_dir).glob(f"{run_date.isoformat()}*.json"))
    runs = []
    for path in files:
        try:
            raw = json.loads(path.read_text())
            if not isinstance(raw, dict):
                raise ValueError("top-level JSON is not an object")
        except (OSError, ValueError) as exc:
            log.warning("Unreadable status file %s: %s", path, exc)
            raw = {"status": "FAILED", "error": {"type": "UnreadableStatusFile", "message": str(exc)}}
        runs.append(normalize_run(raw, run_date, tz, path.name))
    floor = datetime.min.replace(tzinfo=tz)
    runs.sort(key=lambda r: (r["started_at"] or floor, r["source_file"]))
    return runs


def day_status(job, runs, run_date, now):
    """Collapse a day's runs (possibly none) into one status for the dashboard."""
    cell = {
        "status": None,
        "attempts": len(runs),
        "expected_by": job.expected_by.isoformat("minutes") if job.expected_by else None,
        "note": None,
    }
    if runs:
        latest = runs[-1]
        status = latest["status"]
        if status == RUNNING and latest["started_at"] and now - latest["started_at"] > job.max_runtime:
            status = STUCK
            minutes = int(job.max_runtime.total_seconds() // 60)
            cell["note"] = f"Still RUNNING after the {minutes} min limit - pod may have been killed"
        elif len(runs) > 1 and status == SUCCESS:
            cell["note"] = f"Succeeded on attempt {len(runs)}"
        error = latest["error"] or {}
        cell.update(
            status=status,
            execution_id=latest["execution_id"],
            started_at=latest["started_at"],
            finished_at=latest["finished_at"],
            duration_seconds=latest["duration_seconds"],
            records=latest["records"],
            output_files=[f.get("name") for f in latest["output_files"]],
            error_message=(error.get("message") or "")[:300] or None,
        )
        return cell

    if not job.runs_on(run_date):
        cell["status"] = NO_RUN
        return cell
    deadline = datetime.combine(run_date, job.expected_by or time.max, tzinfo=now.tzinfo)
    if now >= deadline:
        cell["status"] = MISSING
        cell["note"] = "No run was recorded for this day"
    else:
        cell["status"] = PENDING
        cell["note"] = f"Due by {cell['expected_by']}" if job.expected_by else "Due later today"
    return cell


def overview(settings, now):
    """Status grid: every job x the last `settings.days` days, plus per-day counts."""
    today = now.date()
    dates = [today - timedelta(days=i) for i in range(settings.days)]
    date_keys = {d.isoformat() for d in dates}

    rows = []
    for job in discover_jobs(settings):
        job_dir = settings.status_dir / job.name
        by_date = {}
        if job_dir.is_dir():
            for path in sorted(job_dir.glob("*.json")):
                if path.name[:10] in date_keys:
                    by_date.setdefault(path.name[:10], []).append(path)
        days = {}
        for d in dates:
            runs = read_runs(job_dir, d, settings.tz, by_date.get(d.isoformat(), []))
            days[d.isoformat()] = day_status(job, runs, d, now)
        rows.append(
            {
                "name": job.name,
                "description": job.description,
                "schedule": job.schedule,
                "registered": job.registered,
                "days": days,
            }
        )

    summary = {}
    for d in dates:
        counts = {}
        for row in rows:
            status = row["days"][d.isoformat()]["status"]
            counts[status] = counts.get(status, 0) + 1
        counts["problems"] = sum(counts.get(s, 0) for s in PROBLEMS)
        summary[d.isoformat()] = counts

    return {
        "generated_at": now,
        "today": today.isoformat(),
        "dates": [d.isoformat() for d in dates],
        "summary": summary,
        "jobs": rows,
    }


def job_detail(settings, name, run_date, now):
    """Every attempt of one job on one day, with errors and log tails. None if unknown job."""
    job = next((j for j in discover_jobs(settings) if j.name == name), None)
    if job is None:
        return None
    runs = read_runs(settings.status_dir / job.name, run_date, settings.tz)
    return {
        "name": job.name,
        "description": job.description,
        "schedule": job.schedule,
        "registered": job.registered,
        "max_runtime_minutes": int(job.max_runtime.total_seconds() // 60),
        "date": run_date.isoformat(),
        "day": day_status(job, runs, run_date, now),
        "runs": runs,
    }
