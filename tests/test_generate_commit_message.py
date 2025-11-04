"""Unit tests for generate_commit_message module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ci_tools.scripts.generate_commit_message import (
    _prepare_payload,
    _read_staged_diff,
    _write_payload,
    main,
    parse_args,
)


def test_parse_args_default():
    """Test parse_args with default arguments."""
    args = parse_args([])
    assert args.model is None
    assert args.reasoning is None
    assert args.detailed is False
    assert args.output is None


def test_parse_args_with_model():
    """Test parse_args with model specified."""
    args = parse_args(["--model", "gpt-5-codex"])
    assert args.model == "gpt-5-codex"


def test_parse_args_with_reasoning():
    """Test parse_args with reasoning specified."""
    args = parse_args(["--reasoning", "high"])
    assert args.reasoning == "high"


def test_parse_args_with_detailed():
    """Test parse_args with detailed flag."""
    args = parse_args(["--detailed"])
    assert args.detailed is True


def test_parse_args_with_output():
    """Test parse_args with output file specified."""
    args = parse_args(["--output", "/tmp/commit.txt"])
    assert args.output == Path("/tmp/commit.txt")


@patch("ci_tools.scripts.generate_commit_message.gather_git_diff")
def test_read_staged_diff(mock_gather_git_diff):
    """Test _read_staged_diff calls gather_git_diff."""
    mock_gather_git_diff.return_value = "diff content"
    result = _read_staged_diff()
    assert result == "diff content"
    mock_gather_git_diff.assert_called_once_with(staged=True)


def test_prepare_payload_summary_only():
    """Test _prepare_payload with summary only."""
    result = _prepare_payload("Fix bug", [])
    assert result == "Fix bug"


def test_prepare_payload_with_body():
    """Test _prepare_payload with summary and body."""
    result = _prepare_payload("Fix bug", ["Details here", "More details"])
    assert result == "Fix bug\nDetails here\nMore details"


def test_prepare_payload_strips_whitespace():
    """Test _prepare_payload strips trailing whitespace and leading/trailing body whitespace."""
    result = _prepare_payload("  Fix bug  ", ["  Details  ", "  More  "])
    # Summary is stripped, trailing whitespace is removed from each line,
    # then the whole body is stripped (removing leading spaces from first line only)
    assert result == "Fix bug\nDetails\n  More"


def test_prepare_payload_empty_body_lines():
    """Test _prepare_payload handles empty body lines."""
    result = _prepare_payload("Fix bug", ["", "  ", ""])
    assert result == "Fix bug"


def test_write_payload_to_stdout(capsys):
    """Test _write_payload writes to stdout when output_path is None."""
    result = _write_payload("Test commit message", None)
    assert result == 0
    captured = capsys.readouterr()
    assert captured.out == "Test commit message\n"


def test_write_payload_to_file(tmp_path):
    """Test _write_payload writes to file when output_path specified."""
    output_file = tmp_path / "commit.txt"
    result = _write_payload("Test commit message", output_file)
    assert result == 0
    assert output_file.read_text() == "Test commit message\n"


def test_write_payload_file_error(tmp_path):
    """Test _write_payload handles OSError."""
    # Try to write to a directory (will cause OSError)
    output_dir = tmp_path / "subdir"
    output_dir.mkdir()
    result = _write_payload("Test commit message", output_dir)
    assert result == 1


@patch("ci_tools.scripts.generate_commit_message.gather_git_diff")
@patch("ci_tools.scripts.generate_commit_message.request_commit_message")
@patch("ci_tools.scripts.generate_commit_message.resolve_model_choice")
@patch("ci_tools.scripts.generate_commit_message.resolve_reasoning_choice")
def test_main_success(
    mock_resolve_reasoning,
    mock_resolve_model,
    mock_request_commit,
    mock_gather_diff,
    capsys,
):
    """Test main with successful commit message generation."""
    mock_gather_diff.return_value = "diff --git a/file.py b/file.py"
    mock_resolve_model.return_value = "gpt-5-codex"
    mock_resolve_reasoning.return_value = "medium"
    mock_request_commit.return_value = ("Fix bug", [])

    result = main([])
    assert result == 0
    captured = capsys.readouterr()
    assert "Fix bug" in captured.out


@patch("ci_tools.scripts.generate_commit_message.gather_git_diff")
def test_main_no_staged_diff(mock_gather_diff):
    """Test main exits with error when no staged diff."""
    mock_gather_diff.return_value = ""
    result = main([])
    assert result == 1


@patch("ci_tools.scripts.generate_commit_message.gather_git_diff")
@patch("ci_tools.scripts.generate_commit_message.request_commit_message")
@patch("ci_tools.scripts.generate_commit_message.resolve_model_choice")
@patch("ci_tools.scripts.generate_commit_message.resolve_reasoning_choice")
def test_main_empty_summary(
    mock_resolve_reasoning,
    mock_resolve_model,
    mock_request_commit,
    mock_gather_diff,
):
    """Test main exits with error when commit message is empty."""
    mock_gather_diff.return_value = "diff --git a/file.py b/file.py"
    mock_resolve_model.return_value = "gpt-5-codex"
    mock_resolve_reasoning.return_value = "medium"
    mock_request_commit.return_value = ("", [])

    result = main([])
    assert result == 1


@patch("ci_tools.scripts.generate_commit_message.gather_git_diff")
@patch("ci_tools.scripts.generate_commit_message.request_commit_message")
@patch("ci_tools.scripts.generate_commit_message.resolve_model_choice")
@patch("ci_tools.scripts.generate_commit_message.resolve_reasoning_choice")
def test_main_codex_exception(
    mock_resolve_reasoning,
    mock_resolve_model,
    mock_request_commit,
    mock_gather_diff,
):
    """Test main handles Codex exceptions."""
    mock_gather_diff.return_value = "diff --git a/file.py b/file.py"
    mock_resolve_model.return_value = "gpt-5-codex"
    mock_resolve_reasoning.return_value = "medium"
    mock_request_commit.side_effect = Exception("Codex failed")

    result = main([])
    assert result == 1


@patch("ci_tools.scripts.generate_commit_message.gather_git_diff")
@patch("ci_tools.scripts.generate_commit_message.request_commit_message")
@patch("ci_tools.scripts.generate_commit_message.resolve_model_choice")
@patch("ci_tools.scripts.generate_commit_message.resolve_reasoning_choice")
def test_main_with_detailed_flag(
    mock_resolve_reasoning,
    mock_resolve_model,
    mock_request_commit,
    mock_gather_diff,
    capsys,
):
    """Test main with detailed flag includes body."""
    mock_gather_diff.return_value = "diff --git a/file.py b/file.py"
    mock_resolve_model.return_value = "gpt-5-codex"
    mock_resolve_reasoning.return_value = "medium"
    mock_request_commit.return_value = ("Fix bug", ["Detailed explanation"])

    result = main(["--detailed"])
    assert result == 0
    captured = capsys.readouterr()
    assert "Fix bug" in captured.out
    assert "Detailed explanation" in captured.out


@patch("ci_tools.scripts.generate_commit_message.gather_git_diff")
@patch("ci_tools.scripts.generate_commit_message.request_commit_message")
@patch("ci_tools.scripts.generate_commit_message.resolve_model_choice")
@patch("ci_tools.scripts.generate_commit_message.resolve_reasoning_choice")
def test_main_with_output_file(
    mock_resolve_reasoning,
    mock_resolve_model,
    mock_request_commit,
    mock_gather_diff,
    tmp_path,
):
    """Test main writes to output file when specified."""
    output_file = tmp_path / "commit.txt"
    mock_gather_diff.return_value = "diff --git a/file.py b/file.py"
    mock_resolve_model.return_value = "gpt-5-codex"
    mock_resolve_reasoning.return_value = "medium"
    mock_request_commit.return_value = ("Fix bug", [])

    result = main(["--output", str(output_file)])
    assert result == 0
    assert output_file.exists()
    assert "Fix bug" in output_file.read_text()


@patch.dict("os.environ", {"CI_COMMIT_MODEL": "gpt-5-codex"})
@patch("ci_tools.scripts.generate_commit_message.gather_git_diff")
@patch("ci_tools.scripts.generate_commit_message.request_commit_message")
@patch("ci_tools.scripts.generate_commit_message.resolve_model_choice")
@patch("ci_tools.scripts.generate_commit_message.resolve_reasoning_choice")
def test_main_uses_env_var_for_model(
    mock_resolve_reasoning,
    mock_resolve_model,
    mock_request_commit,
    mock_gather_diff,
    capsys,
):
    """Test main uses CI_COMMIT_MODEL env var."""
    mock_gather_diff.return_value = "diff --git a/file.py b/file.py"
    mock_resolve_model.return_value = "gpt-5-codex"
    mock_resolve_reasoning.return_value = "medium"
    mock_request_commit.return_value = ("Fix bug", [])

    result = main([])
    assert result == 0
    mock_resolve_model.assert_called_once_with("gpt-5-codex", validate=False)


@patch.dict("os.environ", {"CI_COMMIT_REASONING": "high"})
@patch("ci_tools.scripts.generate_commit_message.gather_git_diff")
@patch("ci_tools.scripts.generate_commit_message.request_commit_message")
@patch("ci_tools.scripts.generate_commit_message.resolve_model_choice")
@patch("ci_tools.scripts.generate_commit_message.resolve_reasoning_choice")
def test_main_uses_env_var_for_reasoning(
    mock_resolve_reasoning,
    mock_resolve_model,
    mock_request_commit,
    mock_gather_diff,
    capsys,
):
    """Test main uses CI_COMMIT_REASONING env var."""
    mock_gather_diff.return_value = "diff --git a/file.py b/file.py"
    mock_resolve_model.return_value = "gpt-5-codex"
    mock_resolve_reasoning.return_value = "high"
    mock_request_commit.return_value = ("Fix bug", [])

    result = main([])
    assert result == 0
    mock_resolve_reasoning.assert_called_once_with("high", validate=False)
