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

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("usai_harness.logger")

REQUIRED_FIELDS: tuple[str, ...] = ("timestamp", "task_id", "model", "status_code")


class CallLogger:
    """JSON-lines structured logger for API calls."""

    def __init__(self, log_dir="logs", job_id: Optional[str] = None,
                 project: Optional[str] = None):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.project = project or "unnamed"

        if job_id is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            job_id = f"{self.project}_{ts}"
        self.job_id = job_id

        self._log_path = self.log_dir / f"{self.job_id}.jsonl"
        self._file = open(self._log_path, "a", encoding="utf-8")
        self._count = 0

    def log_call(self, call_data: dict) -> None:
        missing = [f for f in REQUIRED_FIELDS if f not in call_data]
        if missing:
            raise ValueError(
                f"log_call missing required fields: {missing}. "
                f"Required fields: {list(REQUIRED_FIELDS)}."
            )

        entry: dict = {"job_id": self.job_id, "project": self.project}
        for k, v in call_data.items():
            if v is not None:
                entry[k] = v

        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()
        self._count += 1

    def get_log_path(self) -> Path:
        return self._log_path

    def get_entries(self) -> list[dict]:
        with open(self._log_path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()
            log.info(
                "Closed call log %s (%d entries).",
                self._log_path, self._count,
            )

    def __enter__(self) -> "CallLogger":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False
