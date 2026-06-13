"""Command-line entry point.

This slice wires argument parsing, configuration loading, and startup checks.
Pipeline orchestration is provided by a later slice; once prerequisites pass
this command reports readiness and exits successfully.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import AppConfig, ConfigError, load_config, redact_secrets
from .deps import build_pipeline_deps
from .orchestrator import run_task, task_exit_code
from .startup import failed_checks, run_startup_checks

EXIT_OK = 0
EXIT_STARTUP_FAILED = 1
EXIT_CONFIG_ERROR = 2
EXIT_PARTIAL = 3
EXIT_ALL_FAILED = 4

DEFAULT_DOTENV = ".env"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bili-text",
        description=(
            "Transcribe and summarize the latest video of one or more "
            "Bilibili creators (by UID)."
        ),
    )
    parser.add_argument(
        "uids",
        nargs="+",
        metavar="UID",
        help="One or more Bilibili creator UIDs, processed in order.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Root directory for generated Markdown artifacts (default: CWD).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _print_err(message: str) -> None:
    print(message, file=sys.stderr)


def _print_status(message: str) -> None:
    print(message)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    dotenv_path = DEFAULT_DOTENV if Path(DEFAULT_DOTENV).exists() else None
    secret_pool = list((environ or {}).values())

    try:
        config: AppConfig = load_config(
            environ=environ,
            dotenv_path=dotenv_path,
            output_dir=args.output_dir,
        )
    except ConfigError as exc:
        _print_err(redact_secrets(f"Configuration error: {exc}", secret_pool))
        return EXIT_CONFIG_ERROR

    results = run_startup_checks(config, which=shutil.which)
    failures = failed_checks(results)
    if failures:
        _print_err("Startup checks failed:")
        for failure in failures:
            line = f"  - {failure.name}: {failure.detail}"
            _print_err(redact_secrets(line, config))
        return EXIT_STARTUP_FAILED

    _print_status(f"Prerequisites OK. Processing {len(args.uids)} UID(s).")
    task = run_task(args.uids, config, build_pipeline_deps(), reporter=_print_status)
    return task_exit_code(task)


if __name__ == "__main__":
    raise SystemExit(main())
