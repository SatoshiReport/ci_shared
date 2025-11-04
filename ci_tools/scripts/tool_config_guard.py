#!/usr/bin/env python3
"""
Tool Configuration Guard/Sync Script

Validates that tool configurations in a repository's pyproject.toml match
the shared tool configuration defined in shared-tool-config.toml.

Usage:
    # Validation mode (check only)
    python -m ci_tools.scripts.tool_config_guard --repo-root /path/to/repo

    # Sync mode (update pyproject.toml)
    python -m ci_tools.scripts.tool_config_guard --repo-root /path/to/repo --sync

    # Check current repository
    python -m ci_tools.scripts.tool_config_guard

Exit codes:
    0 - Tool configs match (or successfully synced)
    1 - Tool configs differ (validation mode)
    2 - File errors or invalid arguments
"""

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[import-not-found]  # Fallback for Python 3.10


def load_toml(path: Path) -> dict[str, Any]:
    """Load and parse a TOML file."""
    with path.open("rb") as f:
        return tomllib.load(f)


def extract_tool_config(data: dict[str, Any]) -> dict[str, Any]:
    """Extract [tool.*] sections from pyproject.toml data."""
    return {k: v for k, v in data.items() if k == "tool"}


def compare_configs(
    shared: dict[str, Any], repo: dict[str, Any]
) -> tuple[bool, list[str]]:
    """
    Compare tool configurations.

    The repo can have additional tool subsections beyond what's in shared config.
    We only validate that the shared config's subsections are present and match.

    Returns:
        (matches, differences) where differences is a list of human-readable strings
    """
    differences = []

    if "tool" not in shared:
        return True, []

    if "tool" not in repo:
        differences.append(
            "Repository pyproject.toml is missing [tool] section entirely"
        )
        return False, differences

    shared_tools = shared["tool"]
    repo_tools = repo["tool"]

    # Check for missing or extra tool sections
    shared_keys = set(shared_tools.keys())
    repo_keys = set(repo_tools.keys())

    missing_tools = shared_keys - repo_keys
    # Note: extra tools in repo are OK (repo-specific tools are allowed)

    if missing_tools:
        for tool in sorted(missing_tools):
            differences.append(f"Missing tool configuration: [tool.{tool}]")

    # Compare existing tools - recursively check subsections
    for tool in shared_keys & repo_keys:
        tool_diffs = _compare_tool_section(
            shared_tools[tool], repo_tools[tool], f"tool.{tool}"
        )
        differences.extend(tool_diffs)

    return len(differences) == 0, differences


def _compare_tool_section(shared: Any, repo: Any, path: str) -> list[str]:
    """
    Recursively compare tool config sections.

    Repo can have extra keys/subsections, but all shared keys must match.
    """
    differences = []

    if isinstance(shared, dict) and isinstance(repo, dict):
        # Check that all shared keys exist in repo
        for key, shared_value in shared.items():
            if key not in repo:
                differences.append(f"Missing configuration: [{path}.{key}]")
            else:
                # Recursively compare subsections
                sub_diffs = _compare_tool_section(
                    shared_value, repo[key], f"{path}.{key}"
                )
                differences.extend(sub_diffs)
        # Note: extra keys in repo are OK (repo-specific settings allowed)
    elif shared != repo:
        # Leaf value comparison
        differences.append(
            f"Configuration mismatch: [{path}] (expected: {shared}, got: {repo})"
        )

    return differences


def _format_toml_list(key: str, value: list, indent_str: str) -> list[str]:
    """Format a list value as TOML."""
    import json  # pylint: disable=import-outside-toplevel

    if len(value) == 0:
        return [f"{indent_str}{key} = []"]

    if all(isinstance(x, str) for x in value):
        # Multi-line array
        lines = [f"{indent_str}{key} = ["]
        for item in value:
            lines.append(f'{indent_str}    "{item}",')
        lines.append(f"{indent_str}]")
        return lines

    return [f"{indent_str}{key} = {json.dumps(value)}"]


def _format_toml_value(key: str, value: Any, indent_str: str) -> list[str]:
    """Format a single TOML value."""
    if isinstance(value, dict):
        # Nested table - skip, will be handled separately
        return []
    if isinstance(value, str):
        return [f'{indent_str}{key} = "{value}"']
    if isinstance(value, bool):
        return [f'{indent_str}{key} = {"true" if value else "false"}']
    if isinstance(value, (int, float)):
        return [f"{indent_str}{key} = {value}"]
    if isinstance(value, list):
        return _format_toml_list(key, value, indent_str)
    return []


def format_toml_tool_section(data: dict[str, Any], indent: int = 0) -> str:
    """Format tool configuration data as TOML string."""
    lines = []
    indent_str = "  " * indent

    for key, value in sorted(data.items()):
        lines.extend(_format_toml_value(key, value, indent_str))

    return "\n".join(lines)


def _print_toml_value(key: str, value: Any) -> None:
    """Print a single TOML value."""
    if isinstance(value, str):
        print(f'{key} = "{value}"')
    elif isinstance(value, bool):
        print(f'{key} = {"true" if value else "false"}')
    elif isinstance(value, list):
        _print_toml_list(key, value)
    else:
        print(f"{key} = {value}")


