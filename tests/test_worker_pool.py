"""Tests for async task queue, retries, rate limiter integration."""

import asyncio
import time

import pytest

from usai_harness.rate_limiter import RateLimiter
from usai_harness.worker_pool import AuthHaltError, Task, BatchResult, WorkerPool

pytestmark = pytest.mark.asyncio


def _make_limiter() -> RateLimiter:
    # High rate so the limiter never bottlenecks tests.
    return RateLimiter(refill_rate=100, burst=100)


def _make_mock_request_fn(*, response=None, responses_by_id=None,
                          status_sequence=None, delay=0.0, fail_on=None):
    """Build an async mock for WorkerPool.request_fn.

    response:          default (body, status) tuple for every call
    responses_by_id:   {task_id: (body, status)} — payload must carry "task_id"
    status_sequence:   list of (body, status) consumed in call order
    delay:             simulated latency per call
    fail_on:           set of task_ids that should raise ConnectionError
    """
    call_log: list[dict] = []
    seq_state = {"i": 0}

    async def mock_fn(payload):
        call_log.append(payload)
        if delay:
            await asyncio.sleep(delay)
        tid = payload.get("task_id") if isinstance(payload, dict) else None
        if fail_on and tid in fail_on:
            raise ConnectionError(f"mock connection error for {tid}")
        if status_sequence is not None:
            i = seq_state["i"]
            seq_state["i"] += 1
            return status_sequence[i]
        if responses_by_id and tid in responses_by_id:
            return responses_by_id[tid]
        return response

    mock_fn.call_log = call_log
    return mock_fn


async def test_single_task_success():
    pool = WorkerPool(
        _make_limiter(),
        _make_mock_request_fn(response=({"result": "ok"}, 200)),
        n_workers=1,
    )
    results = await pool.run_batch([Task(task_id="t1", payload={})])

    assert len(results) == 1
    r = results[0]
    assert r.success is True
    assert r.response == {"result": "ok"}
    assert r.status_code == 200
    assert r.error is None


async def test_batch_all_success():
    pool = WorkerPool(
        _make_limiter(),
        _make_mock_request_fn(response=({"ok": True}, 200)),
        n_workers=3,
    )
    tasks = [Task(task_id=f"t{i:02d}", payload={}) for i in range(10)]
    results = await pool.run_batch(tasks)

    assert len(results) == 10
    assert all(r.success for r in results)
    assert [r.task_id for r in results] == [f"t{i:02d}" for i in range(10)]


async def test_batch_mixed_results():
    responses = {
        "t1": ({"ok": 1}, 200),
        "t2": ({"ok": 2}, 200),
        "t3": ({"ok": 3}, 200),
        "t4": ({"err": "bad request"}, 400),
        "t5": ({"err": "server error"}, 500),
    }
    pool = WorkerPool(
        _make_limiter(),
        _make_mock_request_fn(responses_by_id=responses),
        n_workers=3,
        max_retries=2,
    )
    tasks = [Task(task_id=tid, payload={"task_id": tid}) for tid in responses]
    results = await pool.run_batch(tasks)

    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    assert len(successes) == 3
    assert len(failures) == 2
    for f in failures:
        assert f.error, f"failed result {f.task_id} must carry an error message"


async def test_429_triggers_retry():
    limiter = _make_limiter()
    fn = _make_mock_request_fn(status_sequence=[
        ({"retry": True}, 429),
        ({"ok": True}, 200),
    ])
    pool = WorkerPool(limiter, fn, n_workers=1, max_retries=2)
    results = await pool.run_batch([Task(task_id="t1", payload={})])

    assert results[0].success is True
    assert results[0].response == {"ok": True}
    assert limiter.stats()["total_429s"] == 1


async def test_retries_exhausted():
    fn = _make_mock_request_fn(response=({"err": "boom"}, 500))
    pool = WorkerPool(_make_limiter(), fn, n_workers=1, max_retries=2)
    results = await pool.run_batch([Task(task_id="t1", payload={})])

    assert results[0].success is False
    assert results[0].error and (
        "retr" in results[0].error.lower() or "max" in results[0].error.lower()
    )
    assert len(fn.call_log) == 2  # exactly max_retries attempts


async def test_exception_in_request_fn():
    fn = _make_mock_request_fn(
        response=({"ok": True}, 200),
        fail_on={"t1"},
    )
    pool = WorkerPool(_make_limiter(), fn, n_workers=1, max_retries=3)
    results = await pool.run_batch([Task(task_id="t1", payload={"task_id": "t1"})])

    assert results[0].success is False
    assert "mock connection error" in results[0].error.lower()


