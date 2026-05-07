"""usai-harness: Rate-limited, model-agnostic LLM client for USAi.

Public API:
    USAiClient    — main entry point for all LLM calls
    BatchResult   — per-task result returned by `batch()` and surfaced on `ProgressEvent.result`
    ProgressEvent — frozen dataclass delivered to `batch(progress=...)` callbacks
    text_progress — built-in text formatter (the default `batch()` progress callback)
"""

from usai_harness.client import USAiClient
from usai_harness.progress import ProgressEvent, text_progress
from usai_harness.worker_pool import BatchResult

__all__ = ["USAiClient", "BatchResult", "ProgressEvent", "text_progress"]
__version__ = "0.8.1"
