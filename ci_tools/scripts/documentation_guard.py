#!/usr/bin/env python3
"""Fail the build when required documentation is missing.

Binary decision: Either we have the docs or we don't. No thresholds, no warnings.

Auto-Discovery:
    - Base docs: README.md, CLAUDE.md always required
    - Module docs: Every directory in src/ gets a README.md
    - Architecture docs: docs/architecture/*.md files that exist are validated
    - Domain docs: docs/domains/*/ directories that exist require README.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify required documentation exists. FAIL on missing required docs."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repository root directory (defaults to current directory).",
    )
    return parser.parse_args()


def discover_src_modules(root: Path) -> List[str]:
    """Auto-discover all top-level modules in src/ that need README.md files.

    Returns paths like: src/collect_data/README.md, src/modeling/README.md
    """
    required = []
    src_dir = root / "src"

    if not src_dir.exists():
        return required

    for item in src_dir.iterdir():
        if not item.is_dir():
            continue
        if item.name.startswith("_"):  # Skip __pycache__, etc.
            continue
        if item.name == ".git":
            continue

        # Count Python files in this module
        py_files = list(item.rglob("*.py"))
        if len(py_files) > 0:  # If it has any Python files, it needs a README
            readme_path = f"src/{item.name}/README.md"
            required.append(readme_path)

    return required


def discover_architecture_docs(root: Path) -> List[str]:
    """Auto-discover architecture docs in docs/architecture/.

    If docs/architecture/ exists and has .md files, require docs/architecture/README.md
    """
    required = []
    arch_dir = root / "docs" / "architecture"

    if not arch_dir.exists():
        return required

    # If architecture directory exists, it needs a README
    md_files = list(arch_dir.glob("*.md"))
    if len(md_files) > 0:
        required.append("docs/architecture/README.md")

    return required


def discover_domain_docs(root: Path) -> List[str]:
    """Auto-discover domain docs in docs/domains/*/.

    Each subdirectory in docs/domains/ needs a README.md
    """
    required = []
    domains_dir = root / "docs" / "domains"

    if not domains_dir.exists():
        return required

    for item in domains_dir.iterdir():
        if not item.is_dir():
            continue
        if item.name.startswith("_"):
            continue

        # Each domain needs a README
        readme_path = f"docs/domains/{item.name}/README.md"
        required.append(readme_path)

    return required


def discover_operations_docs(root: Path) -> List[str]:
    """Auto-discover operations docs in docs/operations/.

    If docs/operations/ exists, it needs a README.md
    """
    required = []
    ops_dir = root / "docs" / "operations"

    if ops_dir.exists():
        required.append("docs/operations/README.md")

    return required


def discover_reference_docs(root: Path) -> List[str]:
    """Auto-discover reference docs in docs/reference/*/.

    Each subdirectory in docs/reference/ needs a README.md
    """
    required = []
    ref_dir = root / "docs" / "reference"

    if not ref_dir.exists():
        return required

    for item in ref_dir.iterdir():
        if not item.is_dir():
            continue
        if item.name.startswith("_"):
            continue

        # Each reference section needs a README
        readme_path = f"docs/reference/{item.name}/README.md"
        required.append(readme_path)

    return required


def get_base_requirements(root: Path) -> List[str]:
    """Base documentation that's always required."""
    required = [
        "README.md",  # Project README always required
    ]

    # CLAUDE.md is required if it exists (once created, must be maintained)
    claude_md = root / "CLAUDE.md"
    if claude_md.exists():
        required.append("CLAUDE.md")

    # docs/README.md is required if docs/ directory exists
    docs_dir = root / "docs"
    if docs_dir.exists():
        required.append("docs/README.md")

    return required


def discover_all_requirements(root: Path) -> Tuple[List[str], dict]:
    """Discover all documentation requirements automatically.

    Returns: (required_docs, discovery_info)
    """
    required = []
    info = {}

    # Base requirements
    base = get_base_requirements(root)
    required.extend(base)
    info["base"] = base

    # Module READMEs
    modules = discover_src_modules(root)
    required.extend(modules)
    info["modules"] = modules

    # Architecture docs
    arch = discover_architecture_docs(root)
    required.extend(arch)
    info["architecture"] = arch

    # Domain docs
    domains = discover_domain_docs(root)
    required.extend(domains)
    info["domains"] = domains

    # Operations docs
    ops = discover_operations_docs(root)
    required.extend(ops)
    info["operations"] = ops

    # Reference docs
    ref = discover_reference_docs(root)
    required.extend(ref)
    info["reference"] = ref

    return required, info


def check_required_docs(root: Path, required: List[str]) -> List[str]:
    """Return list of missing required documentation files."""
    missing: List[str] = []
    for doc_path in required:
        full_path = root / doc_path
        if not full_path.exists():
            missing.append(doc_path)

    return missing


CATEGORY_KEYS = [
    ("Base", "base"),
    ("Modules", "modules"),
    ("Architecture", "architecture"),
    ("Domains", "domains"),
    ("Operations", "operations"),
    ("Reference", "reference"),
]


def _group_missing_docs(
    missing: List[str], discovery_info: dict
) -> dict[str, List[str]]:
    grouped: dict[str, List[str]] = {label: [] for label, _ in CATEGORY_KEYS}
    for doc in missing:
        for label, key in CATEGORY_KEYS:
            if doc in discovery_info.get(key, []):
                grouped[label].append(doc)
                break
    return grouped


def _print_failure_report(
    grouped: dict[str, List[str]],
) -> None:
    print("Documentation Guard: FAILED", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("❌ Missing required documentation:", file=sys.stderr)
    print("", file=sys.stderr)
    for category, docs in grouped.items():
        if not docs:
            continue
        print(f"  {category}:", file=sys.stderr)
        for doc in docs:
            print(f"    • {doc}", file=sys.stderr)
        print("", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("Build FAILED: Create the missing documentation files.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Requirements auto-discovered from repository structure:", file=sys.stderr)
    print(
        "  • Base: README.md, CLAUDE.md (if exists), docs/README.md",
        file=sys.stderr,
    )
    print("  • Modules: Every directory in src/ with Python files", file=sys.stderr)
    print(
        "  • Architecture: docs/architecture/README.md (if architecture docs exist)",
        file=sys.stderr,
    )
    print("  • Domains: Every subdirectory in docs/domains/", file=sys.stderr)
    print(
        "  • Operations: docs/operations/README.md (if operations dir exists)",
        file=sys.stderr,
    )
    print("  • Reference: Every subdirectory in docs/reference/", file=sys.stderr)


def _print_success(total_docs: int) -> None:
    print("✅ documentation_guard: All required documentation present", file=sys.stderr)
    print(f"   ({total_docs} docs verified)", file=sys.stderr)


def main() -> int:
    args = parse_args()
    root = args.root.resolve()

    if not root.exists():
        print(f"documentation_guard: root path does not exist: {root}", file=sys.stderr)
        return 1

    # Auto-discover all documentation requirements
    required_docs, discovery_info = discover_all_requirements(root)

    # Check for missing docs
    missing = check_required_docs(root, required_docs)

    if missing:
        grouped = _group_missing_docs(missing, discovery_info)
        _print_failure_report(grouped)
        return 1

    _print_success(len(required_docs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
