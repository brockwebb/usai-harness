"""Tests for the per-model CostTracker (ADR-004 amendment, 2026-04-29 / 0.7.0)."""

import logging
from dataclasses import dataclass

import pytest

from usai_harness.cost import CostTracker, LedgerEntry, VALID_FLUSH_REASONS


@dataclass
class _PoolMember:
    """Stand-in for ModelConfig with the two fields CostTracker reads."""
    name: str
    cost_per_1k_input_tokens: float
    cost_per_1k_output_tokens: float


def _pool(*entries: tuple[str, float, float]) -> list[_PoolMember]:
    return [_PoolMember(name, ci, co) for (name, ci, co) in entries]


def _response(prompt_tokens: int, completion_tokens: int) -> dict:
    return {
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
    }


def test_record_call_accumulates_per_model(tmp_path):
    ct = CostTracker(
        pool=_pool(("llama", 0.0, 0.0)),
        ledger_path=tmp_path / "ledger.jsonl",
    )
    ct.record_call("llama", _response(100, 50), success=True)
    ct.record_call("llama", _response(200, 100), success=True)
    ct.record_call("llama", _response(300, 150), success=True)

    totals = ct.get_run_totals()
    assert "llama" in totals
    t = totals["llama"]
    assert t["total_input_tokens"] == 600
    assert t["total_output_tokens"] == 300
    assert t["total_tokens"] == 900
    assert t["total_calls"] == 3
    assert t["successful_calls"] == 3
    assert t["failed_calls"] == 0


def test_cost_calculation_uses_per_model_rates(tmp_path):
    ct = CostTracker(
        pool=_pool(("a", 0.01, 0.03), ("b", 0.001, 0.002)),
        ledger_path=tmp_path / "ledger.jsonl",
    )
    ct.record_call("a", _response(1000, 500), success=True)
    ct.record_call("b", _response(1000, 500), success=True)
    totals = ct.get_run_totals()
    assert totals["a"]["estimated_cost_total"] == pytest.approx(0.025)
    assert totals["b"]["estimated_cost_total"] == pytest.approx(0.002)


def test_missing_usage_data_warns(tmp_path, caplog):
    ct = CostTracker(
        pool=_pool(("llama", 0.01, 0.03)),
        ledger_path=tmp_path / "ledger.jsonl",
    )
    caplog.set_level(logging.WARNING, logger="usai_harness.cost")
    ct.record_call("llama", {}, success=False)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected WARNING when usage data is absent"
    t = ct.get_run_totals()["llama"]
    assert t["total_input_tokens"] == 0
    assert t["total_output_tokens"] == 0
    assert t["total_calls"] == 1
    assert t["failed_calls"] == 1


