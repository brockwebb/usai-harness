"""usai-harness: Rate-limited, model-agnostic LLM client for USAi.

Public API:
    USAiClient    — main entry point for all LLM calls
    ProgressEvent — frozen dataclass delivered to `batch(progress=...)` callbacks
"""

from usai_harness.client import USAiClient
from usai_harness.progress import ProgressEvent

__all__ = ["USAiClient", "ProgressEvent"]
__version__ = "0.8.0"
