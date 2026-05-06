"""usai-harness: Rate-limited, model-agnostic LLM client for USAi.

Public API:
    USAiClient    — main entry point for all LLM calls
    ProgressEvent — frozen dataclass delivered to `batch(progress=...)` callbacks
    text_progress — built-in text formatter (the default `batch()` progress callback)
"""

from usai_harness.client import USAiClient
from usai_harness.progress import ProgressEvent, text_progress

__all__ = ["USAiClient", "ProgressEvent", "text_progress"]
__version__ = "0.8.0"
