"""Tests for token counting, ledger writes, summary generation."""

import logging

import pytest

from usai_harness.cost import CostTracker


def _response(prompt_tokens: int, completion_tokens: int) -> dict:
    return {
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
    }


def test_record_call_accumulates(tmp_path):
    ct = CostTracker("llama", 0.0, 0.0, ledger_path=tmp_path / "ledger.jsonl")
    ct.record_call(_response(100, 50), success=True)
    ct.record_call(_response(200, 100), success=True)
    ct.record_call(_response(300, 150), success=True)

    totals = ct.get_run_totals()
    assert totals["total_input_tokens"] == 600
    assert totals["total_output_tokens"] == 300
    assert totals["total_tokens"] == 900
    assert totals["total_calls"] == 3
    assert totals["successful_calls"] == 3
    assert totals["failed_calls"] == 0


def test_cost_calculation_zero_rates(tmp_path):
    ct = CostTracker("llama", 0.0, 0.0, ledger_path=tmp_path / "ledger.jsonl")
    ct.record_call(_response(1000, 500), success=True)
    totals = ct.get_run_totals()
    assert totals["estimated_cost_input"] == 0.0
    assert totals["estimated_cost_output"] == 0.0
    assert totals["estimated_cost_total"] == 0.0


def test_cost_calculation_nonzero_rates(tmp_path):
    ct = CostTracker("llama", 0.01, 0.03, ledger_path=tmp_path / "ledger.jsonl")
    ct.record_call(_response(1000, 500), success=True)
    totals = ct.get_run_totals()
    assert totals["estimated_cost_input"] == pytest.approx(0.01)
    assert totals["estimated_cost_output"] == pytest.approx(0.015)
    assert totals["estimated_cost_total"] == pytest.approx(0.025)


def test_missing_usage_data_warns(tmp_path, caplog):
    ct = CostTracker("llama", 0.01, 0.03, ledger_path=tmp_path / "ledger.jsonl")
    caplog.set_level(logging.WARNING, logger="usai_harness.cost")
    ct.record_call({}, success=False)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected WARNING when usage data is absent"
    totals = ct.get_run_totals()
    assert totals["total_input_tokens"] == 0
    assert totals["total_output_tokens"] == 0
    assert totals["total_calls"] == 1
    assert totals["failed_calls"] == 1


def test_write_summary_creates_ledger(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ct = CostTracker("llama", 0.0, 0.0, ledger_path=ledger)
    ct.record_call(_response(100, 50), success=True)
    ct.write_summary(job_id="J1", job_name="test-run",
                     project="p", model="llama", duration_seconds=10.0)

    assert ledger.exists()
    assert len(ledger.read_text().splitlines()) == 1


def test_write_summary_appends(tmp_path):
    ledger = tmp_path / "ledger.jsonl"

    ct1 = CostTracker("llama", 0.0, 0.0, ledger_path=ledger)
    ct1.record_call(_response(100, 50), success=True)
    ct1.write_summary("J1", "run1", "p", "llama", 10.0)

    ct2 = CostTracker("llama", 0.0, 0.0, ledger_path=ledger)
    ct2.record_call(_response(200, 100), success=True)
    ct2.write_summary("J2", "run2", "p", "llama", 20.0)

    assert len(ledger.read_text().splitlines()) == 2


def test_read_ledger_missing_file(tmp_path):
    assert CostTracker.read_ledger(ledger_path=tmp_path / "nope.jsonl") == []


def test_read_ledger_parses(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    for i in range(3):
        ct = CostTracker("llama", 0.0, 0.0, ledger_path=ledger)
        ct.record_call(_response(100, 50), success=True)
        ct.write_summary(f"J{i}", f"run{i}", "p", "llama", 10.0)

    entries = CostTracker.read_ledger(ledger_path=ledger)
    assert len(entries) == 3
    for e in entries:
        assert "job_id" in e
        assert "total_tokens_in" in e
        assert "estimated_cost" in e


def test_success_rate_calculation(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ct = CostTracker("llama", 0.0, 0.0, ledger_path=ledger)
    for _ in range(8):
        ct.record_call(_response(10, 5), success=True)
    for _ in range(2):
        ct.record_call(_response(10, 5), success=False)
    ct.write_summary("J1", "run", "p", "llama", 1.0)

    entries = CostTracker.read_ledger(ledger_path=ledger)
    assert entries[0]["success_rate"] == pytest.approx(0.8)


def test_success_rate_zero_calls(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ct = CostTracker("llama", 0.0, 0.0, ledger_path=ledger)
    ct.write_summary("J1", "run", "p", "llama", 0.0)

    entries = CostTracker.read_ledger(ledger_path=ledger)
    assert entries[0]["success_rate"] == 0.0
