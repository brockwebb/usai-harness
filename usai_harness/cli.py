"""usai-harness CLI dispatcher (IR-002).

Subcommands:
    report           — render a per-run report from a JSONL log file
    cost-report      — aggregate entries from cost_ledger.jsonl
    init             — first-run setup: credentials and model catalog
    add-provider     — register an additional provider
    discover-models  — refresh the live model catalog
    verify           — end-to-end health check of all providers
    ping             — minimal single-call check of the default provider
    audit            — security hygiene checks (gitignore, tracked secrets, pip-audit)
"""

import argparse
import sys

from usai_harness.audit_command import handle_audit
from usai_harness.report import cost_report, format_report, generate_report
from usai_harness.setup_commands import (
    handle_add_provider,
    handle_discover_models,
    handle_init,
    handle_ping,
    handle_verify,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="usai-harness",
        description="USAi Harness: rate-limited, model-agnostic LLM client.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    rp = subparsers.add_parser(
        "report", help="Generate run report from a log file"
    )
    rp.add_argument("log_file")

    cp = subparsers.add_parser(
        "cost-report", help="Summarize the cost ledger"
    )
    cp.add_argument("--ledger", default="cost_ledger.jsonl")
    cp.add_argument("--project", default=None)
    cp.add_argument("--model", default=None)

    subparsers.add_parser(
        "init", help="First-run setup: credentials and model catalog"
    )

    ap = subparsers.add_parser(
        "add-provider", help="Register an additional provider"
    )
    ap.add_argument("name", help="Provider identifier, e.g. openrouter")

    dm = subparsers.add_parser(
        "discover-models", help="Refresh the model catalog"
    )
    dm.add_argument(
        "provider", nargs="?", default=None,
        help="Provider to refresh (default: all configured providers)",
    )

    subparsers.add_parser(
        "verify", help="End-to-end health check of all providers"
    )
    subparsers.add_parser(
        "ping", help="Minimal single-call check of the default provider"
    )

    au = subparsers.add_parser("audit", help="Security hygiene checks")
    au.add_argument(
        "--fix-gitignore", action="store_true",
        help="Append missing entries to .gitignore",
    )

    return parser


def cli_main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "report":
        print(format_report(generate_report(args.log_file)))
        return 0
    if args.command == "cost-report":
        print(cost_report(args.ledger, project=args.project, model=args.model))
        return 0
    if args.command == "init":
        return handle_init()
    if args.command == "add-provider":
        return handle_add_provider(args.name)
    if args.command == "discover-models":
        return handle_discover_models(args.provider)
    if args.command == "verify":
        return handle_verify()
    if args.command == "ping":
        return handle_ping()
    if args.command == "audit":
        return handle_audit(fix_gitignore=args.fix_gitignore)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(cli_main())
