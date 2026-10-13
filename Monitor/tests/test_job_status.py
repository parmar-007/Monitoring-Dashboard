import json
import logging

import pytest

from job_status import track_run


def only_file(tmp_path, job):
    files = list((tmp_path / job).glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text())


def test_success_records_file_metrics_and_logs(tmp_path):
    out = tmp_path / "extract.csv"
    with track_run("Job_A", status_dir=tmp_path) as run:
        logging.getLogger("x").warning("hello from logging")
        print("hello from print")
        out.write_text("a,b\n1,2\n")
        run.add_file(out)
        run.records = 1
        run.set(dw_table="T")

    doc = only_file(tmp_path, "Job_A")
    assert doc["status"] == "SUCCESS"
    assert doc["records"] == 1
    assert doc["metrics"] == {"dw_table": "T"}
    assert doc["output_files"][0]["size_bytes"] > 0
    assert any("hello from logging" in line for line in doc["log_tail"])
    assert "hello from print" in doc["log_tail"]


def test_exception_marks_failed_and_reraises(tmp_path):
    with pytest.raises(RuntimeError):
        with track_run("Job_B", status_dir=tmp_path):
            raise RuntimeError("db down")

    doc = only_file(tmp_path, "Job_B")
    assert doc["status"] == "FAILED"
    assert doc["error"]["type"] == "RuntimeError"
    assert "db down" in doc["error"]["traceback"]


def test_missing_output_file_marks_failed(tmp_path):
    with track_run("Job_C", status_dir=tmp_path) as run:
        run.add_file(tmp_path / "never_written.csv")

    doc = only_file(tmp_path, "Job_C")
    assert doc["status"] == "FAILED"
    assert doc["error"]["type"] == "OutputMissing"


def test_old_files_pruned(tmp_path, monkeypatch):
    monkeypatch.setenv("STATUS_RETENTION_DAYS", "30")
    (tmp_path / "Job_D").mkdir()
    (tmp_path / "Job_D" / "2000-01-01_000000.json").write_text("{}")
    with track_run("Job_D", status_dir=tmp_path):
        pass
    assert not (tmp_path / "Job_D" / "2000-01-01_000000.json").exists()