async def test_concurrent_workers():
    fn = _make_mock_request_fn(response=({"ok": True}, 200), delay=0.1)
    pool = WorkerPool(_make_limiter(), fn, n_workers=3)
    tasks = [Task(task_id=f"t{i:02d}", payload={}) for i in range(6)]

    start = time.monotonic()
    results = await pool.run_batch(tasks)
    elapsed = time.monotonic() - start

    assert len(results) == 6
    assert all(r.success for r in results)
    # 3 workers × 2 rounds × 0.1s ≈ 0.2s
    assert 0.05 <= elapsed <= 0.35, (
        f"6 tasks / 3 workers / 0.1s each should be ~0.2s, got {elapsed:.3f}s"
    )


async def test_non_retryable_status_codes():
    """4xx other than 429/401/403 must not retry; 401/403 are covered by halt tests."""
    responses = {
        "t1": ({"err": "bad"}, 400),
        "t2": ({"err": "not found"}, 404),
    }
    fn = _make_mock_request_fn(responses_by_id=responses)
    pool = WorkerPool(_make_limiter(), fn, n_workers=1, max_retries=3)
    tasks = [Task(task_id=tid, payload={"task_id": tid}) for tid in responses]
    results = await pool.run_batch(tasks)

    assert all(not r.success for r in results)
    assert len(fn.call_log) == len(responses)


async def test_results_include_latency():
    fn = _make_mock_request_fn(response=({"ok": True}, 200), delay=0.05)
    pool = WorkerPool(_make_limiter(), fn, n_workers=2)
    tasks = [Task(task_id=f"t{i:02d}", payload={}) for i in range(3)]
    results = await pool.run_batch(tasks)

    assert all(r.latency_ms > 0 for r in results)


async def test_results_echo_metadata():
    fn = _make_mock_request_fn(response=({"ok": True}, 200))
    pool = WorkerPool(_make_limiter(), fn, n_workers=2)
    tasks = [
        Task(task_id=f"t{i:02d}", payload={"i": i},
             metadata={"source": "test", "index": i})
        for i in range(3)
    ]
    results = await pool.run_batch(tasks)

    assert all(r.metadata["source"] == "test" for r in results)
    assert {r.metadata["index"] for r in results} == {0, 1, 2}


async def test_401_halts_pool_and_preserves_results():
    """First two tasks succeed, third returns 401, remaining seven are deferred.

    Results are read from `pool.results` after catching AuthHaltError.
    """
    responses = {
        "t00": ({"ok": True}, 200),
        "t01": ({"ok": True}, 200),
        "t02": ({"err": "auth"}, 401),
    }
    fn = _make_mock_request_fn(responses_by_id=responses)
    pool = WorkerPool(_make_limiter(), fn, n_workers=1, max_retries=3)
    tasks = [
        Task(task_id=f"t{i:02d}", payload={"task_id": f"t{i:02d}"})
        for i in range(10)
    ]

    start = time.monotonic()
    with pytest.raises(AuthHaltError) as excinfo:
        await pool.run_batch(tasks)
    elapsed = time.monotonic() - start

    assert excinfo.value.status_code == 401
    assert elapsed < 1.0, f"halt took {elapsed:.3f}s, expected <1s"

    results = pool.results
    assert len(results) == 10
    successes = [r for r in results if r.success]
    halted = [r for r in results
              if not r.success and r.status_code == 401]
    deferred = [r for r in results if r.error == "auth_halt_deferred"]

    assert len(successes) == 2
    assert {r.task_id for r in successes} == {"t00", "t01"}
    assert len(halted) == 1 and halted[0].task_id == "t02"
    assert len(deferred) == 7
    # Deferred tasks never reach the request function.
    assert len(fn.call_log) == 3


async def test_403_halts_pool():
    """403 triggers the same halt path as 401."""
    responses = {
        "t00": ({"ok": True}, 200),
        "t01": ({"err": "forbidden"}, 403),
    }
    fn = _make_mock_request_fn(responses_by_id=responses)
    pool = WorkerPool(_make_limiter(), fn, n_workers=1, max_retries=3)
    tasks = [
        Task(task_id=f"t{i:02d}", payload={"task_id": f"t{i:02d}"})
        for i in range(5)
    ]

    with pytest.raises(AuthHaltError) as excinfo:
        await pool.run_batch(tasks)

    assert excinfo.value.status_code == 403
    results = pool.results
    deferred = [r for r in results if r.error == "auth_halt_deferred"]
    assert len(deferred) == 3
