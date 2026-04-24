"""`usai-harness audit` subcommand (ADR-007, FR-035).

Three checks:
    1. Gitignore coverage (required patterns present as exact lines).
    2. Tracked-secret scan (git ls-files + regex for Bearer / *_API_KEY).
       File + line number reported; matched value is never printed.
    3. pip-audit invocation (soft-fail if pip-audit is not installed).
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

REQUIRED_GITIGNORE_PATTERNS = [
    ".env",
    "cost_ledger.jsonl",
    "logs/",
    ".usai_key_meta.json",
    "cc_tasks/",
    "handoffs/",
]

_BEARER_RE = re.compile(r"Bearer [A-Za-z0-9._\-]{16,}")
_APIKEY_RE = re.compile(
    r"(USAI|OPENROUTER|ANTHROPIC|OPENAI)_API_KEY\s*=\s*[A-Za-z0-9._\-]{16,}"
)


def _read_gitignore_lines(gitignore_path: Path) -> list[str]:
    if not gitignore_path.exists():
        return []
    return [
        line.strip() for line in gitignore_path.read_text().splitlines()
    ]


def _check_gitignore(
    repo_root: Path, fix: bool = False,
) -> tuple[bool, list[str]]:
    """Return (passed, missing_patterns). If fix=True, append missing patterns."""
    gitignore = repo_root / ".gitignore"
    present = set(_read_gitignore_lines(gitignore))
    missing = [p for p in REQUIRED_GITIGNORE_PATTERNS if p not in present]

    if not missing:
        return True, []

    if fix:
        with gitignore.open("a", encoding="utf-8") as f:
            existing = gitignore.read_text() if gitignore.exists() else ""
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write("\n# Added by usai-harness audit --fix-gitignore\n")
            for p in missing:
                f.write(f"{p}\n")
        return True, missing
    return False, missing


def _list_tracked_files(repo_root: Path) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    files: list[Path] = []
    for rel in out.stdout.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        p = repo_root / rel
        if p.is_file():
            files.append(p)
    return files


def _scan_for_secrets(
    repo_root: Path,
) -> list[tuple[Path, int, str]]:
    """Return list of (file_path, line_number, pattern_label). Never returns values."""
    hits: list[tuple[Path, int, str]] = []
    for f in _list_tracked_files(repo_root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _BEARER_RE.search(line):
                hits.append((f, i, "Bearer token literal"))
            if _APIKEY_RE.search(line):
                hits.append((f, i, "*_API_KEY literal"))
    return hits


def _run_pip_audit() -> tuple[int, str]:
    """Invoke pip-audit. Return (exit_code, detail). exit 0 if not installed."""
    try:
        result = subprocess.run(
            ["pip-audit", "--progress-spinner=off"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return 0, "pip-audit not installed (pip install pip-audit to enable)"
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def handle_audit(
    fix_gitignore: bool = False,
    repo_root: Optional[Path] = None,
) -> int:
    """Security-hygiene checks. Returns 0 if all pass, non-zero otherwise."""
    repo_root = repo_root or Path.cwd()
    failures = 0

    print("usai-harness audit")
    print(f"  Repo: {repo_root}")
    print()

    # Gitignore coverage
    passed, missing = _check_gitignore(repo_root, fix=fix_gitignore)
    if passed and not missing:
        print("  [gitignore] ok")
    elif passed and missing:
        print(f"  [gitignore] fixed: appended {len(missing)} patterns: {missing}")
    else:
        print(
            f"  [gitignore] FAIL: missing patterns: {missing}. "
            f"Re-run with --fix-gitignore to append."
        )
        failures += 1

    # Tracked-secret scan
    hits = _scan_for_secrets(repo_root)
    if not hits:
        print("  [secrets]  ok")
    else:
        print(f"  [secrets]  FAIL: {len(hits)} potential secret(s) in tracked files")
        for path, line, label in hits:
            rel = path.relative_to(repo_root) if path.is_relative_to(repo_root) else path
            print(f"    {rel}:{line} ({label})")
        failures += 1

    # pip-audit
    rc, detail = _run_pip_audit()
    if rc == 0:
        print("  [pip-audit] ok")
        if detail.strip():
            for line in detail.strip().splitlines():
                print(f"    {line}")
    else:
        print(f"  [pip-audit] FAIL (exit {rc})")
        for line in detail.strip().splitlines():
            print(f"    {line}")
        failures += 1

    print()
    print(f"  {failures} failure(s)." if failures else "  All checks passed.")
    return 0 if failures == 0 else 1
