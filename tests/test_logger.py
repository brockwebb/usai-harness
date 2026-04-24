"""Tests for structured call logging."""

import json

import pytest

from usai_harness.logger import CallLogger


def _base_call(**overrides):
    data = {
        "timestamp": "2026-04-22T12:00:00+00:00",
        "task_id": "t1",
        "model_requested": "claude-sonnet-4-5-20241022",
        "status_code": 200,
    }
    data.update(overrides)
    return data


def test_log_creates_file(tmp_path):
    log = CallLogger(log_dir=tmp_path, job_id="test-job", project="p")
    try:
        assert log.get_log_path().exists()
    finally:
        log.close()


def test_log_call_writes_entry(tmp_path):
    log = CallLogger(log_dir=tmp_path, job_id="test-job", project="p")
    log.log_call(_base_call(prompt_tokens=10, completion_tokens=20, latency_ms=100.5))
    log.close()

    lines = log.get_log_path().read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["task_id"] == "t1"
    assert entry["model_requested"] == "claude-sonnet-4-5-20241022"
    assert entry["status_code"] == 200
    assert entry["prompt_tokens"] == 10
    assert entry["completion_tokens"] == 20
    assert entry["latency_ms"] == 100.5


def test_log_call_adds_job_metadata(tmp_path):
    log = CallLogger(log_dir=tmp_path, job_id="J1", project="myproj")
    log.log_call(_base_call())
    log.close()

    entry = json.loads(log.get_log_path().read_text().splitlines()[0])
    assert entry["job_id"] == "J1"
    assert entry["project"] == "myproj"


def test_log_call_missing_required_field_raises(tmp_path):
    log = CallLogger(log_dir=tmp_path, job_id="J1", project="p")
    try:
        with pytest.raises(ValueError):
            log.log_call({})
    finally:
        log.close()


def test_multiple_entries(tmp_path):
    log = CallLogger(log_dir=tmp_path, job_id="J1", project="p")
    for i in range(5):
        log.log_call(_base_call(task_id=f"t{i}"))
    entries = log.get_entries()
    log.close()

    assert len(entries) == 5
    assert [e["task_id"] for e in entries] == [f"t{i}" for i in range(5)]


def test_flush_on_each_write(tmp_path):
    log = CallLogger(log_dir=tmp_path, job_id="J1", project="p")
    try:
        log.log_call(_base_call())
        # Read from disk without closing the writer.
        content = log.get_log_path().read_text()
        assert '"task_id": "t1"' in content
    finally:
        log.close()


def test_context_manager(tmp_path):
    with CallLogger(log_dir=tmp_path, job_id="J1", project="p") as log:
        log.log_call(_base_call())
        handle = log._file
    assert handle.closed


def test_auto_generated_job_id(tmp_path):
    log = CallLogger(log_dir=tmp_path, project="myproj")
    try:
        # {project}_{YYYYMMDD_HHMMSS}
        assert log.job_id.startswith("myproj_")
        suffix = log.job_id[len("myproj_"):]
        assert len(suffix) == 15 and suffix[8] == "_"
        assert suffix[:8].isdigit()
        assert suffix[9:].isdigit()
    finally:
        log.close()
