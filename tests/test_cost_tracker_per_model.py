"""End-to-end per-model cost-tracking integration tests through USAiClient.

Covers the workflow shapes called out in the ADR-004 amendment (2026-04-29):
mixed-model batch, single-model batch in a multi-model pool, complete()-only
sessions, mixed complete()/batch() sequences, and the zero-call client
lifetime. The point is to verify the (model, flush-point) ledger contract
end-to-end, not to re-test CostTracker internals (those live in test_cost.py).
"""

import json
import textwrap
from pathlib import Path

import pytest

from usai_harness.client import USAiClient
from usai_harness.cost import CostTracker
from usai_harness.transport import BaseTransport

pytestmark = pytest.mark.asyncio


class MockTransport(BaseTransport):
    """Transport that echoes back which model was called with token usage."""

    def __init__(self):
        self.calls: list[dict] = []
        self.closed = False

    async def send(self, base_url, api_key, model, messages,
                   temperature=0.0, max_tokens=4096, system_prompt=None, **kwargs):
        self.calls.append({"model": model, "messages": messages})
        body = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
            "model": model,
        }
        return body, 200

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path_factory):
    for var in ("USAI_API_KEY", "USAI_BASE_URL", "OPENROUTER_API_KEY",
                "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(var, raising=False)
    empty = tmp_path_factory.mktemp("empty_user_config")
    monkeypatch.setattr(
        "usai_harness.key_manager.user_config_env_path",
        lambda: empty / "usai-harness" / ".env",
    )


@pytest.fixture
def env_path(tmp_path):
    p = tmp_path / ".env"
    p.write_text("USAI_API_KEY=test-key-AAAAAAAA\n")
    return p


def _multi_pool_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "project.yaml"
    cfg.write_text(textwrap.dedent("""
        models:
          - name: claude-sonnet-4-5-20241022
          - name: claude-opus-4-5-20250521
          - name: gemini-2.5-flash
        default_model: claude-sonnet-4-5-20241022
    """).lstrip())
    return cfg


def _new_client(tmp_path, env_path, *, config_path=None, transport=None):
    return USAiClient(
        project="cost-test",
        env_path=env_path,
        transport=transport if transport is not None else MockTransport(),
        log_dir=tmp_path / "logs",
        ledger_path=tmp_path / "ledger.jsonl",
        config_path=config_path,
    )


def _read_ledger(tmp_path: Path) -> list[dict]:
    return CostTracker.read_ledger(tmp_path / "ledger.jsonl")


async def test_mixed_model_batch_writes_one_line_per_model(tmp_path, env_path, capsys):
    cfg = _multi_pool_config(tmp_path)
    client = _new_client(tmp_path, env_path, config_path=cfg)
    try:
        await client.batch([
            {"model": "claude-sonnet-4-5-20241022",
             "messages": [{"role": "user", "content": "a"}]},
            {"model": "claude-opus-4-5-20250521",
             "messages": [{"role": "user", "content": "b"}]},
            {"model": "claude-sonnet-4-5-20241022",
             "messages": [{"role": "user", "content": "c"}]},
        ])
    finally:
        await client.close()
    capsys.readouterr()

    entries = _read_ledger(tmp_path)
    by_model = {e["model"]: e for e in entries if e["flush_reason"] == "batch_end"}
    assert set(by_model) == {
        "claude-sonnet-4-5-20241022", "claude-opus-4-5-20250521",
    }
    assert by_model["claude-sonnet-4-5-20241022"]["total_calls"] == 2
    assert by_model["claude-opus-4-5-20250521"]["total_calls"] == 1


async def test_single_model_batch_in_multi_pool_writes_one_line(tmp_path, env_path, capsys):
    cfg = _multi_pool_config(tmp_path)
    client = _new_client(tmp_path, env_path, config_path=cfg)
    try:
        await client.batch([
            {"model": "gemini-2.5-flash",
             "messages": [{"role": "user", "content": "x"}]},
            {"model": "gemini-2.5-flash",
             "messages": [{"role": "user", "content": "y"}]},
        ])
    finally:
        await client.close()
    capsys.readouterr()

    entries = _read_ledger(tmp_path)
    batch_lines = [e for e in entries if e["flush_reason"] == "batch_end"]
    assert len(batch_lines) == 1
    assert batch_lines[0]["model"] == "gemini-2.5-flash"
    assert batch_lines[0]["total_calls"] == 2


async def test_complete_only_workflow_flushes_at_close(tmp_path, env_path):
    cfg = _multi_pool_config(tmp_path)
    client = _new_client(tmp_path, env_path, config_path=cfg)
    try:
        await client.complete(
            messages=[{"role": "user", "content": "1"}],
            model="claude-sonnet-4-5-20241022",
        )
        await client.complete(
            messages=[{"role": "user", "content": "2"}],
            model="claude-opus-4-5-20250521",
        )
        # No batch ran: ledger should still be empty before close.
        assert _read_ledger(tmp_path) == []
    finally:
        await client.close()

    entries = _read_ledger(tmp_path)
    assert len(entries) == 2
    assert all(e["flush_reason"] == "client_close" for e in entries)
    by_model = {e["model"]: e for e in entries}
    assert by_model["claude-sonnet-4-5-20241022"]["total_calls"] == 1
    assert by_model["claude-opus-4-5-20250521"]["total_calls"] == 1


async def test_mixed_complete_batch_complete_workflow(tmp_path, env_path, capsys):
    """complete() before a batch is flushed at batch_end (the tracker
    doesn't distinguish complete from batch internally). complete() after
    the batch accumulates fresh totals and flushes at client_close."""
    cfg = _multi_pool_config(tmp_path)
    client = _new_client(tmp_path, env_path, config_path=cfg)
    try:
        await client.complete(
            messages=[{"role": "user", "content": "pre"}],
            model="claude-sonnet-4-5-20241022",
        )
        await client.batch([
            {"model": "claude-sonnet-4-5-20241022",
             "messages": [{"role": "user", "content": "b1"}]},
            {"model": "gemini-2.5-flash",
             "messages": [{"role": "user", "content": "b2"}]},
        ])
        await client.complete(
            messages=[{"role": "user", "content": "post"}],
            model="claude-sonnet-4-5-20241022",
        )
    finally:
        await client.close()
    capsys.readouterr()

    entries = _read_ledger(tmp_path)
    batch_end = [e for e in entries if e["flush_reason"] == "batch_end"]
    client_close = [e for e in entries if e["flush_reason"] == "client_close"]

    # batch_end: claude-sonnet (pre + b1 = 2 calls) + gemini (b2 = 1 call).
    by_batch = {e["model"]: e for e in batch_end}
    assert by_batch["claude-sonnet-4-5-20241022"]["total_calls"] == 2
    assert by_batch["gemini-2.5-flash"]["total_calls"] == 1

    # client_close: only the post-batch complete() (claude-sonnet, 1 call).
    assert len(client_close) == 1
    assert client_close[0]["model"] == "claude-sonnet-4-5-20241022"
    assert client_close[0]["total_calls"] == 1


async def test_zero_call_client_lifetime_writes_nothing(tmp_path, env_path):
    cfg = _multi_pool_config(tmp_path)
    client = _new_client(tmp_path, env_path, config_path=cfg)
    await client.close()
    assert _read_ledger(tmp_path) == []


async def test_failed_call_counted_without_token_contribution(tmp_path, env_path):
    """A failed call (no usage data) increments failed_calls and total_calls
    but contributes zero tokens to the ledger entry."""

    class FailingTransport(BaseTransport):
        async def send(self, **kwargs):
            return {}, 500

        async def close(self):
            pass

    cfg = _multi_pool_config(tmp_path)
    client = _new_client(tmp_path, env_path, config_path=cfg, transport=FailingTransport())
    try:
        await client.complete(
            messages=[{"role": "user", "content": "x"}],
            model="claude-sonnet-4-5-20241022",
        )
    finally:
        await client.close()

    entries = _read_ledger(tmp_path)
    assert len(entries) == 1
    e = entries[0]
    assert e["total_calls"] == 1
    assert e["failed_calls"] == 1
    assert e["successful_calls"] == 0
    assert e["total_tokens_in"] == 0
    assert e["total_tokens_out"] == 0
    assert e["estimated_cost"] == 0.0
