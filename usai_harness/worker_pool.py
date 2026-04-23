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


@dataclass
class Task:
    """A unit of work for the worker pool."""
    task_id: str
    payload: dict
    metadata: dict = field(default_factory=dict)


@dataclass
class TaskResult:
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
        self._results: list[TaskResult] = []

    async def run_batch(self, tasks: list[Task]) -> list[TaskResult]:
        """Process all tasks across n_workers and return deterministic results."""
        self._queue = asyncio.Queue()
        self._results = []

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

        return sorted(self._results, key=lambda r: r.task_id)

    async def _worker_loop(self) -> None:
        assert self._queue is not None
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return
                result = await self._process_task(item)
                self._results.append(result)
            finally:
                self._queue.task_done()

    async def _process_task(self, task: Task) -> TaskResult:
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

            if 200 <= status < 300:
                self.rate_limiter.record_success()
                return TaskResult(
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
                latency_ms: float = 0.0, response: Optional[dict] = None) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            payload=task.payload,
            metadata=task.metadata,
            response=response,
            error=error,
            status_code=status_code,
            latency_ms=latency_ms,
            success=False,
        )

    async def shutdown(self) -> list[TaskResult]:
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
