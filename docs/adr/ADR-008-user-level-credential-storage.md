# ADR-008: User-Level Credential Storage

**Status:** Accepted
**Date:** 2026-04-24

## Context

The value proposition of the harness is credential management that works across many projects. USAi keys rotate every 7 days. A researcher running five active projects does not want to update five copies of `.env` on every rotation. The friction pushes people toward unsafe shortcuts: committing keys, emailing them, pasting them into shared drives.

The default behavior of `python-dotenv` is to read `.env` from the current working directory. Per-project `.env` files are the usual pattern and the wrong pattern for this use case. We want one canonical key location per machine, per user, with a clear override mechanism when a project genuinely needs its own credentials.

Symlinks were considered. They are the wrong primitive. Windows requires administrator privileges or Developer Mode to create them, they commit to git in surprising ways, and they still put a file-shaped object in the project directory where accidental tracking is possible.

The right primitive is a user-level configuration directory, which is what well-behaved CLI tools use (aws, gcloud, docker, gh, terraform).

## Decision

`DotEnvProvider` resolves credentials in the following order, stopping at the first match that yields a non-empty key for the requested provider:

1. **Project-local `.env`** in the current working directory. Present when the project explicitly overrides the user default.
2. **User-level `.env`** in the user's configuration directory. Default location for machine-wide keys.
3. **OS environment variable** named by `api_key_env` in the provider configuration. Fallback for CI, containers, and orchestrator-managed environments.

The user-level directory is computed per operating system without introducing a new dependency:

- Linux: `$XDG_CONFIG_HOME/usai-harness/.env`, defaulting to `~/.config/usai-harness/.env` when `XDG_CONFIG_HOME` is unset.
- macOS: `~/.config/usai-harness/.env`. The XDG convention is used on macOS for consistency with cross-platform CLI tooling. Users who prefer `~/Library/Application Support/usai-harness/.env` can symlink it, but the default is `~/.config`.
- Windows: `%APPDATA%\usai-harness\.env`.

Path resolution is implemented in approximately ten lines of code using `os.environ` and `sys.platform`. Adding a dependency (`platformdirs` or similar) would violate the three-hard-dependency rule from ADR-005, and the logic is simple enough that the dependency would not be worth its install cost.

Projects that need their own credentials place a `.env` in the project root. It takes precedence. No code change needed.

CI environments and containers set credentials as environment variables. No file is required. The resolution order handles all three cases without branching in the caller.

## Consequences

One rotation updates every project. When the USAi key changes, the researcher runs `usai-harness init` (see ADR-009) or edits the user-level `.env` once. Every project using the harness, across that machine, picks up the new key on its next call.

Per-project override remains available. A researcher who needs a different key for a specific project places a local `.env`. Nothing else changes.

CI and container behavior is unchanged. Pipelines that set environment variables continue to work without producing a user-level file.

The harness is not installed into a writable project directory. In particular, no credentials live inside the harness package source tree. Pip-installed harnesses work the same as editable installs. Keys are user data; the harness is code.

Cross-platform behavior is explicit. No ambiguity about where to look.

The resolution order is documented in the operations guide. The `usai-harness audit` command reports which source provided the active credential, so users can confirm they are reading what they think they are reading.
