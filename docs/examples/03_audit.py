"""Programmatic security audit.

Most users should run `usai-harness audit` from the command line. This
script is for callers that want to wire the same checks into a custom
hook (pre-commit, CI step, internal tool) and observe the exit code.

The audit handler is currently exposed under `usai_harness.audit_command`
rather than the top-level package. That is an API surface gap noted in
the Task 13 report-back; importing from the submodule is supported and
stable.

Run from the project root:

    python docs/examples/03_audit.py
    echo "exit code: $?"

Exit codes:
    0  every check passed
    1  at least one finding (gitignore gap, tracked secret, pip-audit failure)
"""

import sys
from pathlib import Path

from usai_harness.audit_command import handle_audit


def main() -> int:
    repo_root = Path.cwd()
    rc = handle_audit(repo_root=repo_root, fix_gitignore=False)
    if rc != 0:
        print()
        print(
            "Findings present. Review the report above. "
            "Re-run `usai-harness audit --fix-gitignore` to "
            "auto-append missing gitignore patterns."
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())
