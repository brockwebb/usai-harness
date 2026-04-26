"""Transport abstraction for LLM API calls.

The transport layer is the seam where httpx and litellm diverge. Everything
above this layer (client, worker pool, rate limiter, etc.) is transport-agnostic.

- BaseTransport: ABC contract for any transport
- HttpxTransport: default, zero LLM framework dependencies
- LiteLLMTransport: stub for future multi-provider support
- get_transport(backend): factory

Error body snippet capture (Task 10): on non-2xx responses, the transport
truncates the response body to a configurable character limit and passes the
truncated text through `redact_secrets()` before attaching it to the returned
body dict under `error_body`. This was originally dropped under Task 04's
conservative security defaults; the Gemini smoke test (Task 08) validated
that boundary-enforced redaction in `redaction.py` correctly scrubs Bearer
headers and provider-shaped key strings, so logging a redacted snippet now
provides high diagnostic value with no security regression. Future
contributors: do not "fix" this by removing the snippet capture; it is the
load-bearing diagnostic for endpoint-side rejections such as Gemini's HTTP
400 on invalid keys, where the only useful information is in the body.
"""

import logging
import sys
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from usai_harness.redaction import redact_secrets


class BaseTransport(ABC):
    """Abstract transport layer for LLM API calls."""

    @abstractmethod
    async def send(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        **kwargs,
    ) -> tuple[dict, int]:
        """Send a completion request. Return (response_body, status_code)."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources (connection pools, etc.)."""
        ...


_TEXTUAL_CONTENT_TYPE_PREFIXES: tuple[str, ...] = (
    "application/json",
    "application/problem+json",
    "text/",
)


def _is_textual_content_type(value: str) -> bool:
    if not value:
        # Absent Content-Type: be permissive; many endpoints return JSON
        # without setting the header on errors.
        return True
    return any(
        value.lower().startswith(prefix)
        for prefix in _TEXTUAL_CONTENT_TYPE_PREFIXES
    )


class HttpxTransport(BaseTransport):
    """Direct HTTP transport using httpx. No external LLM framework dependency."""

    def __init__(
        self,
        timeout: float = 120.0,
        error_body_snippet_max_chars: int = 200,
        **client_kwargs,
    ):
        client_kwargs.setdefault("timeout", timeout)
        self._verify_disabled = client_kwargs.get("verify", True) is False
        self._client = httpx.AsyncClient(**client_kwargs)
        self._log = logging.getLogger("usai_harness.transport.httpx")
        self._error_body_snippet_max_chars = int(error_body_snippet_max_chars)
        if self._verify_disabled:
            self._log.warning(
                "TLS verification is DISABLED for this transport. Every "
                "call will emit a warning. Re-enable verify=True for "
                "production use."
            )

    async def send(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        **kwargs,
    ) -> tuple[dict, int]:
        msgs = list(messages)
        if system_prompt and not (msgs and msgs[0].get("role") == "system"):
            msgs = [{"role": "system", "content": system_prompt}] + msgs

        payload = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        payload.update(kwargs)

        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        if self._verify_disabled:
            print(
                f"WARNING: TLS verification disabled. Call to {url} is not "
                f"TLS-verified. (SEC-003)",
                file=sys.stderr,
            )

        response = await self._client.post(url, json=payload, headers=headers)
        if 200 <= response.status_code < 300:
            return response.json(), response.status_code

        snippet = self._capture_error_body_snippet(response)
        body: dict = {}
        if snippet is not None:
            body["error_body"] = snippet
        return body, response.status_code

    def _capture_error_body_snippet(self, response: "httpx.Response") -> Optional[str]:
        """Return up to N redacted chars of the error body, or None if skipped."""
        content_type = response.headers.get("content-type", "")
        if not _is_textual_content_type(content_type):
            return None
        try:
            text = response.text
        except Exception:
            return None
        if not text:
            return None
        truncated = text[: self._error_body_snippet_max_chars]
        try:
            return redact_secrets(truncated)
        except Exception:
            return None

    async def close(self) -> None:
        await self._client.aclose()


class LiteLLMTransport(BaseTransport):
    """Transport using LiteLLM for multi-provider support.

    NOT IMPLEMENTED. This is plumbing for future LiteLLM integration.
    Install with: pip install -e ".[litellm]"

    When implemented, this transport will:
      - Use litellm.acompletion() for provider-agnostic dispatch
      - Support Azure OpenAI, AWS Bedrock, and any other LiteLLM-supported provider
      - Normalize responses to OpenAI format (LiteLLM does this natively)
    """

    def __init__(self):
        try:
            import litellm  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "LiteLLM transport requires litellm. "
                "Install with: pip install -e '.[litellm]'"
            ) from e
        raise NotImplementedError(
            "LiteLLM transport is planned but not yet implemented. "
            "Use the default httpx transport for now."
        )

    async def send(self, *args, **kwargs):
        raise NotImplementedError

    async def close(self) -> None:
        pass


def get_transport(backend: str = "httpx", **kwargs) -> BaseTransport:
    """Return a transport instance for the named backend.

    Available: "httpx" (default), "litellm" (stub — raises).
    """
    if backend == "httpx":
        return HttpxTransport(**kwargs)
    if backend == "litellm":
        return LiteLLMTransport(**kwargs)
    raise ValueError(
        f"Unknown transport backend: {backend!r}. Available: httpx, litellm"
    )
