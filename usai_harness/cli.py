"""usai-harness CLI dispatcher (IR-002).

Subcommands:
    report           — render a per-run report from a JSONL log file
    cost-report      — aggregate entries from cost_ledger.jsonl
    init             — first-run setup: credentials and model catalog
    add-provider     — register an additional provider
    discover-models  — refresh the live model catalog
    list-models      — print the merged model catalog (repo + user-level)
    families         — print the family catalog (parameter-acceptance rules)
    schema           — print harness schemas (e.g. `schema project-config`)
    validate-config  — validate a project YAML against the schema
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
    handle_families,
    handle_init,
    handle_list_models,
    handle_ping,
    handle_project_init,
    handle_schema_project_config,
    handle_validate_config,
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

    pi = subparsers.add_parser(
        "project-init",
        help="Bootstrap the current directory as a project (creates layout, runs TEVV)",
    )
    pi.add_argument(
        "--models",
        default=None,
        help=(
            "Comma-separated list of catalog model names for the pool "
            "(e.g. 'gemini-2.5-flash,claude_4_5_sonnet'). When omitted, "
            "project-init prompts interactively or falls back to the "
            "user-level default model."
        ),
    )
    pi.add_argument(
        "--default",
        dest="default_model",
        default=None,
        help=(
            "Default model for the pool. Must be one of --models. Required "
            "when --models has more than one entry and you want to skip the "
            "interactive prompt."
        ),
    )
    pi.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite an existing usai_harness.yaml. By default, "
            "project-init validates the existing file against the schema "
            "and exits non-zero if it is invalid; --force skips that check "
            "and writes a fresh template."
        ),
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

    fam = subparsers.add_parser(
        "families",
        help="Print the family catalog (parameter-acceptance rules with citation tiers)",
    )
    fam.add_argument(
        "--family",
        default=None,
        help="Show the full entry for a single family key (e.g. 'claude-sonnet-4')",
    )
    fam.add_argument(
        "--format",
        choices=["table", "yaml", "markdown"],
        default="table",
        help=(
            "Output format. 'table' is the default. 'yaml' emits the raw "
            "catalog. 'markdown' produces a research-methodology-friendly table."
        ),
    )

    lm = subparsers.add_parser(
        "list-models",
        help="Print the merged model catalog (repo + user-level) for use in pool configs",
    )
    lm.add_argument(
        "--provider",
        help="Filter to one provider (e.g., 'usai', 'openrouter')",
        default=None,
    )
    lm.add_argument(
        "--format",
        choices=["table", "yaml", "names"],
        default="table",
        help=(
            "Output format. 'table' for human reading, 'yaml' for catalog "
            "inspection, 'names' for one-per-line model names suitable for "
            "piping"
        ),
    )

    subparsers.add_parser(
        "verify", help="End-to-end health check of all providers"
    )
    pp = subparsers.add_parser(
        "ping", help="Minimal single-call check of the default provider"
    )
    pp.add_argument(
        "--model", default=None,
        help="Override the default model (useful when the catalog is empty)",
    )

    au = subparsers.add_parser("audit", help="Security hygiene checks")
    au.add_argument(
        "--fix-gitignore", action="store_true",
        help="Append missing entries to .gitignore",
    )

    sch = subparsers.add_parser(
        "schema",
        help="Print harness schemas (machine-readable artifacts)",
    )
    sch_sub = sch.add_subparsers(dest="schema_command", required=True)
    sch_pc = sch_sub.add_parser(
        "project-config",
        help="Print the project-config JSON Schema",
    )
    sch_pc.add_argument(
        "--format",
        choices=["json", "yaml", "markdown"],
        default="json",
        help="Output format. JSON is the canonical artifact.",
    )

    vc = subparsers.add_parser(
        "validate-config",
        help=(
            "Validate a project YAML against the project-config schema. "
            "Pure schema check; does not consult the live catalog or "
            "credentials."
        ),
    )
    vc.add_argument("path", help="Path to the YAML file to validate")

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
    if args.command == "project-init":
        return handle_project_init(
            models_arg=args.models,
            default_arg=args.default_model,
            force=args.force,
        )
    if args.command == "add-provider":
        return handle_add_provider(args.name)
    if args.command == "discover-models":
        return handle_discover_models(args.provider)
    if args.command == "list-models":
        return handle_list_models(provider=args.provider, output_format=args.format)
    if args.command == "families":
        return handle_families(family=args.family, output_format=args.format)
    if args.command == "verify":
        return handle_verify()
    if args.command == "ping":
        return handle_ping(model=args.model)
    if args.command == "audit":
        return handle_audit(fix_gitignore=args.fix_gitignore)
    if args.command == "schema":
        if args.schema_command == "project-config":
            return handle_schema_project_config(output_format=args.format)
    if args.command == "validate-config":
        return handle_validate_config(path=args.path)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(cli_main())
