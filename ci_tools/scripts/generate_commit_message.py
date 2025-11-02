#!/usr/bin/env python3
"""Helper invoked by ci.sh to request commit messages from Codex."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ci_tools.ci import gather_git_diff, request_commit_message


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a commit message via Codex")
    parser.add_argument("--model", help="Model name to pass to Codex")
    parser.add_argument(
        "--reasoning",
        help="Reasoning effort to request (low/medium/high)",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Request a body along with the subject (used for auto-push mode)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional file to write the commit summary/body (suppresses stdout).",
    )
    parser.set_defaults(model=None, reasoning=None, output=None)
    return parser.parse_args(argv)


def _resolve_model_choice(args: argparse.Namespace) -> str:
    return (
        args.model
        or os.environ.get("CI_COMMIT_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or "gpt-5-codex"
    )


def _resolve_reasoning_choice(args: argparse.Namespace) -> str:
    return (
        args.reasoning
        or os.environ.get("CI_COMMIT_REASONING")
        or os.environ.get("OPENAI_REASONING_EFFORT")
        or "high"
    )


def _read_staged_diff() -> str:
    return gather_git_diff(staged=True)


def _prepare_payload(summary: str, body_lines: list[str]) -> str:
    body = "\n".join(line.rstrip() for line in body_lines).strip()
    payload_lines = [summary.strip()]
    if body:
        payload_lines.append(body)
    return "\n".join(payload_lines)


def _write_payload(payload: str, output_path: Path | None) -> int | None:
    if output_path is None:
        print(payload)
        return 0
    try:
        output_path.write_text(payload + "\n")
    except OSError as exc:
        print(
            f"Failed to write commit message to {output_path}: {exc}", file=sys.stderr
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    model = _resolve_model_choice(args)
    reasoning = _resolve_reasoning_choice(args)

    staged_diff = _read_staged_diff()
    if not staged_diff.strip():
        print(
            "No staged diff available for commit message generation.", file=sys.stderr
        )
        return 1

    try:
        summary, body_lines = request_commit_message(
            model=model,
            reasoning_effort=reasoning,
            staged_diff=staged_diff,
            extra_context="",
            detailed=args.detailed,
        )
    except Exception as exc:  # pragma: no cover - defensive guardrail
        print(f"Codex commit message request failed: {exc}", file=sys.stderr)
        return 1

    summary = summary.strip()
    if not summary:
        print("Codex commit message response was empty.", file=sys.stderr)
        return 1

    payload = _prepare_payload(summary, body_lines)
    result = _write_payload(payload, args.output)
    return result if result is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
