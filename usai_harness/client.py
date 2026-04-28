"""USAiClient: Main entry point that wires all components together.

Responsibilities:
    - Initialize key manager, rate limiter, worker pool, config, logger, cost tracker
    - Expose async `complete()` method for making LLM calls
    - Expose async `batch()` method for processing lists of tasks
    - Handle graceful shutdown and final report generation

Inputs:
    - project: str — project name for logging and cost attribution
    - config_path: Optional[str] — path to project-specific config YAML
    - env_path: Optional[str] — path to .env file (default: discovered)
    - workers: int — number of async workers (default: 3)
    - transport_backend: str — "httpx" (default) or "litellm"
    - transport: Optional[BaseTransport] — inject transport directly (primarily for tests)
    - log_dir: Optional[path] — directory for per-run log files
    - ledger_path: Optional[path] — path to append-only cost ledger

Outputs:
    - complete() returns response dict (OpenAI-format)
    - batch() returns list[TaskResult] and prints a post-run report
"""

import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from usai_harness.config import ConfigLoader, ProjectConfig
from usai_harness.cost import CostTracker
from usai_harness.key_manager import CredentialProvider, make_credential_provider
from usai_harness.logger import CallLogger
from usai_harness.rate_limiter import RateLimiter
from usai_harness.redaction import redact_secrets
from usai_harness.report import format_report, generate_report
from usai_harness.transport import BaseTransport, get_transport
from usai_harness.worker_pool import Task, TaskResult, WorkerPool

log = logging.getLogger("usai_harness.client")

MAX_COMPLETE_RETRIES = 3


