"""Cost Tracker: Per-model token counting and ledger writes (ADR-004 / 0.7.0).

Per the ADR-004 amendment (2026-04-29), the ledger granularity is one
JSONL entry per (model, flush-point) pair, where a flush-point is the
end of a `batch()` call or the close of the client. Tracker state is
keyed by model name and resets on flush, so each entry describes the
deltas accumulated since the previous flush.

Inputs:
    - pool: list[ModelConfig] — the project's model pool; rates are taken
      from each member's catalog entry
    - ledger_path: Path — append-only JSONL file

Outputs:
    - record_call(model, response, success) — accumulate tokens against
      the named model's bucket
    - flush_to_ledger(job_id, job_name, project, duration_seconds,
      flush_reason) — write one line per model with nonzero calls, then
      reset all buckets
    - get_run_totals() — return per-model totals; useful for tests and
      manual inspection
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("usai_harness.cost")

VALID_FLUSH_REASONS = frozenset({"batch_end", "client_close"})


@dataclass(frozen=True)
class LedgerEntry:
    """Append-only ledger entry. Metadata only, no content fields permitted.

    Per the ADR-004 amendment (2026-04-29), `model` holds the actual model
    whose calls are summarized in this entry, not the project default.
    `flush_reason` records what caused this entry to be written.
    """
    timestamp: str
    job_id: str
    job_name: str
    project: str
    model: str
    total_calls: int
    successful_calls: int
    failed_calls: int
    success_rate: float
    total_tokens_in: int
    total_tokens_out: int
    estimated_cost: float
    duration_seconds: float
    flush_reason: str


@dataclass
class _ModelTotals:
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0


class CostTracker:
    """Per-model token tracking with append-only ledger writes."""

    def __init__(self, pool, ledger_path: Path = Path("cost_ledger.jsonl")):
        self.ledger_path = Path(ledger_path)
        self._totals: dict[str, _ModelTotals] = {
            m.name: _ModelTotals(
                cost_per_1k_input=float(m.cost_per_1k_input_tokens),
                cost_per_1k_output=float(m.cost_per_1k_output_tokens),
            )
            for m in pool
        }

    def record_call(self, model: str, response: dict, success: bool) -> None:
        """Accumulate tokens against `model`'s bucket.

        If `model` is not in the tracker pool (which shouldn't happen given
        client-side pool validation, but is possible if record_call is
        invoked from a non-validating path), a zero-rate bucket is created
        and a WARN is logged so cost data isn't silently lost.
        """
        if model not in self._totals:
            log.warning(
                "record_call: model %r not in cost tracker pool; "
                "creating zero-rate bucket so the call is not silently lost.",
                model,
            )
            self._totals[model] = _ModelTotals()
        bucket = self._totals[model]
        bucket.total_calls += 1
        if success:
            bucket.successful_calls += 1
        else:
            bucket.failed_calls += 1

        usage = response.get("usage") if isinstance(response, dict) else None
        if (not isinstance(usage, dict)
                or "prompt_tokens" not in usage
                or "completion_tokens" not in usage):
            log.warning(
                "Missing usage data on %s call for model %s; "
                "skipping token accumulation.",
                "successful" if success else "failed",
                model,
            )
            return

        bucket.total_input_tokens += int(usage["prompt_tokens"])
        bucket.total_output_tokens += int(usage["completion_tokens"])

    def get_run_totals(self) -> dict[str, dict]:
        """Return per-model totals as a dict keyed by model name.

        Each value is a dict with the same shape as the pre-0.7.0
        single-model totals (call counts, token counts, derived costs).
        """
        out: dict[str, dict] = {}
        for name, b in self._totals.items():
            cost_in = (b.total_input_tokens / 1000.0) * b.cost_per_1k_input
            cost_out = (b.total_output_tokens / 1000.0) * b.cost_per_1k_output
            out[name] = {
                "total_calls": b.total_calls,
                "successful_calls": b.successful_calls,
                "failed_calls": b.failed_calls,
                "total_input_tokens": b.total_input_tokens,
                "total_output_tokens": b.total_output_tokens,
                "total_tokens": b.total_input_tokens + b.total_output_tokens,
                "estimated_cost_input": cost_in,
                "estimated_cost_output": cost_out,
                "estimated_cost_total": cost_in + cost_out,
            }
        return out

    def flush_to_ledger(
        self,
        job_id: str,
        job_name: str,
        project: str,
        duration_seconds: float,
        flush_reason: str,
    ) -> int:
        """Write one ledger line per model with nonzero calls, then reset.

        Returns the number of lines written. Models with zero calls since
        the last flush are skipped. After the flush, every model's totals
        are reset to zero so the next flush emits fresh deltas, not
        cumulative totals.
        """
        if flush_reason not in VALID_FLUSH_REASONS:
            raise ValueError(
                f"flush_reason must be one of {sorted(VALID_FLUSH_REASONS)}; "
                f"got {flush_reason!r}."
            )

        timestamp = datetime.now(timezone.utc).isoformat()
        lines_written = 0
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.ledger_path, "a", encoding="utf-8") as f:
            for name, b in self._totals.items():
                if b.total_calls == 0:
                    continue
                cost = (
                    (b.total_input_tokens / 1000.0) * b.cost_per_1k_input
                    + (b.total_output_tokens / 1000.0) * b.cost_per_1k_output
                )
                success_rate = (
                    b.successful_calls / b.total_calls
                    if b.total_calls > 0 else 0.0
                )
                entry = LedgerEntry(
                    timestamp=timestamp,
                    job_id=job_id,
                    job_name=job_name,
                    project=project,
                    model=name,
                    total_calls=b.total_calls,
                    successful_calls=b.successful_calls,
                    failed_calls=b.failed_calls,
                    success_rate=success_rate,
                    total_tokens_in=b.total_input_tokens,
                    total_tokens_out=b.total_output_tokens,
                    estimated_cost=cost,
                    duration_seconds=duration_seconds,
                    flush_reason=flush_reason,
                )
                f.write(json.dumps(asdict(entry)) + "\n")
                lines_written += 1
            f.flush()

        for b in self._totals.values():
            b.total_calls = 0
            b.successful_calls = 0
            b.failed_calls = 0
            b.total_input_tokens = 0
            b.total_output_tokens = 0

        return lines_written

    @classmethod
    def read_ledger(cls, ledger_path="cost_ledger.jsonl") -> list[dict]:
        path = Path(ledger_path)
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
