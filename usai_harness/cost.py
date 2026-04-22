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
