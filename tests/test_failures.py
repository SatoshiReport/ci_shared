"""Unit tests for ci_tools.ci_runtime.failures module."""

from __future__ import annotations

from unittest.mock import patch
from types import SimpleNamespace

import pytest

from ci_tools.ci_runtime.failures import (
    _gather_focused_diff,
    _render_coverage_context,
    build_failure_context,
)
from ci_tools.ci_runtime.models import (
    CommandResult,
    CoverageCheckResult,
    CoverageDeficit,
    FailureContext,
    CiAbort,
)


class TestGatherFocusedDiff:
    """Tests for _gather_focused_diff helper function."""

    def test_gathers_diffs_for_implicated_files(self):
        """Test gathers diffs for all implicated files."""
        with patch("ci_tools.ci_runtime.failures.gather_file_diff") as mock_diff:
            mock_diff.side_effect = ["diff for file1", "diff for file2"]
            result = _gather_focused_diff(["file1.py", "file2.py"])
            assert "diff for file1" in result
            assert "diff for file2" in result
            assert mock_diff.call_count == 2

    def test_skips_files_with_empty_diffs(self):
        """Test skips files that have no diff."""
        with patch("ci_tools.ci_runtime.failures.gather_file_diff") as mock_diff:
            mock_diff.side_effect = ["diff content", ""]
            result = _gather_focused_diff(["file1.py", "file2.py"])
            assert "diff content" in result
            assert result.count("\n\n") == 0  # Only one diff, no separator

    def test_joins_multiple_diffs_with_double_newline(self):
        """Test joins multiple diffs with double newline separator."""
        with patch("ci_tools.ci_runtime.failures.gather_file_diff") as mock_diff:
            mock_diff.side_effect = ["diff1", "diff2", "diff3"]
            result = _gather_focused_diff(["a.py", "b.py", "c.py"])
            parts = result.split("\n\n")
            assert len(parts) == 3
            assert "diff1" in parts[0]
            assert "diff2" in parts[1]
            assert "diff3" in parts[2]

    def test_handles_empty_file_list(self):
        """Test handles empty implicated file list."""
        result = _gather_focused_diff([])
        assert result == ""

    def test_passes_relative_paths_to_gather_file_diff(self):
        """Test passes file paths to gather_file_diff correctly."""
        with patch("ci_tools.ci_runtime.failures.gather_file_diff") as mock_diff:
            mock_diff.return_value = "diff"
            _gather_focused_diff(["src/module.py"])
            mock_diff.assert_called_once_with("src/module.py")


class TestRenderCoverageContext:
    """Tests for _render_coverage_context helper function."""

    def test_generates_summary_and_log_excerpt(self):
        """Test generates summary and log excerpt for coverage deficits."""
        report = CoverageCheckResult(
            table_text="Name    Cover\nfile.py   50%",
            deficits=[CoverageDeficit(path="file.py", coverage=50.0)],
            threshold=80.0,
        )
        summary, log_excerpt, implicated = _render_coverage_context(report)
        assert "Coverage guard triggered" in summary
        assert "file.py: 50.0%" in summary
        assert "80%" in summary
        assert "threshold" in log_excerpt.lower()
        assert implicated == ["file.py"]

    def test_formats_deficit_list(self):
        """Test formats deficit list with proper formatting."""
        report = CoverageCheckResult(
            table_text="table",
            deficits=[
                CoverageDeficit(path="module1.py", coverage=65.5),
                CoverageDeficit(path="module2.py", coverage=72.3),
            ],
            threshold=80.0,
        )
        summary, _log_excerpt, implicated = _render_coverage_context(report)
        assert "- module1.py: 65.5%" in summary
        assert "- module2.py: 72.3%" in summary
        assert len(implicated) == 2

    def test_includes_table_text_in_log_excerpt(self):
        """Test includes coverage table in log excerpt."""
        report = CoverageCheckResult(
            table_text="Name     Stmts   Cover\nfile.py    100    45%",
            deficits=[CoverageDeficit(path="file.py", coverage=45.0)],
            threshold=80.0,
        )
        _summary, log_excerpt, _implicated = _render_coverage_context(report)
        assert "Name     Stmts   Cover" in log_excerpt
        assert "file.py    100    45%" in log_excerpt

    def test_returns_implicated_paths(self):
        """Test returns list of implicated file paths."""
        report = CoverageCheckResult(
            table_text="",
            deficits=[
                CoverageDeficit(path="a.py", coverage=10.0),
                CoverageDeficit(path="b.py", coverage=20.0),
            ],
            threshold=80.0,
        )
        _summary, _log_excerpt, implicated = _render_coverage_context(report)
        assert implicated == ["a.py", "b.py"]

    def test_formats_threshold_without_decimal_places(self):
        """Test formats threshold as integer percentage."""
        report = CoverageCheckResult(
            table_text="",
            deficits=[CoverageDeficit(path="file.py", coverage=70.0)],
            threshold=85.5,
        )
        summary, _log_excerpt, _implicated = _render_coverage_context(report)
        assert "86%" in summary  # 85.5 rounds to 86


