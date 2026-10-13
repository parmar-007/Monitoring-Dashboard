"""
Status reporting for cron jobs - copy this file into each job's image.

Standard library only. Writes one small JSON file per run to the shared PVC,
which the Extract Monitor dashboard reads:

    <STATUS_DIR>/<job name>/<YYYY-MM-DD>_<HHMMSS>.json

Usage:

    from job_status import track_run

    with track_run("Execution_Extract") as run:
        path = build_extract()            # your existing code
        run.add_file(path)                # checked for existence/size at the end
        sent = load_to_warehouse(path)
        run.records = sent                # shown in the dashboard's Records column
        run.set(dw_table="EXEC_FACT", records_sent_to_dw=sent)

What it records:
  * RUNNING as soon as the job starts, then SUCCESS or FAILED at the end
  * FAILED + exception type/message/traceback if the block raises
    (the exception is re-raised, so the OCP Job still fails as before)
  * FAILED if a file passed to add_file() is missing or empty at the end
  * the last N lines of logging output and print() output

If the pod is killed outright (OOM, activeDeadlineSeconds) the file stays at
RUNNING; the dashboard flags it as STUCK once max_runtime_minutes has passed.

Environment:
  STATUS_DIR             where to write (default /data/status)
  STATUS_TZ              IANA timezone for the run date, e.g. America/New_York
                         (default: the container's local time - usually UTC)
  STATUS_RETENTION_DAYS  delete this job's status files older than this (default 30)
"""

import collections
import contextlib
import json
import logging
import os
import socket
import sys
import tempfile
import traceback
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA_VERSION = 2

_log = logging.getLogger("job_status")


def _now():
    tz_name = os.environ.get("STATUS_TZ")
    if tz_name:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(tz_name))
    return datetime.now().astimezone()


class _Tail:
    """Keeps the last N lines from logging and stdout/stderr."""

    def __init__(self, max_lines):
        self.lines = collections.deque(maxlen=max_lines)
        self._partial = ""

    def add_text(self, text):
        text = self._partial + text
        *complete, self._partial = text.split("\n")
        self.lines.extend(line for line in complete if line.strip())

    def snapshot(self):
        tail = list(self.lines)
        if self._partial.strip():
            tail.append(self._partial)
        return tail


class _TailHandler(logging.Handler):
    def __init__(self, tail):
        super().__init__()
        self.tail = tail
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )

    def emit(self, record):
        try:
            self.tail.add_text(self.format(record) + "\n")
        except Exception:
            pass


class _Tee:
    """Wraps sys.stdout/sys.stderr so print() output lands in the tail too."""

    def __init__(self, stream, tail):
        self._stream = stream
        self._tail = tail

    def write(self, text):
        self._tail.add_text(text)
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


class Run:
    def __init__(self, job, status_dir, log_lines):
        self.job = job
        self.started_at = _now()
        self.execution_id = f"{job}-{self.started_at:%Y%m%d-%H%M%S}"
        self.records = None
        self.metrics = {}
        self._files = []
        self._tail = _Tail(log_lines)
        self._dir = Path(status_dir) / job
        self._path = self._dir / f"{self.started_at:%Y-%m-%d_%H%M%S}.json"

    def add_file(self, path):
        """Declare an output file; the run fails if it is missing or empty at the end."""
        self._files.append(str(path))

    def set(self, **metrics):
        """Attach any extra facts to show in the dashboard (DW table, batch id, ...)."""
        self.metrics.update(metrics)

    def _file_info(self):
        info = []
        for f in self._files:
            p = Path(f)
            exists = p.is_file()
            info.append(
                {
                    "name": p.name,
                    "path": str(p),
                    "exists": exists,
                    "size_bytes": p.stat().st_size if exists else None,
                }
            )
        return info

    def _write(self, status, error=None):
        finished = None if status == "RUNNING" else _now()
        doc = {
            "schema_version": SCHEMA_VERSION,
            "job": self.job,
            "execution_id": self.execution_id,
            "run_date": self.started_at.date().isoformat(),
            "status": status,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "finished_at": finished and finished.isoformat(timespec="seconds"),
            "duration_seconds": finished
            and round((finished - self.started_at).total_seconds()),
            "host": socket.gethostname(),
            "records": self.records,
            "output_files": self._file_info(),
            "metrics": self.metrics,
            "error": error,
            "log_tail": self._tail.snapshot(),
        }
        # Status reporting must never break the job itself.
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            # Write-then-rename so the dashboard never reads a half-written file.
            fd, tmp = tempfile.mkstemp(dir=self._dir, prefix=".tmp-", suffix=".json")
            with os.fdopen(fd, "w") as fh:
                json.dump(doc, fh, indent=2, default=str)
            os.replace(tmp, self._path)
        except Exception:
            _log.warning("Could not write status file %s", self._path, exc_info=True)

    def _prune(self, retention_days):
        cutoff = (self.started_at - timedelta(days=retention_days)).date().isoformat()
        try:
            for p in self._dir.glob("*.json"):
                if p.name[:10] < cutoff:
                    p.unlink(missing_ok=True)
        except Exception:
            _log.warning("Could not prune old status files", exc_info=True)


@contextlib.contextmanager
def track_run(job, status_dir=None, log_lines=200, capture_stdout=True):
    """Record the status of one run of `job` for the Extract Monitor dashboard."""
    run = Run(job, status_dir or os.environ.get("STATUS_DIR", "/data/status"), log_lines)

    handler = _TailHandler(run._tail)
    logging.getLogger().addHandler(handler)
    saved_streams = sys.stdout, sys.stderr
    if capture_stdout:
        sys.stdout = _Tee(sys.stdout, run._tail)
        sys.stderr = _Tee(sys.stderr, run._tail)

    run._write("RUNNING")
    try:
        yield run
    except SystemExit as exc:
        if exc.code in (None, 0):
            _finish(run)
        else:
            run._write("FAILED", {"type": "SystemExit", "message": f"exit code {exc.code}"})
        raise
    except BaseException as exc:
        run._write(
            "FAILED",
            {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        raise
    else:
        _finish(run)
    finally:
        sys.stdout, sys.stderr = saved_streams
        logging.getLogger().removeHandler(handler)
        run._prune(int(os.environ.get("STATUS_RETENTION_DAYS", "30")))


def _finish(run):
    bad = [f for f in run._file_info() if not f["exists"] or not f["size_bytes"]]
    if bad:
        names = ", ".join(f["path"] for f in bad)
        run._write("FAILED", {"type": "OutputMissing", "message": f"Missing or empty output: {names}"})
    else:
        run._write("SUCCESS")
