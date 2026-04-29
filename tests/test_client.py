"""Tests for USAiClient integration layer."""

import json
import textwrap
from pathlib import Path

import pytest

from usai_harness.client import USAiClient
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
        "model": "claude-sonnet-4-5-20241022",
    }


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path_factory):
    """Prevent host USAi env vars and user-level .env from leaking into tests."""
    for var in ("USAI_API_KEY", "USAI_BASE_URL", "OPENROUTER_API_KEY",
                "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(var, raising=False)
    # Point user_config_env_path at an empty tmp dir so the host user-level
    # .env is not consulted.
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
        assert client.config.default_model.name == "claude-sonnet-4-5-20241022"
        assert (tmp_path / "logs").exists()
    finally:
        await client.close()


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
        model: claude-sonnet-4-5-20241022
        temperature: 0.5
        max_tokens: 1024
    """).lstrip())

    mock = MockTransport()
    client = _client(tmp_path, env_path, transport=mock, config_path=cfg)
    try:
        await client.complete(messages=[{"role": "user", "content": "hi"}])
    finally:
        await client.close()

    assert mock.calls[0]["model"] == "claude-sonnet-4-5-20241022"
    assert mock.calls[0]["temperature"] == 0.5
    assert mock.calls[0]["max_tokens"] == 1024


async def test_client_defaults_without_config(tmp_path, env_path):
    client = _client(tmp_path, env_path)
    try:
        assert client.config.default_model.name == "claude-sonnet-4-5-20241022"
        # base_url now comes from the providers block in models.yaml.
        assert client._base_url.startswith("https://")
        assert client._api_key == "test-key-AAAAAAAA"
    finally:
        await client.close()


async def test_client_init_raises_on_unconfigured_provider(tmp_path):
    """With no project .env, no user .env, and no env var set, init must fail fast."""
    from usai_harness.key_manager import CredentialNotFoundError

    missing_env = tmp_path / "does-not-exist.env"

    with pytest.raises(CredentialNotFoundError):
        USAiClient(
            project="test-proj",
            env_path=missing_env,
            transport=MockTransport(),
            log_dir=tmp_path / "logs",
            ledger_path=tmp_path / "ledger.jsonl",
        )


async def test_model_echo_matching(tmp_path, env_path):
    """Response model matches requested: both fields logged with same value."""
    client = _client(tmp_path, env_path)
    try:
        await client.complete(messages=[{"role": "user", "content": "hi"}])
        log_path = client._logger.get_log_path()
    finally:
        await client.close()

    entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    assert len(entries) == 1
    assert entries[0]["model_requested"] == "claude-sonnet-4-5-20241022"
    assert entries[0]["model_returned"] == "claude-sonnet-4-5-20241022"


async def test_model_echo_mismatch_logged(tmp_path, env_path):
    """Transport returns a different model id: both fields are logged distinctly."""
    response_body = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "model": "some-other-model",
    }
    mock = MockTransport(responses=[(response_body, 200)])
    client = _client(tmp_path, env_path, transport=mock)
    try:
        await client.complete(messages=[{"role": "user", "content": "hi"}])
        log_path = client._logger.get_log_path()
    finally:
        await client.close()

    entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    assert entries[0]["model_requested"] == "claude-sonnet-4-5-20241022"
    assert entries[0]["model_returned"] == "some-other-model"


async def test_content_logging_off_by_default(tmp_path, env_path, capsys):
    client = _client(tmp_path, env_path)
    try:
        tasks = [{"messages": [{"role": "user", "content": "secret"}]}]
        await client.batch(tasks, job_name="b1")
        log_path = client._logger.get_log_path()
    finally:
        await client.close()
    capsys.readouterr()

    entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    assert all("prompt" not in e for e in entries)
    assert all("response" not in e for e in entries)


async def test_content_logging_opt_in_writes_content(tmp_path, env_path, capsys):
    client = _client(tmp_path, env_path)
    try:
        tasks = [{"messages": [{"role": "user", "content": "hello world"}]}]
        await client.batch(tasks, job_name="b2", log_content=True)
        log_path = client._logger.get_log_path()
    finally:
        await client.close()
    capsys.readouterr()

    entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    assert entries[0]["prompt"] == [{"role": "user", "content": "hello world"}]
    assert "response" in entries[0]


async def test_content_logging_warning_on_stderr(tmp_path, env_path, capsys):
    client = _client(tmp_path, env_path)
    try:
        tasks = [
            {"messages": [{"role": "user", "content": f"q{i}"}]}
            for i in range(3)
        ]
        await client.batch(tasks, job_name="b3", log_content=True)
    finally:
        await client.close()
    captured = capsys.readouterr()
    # Warning appears exactly once per batch call.
    assert captured.err.count("content logging is ENABLED") == 1


async def test_complete_exception_is_redacted(tmp_path, env_path):
    """A raised exception containing a Bearer token is redacted before logging."""
    class LeakyTransport(MockTransport):
        async def send(self, **kw):
            raise RuntimeError("Authorization: Bearer abc123def456ghi789 failed")

    client = _client(tmp_path, env_path, transport=LeakyTransport())
    try:
        with pytest.raises(RuntimeError):
            await client.complete(messages=[{"role": "user", "content": "hi"}])
        log_path = client._logger.get_log_path()
    finally:
        await client.close()

    entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    assert "abc123def456ghi789" not in entries[0]["error"]
    assert "REDACTED" in entries[0]["error"]


# ---------- Pool validation (ADR-012, FR-050) -----------------------------


def _multi_pool_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "project.yaml"
    cfg.write_text(textwrap.dedent("""
        models:
          - name: claude-sonnet-4-5-20241022
          - name: claude-opus-4-5-20250521
          - name: claude-3-5-haiku-20241022
        default_model: claude-sonnet-4-5-20241022
    """).lstrip())
    return cfg


async def test_client_complete_with_pool_member_model(tmp_path, env_path):
    cfg = _multi_pool_config(tmp_path)
    mock = MockTransport()
    client = _client(tmp_path, env_path, transport=mock, config_path=cfg)
    try:
        await client.complete(
            messages=[{"role": "user", "content": "hi"}],
            model="claude-opus-4-5-20250521",
        )
    finally:
        await client.close()
    assert mock.calls[0]["model"] == "claude-opus-4-5-20250521"


async def test_client_complete_with_non_pool_model(tmp_path, env_path):
    cfg = _multi_pool_config(tmp_path)
    client = _client(tmp_path, env_path, config_path=cfg)
    try:
        with pytest.raises(ValueError, match="not in this project's pool"):
            await client.complete(
                messages=[{"role": "user", "content": "hi"}],
                model="gemini-2.5-flash",
            )
    finally:
        await client.close()


async def test_client_batch_per_task_model_override(tmp_path, env_path, capsys):
    cfg = _multi_pool_config(tmp_path)
    mock = MockTransport()
    client = _client(tmp_path, env_path, transport=mock, config_path=cfg)
    try:
        tasks = [
            {"messages": [{"role": "user", "content": "a"}],
             "model": "claude-sonnet-4-5-20241022", "task_id": "t1"},
            {"messages": [{"role": "user", "content": "b"}],
             "model": "claude-opus-4-5-20250521", "task_id": "t2"},
        ]
        await client.batch(tasks, job_name="pool-test")
    finally:
        await client.close()
    capsys.readouterr()
    used = sorted(c["model"] for c in mock.calls)
    assert used == ["claude-opus-4-5-20250521", "claude-sonnet-4-5-20241022"]


async def test_client_batch_per_task_invalid_model(tmp_path, env_path):
    cfg = _multi_pool_config(tmp_path)
    client = _client(tmp_path, env_path, config_path=cfg)
    try:
        tasks = [
            {"messages": [{"role": "user", "content": "a"}],
             "model": "gemini-2.5-flash", "task_id": "rogue"},
        ]
        with pytest.raises(ValueError, match="not in the project's pool"):
            await client.batch(tasks, job_name="bad-pool")
    finally:
        await client.close()


async def test_complete_forwards_temperature_to_transport(tmp_path, env_path):
    """Per the ADR-012 amendment (2026-04-29): per-call temperature is
    forwarded to the transport unchanged, regardless of any catalog range."""
    cfg = _multi_pool_config(tmp_path)
    mock = MockTransport()
    client = _client(tmp_path, env_path, transport=mock, config_path=cfg)
    try:
        await client.complete(
            messages=[{"role": "user", "content": "hi"}],
            model="claude-sonnet-4-5-20241022",
            temperature=5.0,
        )
    finally:
        await client.close()
    assert mock.calls[0]["temperature"] == 5.0
