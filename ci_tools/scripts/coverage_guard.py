#!/usr/bin/env python3
"""Enforce per-file coverage thresholds using coverage.py data."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

from coverage import Coverage
from coverage.exceptions import CoverageException, NoDataError, NoSource

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CoverageResult:
    path: Path
    statements: int
    missing: int

    @property
    def percent(self) -> float:
        if self.statements == 0:
            return 100.0
        covered = self.statements - self.missing
        return (covered / self.statements) * 100.0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail when any measured file falls below the coverage threshold."
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.environ.get("ZEUS_COVERAGE_THRESHOLD", "80")),
        help="Required per-file coverage percentage (default: 80).",
    )
    parser.add_argument(
        "--data-file",
        default=None,
        help="Coverage data file (defaults to COVERAGE_FILE or .coverage).",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Relative path prefixes to check (repeatable). Defaults to repo root.",
    )
    return parser.parse_args(argv)


def resolve_data_file(candidate: str | None) -> Path:
    raw = candidate or os.environ.get("COVERAGE_FILE") or ".coverage"
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def normalize_prefixes(prefixes: Iterable[str]) -> List[Path]:
    paths: List[Path] = []
    for prefix in prefixes:
        candidate = (ROOT / prefix).resolve()
        paths.append(candidate)
    return paths


def should_include(path: Path, prefixes: Sequence[Path]) -> bool:
    try:
        path.relative_to(ROOT)
    except ValueError:
        return False
    if not prefixes:
        return True
    return any(path == prefix or str(path).startswith(str(prefix) + os.sep) for prefix in prefixes)


def collect_results(cov: Coverage, prefixes: Sequence[Path]) -> List[CoverageResult]:
    try:
        cov.load()
    except NoDataError as exc:
        raise SystemExit(f"coverage_guard: no data found ({exc})") from exc
    data = cov.get_data()
    results: List[CoverageResult] = []
    for filename in sorted(data.measured_files()):
        file_path = Path(filename).resolve()
        if not should_include(file_path, prefixes):
            continue
        try:
            _, statements, _, missing, _ = cov.analysis2(str(file_path))
        except NoSource:
            continue
        total_statements = len(statements)
        missing_count = len(missing)
        results.append(
            CoverageResult(
                path=file_path,
                statements=total_statements,
                missing=missing_count,
            )
        )
    return results


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    data_file = resolve_data_file(args.data_file)
    if not data_file.exists():
        print(f"coverage_guard: coverage data file not found: {data_file}", file=sys.stderr)
        return 1
    cov = Coverage(data_file=str(data_file))
    prefixes = normalize_prefixes(args.include)
    try:
        results = collect_results(cov, prefixes)
    except CoverageException as exc:
        print(f"coverage_guard: failed to load coverage data: {exc}", file=sys.stderr)
        return 1
    threshold = float(args.threshold)
    failures = [
        result
        for result in results
        if result.statements > 0 and result.percent + 1e-9 < threshold
    ]
    if failures:
        print(
            "coverage_guard: per-file coverage below threshold "
            f"({threshold:.2f}%):",
            file=sys.stderr,
        )
        for result in failures:
            rel_path = result.path.relative_to(ROOT)
            covered = result.statements - result.missing
            print(
                f"  {rel_path.as_posix()}: {result.percent:.2f}% "
                f"({covered}/{result.statements} lines covered)",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
