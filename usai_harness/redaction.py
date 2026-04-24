"""Secret redaction for logs, error messages, and stack traces.

Security policy (ADR-007, SEC-001): any output path that writes to disk or
stderr passes through redact_secrets() first. Bearer tokens and configured
key-shaped strings are replaced with fixed placeholders before the output is
emitted.

Coverage:
    - `Bearer <token>` substrings (case insensitive).
    - `*_API_KEY` / `*_KEY` assignments from known providers
      (USAI, OPENROUTER, ANTHROPIC, OPENAI, AZURE, AWS, GOOGLE).
    - Bare `sk-` prefixed tokens (OpenAI-style).

Not covered here:
    - stdlib `logging` output to stderr. Callers must scrub strings before
      handing them to log.*. This module does that for known paths; new code
      must do the same.
    - Uncaught exceptions that bubble out of the harness. If a user's program
      prints the stack trace, that is outside the harness boundary.
    - Environment variables in the process image. Python-level limit.

A future improvement is a `logging.Filter` that scrubs every log record
centrally. Deferred to keep this module targeted and auditable.
"""

import re
from typing import Any

_BEARER_RE = re.compile(
    r"(Bearer\s+)[A-Za-z0-9._\-]{16,}",
    re.IGNORECASE,
)

_KEY_ASSIGN_RE = re.compile(
    r"((?:USAI|OPENROUTER|ANTHROPIC|OPENAI|AZURE|AWS|GOOGLE)_(?:API_)?KEY"
    r"[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9._\-]{16,})",
    re.IGNORECASE,
)

_BARE_KEY_RE = re.compile(r"(sk-[A-Za-z0-9._\-]{20,})")

_REDACTED = "***REDACTED***"


def redact_secrets(value: Any) -> Any:
    """Return value with secret-shaped substrings replaced by placeholders.

    Strings are scrubbed with all three rules. Dicts, lists, and tuples are
    walked recursively, scrubbing every string leaf. Non-string, non-container
    values pass through unchanged.

    Pure and side-effect free. Does not mutate its argument.
    """
    if isinstance(value, str):
        out = _BEARER_RE.sub(r"\1" + _REDACTED, value)
        out = _KEY_ASSIGN_RE.sub(r"\1" + _REDACTED, out)
        out = _BARE_KEY_RE.sub(_REDACTED, out)
        return out
    if isinstance(value, dict):
        return {k: redact_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(v) for v in value)
    return value
