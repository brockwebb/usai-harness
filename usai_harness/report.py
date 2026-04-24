"""Post-Run Report and CLI: Summary generation and cost reporting.

Responsibilities:
    - Read per-run log file after completion
    - Generate report: total calls, success rate, mean/p95 latency,
      tokens consumed, throughput achieved, estimated cost
    - Tuning insights:
        - Prompt size distribution (flag bloated prompts)
        - Model speed comparison for comparable token counts
        - Context length failures
    - CLI command: `usai-harness cost-report` for ledger summaries

Inputs:
    - log_path: str — path to run log file
    - ledger_path: str — path to cost_ledger.jsonl

Outputs:
    - generate_report(log_path) — print/return run summary
    - cli_main() — entry point for `usai-harness cost-report`
"""

import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional


def _read_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (p is 0..100)."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    if len(sorted_v) == 1:
        return float(sorted_v[0])
    k = (len(sorted_v) - 1) * p / 100.0
    low = int(k)
    high = min(low + 1, len(sorted_v) - 1)
    if low == high:
        return float(sorted_v[low])
    return sorted_v[low] + (sorted_v[high] - sorted_v[low]) * (k - low)


def generate_report(log_path) -> dict:
    """Parse a per-run JSONL log file and compute a summary dict."""
    entries = _read_jsonl(log_path)
    if not entries:
        print(f"Warning: no entries found in {log_path}", file=sys.stderr)
        return {}

    # Backward-compat: old logs had "model"; new logs have "model_requested".
    for e in entries:
        if "model_requested" not in e and "model" in e:
            e["model_requested"] = e["model"]

    first = entries[0]
    models = {e.get("model_requested") for e in entries if e.get("model_requested")}
    model_label = next(iter(models)) if len(models) == 1 else "mixed"

    mismatches = [
        {
            "task_id": e.get("task_id"),
            "requested": e.get("model_requested"),
            "returned": e.get("model_returned"),
        }
        for e in entries
        if e.get("model_requested")
        and e.get("model_returned")
        and e["model_requested"] != e["model_returned"]
    ]

    successful = [e for e in entries if 200 <= int(e.get("status_code", 0)) < 300]
    failed = [e for e in entries if not (200 <= int(e.get("status_code", 0)) < 300)]
    total = len(entries)
    success_rate = len(successful) / total if total else 0.0

    latencies = [float(e["latency_ms"]) for e in entries if "latency_ms" in e]
    prompt_sizes = [int(e["prompt_tokens"]) for e in entries if "prompt_tokens" in e]
    input_tokens = sum(prompt_sizes)
    output_tokens = sum(int(e["completion_tokens"]) for e in entries
                        if "completion_tokens" in e)

    timestamps = []
    for e in entries:
        ts = e.get("timestamp")
        if ts:
            try:
                timestamps.append(datetime.fromisoformat(ts))
            except ValueError:
                pass
    duration = (max(timestamps) - min(timestamps)).total_seconds() if len(timestamps) >= 2 else 0.0
    throughput = total / duration if duration > 0 else 0.0

    error_codes = Counter(
        int(e.get("status_code", 0)) for e in failed
    )

    lat_mean = statistics.mean(latencies) if latencies else 0.0
    lat_p95 = _percentile(latencies, 95)

    insights: list[str] = []
    if latencies and lat_p95 > 3 * lat_mean and lat_mean > 0:
        insights.append(
            f"High latency variance: p95 is {lat_p95:.0f}ms vs mean "
            f"{lat_mean:.0f}ms. Check for outlier prompts."
        )
    if success_rate < 0.95:
        insights.append(
            f"Success rate {success_rate:.1%} is below 95%. "
            "Review error distribution."
        )
    if success_rate == 1.0 and total > 10:
        insights.append(f"Perfect success rate across {total} calls.")
    n_429 = error_codes.get(429, 0)
    if n_429 > 0:
        insights.append(
            f"Rate limiting hit {n_429} times. "
            "Current throughput may be near USAi's limit."
        )

    return {
        "job_id": first.get("job_id", ""),
        "project": first.get("project", ""),
        "model": model_label,
        "total_calls": total,
        "successful_calls": len(successful),
        "failed_calls": len(failed),
        "success_rate": success_rate,
        "latency_mean_ms": lat_mean,
        "latency_p95_ms": lat_p95,
        "latency_min_ms": min(latencies) if latencies else 0.0,
        "latency_max_ms": max(latencies) if latencies else 0.0,
        "total_input_tokens": input_tokens,
        "total_output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "throughput_calls_per_sec": throughput,
        "prompt_size_distribution": {
            "min_tokens": min(prompt_sizes) if prompt_sizes else 0,
            "max_tokens": max(prompt_sizes) if prompt_sizes else 0,
            "mean_tokens": statistics.mean(prompt_sizes) if prompt_sizes else 0.0,
            "p95_tokens": _percentile([float(x) for x in prompt_sizes], 95),
        },
        "errors": {
            "count": len(failed),
            "types": dict(error_codes),
        },
        "model_mismatches": mismatches,
        "insights": insights,
    }


