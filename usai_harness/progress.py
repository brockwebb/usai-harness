"""Caller observability for `USAiClient.batch()` (ADR-017).

Per FR-066, `batch()` accepts an optional `progress` callback that fires
once per task as each task reaches a terminal state, in completion order.
Counters are owned by a `_ProgressTracker` instance scoped to one
`batch()` invocation; the same instance spans the recovery retries in
the FR-064 auto-rotation flow so the caller sees one event per task,
not one per retry, and the public counters reflect the original
submission size.

The harness is a library, not a service. The callback runs inline on the
asyncio event loop. A buggy callback is wrapped in `try/except`; any
exception it raises is logged at WARN level and suppressed so the
workload itself cannot be poisoned by caller-side bugs.
"""

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger("usai_harness.progress")


@dataclass(frozen=True)
class ProgressEvent:
    """One task-completion event delivered to a `progress` callback.

    Counters are a snapshot at the moment this event fires. They are
    monotonically non-decreasing across the events of a single `batch()`
    call. `succeeded + failed == completed` is invariant on every event.
    The final event of a successful workload has `completed == total`.

    Events fire in *completion order*, which is not submission order
    under concurrent execution. A task `b0042` may complete before
    `b0041` and arrive in the callback first.
    """
    job_name: str
    task_id: str
    completed: int
    total: int
    succeeded: int
    failed: int
    success: bool
    status_code: Optional[int]
    latency_ms: float
    elapsed_seconds: float


class _ProgressTracker:
    """Internal per-batch progress tracker.

    Owns counters for one `batch()` call. The same instance is passed
    into both `run_batch` invocations in the recovery flow so counters
    span retries: a task that succeeds after credential recovery still
    counts as one task in the total, fires one event, and contributes
    once to `completed`.

    Not thread-safe. Worker pool workers run on the same asyncio event
    loop and call `emit` from their completion handlers; concurrent
    invocation across threads is not supported.
    """

    def __init__(
        self,
        total: int,
        job_name: str,
        callback: Callable[[ProgressEvent], None],
    ):
        self._total = int(total)
        self._job_name = job_name or ""
        self._callback = callback
        self._completed = 0
        self._succeeded = 0
        self._failed = 0
        self._start_time = time.monotonic()

    @property
    def total(self) -> int:
        return self._total

    @property
    def completed(self) -> int:
        return self._completed

    def emit(
        self,
        task_id: str,
        success: bool,
        status_code: Optional[int],
        latency_ms: float,
    ) -> None:
        self._completed += 1
        if success:
            self._succeeded += 1
        else:
            self._failed += 1
        event = ProgressEvent(
            job_name=self._job_name,
            task_id=task_id,
            completed=self._completed,
            total=self._total,
            succeeded=self._succeeded,
            failed=self._failed,
            success=success,
            status_code=status_code,
            latency_ms=latency_ms,
            elapsed_seconds=time.monotonic() - self._start_time,
        )
        try:
            self._callback(event)
        except Exception as e:
            log.warning(
                "progress callback raised %s: %s; suppressed (the workload "
                "is not affected).",
                type(e).__name__, e,
            )
