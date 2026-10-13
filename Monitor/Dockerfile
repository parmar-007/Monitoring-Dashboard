# Runs as an arbitrary non-root UID, as OpenShift requires.
FROM registry.access.redhat.com/ubi9/python-311

WORKDIR /opt/app-root/src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend backend
COPY frontend frontend
COPY jobs.yaml .

ENV STATUS_DIR=/data/status \
    JOBS_FILE=/opt/app-root/src/jobs.yaml \
    DASHBOARD_DAYS=7

EXPOSE 8080
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
