"""Shared test fixtures and utilities for guard tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


def write_module(path: Path, content: str) -> None:
    """Helper to write Python module content.

    Args:
        path: Path to write the module to (parent directory will be created)
        content: Module source code (will be dedented and stripped)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


@pytest.fixture
def policy_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a temporary policy context root for testing.

    Args:
        tmp_path: Pytest temporary directory fixture
        monkeypatch: Pytest monkeypatch fixture

    Returns:
        Path to the temporary root directory
    """
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    return tmp_path


def setup_policy_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    filename: str = "module.py",
) -> Path:
    """Set up a module for policy testing.

    Args:
        tmp_path: Temporary directory
        monkeypatch: Pytest monkeypatch fixture
        source: Source code for the module
        filename: Name of the module file (default: module.py)

    Returns:
        Path to the created module
    """
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    module_path = tmp_path / filename
    write_module(module_path, source)
    return module_path


def assert_collector_finds_issue(collector_func, source: str, root_path: Path) -> list:
    """Assert that a collector function finds at least one issue in the source.

    Args:
        collector_func: Collector function to call
        source: Python source code to analyze
        root_path: Policy root directory

    Returns:
        Results from the collector function
    """
    write_module(root_path / "module.py", source)
    results = list(collector_func())
    assert len(results) >= 1, f"{collector_func.__name__} found no issues"
    return results


def assert_collector_finds_token(
    collector_func, source: str, expected_token: str, root_path: Path
) -> list:
    """Assert that a collector function finds a specific token.

    Args:
        collector_func: Collector function to call
        source: Python source code to analyze
        expected_token: Token that should be found
        root_path: Policy root directory

    Returns:
        Results from the collector function
    """
    results = assert_collector_finds_issue(collector_func, source, root_path)
    assert any(
        token == expected_token for _, _, token in results
    ), f"Token '{expected_token}' not found in results"
    return results


def assert_collector_finds_reason(
    collector_func, source: str, expected_reason: str, root_path: Path
) -> list:
    """Assert that a collector function finds an issue with a specific reason.

    Args:
        collector_func: Collector function to call
        source: Python source code to analyze
        expected_reason: Substring that should appear in reason
        root_path: Policy root directory

    Returns:
        Results from the collector function
    """
    results = assert_collector_finds_issue(collector_func, source, root_path)
    assert any(
        expected_reason in reason for _, _, reason in results
    ), f"Reason containing '{expected_reason}' not found in results"
    return results
