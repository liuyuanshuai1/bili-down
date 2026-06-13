"""Startup prerequisite checks.

These run before any expensive work so missing prerequisites (Python version,
external executables, configuration, writable output directory) fail fast.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig

MINIMUM_PYTHON = (3, 12)
REQUIRED_EXECUTABLES = ("yt-dlp", "ffmpeg")


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def check_python_version(
    *,
    minimum: tuple[int, int] = MINIMUM_PYTHON,
    current: tuple[int, ...] | None = None,
) -> CheckResult:
    current = current if current is not None else sys.version_info[:3]
    ok = tuple(current[: len(minimum)]) >= minimum
    wanted = ".".join(str(p) for p in minimum)
    have = ".".join(str(p) for p in current)
    detail = f"requires Python >= {wanted}, found {have}"
    return CheckResult(name=f"Python {wanted}+", ok=ok, detail=detail)


def check_executable(
    name: str, *, finder: Callable[[str], str | None] = shutil.which
) -> CheckResult:
    path = finder(name)
    if path:
        return CheckResult(name=f"executable: {name}", ok=True, detail=path)
    return CheckResult(
        name=f"executable: {name}",
        ok=False,
        detail=f"{name} not found on PATH",
    )


def check_output_dir(path: str | Path) -> CheckResult:
    target = Path(path)
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".bili-text-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return CheckResult(
            name=f"output dir: {target}",
            ok=False,
            detail=f"not writable: {exc}",
        )
    return CheckResult(name=f"output dir: {target}", ok=True, detail=str(target))


def run_startup_checks(
    config: AppConfig,
    *,
    which: Callable[[str], str | None] = shutil.which,
    current_version: tuple[int, ...] | None = None,
) -> list[CheckResult]:
    results = [check_python_version(current=current_version)]
    results.extend(check_executable(name, finder=which) for name in REQUIRED_EXECUTABLES)
    results.append(check_output_dir(config.output_dir))
    return results


def failed_checks(results: Sequence[CheckResult]) -> list[CheckResult]:
    return [result for result in results if not result.ok]
