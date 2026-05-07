"""Worker Pool: Async workers pulling tasks from a queue.

Responsibilities:
    - N async workers (configurable, default 3)
    - Each worker: pull task from queue, acquire rate limiter token, fire request
    - Return results via callback or collected list
    - Graceful shutdown: drain queue, wait for in-flight requests

Inputs:
    - n_workers: int — number of concurrent workers (default: 3)
    - rate_limiter: RateLimiter instance
    - request_fn: async callable — the actual HTTP request function

Outputs:
    - submit(task) — add a task to the queue
    - run_batch(tasks) — process all tasks, return results
    - shutdown() — graceful stop
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger("usai_harness.worker_pool")

RequestFn = Callable[[dict], Awaitable[tuple[dict, int]]]


class AuthHaltError(Exception):
    """Raised by WorkerPool when the endpoint returns 401/403.

    Halts the pool within 1 second, preserves results collected so far,
    and surfaces the failing task's status and body so the caller can
    rotate the credential and retry.
    """

    def __init__(self, status_code: int, task_id: str,
                 body: Optional[dict] = None):
        self.status_code = status_code
        self.task_id = task_id
        self.body = body
        super().__init__(
            f"Endpoint returned {status_code} on task {task_id}. "
            f"Pool halted. Rotate the credential and retry."
        )


@dataclass
class Task:
    """A unit of work for the worker pool."""
    task_id: str
    payload: dict
    metadata: dict = field(default_factory=dict)


@dataclass
class BatchResult:
    """Result of a completed task."""
    task_id: str
    payload: dict
    metadata: dict
    response: Optional[dict] = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    latency_ms: float = 0.0
    success: bool = False


class WorkerPool:
    """Async worker pool that pulls tasks from a queue with rate limiting."""

    def __init__(self, rate_limiter, request_fn: RequestFn,
                 n_workers: int = 3, max_retries: int = 3):
        self.rate_limiter = rate_limiter
        self.request_fn = request_fn
        self.n_workers = n_workers
        self.max_retries = max_retries

        self._queue: Optional[asyncio.Queue] = None
        self._workers: list[asyncio.Task] = []
        self._results: list[BatchResult] = []
        self._halt_event: Optional[asyncio.Event] = None
        self._halt_reason: Optional[AuthHaltError] = None
        self._tracker = None

    @property
    def results(self) -> list[BatchResult]:
        """Sorted snapshot of collected results. Safe to read after a halt."""
        return sorted(self._results, key=lambda r: r.task_id)

    async def run_batch(
        self,
        tasks: list[Task],
        tracker=None,
    ) -> list[BatchResult]:
        """Process all tasks across n_workers and return deterministic results.

        Raises AuthHaltError (after gathering in-flight workers) if the endpoint
        returns 401 or 403. Partial results are still available via `self.results`.

        Per ADR-017, an optional `tracker` (a `_ProgressTracker` instance)
        receives one `emit` call per task that reaches a terminal state in
        completion order. Auth-halted tasks (401/403) and tasks deferred
        by an auth halt do not emit; they will be retried by the caller
        after credential recovery and emit then. The same tracker instance
        is reused across recovery retries so the per-batch counters span
        retries.
        """
        self._queue = asyncio.Queue()
        self._results = []
        self._halt_event = asyncio.Event()
        self._halt_reason = None
        self._tracker = tracker

        for task in tasks:
            await self._queue.put(task)
        # One sentinel per worker so each one exits cleanly.
        for _ in range(self.n_workers):
            await self._queue.put(None)

        self._workers = [
            asyncio.create_task(self._worker_loop())
            for _ in range(self.n_workers)
        ]
        await asyncio.gather(*self._workers, return_exceptions=False)

        sorted_results = sorted(self._results, key=lambda r: r.task_id)
        if self._halt_reason is not None:
            raise self._halt_reason
        return sorted_results

    async def _worker_loop(self) -> None:
        assert self._queue is not None
        assert self._halt_event is not None
        while True:
            if self._halt_event.is_set():
                self._drain_as_deferred()
                return
            item = await self._queue.get()
            try:
                if item is None:
                    return
                if self._halt_event.is_set():
                    self._results.append(self._failed(
                        item, error="auth_halt_deferred",
                    ))
                    # Per ADR-017, deferred tasks do not emit a progress
                    # event; they will be retried by the caller after
                    # credential recovery and emit then.
                    continue
                result = await self._process_task(item)
                self._results.append(result)
                if (
                    self._tracker is not None
                    and result.status_code not in (401, 403)
                ):
                    self._tracker.emit(
                        task_id=result.task_id,
                        success=result.success,
                        status_code=result.status_code,
                        latency_ms=result.latency_ms,
                        result=result,
                    )
            finally:
                self._queue.task_done()

    def _drain_as_deferred(self) -> None:
        """Convert any remaining queued non-sentinel items to deferred failures."""
        assert self._queue is not None
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                if item is None:
                    continue
                self._results.append(self._failed(
                    item, error="auth_halt_deferred",
                ))
            finally:
                self._queue.task_done()

    async def _process_task(self, task: Task) -> BatchResult:
        last_status: Optional[int] = None
        last_latency_ms: float = 0.0

        for attempt in range(self.max_retries):
            await self.rate_limiter.acquire()
            start = time.monotonic()
            try:
                body, status = await self.request_fn(task.payload)
            except Exception as e:
                latency_ms = (time.monotonic() - start) * 1000.0
                log.error(
                    "Exception on task %s (attempt %d): %s",
                    task.task_id, attempt + 1, e,
                )
                return self._failed(task, error=str(e), latency_ms=latency_ms)

            latency_ms = (time.monotonic() - start) * 1000.0
            last_status = status
            last_latency_ms = latency_ms

            if status in (401, 403):
                # Auth failure: do not penalize the rate limiter, do not retry.
                self.rate_limiter.record_success()
                halt_result = self._failed(
                    task,
                    error=f"HTTP {status}: authentication failed",
                    status_code=status,
                    latency_ms=latency_ms,
                    response=body,
                )
                self._halt_reason = AuthHaltError(status, task.task_id, body)
                if self._halt_event is not None:
                    self._halt_event.set()
                return halt_result

            if 200 <= status < 300:
                self.rate_limiter.record_success()
                return BatchResult(
                    task_id=task.task_id,
                    payload=task.payload,
                    metadata=task.metadata,
                    response=body,
                    status_code=status,
                    latency_ms=latency_ms,
                    success=True,
                )

            if status == 429:
                self.rate_limiter.record_429()
                log.warning(
                    "429 on task %s (attempt %d/%d).",
                    task.task_id, attempt + 1, self.max_retries,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            if status >= 500:
                log.warning(
                    "HTTP %d on task %s (attempt %d/%d).",
                    status, task.task_id, attempt + 1, self.max_retries,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            # Non-retryable (4xx other than 429, 3xx, etc.).
            return self._failed(
                task,
                error=f"HTTP {status}: non-retryable status",
                status_code=status,
                latency_ms=latency_ms,
                response=body,
            )

        return self._failed(
            task,
            error=f"max retries ({self.max_retries}) exceeded; last status {last_status}",
            status_code=last_status,
            latency_ms=last_latency_ms,
        )

    @staticmethod
    def _failed(task: Task, *, error: str, status_code: Optional[int] = None,
                latency_ms: float = 0.0, response: Optional[dict] = None) -> BatchResult:
        return BatchResult(
            task_id=task.task_id,
            payload=task.payload,
            metadata=task.metadata,
            response=response,
            error=error,
            status_code=status_code,
            latency_ms=latency_ms,
            success=False,
        )

    async def shutdown(self) -> list[BatchResult]:
        """Cancel in-flight workers and drain remaining queued tasks as failures."""
        for w in self._workers:
            if not w.done():
                w.cancel()

        if self._queue is not None:
            while not self._queue.empty():
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is None:
                    continue
                self._results.append(
                    self._failed(item, error="shutdown")
                )
        return list(self._results)