def _print_toml_list(key: str, value: list) -> None:
    """Print a list value as TOML."""
    if all(isinstance(x, str) for x in value):
        print(f"{key} = [")
        for item in value:
            print(f'    "{item}",')
        print("]")
    else:
        print(f"{key} = {value}")


def _print_tool_section(tool_name: str, tool_config: dict[str, Any]) -> None:
    """Print a single tool section with all its values."""
    print(f"[tool.{tool_name}]")

    # Print non-dict values first
    for key, value in sorted(tool_config.items()):
        if not isinstance(value, dict):
            _print_toml_value(key, value)

    # Print subsections
    for key, value in sorted(tool_config.items()):
        if isinstance(value, dict):
            print(f"\n[tool.{tool_name}.{key}]")
            print(format_toml_tool_section(value))

    print()  # Blank line between tools


def print_tool_config_diff(
    shared_data: dict[str, Any],
    repo_data: dict[str, Any],  # pylint: disable=unused-argument
) -> None:
    """Print the tool configuration that should be in pyproject.toml."""
    print("\n" + "=" * 70)
    print("Expected tool configuration (copy to pyproject.toml):")
    print("=" * 70 + "\n")

    if "tool" not in shared_data:
        return

    shared_tools = shared_data["tool"]
    for tool_name in sorted(shared_tools.keys()):
        _print_tool_section(tool_name, shared_tools[tool_name])


def sync_configs(shared_config_path: Path, repo_pyproject_path: Path) -> bool:
    """
    Display instructions for syncing tool configurations.

    Note: This does not automatically modify files to avoid risk of corruption.
    Users should manually copy the tool configurations.

    Returns:
        True (always, since we just display instructions)
    """
    try:
        shared_data = load_toml(shared_config_path)
        repo_data = load_toml(repo_pyproject_path)
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error displaying sync instructions: {e}", file=sys.stderr)
        return False

    print("\n" + "!" * 70)
    print("SYNC MODE: Manual steps required")
    print("!" * 70)
    print(f"\n1. Open {repo_pyproject_path}")
    print("2. Remove all existing [tool.*] sections")
    print("3. Copy the following configuration to the end of the file:")

    print_tool_config_diff(shared_data, repo_data)

    print("=" * 70)
    print("\nAlternative: Copy directly from shared-tool-config.toml")
    print(f"  File location: {shared_config_path}")
    print("=" * 70)

    return True


def _find_shared_config(repo_root: Path, shared_config: Path | None) -> Path:
    """Auto-detect or validate shared config path."""
    if shared_config:
        return shared_config

    # First try relative to this script
    script_dir = Path(__file__).parent.parent.parent
    shared_config_path = script_dir / "shared-tool-config.toml"
    if shared_config_path.exists():
        return shared_config_path

    # Try as sibling directory
    return repo_root.parent / "ci_shared" / "shared-tool-config.toml"


def _validate_paths(shared_config_path: Path, repo_pyproject: Path) -> int | None:
    """Validate that required paths exist. Returns error code or None if valid."""
    if not shared_config_path.exists():
        print(
            f"Error: Shared config not found at {shared_config_path}", file=sys.stderr
        )
        print("Specify path with --shared-config", file=sys.stderr)
        return 2

    if not repo_pyproject.exists():
        print(f"Error: pyproject.toml not found at {repo_pyproject}", file=sys.stderr)
        return 2

    return None


def _handle_config_mismatch(
    repo_pyproject: Path,
    differences: list[str],
    sync_mode: bool,
    shared_config_path: Path,
) -> int:
    """Handle case where configs don't match."""
    status_icon = "✓" if sync_mode else "✗"
    print(
        f"{status_icon} Tool configurations in {repo_pyproject.name} "
        f"differ from shared config:"
    )
    for diff in differences:
        print(f"  - {diff}")

    if sync_mode:
        sync_configs(shared_config_path, repo_pyproject)
        return 0

    print("\nRun with --sync to see update instructions")
    return 1


def main() -> int:
    """Main entry point for tool config guard."""
    parser = argparse.ArgumentParser(
        description="Validate or sync tool configurations across repositories"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Root directory of repository to check (default: current directory)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Sync mode: update pyproject.toml with shared tool config",
    )
    parser.add_argument(
        "--shared-config",
        type=Path,
        help="Path to shared-tool-config.toml (default: auto-detect)",
    )

    args = parser.parse_args()

    shared_config_path = _find_shared_config(args.repo_root, args.shared_config)
    repo_pyproject = args.repo_root / "pyproject.toml"

    error_code = _validate_paths(shared_config_path, repo_pyproject)
    if error_code is not None:
        return error_code

    try:
        shared_data = load_toml(shared_config_path)
        repo_data = load_toml(repo_pyproject)
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error loading TOML files: {e}", file=sys.stderr)
        return 2

    matches, differences = compare_configs(shared_data, repo_data)

    if matches:
        print(f"✓ Tool configurations in {repo_pyproject.name} match shared config")
        return 0

    return _handle_config_mismatch(
        repo_pyproject, differences, args.sync, shared_config_path
    )


if __name__ == "__main__":
    sys.exit(main())
