import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend import store
from backend.config import Settings

TZ = ZoneInfo("America/New_York")
TODAY = date(2026, 10, 13)  # a Tuesday
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=TZ)


@pytest.fixture
def settings(tmp_path):
    jobs = tmp_path / "jobs.yaml"
    jobs.write_text(
        """
defaults:
  expected_by: "08:00"
  max_runtime_minutes: 60
jobs:
  - name: Daily_Job
  - name: Weekday_Job
    schedule: weekdays
  - name: Late_Job
    expected_by: "22:00"
"""
    )
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    return Settings(status_dir=status_dir, jobs_file=jobs, tz=TZ, days=7)


def write_run(settings, job, started, **fields):
    folder = settings.status_dir / job
    folder.mkdir(exist_ok=True)
    doc = {"job": job, "status": "SUCCESS", "started_at": started.isoformat(), **fields}
    (folder / f"{started:%Y-%m-%d_%H%M%S}.json").write_text(json.dumps(doc))


def at(d, hh, mm=0):
    return datetime.combine(d, time(hh, mm), tzinfo=TZ)


def cell(settings, job, d=TODAY, now=NOW):
    overview = store.overview(settings, now)
    row = next(r for r in overview["jobs"] if r["name"] == job)
    return row["days"][d.isoformat()]


def test_success(settings):
    write_run(settings, "Daily_Job", at(TODAY, 6), records=10)
    c = cell(settings, "Daily_Job")
    assert c["status"] == store.SUCCESS
    assert c["records"] == 10


def test_no_file_after_deadline_is_missing(settings):
    assert cell(settings, "Daily_Job")["status"] == store.MISSING


def test_no_file_before_deadline_is_pending(settings):
    assert cell(settings, "Late_Job")["status"] == store.PENDING


def test_past_day_without_file_is_missing_even_with_late_deadline(settings):
    assert cell(settings, "Late_Job", TODAY - timedelta(days=1))["status"] == store.MISSING


def test_not_scheduled_on_weekend(settings):
    saturday = date(2026, 10, 10)
    assert cell(settings, "Weekday_Job", saturday)["status"] == store.NO_RUN
    assert cell(settings, "Weekday_Job", TODAY - timedelta(days=1))["status"] == store.MISSING  # Monday


def test_running_within_limit_then_stuck(settings):
    write_run(settings, "Daily_Job", at(TODAY, 8, 30), status="RUNNING")
    assert cell(settings, "Daily_Job")["status"] == store.RUNNING
    assert cell(settings, "Daily_Job", now=at(TODAY, 9, 31))["status"] == store.STUCK


def test_latest_attempt_wins(settings):
    write_run(settings, "Daily_Job", at(TODAY, 6), status="FAILED", error={"message": "boom"})
    write_run(settings, "Daily_Job", at(TODAY, 7), status="SUCCESS")
    c = cell(settings, "Daily_Job")
    assert c["status"] == store.SUCCESS
    assert c["attempts"] == 2


def test_legacy_format_is_read(settings):
    folder = settings.status_dir / "Daily_Job"
    folder.mkdir()
    (folder / "2026-10-13.json").write_text(json.dumps({
        "application": "Daily_Job", "execution_date": "2026-10-13", "start_time": "06:00:00",
        "end_time": "06:05:00", "status": "FAILED", "total_records": 0,
        "error_code": "E1", "error_message": "bad",
    }))
    c = cell(settings, "Daily_Job")
    assert c["status"] == store.FAILED
    assert c["error_message"] == "bad"
    assert c["started_at"] == at(TODAY, 6)


def test_corrupt_file_shows_as_failed(settings):
    folder = settings.status_dir / "Daily_Job"
    folder.mkdir()
    (folder / "2026-10-13_060000.json").write_text("{not json")
    assert cell(settings, "Daily_Job")["status"] == store.FAILED


def test_unregistered_folder_is_listed(settings):
    write_run(settings, "Adhoc", at(TODAY, 6))
    overview = store.overview(settings, NOW)
    row = next(r for r in overview["jobs"] if r["name"] == "Adhoc")
    assert row["registered"] is False
    assert row["days"][(TODAY - timedelta(days=1)).isoformat()]["status"] == store.NO_RUN


def test_summary_counts_problems(settings):
    write_run(settings, "Daily_Job", at(TODAY, 6), status="FAILED")
    summary = store.overview(settings, NOW)["summary"][TODAY.isoformat()]
    # Daily_Job failed, Weekday_Job missing, Late_Job pending
    assert summary["problems"] == 2
    assert summary[store.PENDING] == 1


def test_bad_schedule_rejected(tmp_path):
    jobs = tmp_path / "jobs.yaml"
    jobs.write_text("jobs:\n  - name: X\n    schedule: '0 9 * * *'\n")
    with pytest.raises(ValueError):
        store.load_registry(jobs)


def test_api(settings, monkeypatch):
    from backend import main

    monkeypatch.setattr(main, "settings", settings)
    write_run(settings, "Daily_Job", datetime.now(TZ).replace(hour=0, minute=1))
    client = TestClient(main.app)

    assert client.get("/api/overview").status_code == 200
    today = datetime.now(TZ).date().isoformat()
    detail = client.get(f"/api/jobs/Daily_Job/{today}").json()
    assert detail["runs"][0]["status"] == store.SUCCESS
    assert client.get(f"/api/jobs/Nope/{today}").status_code == 404
    assert client.get(f"/api/jobs/..%2F..%2Fetc/{today}").status_code in (400, 404)
    assert client.get("/").status_code == 200  # dashboard page
