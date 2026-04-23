"""Cost Tracker: Token counting, cost calculation, ledger writes.

Responsibilities:
    - Read prompt_tokens and completion_tokens from OpenAI-format responses
    - Look up per-token rates from model config
    - After each run: append summary to cost_ledger.jsonl (append-only, never deleted)
    - Ledger fields: timestamp, job_id, job_name, project, model,
      total_calls, total_tokens_in, total_tokens_out, estimated_cost,
      duration_seconds, success_rate

Inputs:
    - model_config: ModelConfig — for cost rates
    - ledger_path: str — path to cost_ledger.jsonl

Outputs:
    - record_call(response) — extract and store token counts
    - write_summary(job_stats) — append run summary to ledger
    - get_run_totals() — return accumulated counts for current run
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("usai_harness.cost")


class CostTracker:
    """Tracks token usage and costs per run, writes to append-only ledger."""

    def __init__(self, model_name: str, cost_per_1k_input: float,
                 cost_per_1k_output: float, ledger_path="cost_ledger.jsonl"):
        self.model_name = model_name
        self.cost_per_1k_input = float(cost_per_1k_input)
        self.cost_per_1k_output = float(cost_per_1k_output)
        self.ledger_path = Path(ledger_path)

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0

    def record_call(self, response: dict, success: bool) -> None:
        self.total_calls += 1
        if success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1

        usage = response.get("usage") if isinstance(response, dict) else None
        if (not isinstance(usage, dict)
                or "prompt_tokens" not in usage
                or "completion_tokens" not in usage):
            log.warning(
                "Missing usage data on %s call for model %s; "
                "skipping token accumulation.",
                "successful" if success else "failed",
                self.model_name,
            )
            return

        self.total_input_tokens += int(usage["prompt_tokens"])
        self.total_output_tokens += int(usage["completion_tokens"])

    def get_run_totals(self) -> dict:
        cost_in = (self.total_input_tokens / 1000.0) * self.cost_per_1k_input
        cost_out = (self.total_output_tokens / 1000.0) * self.cost_per_1k_output
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "estimated_cost_input": cost_in,
            "estimated_cost_output": cost_out,
            "estimated_cost_total": cost_in + cost_out,
        }

    def write_summary(self, job_id: str, job_name: str, project: str,
                      model: str, duration_seconds: float) -> None:
        totals = self.get_run_totals()
        success_rate = (
            totals["successful_calls"] / totals["total_calls"]
            if totals["total_calls"] > 0 else 0.0
        )
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "job_id": job_id,
            "job_name": job_name,
            "project": project,
            "model": model,
            "total_calls": totals["total_calls"],
            "successful_calls": totals["successful_calls"],
            "failed_calls": totals["failed_calls"],
            "success_rate": success_rate,
            "total_tokens_in": totals["total_input_tokens"],
            "total_tokens_out": totals["total_output_tokens"],
            "estimated_cost": totals["estimated_cost_total"],
            "duration_seconds": duration_seconds,
        }

        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
            f.flush()

    @classmethod
    def read_ledger(cls, ledger_path="cost_ledger.jsonl") -> list[dict]:
        path = Path(ledger_path)
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
