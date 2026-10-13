import os
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

APP_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    status_dir: Path  # PVC mount the cron jobs write to
    jobs_file: Path  # registry of expected jobs
    tz: tzinfo  # decides what "today" is; must match the jobs' STATUS_TZ
    days: int  # how many days the dashboard shows


def load_settings():
    tz_name = os.environ.get("STATUS_TZ")
    return Settings(
        status_dir=Path(os.environ.get("STATUS_DIR", APP_ROOT / "demo_data")),
        jobs_file=Path(os.environ.get("JOBS_FILE", APP_ROOT / "jobs.yaml")),
        tz=ZoneInfo(tz_name) if tz_name else datetime.now().astimezone().tzinfo,
        days=int(os.environ.get("DASHBOARD_DAYS", "7")),
    )