class TestBuildFailureContext:
    """Tests for build_failure_context function."""

    def test_handles_coverage_report(self, capsys):
        """Test handles coverage report scenario."""
        args = SimpleNamespace(log_tail=100)
        result = CommandResult(returncode=1, stdout="", stderr="")
        report = CoverageCheckResult(
            table_text="table",
            deficits=[CoverageDeficit(path="module.py", coverage=60.0)],
            threshold=80.0,
        )
        with patch("ci_tools.ci_runtime.failures._gather_focused_diff") as mock_focused:
            mock_focused.return_value = "focused diff"
            context = build_failure_context(args, result, report)
            assert isinstance(context, FailureContext)
            assert "Coverage" in context.log_excerpt
            assert context.coverage_report == report
            assert "module.py" in context.implicated_files
            captured = capsys.readouterr()
            assert "Coverage below" in captured.out

    def test_handles_regular_ci_failure(self, capsys):
        """Test handles regular CI failure without coverage report."""
        args = SimpleNamespace(log_tail=50)
        result = CommandResult(returncode=1, stdout="test output\nerror occurred", stderr="")
        with patch("ci_tools.ci_runtime.failures.summarize_failure") as mock_summarize:
            with patch("ci_tools.ci_runtime.failures._gather_focused_diff") as mock_focused:
                with patch(
                    "ci_tools.ci_runtime.failures.detect_missing_symbol_error"
                ) as mock_missing:
                    with patch("ci_tools.ci_runtime.failures.detect_attribute_error") as mock_attr:
                        mock_summarize.return_value = ("summary", ["file.py"])
                        mock_missing.return_value = None
                        mock_attr.return_value = None
                        mock_focused.return_value = "diff"
                        context = build_failure_context(args, result, None)
                        assert context.summary == "summary"
                        assert context.implicated_files == ["file.py"]
                        captured = capsys.readouterr()
                        assert "CI failed" in captured.out

    def test_aborts_on_missing_symbol_error(self, capsys):
        """Test aborts when missing symbol error detected."""
        args = SimpleNamespace(log_tail=50)
        result = CommandResult(returncode=1, stdout="ImportError detected", stderr="")
        with patch("ci_tools.ci_runtime.failures.summarize_failure") as mock_summarize:
            with patch("ci_tools.ci_runtime.failures.detect_missing_symbol_error") as mock_missing:
                mock_summarize.return_value = ("", [])
                mock_missing.return_value = "Missing symbol hint"
                with pytest.raises(CiAbort) as exc_info:
                    build_failure_context(args, result, None)
                assert "Manual intervention required" in str(exc_info.value)
                captured = capsys.readouterr()
                assert "Missing symbol hint" in captured.err

    def test_aborts_on_attribute_error(self, capsys):
        """Test aborts when attribute error detected."""
        args = SimpleNamespace(log_tail=50)
        result = CommandResult(returncode=1, stdout="AttributeError occurred", stderr="")
        with patch("ci_tools.ci_runtime.failures.summarize_failure") as mock_summarize:
            with patch("ci_tools.ci_runtime.failures.detect_missing_symbol_error") as mock_missing:
                with patch("ci_tools.ci_runtime.failures.detect_attribute_error") as mock_attr:
                    mock_summarize.return_value = ("", [])
                    mock_missing.return_value = None
                    mock_attr.return_value = "Attribute error hint"
                    with pytest.raises(CiAbort):
                        build_failure_context(args, result, None)
                    captured = capsys.readouterr()
                    assert "Attribute error hint" in captured.err

    def test_uses_tail_text_for_log_excerpt(self):
        """Test uses tail_text to extract log excerpt."""
        args = SimpleNamespace(log_tail=5)
        long_output = "\n".join([f"line{i}" for i in range(20)])
        result = CommandResult(returncode=1, stdout=long_output, stderr="")
        with patch("ci_tools.ci_runtime.failures.tail_text") as mock_tail:
            with patch("ci_tools.ci_runtime.failures.summarize_failure") as mock_summarize:
                with patch("ci_tools.ci_runtime.failures._gather_focused_diff") as mock_focused:
                    with patch(
                        "ci_tools.ci_runtime.failures.detect_missing_symbol_error"
                    ) as mock_missing:
                        with patch(
                            "ci_tools.ci_runtime.failures.detect_attribute_error"
                        ) as mock_attr:
                            mock_tail.return_value = "last 5 lines"
                            mock_summarize.return_value = ("summary", [])
                            mock_missing.return_value = None
                            mock_attr.return_value = None
                            mock_focused.return_value = ""
                            context = build_failure_context(args, result, None)
                            mock_tail.assert_called_once_with(long_output, 5)
                            assert context.log_excerpt == "last 5 lines"

    def test_gathers_focused_diff_for_implicated_files(self):
        """Test gathers focused diff for implicated files."""
        args = SimpleNamespace(log_tail=50)
        result = CommandResult(returncode=1, stdout="", stderr="")
        with patch("ci_tools.ci_runtime.failures.summarize_failure") as mock_summarize:
            with patch("ci_tools.ci_runtime.failures._gather_focused_diff") as mock_focused:
                with patch(
                    "ci_tools.ci_runtime.failures.detect_missing_symbol_error"
                ) as mock_missing:
                    with patch("ci_tools.ci_runtime.failures.detect_attribute_error") as mock_attr:
                        mock_summarize.return_value = ("summary", ["a.py", "b.py"])
                        mock_focused.return_value = "focused diff content"
                        mock_missing.return_value = None
                        mock_attr.return_value = None
                        context = build_failure_context(args, result, None)
                        mock_focused.assert_called_once_with(["a.py", "b.py"])
                        assert context.focused_diff == "focused diff content"

    def test_coverage_report_included_in_context(self):
        """Test coverage report is included in failure context."""
        args = SimpleNamespace(log_tail=50)
        result = CommandResult(returncode=0, stdout="", stderr="")
        report = CoverageCheckResult(
            table_text="", deficits=[CoverageDeficit("f.py", 50.0)], threshold=80.0
        )
        with patch("ci_tools.ci_runtime.failures._gather_focused_diff"):
            context = build_failure_context(args, result, report)
            assert context.coverage_report == report

    def test_prints_coverage_deficits_with_details(self, capsys):
        """Test prints coverage deficit details."""
        args = SimpleNamespace(log_tail=50)
        result = CommandResult(returncode=1, stdout="", stderr="")
        report = CoverageCheckResult(
            table_text="",
            deficits=[
                CoverageDeficit(path="module1.py", coverage=55.5),
                CoverageDeficit(path="module2.py", coverage=70.0),
            ],
            threshold=85.0,
        )
        with patch("ci_tools.ci_runtime.failures._gather_focused_diff"):
            build_failure_context(args, result, report)
            captured = capsys.readouterr()
            assert "module1.py (55.5%)" in captured.out
            assert "module2.py (70.0%)" in captured.out

    def test_handles_empty_implicated_files(self):
        """Test handles scenario with no implicated files."""
        args = SimpleNamespace(log_tail=50)
        result = CommandResult(returncode=1, stdout="generic error", stderr="")
        with patch("ci_tools.ci_runtime.failures.summarize_failure") as mock_summarize:
            with patch("ci_tools.ci_runtime.failures._gather_focused_diff") as mock_focused:
                with patch(
                    "ci_tools.ci_runtime.failures.detect_missing_symbol_error"
                ) as mock_missing:
                    with patch("ci_tools.ci_runtime.failures.detect_attribute_error") as mock_attr:
                        mock_summarize.return_value = ("generic failure", [])
                        mock_focused.return_value = ""
                        mock_missing.return_value = None
                        mock_attr.return_value = None
                        context = build_failure_context(args, result, None)
                        assert not context.implicated_files
                        assert context.focused_diff == ""


