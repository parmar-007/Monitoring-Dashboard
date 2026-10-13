from dataclasses import replace
from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from backend import store
from backend.config import APP_ROOT, load_settings

settings = load_settings()

app = FastAPI(title="Extract Monitor")


@app.get("/api/health")
def health():
    return {"status": "UP", "status_dir_readable": settings.status_dir.is_dir()}


@app.get("/api/overview")
def get_overview(days: int = Query(settings.days, ge=1, le=31)):
    return store.overview(replace(settings, days=days), datetime.now(settings.tz))


@app.get("/api/jobs/{name}/{run_date}")
def get_job_detail(name: str, run_date: date):
    if not store.JOB_NAME_RE.match(name):
        raise HTTPException(400, "Invalid job name")
    detail = store.job_detail(settings, name, run_date, datetime.now(settings.tz))
    if detail is None:
        raise HTTPException(404, f"Unknown job {name}")
    return detail


# The dashboard itself; mounted last so /api routes take precedence.
app.mount("/", StaticFiles(directory=APP_ROOT / "frontend", html=True), name="frontend")
