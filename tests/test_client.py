"""Tests for USAiClient integration layer."""

import hashlib
import json
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from usai_harness.client import USAiClient
from usai_harness.key_manager import KeyExpiredError
from usai_harness.transport import BaseTransport

pytestmark = pytest.mark.asyncio


class MockTransport(BaseTransport):
    """Programmable BaseTransport for client tests."""

    def __init__(self, responses=None, raise_on_call=None):
        self.responses = responses or []
        self._i = 0
        self.calls: list[dict] = []
        self.closed = False
        self.raise_on_call = raise_on_call  # exception to raise on first call

    async def send(self, base_url, api_key, model, messages,
                   temperature=0.0, max_tokens=4096, system_prompt=None, **kwargs):
        self.calls.append({
            "base_url": base_url, "api_key": api_key, "model": model,
            "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "system_prompt": system_prompt,
            **kwargs,
        })
        if self.raise_on_call is not None and self._i == 0:
            self._i += 1
            raise self.raise_on_call
        if self._i < len(self.responses):
            resp = self.responses[self._i]
            self._i += 1
            return resp
        return (_default_response(), 200)

    async def close(self):
        self.closed = True


def _default_response(prompt_tokens=10, completion_tokens=5):
    return {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "model": "llama-4-maverick",
    }


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    monkeypatch.delenv("USAI_API_KEY", raising=False)
    monkeypatch.delenv("USAI_BASE_URL", raising=False)


@pytest.fixture
def env_path(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "USAI_API_KEY=test-key-AAAAAAAA\n"
        "USAI_BASE_URL=https://example.com/v1\n"
    )
    return p


def _client(tmp_path, env_path, *, transport=None, config_path=None, **kwargs):
    return USAiClient(
        project="test-proj",
        env_path=env_path,
        transport=transport if transport is not None else MockTransport(),
        log_dir=tmp_path / "logs",
        ledger_path=tmp_path / "ledger.jsonl",
        config_path=config_path,
        **kwargs,
    )


async def test_client_init_success(tmp_path, env_path):
    client = _client(tmp_path, env_path)
    try:
        assert client.project == "test-proj"
        assert client.config.model.name == "llama-4-maverick"
        assert (tmp_path / "logs").exists()
    finally:
        await client.close()


async def test_client_init_expired_key_fails(tmp_path, env_path):
    api_key = "test-key-AAAAAAAA"
    meta = tmp_path / ".usai_key_meta.json"
    key_hash = hashlib.sha256(api_key[-8:].encode()).hexdigest()
    expired = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    meta.write_text(json.dumps({
        "key_hash": key_hash,
        "issued_at": expired,
        "rotations": [],
    }))

    with pytest.raises(KeyExpiredError):
        USAiClient(
            project="test-proj",
            env_path=env_path,
            transport=MockTransport(),
            log_dir=tmp_path / "logs",
            ledger_path=tmp_path / "ledger.jsonl",
        )


async def test_complete_single_call(tmp_path, env_path):
    mock = MockTransport()
    client = _client(tmp_path, env_path, transport=mock)
    try:
        resp = await client.complete(
            messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await client.close()

    assert len(mock.calls) == 1
    assert "choices" in resp


async def test_complete_logs_call(tmp_path, env_path):
    client = _client(tmp_path, env_path)
    try:
        await client.complete(messages=[{"role": "user", "content": "hi"}])
        log_path = client._logger.get_log_path()
    finally:
        await client.close()

    entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    assert len(entries) == 1
    assert entries[0]["status_code"] == 200
    assert entries[0]["prompt_tokens"] == 10


async def test_complete_tracks_cost(tmp_path, env_path):
    mock = MockTransport(responses=[(_default_response(100, 40), 200)])
    client = _client(tmp_path, env_path, transport=mock)
    try:
        await client.complete(messages=[{"role": "user", "content": "hi"}])
        totals = client._cost_tracker.get_run_totals()
    finally:
        await client.close()

    assert totals["total_input_tokens"] == 100
    assert totals["total_output_tokens"] == 40
    assert totals["successful_calls"] == 1


async def test_batch_processes_all_tasks(tmp_path, env_path, capsys):
    client = _client(tmp_path, env_path)
    try:
        tasks = [
            {"messages": [{"role": "user", "content": f"q{i}"}]}
            for i in range(5)
        ]
        results = await client.batch(tasks, job_name="test-batch")
    finally:
        await client.close()
    capsys.readouterr()  # swallow printed report

    assert len(results) == 5
    assert all(r.success for r in results)


async def test_batch_generates_report(tmp_path, env_path, capsys):
    client = _client(tmp_path, env_path)
    try:
        tasks = [
            {"messages": [{"role": "user", "content": f"q{i}"}]}
            for i in range(3)
        ]
        await client.batch(tasks, job_name="test-batch")
        log_path = client._logger.get_log_path()
    finally:
        await client.close()
    out = capsys.readouterr().out

    entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    assert len(entries) == 3
    assert "Job:" in out or "Calls:" in out


async def test_context_manager(tmp_path, env_path):
    mock = MockTransport()
    async with USAiClient(
        project="test-proj",
        env_path=env_path,
        transport=mock,
        log_dir=tmp_path / "logs",
        ledger_path=tmp_path / "ledger.jsonl",
    ) as client:
        await client.complete(messages=[{"role": "user", "content": "hi"}])
    assert mock.closed is True


async def test_client_uses_project_config(tmp_path, env_path):
    cfg = tmp_path / "project.yaml"
    cfg.write_text(textwrap.dedent("""
        model: llama-4-maverick
        temperature: 0.5
        max_tokens: 1024
    """).lstrip())

    mock = MockTransport()
    client = _client(tmp_path, env_path, transport=mock, config_path=cfg)
    try:
        await client.complete(messages=[{"role": "user", "content": "hi"}])
    finally:
        await client.close()

    assert mock.calls[0]["model"] == "llama-4-maverick"
    assert mock.calls[0]["temperature"] == 0.5
    assert mock.calls[0]["max_tokens"] == 1024


async def test_client_defaults_without_config(tmp_path, env_path):
    client = _client(tmp_path, env_path)
    try:
        assert client.config.model.name == "llama-4-maverick"
    finally:
        await client.close()
