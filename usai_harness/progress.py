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

Per the ADR-017 amendment (2026-05-06 / 0.8.1), this module also exports
`text_progress`, a ready-to-use formatter that callers do not have to
write themselves. `text_progress` is the default value of
`USAiClient.batch(progress=...)`, which flips the default from "silent"
to "visible." Callers who want pre-0.8.1 silence pass `progress=None`.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from usai_harness.worker_pool import BatchResult

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

    Per the ADR-017 amendment (2026-05-06 / 0.9.0), `result` carries the
    full `BatchResult` for the completed task — payload, metadata,
    response body, status, error, latency. Callers can use it to
    checkpoint per task, stream JSONL, or extract response content
    incrementally without waiting for `batch()` to return. `text_progress`
    and other count-only callbacks ignore the field. The type is
    `Optional` for forward-compatibility with future event sources that
    might fire without an associated result; under all 0.9.0 emission
    paths, `result` is always populated.
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
    result: Optional["BatchResult"] = None


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
        result: Optional["BatchResult"] = None,
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
            result=result,
        )
        try:
            self._callback(event)
        except Exception as e:
            log.warning(
                "progress callback raised %s: %s; suppressed (the workload "
                "is not affected).",
                type(e).__name__, e,
            )


def _fmt_time(seconds: float) -> str:
    """Render a non-negative duration as `Ns`, `Nm SSs`, or `Nh MMm SSs`.

    Negative inputs (which can occur if `elapsed_seconds` is briefly
    smaller than the previous tick due to clock skew) clamp to 0.
    """
    s = int(seconds) if seconds > 0 else 0
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m {s % 60:02d}s"


def text_progress(event: ProgressEvent) -> None:
    """Built-in text formatter for `batch(progress=...)` (ADR-017 amendment).

    Default callback as of 0.8.1: every line carries a local-clock
    timestamp, an optional `[job_name]` label, the `completed/total`
    fraction with one-decimal-place percent, the elapsed wall time, and
    an ETA derived from `elapsed_seconds / completed * (total - completed)`.
    Failed events append `FAIL: <task_id>`. Output goes to stdout with
    `flush=True` so a long-running batch produces visible progress
    immediately rather than buffering.

    Callers who want a different format pass their own
    `Callable[[ProgressEvent], None]`. Callers who want silence pass
    `progress=None`.
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    label = f" [{event.job_name}]" if event.job_name else ""
    pct = (event.completed / event.total * 100.0) if event.total else 0.0
    elapsed = _fmt_time(event.elapsed_seconds)
    if event.completed > 0:
        eta_seconds = (
            event.elapsed_seconds / event.completed
            * (event.total - event.completed)
        )
    else:
        eta_seconds = 0.0
    eta = _fmt_time(eta_seconds)
    line = (
        f"[{timestamp}]{label} {event.completed}/{event.total} ({pct:.1f}%)  "
        f"elapsed {elapsed}  eta {eta}"
    )
    if not event.success:
        line += f"  FAIL: {event.task_id}"
    print(line, flush=True)
