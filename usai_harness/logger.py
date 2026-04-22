"""Structured Call Logger: JSON-lines logging for every API call.

Responsibilities:
    - Write one JSON line per API call to per-run log file
    - Fields: timestamp, job_id, project, model, prompt_tokens,
      completion_tokens, latency_ms, status_code, error, task_id
    - Create log files in logs/ directory with run timestamp in filename
    - Every call outcome logged regardless of success/failure
    - No swallowed exceptions

Inputs:
    - log_dir: str — directory for log files (default: logs/)
    - job_id: str — identifier for the current run
    - project: str — project name

Outputs:
    - log_call(call_data) — write one log entry
    - get_log_path() — returns path to current run's log file
"""
