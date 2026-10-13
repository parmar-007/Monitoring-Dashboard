# Extract Monitor

One page that shows whether each OpenShift cron job ran, succeeded, and
produced its file, for today and the previous 6 days. It replaces opening each
job's logs in OCP every morning.

## How it works

```text
 CronJob pods (25 jobs)                     Shared PVC                      Dashboard pod
 ──────────────────────                     ──────────                      ─────────────
 with track_run("Execution_Extract"):  ──▶  /data/status/                ◀── reads (read-only mount)
     ...existing code...                      Execution_Extract/              FastAPI  /api/overview
                                                2026-10-13_053020.json        + static page
                                              Portfolio_Extract/ ...       ◀── jobs.yaml (ConfigMap)
```

* Each job writes **one small JSON file per run**: `RUNNING` when it starts, then
  `SUCCESS` or `FAILED` when it ends, with records, output files, any metrics you
  add, the error and traceback, and the last 200 log lines.
* **`jobs.yaml`** lists which jobs are expected on which days and by what time.
  This is how the dashboard reports a job that **didn't run at all**, which no
  status file can do on its own.
* The dashboard combines the two into a status per job per day:

| Status | Meaning |
|---|---|
| ✓ Succeeded | Latest run that day finished OK (earlier failed attempts are kept and shown) |
| ✕ Failed | Latest run failed, or a declared output file was missing/empty |
| ◷ Stuck | Still `RUNNING` after `max_runtime_minutes`; the pod was probably OOM-killed or hit its deadline |
| ! Missing | Scheduled, past `expected_by`, no status file. The CronJob didn't fire or the pod died before starting |
| ▶ Running | In progress |
| … Pending | Scheduled, not due yet |
| – Not scheduled | Not expected that day |

## Adding a job (one-time per job)

1. Copy [`job_status.py`](job_status.py) into the job's image (standard library only, no dependencies).
2. Wrap the job's main logic:

   ```python
   from job_status import track_run

   with track_run("Execution_Extract") as run:
       path = build_extract()                 # existing code
       run.add_file(path)                     # run is FAILED if this is missing/empty
       sent = load_to_warehouse(path)
       run.records = sent                     # "Records" column
       run.set(dw_table="EXEC_FACT", records_sent_to_dw=sent)   # shown under Details
   ```

   Exceptions are recorded and **re-raised**, so the OCP Job still fails exactly as before.
3. Give the CronJob `STATUS_DIR` and `STATUS_TZ` and mount the PVC.
   See [`openshift/cronjob-example.yaml`](openshift/cronjob-example.yaml).
4. Add the job to [`jobs.yaml`](jobs.yaml) (name, schedule, expected_by).

Jobs not yet migrated still work if they write the original format
(`<job>/<YYYY-MM-DD>.json` with `application`, `status`, `total_records`, ...).
They just won't have log tails or the stuck/output-file checks.

Status files older than `STATUS_RETENTION_DAYS` (default 30) are deleted by the
job itself, so nothing else has to clean up the PVC.

## Run locally

Install into a virtualenv, not your global Python. FastAPI pulls in
`opentelemetry-api`, which can conflict with other tools installed globally.

```bash
cd Monitor
python3 -m venv venv
source venv/bin/activate                             # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt

python scripts/make_demo_data.py                     # a fake week of runs in ./demo_data
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000. The page and API are served by the same app.

Run the tests with `pytest`.

### Configuration (environment variables)

| Variable | Default | Used by |
|---|---|---|
| `STATUS_DIR` | `./demo_data` (dashboard), `/data/status` (jobs) | both |
| `STATUS_TZ` | container local time (usually UTC in OCP) | both, **must match** |
| `JOBS_FILE` | `./jobs.yaml` | dashboard |
| `DASHBOARD_DAYS` | `7` | dashboard |
| `STATUS_RETENTION_DAYS` | `30` | jobs |

## Deploy to OpenShift

```bash
podman build -t <your-registry>/extract-monitor:latest . && podman push <your-registry>/extract-monitor:latest
oc create configmap extract-monitor-jobs --from-file=jobs.yaml
oc apply -f openshift/dashboard.yaml       # edit image, PVC name and STATUS_TZ first
oc get route extract-monitor
```

Edits to the ConfigMap show up on the next page refresh. No restart needed.

**PVC access mode.** The dashboard pod mounts the same PVC as the jobs, read-only.
If the PVC is `ReadWriteMany` this just works. If it's `ReadWriteOnce`, the
dashboard and jobs must land on the same node (or move status files to an RWX
PVC of their own by pointing `STATUS_DIR` at it).

**Access.** The Route has no login. If the page shouldn't be open to everyone on
the network, put the OpenShift oauth-proxy sidecar in front of it.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/overview?days=7` | Every job x every day: status, attempts, records, timings, plus per-day counts |
| `GET /api/jobs/{job}/{YYYY-MM-DD}` | All attempts for that job/day with error, traceback, output files, metrics, log tail |
| `GET /api/health` | Liveness, and whether `STATUS_DIR` is readable |

The page keeps the selected day and job in the URL (`#date=2026-10-12&job=Pricing_Snapshot`),
so you can paste a link to a specific failure into chat.

## Layout

```text
Monitor/
├── job_status.py          # copy into each cron job
├── jobs.yaml              # registry of expected jobs
├── backend/
│   ├── main.py            # FastAPI: /api/* + serves frontend/
│   ├── store.py           # reads status files, derives per-day status
│   └── config.py
├── frontend/              # index.html, css/, js/ (no build step)
├── scripts/make_demo_data.py
├── tests/
├── openshift/             # dashboard Deployment/Service/Route, CronJob example
└── Dockerfile
```
