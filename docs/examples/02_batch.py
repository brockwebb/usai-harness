"""Batch processing: rate-limited, logged, cost-tracked.

Submits a small batch through the worker pool, then prints a per-task
outcome summary plus aggregate metrics derived from the run.

Assumes you have run `usai-harness init` and configured at least one
provider. Run from the project root:

    python docs/examples/02_batch.py

Note on the API surface: `client.batch()` returns `list[TaskResult]`
and prints a formatted post-run report to stdout via the internal
report module. There is no public `BatchReport` dataclass; aggregate
metrics in this script are computed directly from the result list.
"""

import asyncio
from collections import Counter

from usai_harness import USAiClient

PROMPTS = [
    "What is the capital of France?",
    "Who wrote Hamlet?",
    "What year did the first iPhone ship?",
    "What is the chemical symbol for gold?",
    "Which planet is closest to the Sun?",
    "What language is most spoken in Brazil?",
    "What is two plus two?",
]


def _build_tasks(model: str | None = None) -> list[dict]:
    """Build the task list. If `model` is provided, pin it on every task.

    Pinning is useful when the live catalog's first model is not appropriate
    for chat completions (some Gemini variants in `/models` 404 on
    `/chat/completions`); set USAI_HARNESS_EXAMPLE_MODEL to pin without
    editing this file.
    """
    return [
        {
            "task_id": f"q_{i:03d}",
            "messages": [{"role": "user", "content": prompt}],
            **({"model": model} if model else {}),
        }
        for i, prompt in enumerate(PROMPTS)
    ]


def _summarize(results: list) -> None:
    total = len(results)
    successful = sum(1 for r in results if r.success)
    failed = total - successful

    statuses = Counter(r.status_code for r in results if r.status_code is not None)
    total_input = 0
    total_output = 0
    for r in results:
        usage = (r.response or {}).get("usage") or {}
        total_input += int(usage.get("prompt_tokens", 0) or 0)
        total_output += int(usage.get("completion_tokens", 0) or 0)

    print()
    print("Batch summary")
    print(f"  total_calls       : {total}")
    print(f"  successful        : {successful}")
    print(f"  failed            : {failed}")
    print(f"  status_codes      : {dict(statuses)}")
    print(f"  total_input_tokens: {total_input}")
    print(f"  total_output_tokens: {total_output}")
    print()
    print("Per-task outcomes")
    for r in sorted(results, key=lambda x: x.task_id):
        if r.success:
            content = (r.response or {}).get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"  {r.task_id} OK  ({r.latency_ms:.0f}ms): {content[:80]!r}")
        else:
            print(f"  {r.task_id} FAIL ({r.status_code}): {r.error}")


async def main() -> None:
    import os
    model = os.environ.get("USAI_HARNESS_EXAMPLE_MODEL")
    tasks = _build_tasks(model=model)
    async with USAiClient(project="batch-example") as client:
        results = await client.batch(tasks, job_name="example-batch")
    _summarize(results)


if __name__ == "__main__":
    asyncio.run(main())
