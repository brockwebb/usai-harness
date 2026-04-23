"""Live integration test against the USAi endpoint.

NOT part of the regular pytest suite. Run manually:

    python tests/integration/test_live_usai.py

Requires:
    - Valid USAI_API_KEY and USAI_BASE_URL in .env at the repo root
    - Network access to the USAi endpoint

This runs real API calls (~10-13 total) against the live endpoint. Do not run
in CI. Do not run unattended. Watch the output.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from usai_harness import USAiClient
from usai_harness.config import ConfigValidationError
from usai_harness.report import format_report, generate_report

INTEGRATION_DIR = Path(__file__).resolve().parent
LOG_DIR = INTEGRATION_DIR / "logs"
LEDGER_PATH = INTEGRATION_DIR / "cost_ledger.jsonl"


def _record(results: dict, name: str, passed: bool, *, warn: bool = False,
            detail: str = "") -> None:
    results[name] = {"passed": passed, "warn": warn, "detail": detail}


async def _test_init(results: dict) -> USAiClient:
    name = "1. client_initializes"
    try:
        client = USAiClient(
            project="integration-test",
            log_dir=LOG_DIR,
            ledger_path=LEDGER_PATH,
        )
    except Exception as e:
        _record(results, name, False, detail=f"init failed: {e}")
        raise

    domain = urlparse(client._key_manager.base_url).netloc or "(unknown)"
    expires = client._key_manager.expires_at.isoformat()
    detail = (
        f"model={client.config.model.name} base_url_domain={domain} "
        f"key_expires={expires}"
    )
    _record(results, name, True, detail=detail)
    print(f"  [init] {detail}")
    return client


async def _test_single_completion(client: USAiClient, results: dict) -> None:
    name = "2. single_completion"
    try:
        t0 = time.monotonic()
        response = await client.complete(
            messages=[{"role": "user",
                       "content": "Respond with exactly one word: hello"}],
        )
        latency_ms = (time.monotonic() - t0) * 1000.0

        assert isinstance(response, dict), "response not a dict"
        assert response.get("choices"), "choices missing or empty"
        content = response["choices"][0]["message"]["content"]
        assert isinstance(content, str) and content, "content empty"
        usage = response.get("usage") or {}
        assert int(usage.get("prompt_tokens", 0)) > 0, "prompt_tokens == 0"
        assert int(usage.get("completion_tokens", 0)) > 0, "completion_tokens == 0"

        detail = (
            f"model={response.get('model')} "
            f"prompt={usage['prompt_tokens']} "
            f"completion={usage['completion_tokens']} "
            f"latency={latency_ms:.0f}ms"
        )
        _record(results, name, True, detail=detail)
        print(f"  [single] {detail}")
    except Exception as e:
        _record(results, name, False, detail=str(e))
        print(f"  [single] FAIL: {e}")


async def _test_system_prompt(client: USAiClient, results: dict) -> None:
    name = "3. system_prompt"
    try:
        response = await client.complete(
            messages=[{"role": "user", "content": "What is 2 + 2?"}],
            system_prompt="You are a calculator. Only respond with numbers.",
        )
        content = response["choices"][0]["message"]["content"]
        assert "4" in content, f"'4' not in response: {content!r}"
        detail = f"content={content[:100]!r}"
        _record(results, name, True, detail=detail)
        print(f"  [sysprompt] {detail}")
    except Exception as e:
        _record(results, name, False, detail=str(e))
        print(f"  [sysprompt] FAIL: {e}")


async def _test_temperature(client: USAiClient, results: dict) -> None:
    name = "4. temperature_deterministic"
    try:
        msgs = [{"role": "user", "content": "List the first three prime numbers."}]
        r1 = await client.complete(messages=msgs, temperature=0.0)
        r2 = await client.complete(messages=msgs, temperature=0.0)
        c1 = r1["choices"][0]["message"]["content"]
        c2 = r2["choices"][0]["message"]["content"]
        if c1 == c2:
            _record(results, name, True, detail="both identical at temp=0")
            print(f"  [temp] identical: {c1[:80]!r}")
        else:
            _record(
                results, name, True, warn=True,
                detail=f"temp=0 not deterministic (model quirk, non-fatal)",
            )
            print(f"  [temp] WARN non-deterministic at temp=0\n"
                  f"       r1={c1[:80]!r}\n       r2={c2[:80]!r}")
    except Exception as e:
        _record(results, name, False, detail=str(e))
        print(f"  [temp] FAIL: {e}")


async def _test_batch(client: USAiClient, results: dict) -> list:
    name = "5. small_batch"
    batch_results = []
    try:
        tasks = [
            {
                "messages": [{"role": "user", "content": f"What is {i} + {i}?"}],
                "task_id": f"int_batch_{i:02d}",
            }
            for i in range(1, 6)
        ]
        t0 = time.monotonic()
        batch_results = await client.batch(tasks, job_name="integration-batch")
        elapsed = time.monotonic() - t0

        assert len(batch_results) == 5, f"got {len(batch_results)} results, expected 5"
        assert all(r.success for r in batch_results), "not all tasks succeeded"
        assert all(r.latency_ms > 0 for r in batch_results), "zero latency detected"

        mean_latency = sum(r.latency_ms for r in batch_results) / len(batch_results)
        total_tokens = 0
        for r in batch_results:
            usage = (r.response or {}).get("usage") or {}
            total_tokens += int(usage.get("total_tokens", 0))
        detail = (
            f"5/5 success mean_latency={mean_latency:.0f}ms "
            f"total_tokens={total_tokens} elapsed={elapsed:.1f}s"
        )
        # stash elapsed for throughput test
        results["_batch_elapsed"] = elapsed
        _record(results, name, True, detail=detail)
        print(f"  [batch] {detail}")
    except Exception as e:
        _record(results, name, False, detail=str(e))
        print(f"  [batch] FAIL: {e}")
    return batch_results


def _test_log_file(client: USAiClient, results: dict) -> Path:
    name = "6. log_file_written"
    log_path = client._logger.get_log_path()
    try:
        assert log_path.exists(), f"log file missing: {log_path}"
        entries = [
            json.loads(line)
            for line in log_path.read_text().splitlines()
            if line.strip()
        ]
        assert len(entries) >= 5, f"only {len(entries)} entries, expected >=5"
        required = ("timestamp", "task_id", "model", "status_code")
        for i, e in enumerate(entries):
            for f in required:
                assert f in e, f"entry[{i}] missing field {f}"
        detail = f"path={log_path.name} entries={len(entries)}"
        _record(results, name, True, detail=detail)
        print(f"  [log] {detail}")
    except Exception as e:
        _record(results, name, False, detail=str(e))
        print(f"  [log] FAIL: {e}")
    return log_path


def _test_cost_ledger(results: dict) -> None:
    name = "7. cost_ledger_written"
    try:
        assert LEDGER_PATH.exists(), f"ledger missing: {LEDGER_PATH}"
        entries = [
            json.loads(line)
            for line in LEDGER_PATH.read_text().splitlines()
            if line.strip()
        ]
        assert entries, "ledger empty"
        required = ("job_id", "project", "model", "total_calls",
                    "total_tokens_in", "total_tokens_out")
        last = entries[-1]
        for f in required:
            assert f in last, f"ledger entry missing field {f}"
        detail = (
            f"entries={len(entries)} last_job={last['job_id']} "
            f"calls={last['total_calls']} "
            f"tokens_in={last['total_tokens_in']} "
            f"tokens_out={last['total_tokens_out']}"
        )
        _record(results, name, True, detail=detail)
        print(f"  [ledger] {detail}")
    except Exception as e:
        _record(results, name, False, detail=str(e))
        print(f"  [ledger] FAIL: {e}")


def _test_report(log_path: Path, results: dict) -> None:
    name = "8. post_run_report"
    try:
        report = generate_report(log_path)
        assert report, "empty report dict"
        text = format_report(report)
        assert isinstance(text, str) and text, "format_report returned empty"
        _record(
            results, name, True,
            detail=f"report keys={len(report)} calls={report.get('total_calls')}",
        )
        print("  [report] generated OK")
    except Exception as e:
        _record(results, name, False, detail=str(e))
        print(f"  [report] FAIL: {e}")


def _test_throughput(batch_results: list, elapsed: float, results: dict) -> None:
    name = "9. throughput_within_bounds"
    try:
        assert batch_results, "no batch results to measure"
        assert elapsed > 0, "invalid elapsed time"
        throughput = len(batch_results) / elapsed
        assert throughput <= 3.0, f"throughput {throughput:.2f}/s exceeds 3.0/s"
        assert throughput > 0.5, f"throughput {throughput:.2f}/s unreasonably low"
        _record(
            results, name, True,
            detail=f"{throughput:.2f} calls/sec ({len(batch_results)}/{elapsed:.2f}s)",
        )
        print(f"  [throughput] {throughput:.2f} calls/sec")
    except Exception as e:
        _record(results, name, False, detail=str(e))
        print(f"  [throughput] FAIL: {e}")


async def _test_bad_model(client: USAiClient, results: dict) -> None:
    name = "10. bad_model_graceful"
    try:
        response = await client.complete(
            messages=[{"role": "user", "content": "hi"}],
            model="nonexistent-model-xyz",
        )
        is_error_body = (
            isinstance(response, dict)
            and ("error" in response or not response.get("choices"))
        )
        assert is_error_body, (
            f"expected error response for bad model, got: {str(response)[:200]}"
        )
        _record(
            results, name, True,
            detail=f"graceful error body: {str(response)[:120]}",
        )
        print("  [bad_model] handled gracefully via error response")
    except ConfigValidationError as e:
        _record(results, name, True, detail=f"ConfigValidationError: {e}")
        print(f"  [bad_model] handled gracefully via ConfigValidationError: {e}")
    except Exception as e:
        _record(results, name, False, detail=f"unhandled {type(e).__name__}: {e}")
        print(f"  [bad_model] FAIL unhandled exception: {e}")


def print_summary(results: dict) -> None:
    display = {k: v for k, v in results.items() if not k.startswith("_")}
    print("\n" + "═" * 60)
    print("  USAi Harness Integration Test Results")
    print("═" * 60)
    for name, result in display.items():
        if result["passed"] and result.get("warn"):
            status = "WARN"
        elif result["passed"]:
            status = "PASS"
        else:
            status = "FAIL"
        print(f"  {status:4}  {name}")
        if result.get("detail"):
            print(f"        {result['detail']}")
    passed = sum(1 for r in display.values() if r["passed"] and not r.get("warn"))
    warned = sum(1 for r in display.values() if r["passed"] and r.get("warn"))
    failed = sum(1 for r in display.values() if not r["passed"])
    total = len(display)
    print(f"\n  {passed} passed, {warned} warned, {failed} failed out of {total}")
    print("═" * 60)


async def main() -> int:
    results: dict = {}
    client = None
    try:
        client = await _test_init(results)
        await _test_single_completion(client, results)
        await _test_system_prompt(client, results)
        await _test_temperature(client, results)
        batch_results = await _test_batch(client, results)
        log_path = _test_log_file(client, results)
        _test_cost_ledger(results)
        _test_report(log_path, results)
        _test_throughput(
            batch_results,
            results.get("_batch_elapsed", 0.0),
            results,
        )
        await _test_bad_model(client, results)
    finally:
        if client is not None:
            await client.close()
        print_summary(results)

    display = {k: v for k, v in results.items() if not k.startswith("_")}
    return 0 if all(r["passed"] for r in display.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