class USAiClient:
    """Main entry point for USAi Harness. Wires all components together."""

    def __init__(
        self,
        project: str,
        config_path: Optional[Path] = None,
        env_path: Optional[Path] = None,
        workers: Optional[int] = None,
        transport_backend: str = "httpx",
        transport_kwargs: Optional[dict] = None,
        transport: Optional[BaseTransport] = None,
        log_dir: Optional[Path] = None,
        ledger_path: Optional[Path] = None,
        provider: Optional[str] = None,
        credentials: Optional[CredentialProvider] = None,
    ):
        self.project = project

        # 1. Config (ADR-011: when config_path is None, discover usai_harness.yaml in CWD)
        self._loader = ConfigLoader()
        resolved_config_path = self._resolve_project_config_path(config_path)
        if resolved_config_path is not None:
            self.config: ProjectConfig = self._loader.load_project_config(
                resolved_config_path,
            )
        else:
            default_model = self._loader.get_default_model()
            self.config = ProjectConfig(
                models=[default_model],
                default_model=default_model,
                provider=default_model.provider,
                max_tokens=default_model.max_output_tokens,
            )

        self._workers = workers if workers is not None else self.config.workers

        # 2. Credential provider (ADR-003, ADR-002).
        provider_name = (
            provider if provider is not None else self.config.provider
        )
        self._provider_config = self._loader.get_provider(provider_name)
        if (
            env_path is not None
            and self.config.credentials_backend == "dotenv"
        ):
            self.config.credentials_kwargs.setdefault("project_env", env_path)
        if credentials is not None:
            self._credentials: CredentialProvider = credentials
        else:
            if self.config.credentials_backend == "azure_keyvault":
                providers_map = self._loader.providers_to_secret_map()
            else:
                providers_map = self._loader.providers_to_env_map()
            self._credentials = make_credential_provider(
                backend=self.config.credentials_backend,
                providers=providers_map,
                **self.config.credentials_kwargs,
            )
        # Resolve once at init to fail fast on missing credentials.
        self._api_key = self._credentials.get_key(provider_name)
        self._base_url = self._provider_config.base_url

        # 3. Transport (accept injected instance for tests)
        if transport is not None:
            self._transport = transport
        else:
            tk = dict(transport_kwargs or {})
            tk.setdefault(
                "error_body_snippet_max_chars",
                self._loader.error_body_snippet_max_chars,
            )
            self._transport = get_transport(transport_backend, **tk)

        # 4. Rate Limiter (shared across all workers)
        self._rate_limiter = RateLimiter()

        # 5. Logger
        log_dir = log_dir if log_dir is not None else Path("logs")
        self._logger = CallLogger(log_dir=log_dir, project=project)

        # 6. Cost Tracker
        self._cost_tracker = CostTracker(
            model_name=self.config.default_model.name,
            cost_per_1k_input=self.config.default_model.cost_per_1k_input_tokens,
            cost_per_1k_output=self.config.default_model.cost_per_1k_output_tokens,
            ledger_path=ledger_path if ledger_path is not None else Path("cost_ledger.jsonl"),
        )

        self._complete_counter = 0
        self._closed = False

        log.info(
            "USAi Harness initialized: project=%s model=%s workers=%d transport=%s",
            project, self.config.default_model.name, self._workers, transport_backend,
        )

    # ---- single-call API --------------------------------------------------

    async def complete(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        task_id: Optional[str] = None,
        log_content: bool = False,
        **kwargs,
    ) -> dict:
        """Make one completion call with rate limiting, logging, and cost tracking.

        Retries up to MAX_COMPLETE_RETRIES on HTTP 429 with exponential backoff.
        Non-retryable errors and exhausted retries return the error body (still logged).
        """
        if model is not None and not self.config.has_model(model):
            raise ValueError(
                f"complete(): model {model!r} is not in this project's pool. "
                f"Pool: {[m.name for m in self.config.models]}."
            )

        model_name = model if model is not None else self.config.default_model.name
        chosen_model = self.config.get_pool_model(model_name)

        temp = temperature if temperature is not None else self.config.temperature
        if temperature is not None:
            self._validate_temperature_for_model(temp, chosen_model, "complete()")
        mt = max_tokens if max_tokens is not None else self.config.max_tokens
        if max_tokens is not None:
            self._validate_max_tokens_for_model(mt, chosen_model, "complete()")
        sp = system_prompt if system_prompt is not None else self.config.system_prompt

        if task_id is None:
            task_id = f"{self.project}_complete_{self._complete_counter:04d}"
            self._complete_counter += 1

        body: dict = {}
        status: int = 0
        latency_ms: float = 0.0

        for attempt in range(MAX_COMPLETE_RETRIES):
            await self._rate_limiter.acquire()
            start = time.monotonic()
            try:
                body, status = await self._transport.send(
                    base_url=self._base_url,
                    api_key=self._api_key,
                    model=model_name,
                    messages=messages,
                    temperature=temp,
                    max_tokens=mt,
                    system_prompt=sp,
                    **kwargs,
                )
            except Exception as e:
                latency_ms = (time.monotonic() - start) * 1000.0
                redacted = redact_secrets(str(e))
                log.error("complete() transport error on task %s: %s", task_id, redacted)
                self._record_outcome(
                    task_id=task_id, model=model_name, status_code=0,
                    latency_ms=latency_ms, response=None, error=redacted,
                    success=False, messages=messages, log_content=log_content,
                )
                raise

            latency_ms = (time.monotonic() - start) * 1000.0

            if 200 <= status < 300:
                self._rate_limiter.record_success()
                self._record_outcome(
                    task_id=task_id, model=model_name, status_code=status,
                    latency_ms=latency_ms, response=body, error=None,
                    success=True, messages=messages, log_content=log_content,
                )
                return body

            if status == 429:
                self._rate_limiter.record_429()
                if attempt < MAX_COMPLETE_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue

            break

        # Retries exhausted, or non-retryable status.
        self._record_outcome(
            task_id=task_id, model=model_name, status_code=status,
            latency_ms=latency_ms, response=body,
            error=f"HTTP {status}",
            success=False, messages=messages, log_content=log_content,
        )
        return body

    # ---- batch API --------------------------------------------------------

    async def batch(
        self,
        tasks: list[dict],
        job_name: Optional[str] = None,
        log_content: bool = False,
    ) -> list[TaskResult]:
        """Process a list of task dicts through the worker pool.

        Each task dict must contain `messages`. Optional: `model`, `temperature`,
        `max_tokens`, `system_prompt`, `task_id`, `metadata`, plus any provider
        kwargs to forward.

        If log_content=True, full prompts and responses are written to the call
        log (subject to secret redaction). A one-time stderr warning is emitted.
        """
        if not tasks:
            return []

        if log_content:
            print(
                "WARNING: content logging is ENABLED. Prompts and responses "
                "will be written to the call log. This may contain PII. "
                "(FR-028, ADR-007)",
                file=sys.stderr,
            )

        job_name = job_name or self.project
        task_objs = self._build_tasks(tasks, job_name)

        pool = WorkerPool(
            rate_limiter=self._rate_limiter,
            request_fn=self._make_request,
            n_workers=self._workers,
        )

        start = time.monotonic()
        results = await pool.run_batch(task_objs)
        duration = time.monotonic() - start

        for r in results:
            self._record_result(r, log_content=log_content)

        self._cost_tracker.write_summary(
            job_id=self._logger.job_id,
            job_name=job_name,
            project=self.project,
            model=self.config.default_model.name,
            duration_seconds=duration,
        )

        report = generate_report(self._logger.get_log_path())
        if report:
            print(format_report(report))

        return results

    # ---- internals --------------------------------------------------------

    def _build_tasks(self, tasks: list[dict], job_name: str) -> list[Task]:
        reserved = {"messages", "model", "temperature", "max_tokens",
                    "system_prompt", "task_id", "metadata"}
        out: list[Task] = []
        for i, t in enumerate(tasks):
            if "messages" not in t:
                raise ValueError(
                    f"Task at index {i} is missing required 'messages' field."
                )

            if "model" in t:
                if not self.config.has_model(t["model"]):
                    raise ValueError(
                        f"Task at index {i} (task_id={t.get('task_id')!r}) "
                        f"selects model {t['model']!r} which is not in the "
                        f"project's pool. "
                        f"Pool: {[m.name for m in self.config.models]}."
                    )
                chosen_model = self.config.get_pool_model(t["model"])
            else:
                chosen_model = self.config.default_model

            if "temperature" in t:
                self._validate_temperature_for_model(
                    float(t["temperature"]), chosen_model,
                    f"task index {i}",
                )
            if "max_tokens" in t:
                self._validate_max_tokens_for_model(
                    int(t["max_tokens"]), chosen_model,
                    f"task index {i}",
                )

            payload = {
                "messages": t["messages"],
                "model": t.get("model", self.config.default_model.name),
                "temperature": t.get("temperature", self.config.temperature),
                "max_tokens": t.get("max_tokens", self.config.max_tokens),
                "system_prompt": t.get("system_prompt", self.config.system_prompt),
            }
            for k, v in t.items():
                if k not in reserved:
                    payload[k] = v
            task_id = t.get("task_id") or f"{job_name}_{i:04d}"
            out.append(Task(
                task_id=task_id,
                payload=payload,
                metadata=t.get("metadata", {}),
            ))
        return out

    @staticmethod
    def _validate_temperature_for_model(
        value: float, model, context: str,
    ) -> None:
        if not model.supports_temperature:
            raise ValueError(
                f"{context}: model '{model.name}' does not support "
                f"temperature; got temperature={value}."
            )
        low, high = model.temperature_range
        if not (low <= value <= high):
            raise ValueError(
                f"{context}: temperature={value} out of range for model "
                f"'{model.name}'. Valid range: [{low}, {high}]."
            )

    @staticmethod
    def _validate_max_tokens_for_model(
        value: int, model, context: str,
    ) -> None:
        if value <= 0:
            raise ValueError(
                f"{context}: max_tokens must be > 0, got {value}."
            )
        if value > model.max_output_tokens:
            raise ValueError(
                f"{context}: max_tokens={value} exceeds model "
                f"'{model.name}' limit of {model.max_output_tokens}."
            )

    async def _make_request(self, payload: dict) -> tuple[dict, int]:
        """request_fn handed to the worker pool."""
        extra = {
            k: v for k, v in payload.items()
            if k not in {"messages", "model", "temperature",
                         "max_tokens", "system_prompt"}
        }
        return await self._transport.send(
            base_url=self._base_url,
            api_key=self._api_key,
            model=payload["model"],
            messages=payload["messages"],
            temperature=payload["temperature"],
            max_tokens=payload["max_tokens"],
            system_prompt=payload.get("system_prompt"),
            **extra,
        )

    def _record_outcome(
        self,
        *,
        task_id: str,
        model: str,
        status_code: int,
        latency_ms: float,
        response: Optional[dict],
        error: Optional[str],
        success: bool,
        messages: Optional[list[dict]] = None,
        log_content: bool = False,
    ) -> None:
        usage = {}
        model_returned = None
        error_body = None
        if isinstance(response, dict):
            u = response.get("usage")
            if isinstance(u, dict):
                usage = u
            model_returned = response.get("model")
            if not success:
                snippet = response.get("error_body")
                if isinstance(snippet, str) and snippet:
                    error_body = snippet

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "model_requested": model,
            "model_returned": model_returned,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "error": error,
            "error_body": error_body,
            "success": success,
        }
        if log_content:
            entry["prompt"] = messages
            entry["response"] = response
        self._logger.log_call(entry)
        self._cost_tracker.record_call(response or {}, success=success)

    def _record_result(
        self,
        result: TaskResult,
        log_content: bool = False,
    ) -> None:
        model = result.payload.get("model", self.config.default_model.name)
        response = result.response if isinstance(result.response, dict) else {}
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        model_returned = response.get("model") if isinstance(response, dict) else None
        error_body = None
        if not result.success:
            snippet = response.get("error_body")
            if isinstance(snippet, str) and snippet:
                error_body = snippet

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": result.task_id,
            "model_requested": model,
            "model_returned": model_returned,
            "status_code": result.status_code if result.status_code is not None else 0,
            "latency_ms": result.latency_ms,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "error": result.error,
            "error_body": error_body,
            "success": result.success,
        }
        if log_content:
            entry["prompt"] = result.payload.get("messages")
            entry["response"] = result.response
        self._logger.log_call(entry)
        self._cost_tracker.record_call(response, success=result.success)

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _resolve_project_config_path(
        config_path: Optional[Path],
    ) -> Optional[Path]:
        """Apply the ADR-011 discovery rule.

        - If `config_path` is supplied, use it (FR-044).
        - Otherwise, look for `usai_harness.yaml` in the current working
          directory (FR-043). When absent, return None and let the caller
          fall back to default ProjectConfig (FR-045).
        """
        if config_path is not None:
            return Path(config_path)
        cwd_default = Path.cwd() / "usai_harness.yaml"
        if cwd_default.exists():
            return cwd_default
        return None

    # ---- lifecycle --------------------------------------------------------

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._transport.close()
        finally:
            self._logger.close()
        log.info("USAi Harness shut down.")

    async def __aenter__(self) -> "USAiClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()