class TestFailureContext:
    """Tests for FailureContext dataclass."""

    def test_dataclass_initialization(self):
        """Test FailureContext can be initialized."""
        context = FailureContext(
            log_excerpt="log",
            summary="summary",
            implicated_files=["file.py"],
            focused_diff="diff",
            coverage_report=None,
        )
        assert context.log_excerpt == "log"
        assert context.summary == "summary"
        assert context.implicated_files == ["file.py"]
        assert context.focused_diff == "diff"
        assert context.coverage_report is None

    def test_coverage_report_can_be_none(self):
        """Test coverage_report field can be None."""
        context = FailureContext(
            log_excerpt="",
            summary="",
            implicated_files=[],
            focused_diff="",
            coverage_report=None,
        )
        assert context.coverage_report is None

    def test_coverage_report_can_hold_result(self):
        """Test coverage_report field can hold CoverageCheckResult."""
        report = CoverageCheckResult(
            table_text="table",
            deficits=[CoverageDeficit("file.py", 60.0)],
            threshold=80.0,
        )
        context = FailureContext(
            log_excerpt="",
            summary="",
            implicated_files=[],
            focused_diff="",
            coverage_report=report,
        )
        assert context.coverage_report == report
        assert context.coverage_report is not None
        assert context.coverage_report.threshold == 80.0
