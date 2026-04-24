"""Transport abstraction for LLM API calls.

The transport layer is the seam where httpx and litellm diverge. Everything
above this layer (client, worker pool, rate limiter, etc.) is transport-agnostic.

- BaseTransport: ABC contract for any transport
- HttpxTransport: default, zero LLM framework dependencies
- LiteLLMTransport: stub for future multi-provider support
- get_transport(backend): factory
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


class HttpxTransport(BaseTransport):
    """Direct HTTP transport using httpx. No external LLM framework dependency."""

    def __init__(self, timeout: float = 120.0, **client_kwargs):
        client_kwargs.setdefault("timeout", timeout)
        self._verify_disabled = client_kwargs.get("verify", True) is False
        self._client = httpx.AsyncClient(**client_kwargs)
        self._log = logging.getLogger("usai_harness.transport.httpx")
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
        return {"error": redact_secrets(response.text)}, response.status_code

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
