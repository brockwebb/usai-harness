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


def cli_main():
    """Entry point for `usai-harness cost-report`. Implementation pending."""
    raise NotImplementedError("cli_main implementation pending")
