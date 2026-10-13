"""
Generate a week of fake status files (relative to today) so the dashboard can
be tried locally without OpenShift.

    python scripts/make_demo_data.py            # writes ./demo_data
    python scripts/make_demo_data.py /some/dir

Covers every status the dashboard knows: success, failure with traceback,
success-on-retry, still running, stuck, missing, pending, not scheduled,
an unregistered job, and one job written in the original JSON layout.
"""

import json
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.store import load_registry  # noqa: E402

START_TIMES = {
    "Execution_Extract": (5, 30),
    "Portfolio_Extract": (5, 45),
    "TimeBox_Extract": (6, 0),
    "Risk_Exposure_Extract": (4, 0),
    "Pricing_Snapshot": (4, 15),
    "Counterparty_Extract": (6, 30),
    "GL_Reconciliation": (21, 0),
    "Customer_Accounts_Extract": (6, 45),
}

TRACEBACK = """Traceback (most recent call last):
  File "/app/extract.py", line 88, in main
    rows = fetch_exposures(conn, desk_ids)
  File "/app/extract.py", line 41, in fetch_exposures
    cur.execute(SQL_EXPOSURE, params)
  File "/usr/lib/python3.11/site-packages/oracledb/cursor.py", line 710, in execute
    impl.execute(self)
oracledb.exceptions.DatabaseError: ORA-01555: snapshot too old: rollback segment number 9 with name "_SYSSMU9$" too small
"""


def log_lines(job, start, records, fail=None):
    t = start
    lines = []

    def add(level, msg, secs):
        nonlocal t
        t += timedelta(seconds=secs)
        lines.append(f"{t:%Y-%m-%d %H:%M:%S},{random.randint(100, 999)} {level} {job}: {msg}")

    add("INFO", "Starting extract", 0)
    add("INFO", "Connected to source database", 2)
    add("INFO", "Querying source tables", 1)
    if fail:
        add("WARNING", "Query running longer than expected", 140)
        add("ERROR", fail, 95)
        return lines
    add("INFO", f"Fetched {records:,} rows", 110)
    add("INFO", f"Wrote /data/extracts/{job.lower()}_{start:%Y%m%d}.csv", 25)
    add("INFO", f"Loaded {records:,} rows to warehouse", 70)
    add("INFO", "Done", 1)
    return lines


def write(folder, start, doc):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{start:%Y-%m-%d_%H%M%S}.json").write_text(json.dumps(doc, indent=2))


def run_doc(job, start, status, records=None, duration=None, error=None, tail=None):
    finished = start + timedelta(seconds=duration) if duration is not None else None
    file_name = f"{job.lower()}_{start:%Y%m%d}.csv"
    ok = status == "SUCCESS"
    return {
        "schema_version": 2,
        "job": job,
        "execution_id": f"{job}-{start:%Y%m%d-%H%M%S}",
        "run_date": start.date().isoformat(),
        "status": status,
        "started_at": start.isoformat(timespec="seconds"),
        "finished_at": finished and finished.isoformat(timespec="seconds"),
        "duration_seconds": duration,
        "host": f"{job.lower().replace('_', '-')}-{start:%H%M}{random.randint(10, 99)}-x7k2p",
        "records": records if ok else None,
        "output_files": [
            {
                "name": file_name,
                "path": f"/data/extracts/{file_name}",
                "exists": ok,
                "size_bytes": records * 212 if ok and records else None,
            }
        ]
        if status != "RUNNING"
        else [],
        "metrics": {"dw_table": f"STG_{job.upper()}", "records_sent_to_dw": records}
        if ok
        else {},
        "error": error,
        "log_tail": tail or [],
    }


def main(out_dir):
    random.seed(7)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    now = datetime.now().astimezone()
    today = now.date()
    jobs = {j.name: j for j in load_registry(ROOT / "jobs.yaml")}

    for offset in range(8):
        day = today - timedelta(days=offset)
        for name, (hh, mm) in START_TIMES.items():
            job = jobs.get(name)
            if job is None or not job.runs_on(day):
                continue
            start = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo).replace(
                hour=hh, minute=mm, second=random.randint(0, 59)
            )
            folder = out_dir / name
            records = random.randint(8_000, 60_000)
            duration = random.randint(180, 420)

            if name == "Pricing_Snapshot" and offset == 1:
                continue  # MISSING: cron never fired
            if name == "GL_Reconciliation" and offset == 0:
                continue  # PENDING: due at 23:00
            if name == "TimeBox_Extract" and offset == 0:
                start = now - timedelta(minutes=11)
                write(folder, start, run_doc(name, start, "RUNNING", tail=log_lines(name, start, records)[:3]))
                continue
            if start > now:
                continue  # today's run hasn't happened yet

            if name == "Risk_Exposure_Extract" and offset == 0:
                msg = 'ORA-01555: snapshot too old: rollback segment number 9 with name "_SYSSMU9$" too small'
                write(folder, start, run_doc(
                    name, start, "FAILED", duration=241,
                    error={"type": "DatabaseError", "message": msg, "traceback": TRACEBACK},
                    tail=log_lines(name, start, records, fail=f"Extract failed: {msg}"),
                ))
            elif name == "Portfolio_Extract" and offset == 3:
                # STUCK: pod OOM-killed mid-run, file never updated past RUNNING
                write(folder, start, run_doc(name, start, "RUNNING", tail=log_lines(name, start, records)[:4]))
            elif name == "Execution_Extract" and offset == 2:
                msg = "Timed out connecting to warehouse after 3 retries"
                write(folder, start, run_doc(
                    name, start, "FAILED", duration=95,
                    error={"type": "TimeoutError", "message": msg},
                    tail=log_lines(name, start, records, fail=msg),
                ))
                retry = start + timedelta(minutes=95)
                write(folder, retry, run_doc(name, retry, "SUCCESS", records, duration, tail=log_lines(name, retry, records)))
            elif name == "Customer_Accounts_Extract":
                # Original JSON layout, to show existing jobs keep working unchanged.
                failed = offset == 5
                end = start + timedelta(seconds=duration)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{day.isoformat()}.json").write_text(json.dumps({
                    "application": name,
                    "execution_id": f"CUS-{day:%Y%m%d}-001",
                    "execution_date": day.isoformat(),
                    "start_time": f"{start:%H:%M:%S}",
                    "end_time": f"{end:%H:%M:%S}",
                    "duration_seconds": duration,
                    "status": "FAILED" if failed else "SUCCESS",
                    "total_records": 0 if failed else records,
                    "error_code": "SFTP-403" if failed else "",
                    "error_message": "Permission denied writing to /outbound/accounts" if failed else "",
                }, indent=4))
            else:
                write(folder, start, run_doc(name, start, "SUCCESS", records, duration, tail=log_lines(name, start, records)))

    # A job writing to the PVC that nobody added to jobs.yaml yet.
    start = datetime.combine(today - timedelta(days=4), datetime.min.time(), tzinfo=now.tzinfo).replace(hour=13, minute=5)
    write(out_dir / "Adhoc_Backfill", start, run_doc("Adhoc_Backfill", start, "SUCCESS", 1_250_000, 2_710,
                                                     tail=log_lines("Adhoc_Backfill", start, 1_250_000)))
    print(f"Demo status files written to {out_dir}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "demo_data")
