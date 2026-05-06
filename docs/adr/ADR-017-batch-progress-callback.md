# ADR-017: Batch Progress Callback

**Status:** Accepted
**Date:** 2026-05-06

## Context

`USAiClient.batch(tasks)` submits a task list to the worker pool and returns a list of results when every task has reached a terminal state. The worker pool internally knows the moment each task completes; the harness consumes that signal for rate-limiter accounting and call-log emission. Callers see nothing.

The federal-survey-concept-mapper observed the failure mode in practice on 2026-05-06: a 1,398-task workload ran for ~30 minutes with zero output between submit and final return. The user could not tell whether the run was making progress, was stalled, or was being throttled. A failure mid-run would have been invisible until the final return — the caller could not, for example, abort early on seeing the first ten consecutive request failures.

The cost ledger and call log are append-only, so theoretically a caller could `tail -f` them, but their formats are not optimized for human progress reading and the caller would have to know that recipe.

This is not a UI feature. It is an observability hook. The harness already produces the events; it just refuses to expose them.

The "no dashboards, no real-time UIs" project convention warrants a careful read here. A *callback parameter* is not a UI: it is a typed Python hook the caller invokes. Whether the caller renders anything is the caller's concern. The harness emits events; the caller decides what to do with them.

## Decision

`USAiClient.batch()` accepts an optional `progress: Callable[[ProgressEvent], None]` keyword argument. When provided, the harness invokes the callback exactly once per task as each task reaches a terminal state, in completion order. When `None` (the default), behavior is byte-identical to pre-0.8.0 `batch()`.

### `ProgressEvent` shape

A frozen dataclass exported from `usai_harness`:

```python
@dataclass(frozen=True)
class ProgressEvent:
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
```

The caller derives `pct = completed / total * 100` and ETA = `elapsed_seconds / completed * (total - completed)`. Formatting and rendering are caller concerns.

### Event ordering and concurrency

Events fire inside the worker pool's task-completion handler, on the same asyncio event loop. The harness wraps the user callback in a `try/except` and logs (does not re-raise) any exception the callback throws; a buggy callback cannot poison the workload.

Events fire in *completion order*, not submission order. Under concurrent workers, task `b0042` may complete before `b0041`. This is documented explicitly in the API reference.

Counters are monotonically non-decreasing. `completed` strictly increases by 1 per event. `succeeded` and `failed` partition `completed`; the invariant `succeeded + failed == completed` holds on every event. The final event of a successful workload has `completed == total`.

### Auth-halt and retry interaction (FR-064)

The auto-recovery flow in FR-064 retries deferred tasks after a credential refresh. From the caller's perspective, a retried task fires *exactly one* progress event when it ultimately reaches a terminal state — not one per retry. The internal retry machinery is not visible at the progress layer.

Implementation: a single `_ProgressTracker` instance is built per `batch()` call and reused across both `WorkerPool.run_batch` invocations in the recovery flow. The tracker's `total` is the original task count. Auth-halted tasks (status 401/403) and tasks deferred by an auth halt do not emit on the first run; they are retried after credential recovery and emit then. The counters span retries.

If a workload aborts due to a second-consecutive auth halt (the FR-064 ceiling), the progress callback has already fired for tasks that succeeded before the halt. Tasks that were deferred but never retried fire no event. The caller observes `completed < total` at the moment `AuthHaltError` propagates, which is correct: those tasks did not reach a terminal state.

### `complete()` is out of scope

A single call has nothing to stream. If a future use case wants per-token streaming for `complete()`, that is a separate ADR.

## Alternatives considered