def test_flush_writes_one_line_per_model(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ct = CostTracker(
        pool=_pool(("a", 0.01, 0.0), ("b", 0.0, 0.02)),
        ledger_path=ledger,
    )
    ct.record_call("a", _response(100, 50), success=True)
    ct.record_call("b", _response(200, 100), success=True)
    written = ct.flush_to_ledger(
        job_id="J1", job_name="run", project="p",
        duration_seconds=10.0, flush_reason="batch_end",
    )
    assert written == 2

    entries = CostTracker.read_ledger(ledger)
    assert len(entries) == 2
    by_model = {e["model"]: e for e in entries}
    assert by_model["a"]["estimated_cost"] == pytest.approx(0.001)
    assert by_model["b"]["estimated_cost"] == pytest.approx(0.002)
    assert by_model["a"]["flush_reason"] == "batch_end"


def test_flush_skips_models_with_zero_calls(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ct = CostTracker(
        pool=_pool(("a", 0.0, 0.0), ("b", 0.0, 0.0)),
        ledger_path=ledger,
    )
    ct.record_call("a", _response(50, 25), success=True)
    written = ct.flush_to_ledger(
        job_id="J1", job_name="run", project="p",
        duration_seconds=1.0, flush_reason="batch_end",
    )
    assert written == 1
    entries = CostTracker.read_ledger(ledger)
    assert [e["model"] for e in entries] == ["a"]


def test_flush_resets_totals(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ct = CostTracker(
        pool=_pool(("a", 0.0, 0.0)),
        ledger_path=ledger,
    )
    ct.record_call("a", _response(100, 50), success=True)
    ct.flush_to_ledger("J1", "r1", "p", 1.0, "batch_end")
    assert ct.get_run_totals()["a"]["total_calls"] == 0

    ct.record_call("a", _response(200, 100), success=True)
    ct.flush_to_ledger("J2", "r2", "p", 1.0, "client_close")
    entries = CostTracker.read_ledger(ledger)
    assert len(entries) == 2
    assert entries[0]["total_tokens_in"] == 100
    assert entries[1]["total_tokens_in"] == 200
    assert entries[0]["flush_reason"] == "batch_end"
    assert entries[1]["flush_reason"] == "client_close"


def test_flush_with_no_calls_writes_nothing(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ct = CostTracker(pool=_pool(("a", 0.0, 0.0)), ledger_path=ledger)
    written = ct.flush_to_ledger("J1", "r1", "p", 0.0, "client_close")
    assert written == 0
    assert not ledger.exists() or ledger.read_text() == ""


def test_flush_invalid_reason_raises(tmp_path):
    ct = CostTracker(pool=_pool(("a", 0.0, 0.0)), ledger_path=tmp_path / "x.jsonl")
    with pytest.raises(ValueError, match="flush_reason"):
        ct.flush_to_ledger("J1", "r1", "p", 0.0, "midnight")


def test_unknown_model_creates_synthetic_bucket_with_warn(tmp_path, caplog):
    ct = CostTracker(pool=_pool(("known", 0.0, 0.0)), ledger_path=tmp_path / "x.jsonl")
    caplog.set_level(logging.WARNING, logger="usai_harness.cost")
    ct.record_call("not-in-pool", _response(10, 5), success=True)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("not in cost tracker pool" in r.getMessage() for r in warnings)
    totals = ct.get_run_totals()
    assert "not-in-pool" in totals
    assert totals["not-in-pool"]["total_calls"] == 1
    # Synthetic bucket has zero rates → zero cost.
    assert totals["not-in-pool"]["estimated_cost_total"] == 0.0


def test_read_ledger_missing_file(tmp_path):
    assert CostTracker.read_ledger(ledger_path=tmp_path / "nope.jsonl") == []


def test_success_rate_calculation(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ct = CostTracker(pool=_pool(("llama", 0.0, 0.0)), ledger_path=ledger)
    for _ in range(8):
        ct.record_call("llama", _response(10, 5), success=True)
    for _ in range(2):
        ct.record_call("llama", _response(10, 5), success=False)
    ct.flush_to_ledger("J1", "r", "p", 1.0, "batch_end")
    entries = CostTracker.read_ledger(ledger)
    assert entries[0]["success_rate"] == pytest.approx(0.8)


def test_ledger_entry_has_no_content_fields():
    """Structural guarantee: LedgerEntry has no prompt/response/content fields (FR-031)."""
    from dataclasses import fields

    forbidden = {"prompt", "response", "content", "messages",
                 "completion", "text"}
    actual = {f.name for f in fields(LedgerEntry)}
    overlap = actual & forbidden
    assert not overlap, (
        f"LedgerEntry has forbidden content field(s): {overlap}. "
        f"Per FR-031, the ledger is metadata-only."
    )


def test_ledger_entry_has_flush_reason_field():
    """The 0.7.0 ADR-004 amendment adds flush_reason as a required field."""
    from dataclasses import fields
    field_names = {f.name for f in fields(LedgerEntry)}
    assert "flush_reason" in field_names
    assert "model" in field_names


def test_valid_flush_reasons_constant():
    assert VALID_FLUSH_REASONS == frozenset({"batch_end", "client_close"})