def format_report(report: dict) -> str:
    """Render a report dict as aligned plain text for terminal output."""
    if not report:
        return "No run data to report.\n"

    lines: list[str] = []
    lines.append("═══ USAi Harness Run Report ═══")
    lines.append("")
    lines.append(f"Job:         {report['job_id']}")
    lines.append(f"Project:     {report['project']}")
    lines.append(f"Model:       {report['model']}")
    lines.append("")
    lines.append(
        f"Calls:       {report['total_calls']:,} total "
        f"({report['successful_calls']:,} ok, {report['failed_calls']:,} failed)"
    )
    lines.append(f"Success:     {report['success_rate']:.1%}")
    lines.append("")
    lines.append(
        f"Latency:     mean {report['latency_mean_ms']:,.0f}ms "
        f"| p95 {report['latency_p95_ms']:,.0f}ms "
        f"| min {report['latency_min_ms']:,.0f}ms "
        f"| max {report['latency_max_ms']:,.0f}ms"
    )
    lines.append(f"Throughput:  {report['throughput_calls_per_sec']:.1f} calls/sec")
    lines.append("")
    lines.append(
        f"Tokens:      {report['total_input_tokens']:,} in "
        f"| {report['total_output_tokens']:,} out "
        f"| {report['total_tokens']:,} total"
    )
    lines.append("Cost:        $0.00 (free credits)")
    lines.append("")

    psd = report["prompt_size_distribution"]
    lines.append(
        f"Prompts:     min {psd['min_tokens']:,} "
        f"| mean {psd['mean_tokens']:,.0f} "
        f"| p95 {psd['p95_tokens']:,.0f} "
        f"| max {psd['max_tokens']:,} tokens"
    )
    lines.append("")

    errs = report["errors"]
    lines.append(f"Errors:      {errs['count']} total")
    for status, count in sorted(errs["types"].items()):
        lines.append(f"  {status}:       {count}")

    mismatches = report.get("model_mismatches") or []
    if mismatches:
        lines.append("")
        lines.append(f"Model echo:  {len(mismatches)} mismatch(es) detected")
        for m in mismatches:
            lines.append(
                f"  {m['task_id']}: requested {m['requested']}, "
                f"returned {m['returned']}"
            )

    if report["insights"]:
        lines.append("")
        lines.append("Insights:")
        for ins in report["insights"]:
            lines.append(f"  • {ins}")

    lines.append("")
    return "\n".join(lines)


def cost_report(ledger_path, project: Optional[str] = None,
                model: Optional[str] = None) -> str:
    """Read cost_ledger.jsonl and format a summary (optionally filtered)."""
    entries = _read_jsonl(ledger_path)
    if not entries:
        return f"No data: cost ledger at {ledger_path} has no entries.\n"

    if project is not None:
        entries = [e for e in entries if e.get("project") == project]
    if model is not None:
        entries = [e for e in entries if e.get("model") == model]

    if not entries:
        return (
            "No data: no ledger entries match the given filters "
            f"(project={project!r}, model={model!r}).\n"
        )

    total_runs = len(entries)
    total_calls = sum(int(e.get("total_calls", 0)) for e in entries)
    total_ok = sum(int(e.get("successful_calls", 0)) for e in entries)
    total_failed = sum(int(e.get("failed_calls", 0)) for e in entries)
    total_in = sum(int(e.get("total_tokens_in", 0)) for e in entries)
    total_out = sum(int(e.get("total_tokens_out", 0)) for e in entries)
    total_cost = sum(float(e.get("estimated_cost", 0.0)) for e in entries)

    timestamps = sorted(e.get("timestamp", "") for e in entries if e.get("timestamp"))
    date_range = (
        f"{timestamps[0]} to {timestamps[-1]}" if timestamps else "unknown"
    )

    filters: list[str] = []
    if project:
        filters.append(f"project={project}")
    if model:
        filters.append(f"model={model}")
    filter_line = ", ".join(filters) if filters else "none"

    lines: list[str] = []
    lines.append("═══ USAi Harness Cost Report ═══")
    lines.append("")
    lines.append(f"Filters:     {filter_line}")
    lines.append(f"Date range:  {date_range}")
    lines.append("")
    lines.append(f"Total runs:  {total_runs:,}")
    lines.append(
        f"Total calls: {total_calls:,} ({total_ok:,} ok, {total_failed:,} failed)"
    )
    lines.append(
        f"Tokens:      {total_in:,} in | {total_out:,} out "
        f"| {total_in + total_out:,} total"
    )
    lines.append(f"Cost:        ${total_cost:.2f}")

    if project is None:
        by_project: Counter = Counter()
        calls_by_project: Counter = Counter()
        for e in entries:
            p = e.get("project", "unknown")
            by_project[p] += float(e.get("estimated_cost", 0.0))
            calls_by_project[p] += int(e.get("total_calls", 0))
        if by_project:
            lines.append("")
            lines.append("By project:")
            for p, cost in sorted(by_project.items()):
                lines.append(
                    f"  {p}: ${cost:.2f} ({calls_by_project[p]:,} calls)"
                )

    if model is None:
        by_model: Counter = Counter()
        calls_by_model: Counter = Counter()
        for e in entries:
            m = e.get("model", "unknown")
            by_model[m] += float(e.get("estimated_cost", 0.0))
            calls_by_model[m] += int(e.get("total_calls", 0))
        if by_model:
            lines.append("")
            lines.append("By model:")
            for m, cost in sorted(by_model.items()):
                lines.append(
                    f"  {m}: ${cost:.2f} ({calls_by_model[m]:,} calls)"
                )

    lines.append("")
    return "\n".join(lines)