- **Built-in stderr progress bar.** Rejected. Dashboards are out of scope per project conventions, and "what kind of bar" is exactly the question the harness should not answer for the caller. Different callers want different things (text counter, log line, structured event stream, none of the above). The callback gives all of them what they need without picking a default that will be wrong for most.
- **File-based progress (e.g., write to `progress.json`).** Rejected. Synchronization, race conditions, and filesystem noise. The in-process callback is strictly better for in-process callers, and out-of-process consumers should `tail` the call log.
- **Async generator that yields results as they complete.** Considered. Pro: more Pythonic, lazy iteration, callers `async for` over it. Con: changes the public API shape (return type), incompatible with current callers, and forces every caller into an `async for` loop. The callback approach is additive and zero-friction; existing callers do nothing different and pre-0.8.0 behavior is preserved exactly.
- **Add a config flag for an opt-in built-in progress bar.** Rejected for the same reasons as the stderr progress bar — the harness should not be in the rendering business.

## Consequences

Callers can render progress however they like. A canonical "text status loop" recipe lives in the API reference, not in the harness itself; callers copy-paste, modify, or ignore. Callers writing structured pipelines emit one JSON object per event to stderr and pipe through `jq` or a log aggregator; the same callback shape works for both.

The worker pool gains one new emission call site (immediately after `_results.append(result)` in the main worker loop, gated on `result.status_code not in (401, 403)` and `tracker is not None`). No changes to scheduling logic.

The implementation surface is small: one new module (`progress.py`) holding the `ProgressEvent` dataclass and the `_ProgressTracker` helper, one threaded kwarg through `WorkerPool.run_batch`, one new keyword on `USAiClient.batch()`. The hard-deps list is unchanged.

The change is purely additive. No `### Breaking` section in CHANGELOG.

## Amendment, 2026-05-06 — built-in text formatter, default flipped to visible

The 0.8.0 design left the default at `progress=None`, on the reasoning that the harness should not pick a default rendering for the caller. The first downstream adoption (federal-survey-concept-mapper Stage 1) immediately reproduced the original failure mode: nobody bothered to wire a callback, runs went silent for ~30 minutes, the user kept asking "is it stalled?" The design decision was right in the abstract and wrong in practice — the caller does not, in the moment, want to write a callback; they want progress to just appear.

0.8.1 ships a built-in `text_progress` formatter inside `progress.py` (alongside the existing `ProgressEvent` and `_ProgressTracker`) and makes it the default value of `USAiClient.batch(progress=...)`. The output format is opinionated and simple:

```
[HH:MM:SS] [<job_name>] <completed>/<total> (<pct>%)  elapsed <elapsed>  eta <eta>
```

Failed events append `  FAIL: <task_id>`. The `[<job_name>]` label is omitted when `job_name` is empty. Time durations are rendered as `Ns`, `Nm SSs`, or `Nh MMm SSs` depending on magnitude. Output goes to stdout with `flush=True` so a long-running batch produces visible progress immediately rather than buffering.

Callers who want pre-0.8.1 silence pass `progress=None`. Callers who want a different format pass their own callable. The 0.8.0 plumbing (`ProgressEvent`, `_ProgressTracker`, `WorkerPool.run_batch(tracker=...)`) is unchanged.

Backward compatibility note: a caller running 0.8.0 code that did not pass `progress=` got no output. Under 0.8.1 the same code now writes status lines to stdout. This is a behavioral change but not a breaking one — no return values change, no exceptions change, no data changes. The only difference is stdout. Callers that pipe stdout through a parser will need to opt out with `progress=None`. The harness convention remains "library, not service": stdout is for humans, not machines, and machine-readable progress remains available through a custom JSON-emitting callback.

The default flip aligns the project convention "silent failures are bugs" with the practical default: a 30-minute batch with zero output was, by that principle, a bug. Making progress the default fixes it at the root.

The "stderr progress bar" alternative rejected in 0.8.0 remains rejected; `text_progress` is plain `print(...)`, not a bar (no `\r` rewrites, no terminal-control sequences, no curses, no tqdm). One line per terminal-state task. That's the entire surface.

*Source:* CC task 2026-05-06_builtin_text_progress.
