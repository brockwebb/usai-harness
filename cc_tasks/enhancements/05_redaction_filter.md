# Central redacting logging filter

## Goal

Reduce the chance that a future logging call forgets to call `redact_secrets()`.

## Why now

`redaction.py` already notes that stdlib logging records are not centrally scrubbed.

The current explicit boundary redaction should remain, but a filter adds defense in depth.

## Proposed behavior

- Attach a `logging.Filter` to the `usai_harness` logger.
- Scrub `record.msg` when it is a string.
- Scrub `record.args` recursively.
- Leave non-harness loggers alone.
- Preserve existing explicit redaction at transport, logger, and client boundaries.

## Acceptance tests

- A log call with `%s` args containing `sk-...` emits redacted text.
- A dict arg containing `USAI_API_KEY=...` emits redacted text.
- A normal log line is unchanged.
- No exception is raised when args are non-string objects.

## Prototype

See `prototypes/redacting_logging_filter.py`.
