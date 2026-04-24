"""Tests for transport abstraction (httpx + litellm factory)."""

import httpx
import pytest

from usai_harness.transport import (
    BaseTransport,
    HttpxTransport,
    LiteLLMTransport,
    get_transport,
)

pytestmark = pytest.mark.asyncio


def _mock_httpx(handler):
    return httpx.MockTransport(handler)


async def test_httpx_transport_sends_request():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "model": "m",
        })

    t = HttpxTransport(transport=_mock_httpx(handler))
    try:
        await t.send(
            base_url="https://example.com/v1",
            api_key="K",
            model="m",
            messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await t.close()

    assert captured["url"] == "https://example.com/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer K"
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["body"]["model"] == "m"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]


async def test_httpx_transport_returns_response():
    body = {
        "choices": [{"message": {"role": "assistant", "content": "hi"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "m",
    }

    def handler(request):
        return httpx.Response(200, json=body)

    t = HttpxTransport(transport=_mock_httpx(handler))
    try:
        resp, status = await t.send(
            base_url="https://example.com/v1", api_key="K",
            model="m", messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await t.close()

    assert status == 200
    assert resp == body


async def test_httpx_transport_returns_error_status():
    def handler(request):
        return httpx.Response(429, text="rate limited")

    t = HttpxTransport(transport=_mock_httpx(handler))
    try:
        resp, status = await t.send(
            base_url="https://example.com/v1", api_key="K",
            model="m", messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await t.close()

    assert status == 429
    assert "rate limited" in resp["error"]


async def test_httpx_transport_connection_error_raises():
    def handler(request):
        raise httpx.ConnectError("boom")

    t = HttpxTransport(transport=_mock_httpx(handler))
    try:
        with pytest.raises(httpx.ConnectError):
            await t.send(
                base_url="https://example.com/v1", api_key="K",
                model="m", messages=[{"role": "user", "content": "hi"}],
            )
    finally:
        await t.close()


async def test_httpx_transport_system_prompt_prepended():
    captured = {}

    def handler(request):
        import json
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [], "usage": {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        }, "model": "m"})

    t = HttpxTransport(transport=_mock_httpx(handler))
    try:
        await t.send(
            base_url="https://example.com/v1", api_key="K",
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            system_prompt="Be helpful",
        )
    finally:
        await t.close()

    msgs = captured["body"]["messages"]
    assert msgs[0] == {"role": "system", "content": "Be helpful"}
    assert msgs[1]["role"] == "user"


async def test_httpx_transport_system_prompt_not_duplicated():
    captured = {}

    def handler(request):
        import json
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [], "usage": {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        }, "model": "m"})

    t = HttpxTransport(transport=_mock_httpx(handler))
    try:
        await t.send(
            base_url="https://example.com/v1", api_key="K",
            model="m",
            messages=[
                {"role": "system", "content": "Existing"},
                {"role": "user", "content": "hi"},
            ],
            system_prompt="Ignored because existing system message present",
        )
    finally:
        await t.close()

    msgs = captured["body"]["messages"]
    system_msgs = [m for m in msgs if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0]["content"] == "Existing"


async def test_httpx_transport_kwargs_passed_through():
    captured = {}

    def handler(request):
        import json
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [], "usage": {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        }, "model": "m"})

    t = HttpxTransport(transport=_mock_httpx(handler))
    try:
        await t.send(
            base_url="https://example.com/v1", api_key="K",
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            top_p=0.9,
        )
    finally:
        await t.close()

    assert captured["body"]["top_p"] == 0.9


async def test_get_transport_httpx():
    t = get_transport("httpx")
    try:
        assert isinstance(t, HttpxTransport)
        assert isinstance(t, BaseTransport)
    finally:
        await t.close()


async def test_get_transport_litellm_not_implemented():
    with pytest.raises((NotImplementedError, ImportError)):
        get_transport("litellm")


async def test_get_transport_unknown_raises():
    with pytest.raises(ValueError, match="Unknown transport backend"):
        get_transport("magic")


async def test_tls_verify_disabled_warns_per_call(capsys):
    def handler(request):
        return httpx.Response(200, json={
            "choices": [], "usage": {
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            }, "model": "m",
        })

    t = HttpxTransport(transport=_mock_httpx(handler), verify=False)
    try:
        await t.send(
            base_url="https://example.com/v1", api_key="K",
            model="m", messages=[{"role": "user", "content": "hi"}],
        )
        await t.send(
            base_url="https://example.com/v1", api_key="K",
            model="m", messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await t.close()

    err = capsys.readouterr().err
    # The warning must appear for both calls (ADR-007 intentionally noisy).
    assert err.count("TLS verification disabled") == 2


async def test_tls_verify_default_silent(capsys):
    def handler(request):
        return httpx.Response(200, json={
            "choices": [], "usage": {
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            }, "model": "m",
        })

    t = HttpxTransport(transport=_mock_httpx(handler))
    try:
        await t.send(
            base_url="https://example.com/v1", api_key="K",
            model="m", messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await t.close()

    err = capsys.readouterr().err
    assert "TLS verification disabled" not in err


async def test_url_composition_preserves_path_prefix():
    """Transport must compose base_url + '/chat/completions' without stripping the prefix."""
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={
            "choices": [], "usage": {
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            }, "model": "m",
        })

    # No trailing slash
    t = HttpxTransport(transport=_mock_httpx(handler))
    try:
        await t.send(
            base_url="https://example.com/api/v1",
            api_key="K", model="m",
            messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await t.close()
    assert captured["url"] == "https://example.com/api/v1/chat/completions"

    # With trailing slash: still single slash
    captured.clear()
    t = HttpxTransport(transport=_mock_httpx(handler))
    try:
        await t.send(
            base_url="https://example.com/api/v1/",
            api_key="K", model="m",
            messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await t.close()
    assert captured["url"] == "https://example.com/api/v1/chat/completions"


async def test_error_body_is_redacted():
    def handler(request):
        return httpx.Response(
            401, text="Authorization: Bearer abc123def456ghi789 invalid",
        )

    t = HttpxTransport(transport=_mock_httpx(handler))
    try:
        body, status = await t.send(
            base_url="https://example.com/v1", api_key="K",
            model="m", messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await t.close()

    assert status == 401
    assert "abc123def456ghi789" not in body["error"]
    assert "REDACTED" in body["error"]
