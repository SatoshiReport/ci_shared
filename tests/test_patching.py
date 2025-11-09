"""Unit tests for ci_tools.ci_runtime.patching module."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from ci_tools.ci_runtime.patching import (
    _extract_diff_paths,
    patch_looks_risky,
    _ensure_trailing_newline,
    _apply_patch_with_git,
    _patch_already_applied,
    _apply_patch_with_patch_tool,
    apply_patch,
)
from ci_tools.ci_runtime.models import PatchApplyError


class TestExtractDiffPaths:
    """Tests for _extract_diff_paths helper function."""

    def test_extracts_paths_from_diff_headers(self):
        """Test extracts file paths from diff headers."""
        patch_text = """diff --git a/ci.py b/ci.py
index 123..456 100644
--- a/ci.py
+++ b/ci.py
"""
        with patch("ci_tools.ci_runtime.patching.PROTECTED_PATH_PREFIXES", ("ci.py",)):
            paths = _extract_diff_paths(patch_text)
            assert "ci.py" in paths

    def test_ignores_non_protected_paths(self):
        """Test ignores paths that aren't protected."""
        patch_text = """diff --git a/src/module.py b/src/module.py
index 123..456 100644
--- a/src/module.py
+++ b/src/module.py
"""
        with patch("ci_tools.ci_runtime.patching.PROTECTED_PATH_PREFIXES", ("ci.py",)):
            paths = _extract_diff_paths(patch_text)
            assert len(paths) == 0

    def test_handles_multiple_files(self):
        """Test handles multiple files in patch."""
        patch_text = """diff --git a/ci.py b/ci.py
--- a/ci.py
+++ b/ci.py
diff --git a/Makefile b/Makefile
--- a/Makefile
+++ b/Makefile
"""
        with patch(
            "ci_tools.ci_runtime.patching.PROTECTED_PATH_PREFIXES",
            ("ci.py", "Makefile"),
        ):
            paths = _extract_diff_paths(patch_text)
            assert "ci.py" in paths
            assert "Makefile" in paths

    def test_handles_malformed_diff_lines(self):
        """Test handles malformed diff lines gracefully."""
        patch_text = """diff --git incomplete
diff --git a/file.py
"""
        with patch("ci_tools.ci_runtime.patching.PROTECTED_PATH_PREFIXES", ("file.py",)):
            paths = _extract_diff_paths(patch_text)
            assert len(paths) == 0

    def test_returns_empty_set_when_no_diffs(self):
        """Test returns empty set when no diff headers found."""
        patch_text = "just some text\nno diffs here"
        paths = _extract_diff_paths(patch_text)
        assert len(paths) == 0

    def test_handles_paths_with_prefixes(self):
        """Test correctly matches path prefixes."""
        patch_text = """diff --git a/ci_tools/module.py b/ci_tools/module.py
--- a/ci_tools/module.py
+++ b/ci_tools/module.py
"""
        with patch("ci_tools.ci_runtime.patching.PROTECTED_PATH_PREFIXES", ("ci_tools/",)):
            paths = _extract_diff_paths(patch_text)
            assert "ci_tools/module.py" in paths


class TestPatchLooksRisky:
    """Tests for patch_looks_risky safety checker."""

    def test_empty_patch_is_risky(self):
        """Test empty patch content is flagged as risky."""
        risky, reason = patch_looks_risky("", max_lines=100)
        assert risky is True
        assert reason is not None
        assert "empty" in reason.lower()

    def test_large_patch_exceeds_limit(self):
        """Test patch exceeding line limit is flagged."""
        large_patch = "\n".join(["+new line" for _ in range(150)])
        risky, reason = patch_looks_risky(large_patch, max_lines=100)
        assert risky is True
        assert reason is not None
        assert "150" in reason
        assert "100" in reason

    def test_protected_path_modification_is_risky(self):
        """Test modifying protected paths is flagged."""
        patch_text = """diff --git a/ci.py b/ci.py
--- a/ci.py
+++ b/ci.py
@@ -1 +1 @@
-old
+new
"""
        with patch("ci_tools.ci_runtime.patching.PROTECTED_PATH_PREFIXES", ("ci.py",)):
            risky, reason = patch_looks_risky(patch_text, max_lines=1000)
            assert risky is True
            assert reason is not None
            assert "protected path" in reason.lower()
            assert "ci.py" in reason

    def test_risky_pattern_detected(self):
        """Test risky patterns in diff are detected."""
        patch_text = """diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
@@ -1 +1 @@
-old
+subprocess.run(['rm', '-rf', '/'])
"""
        with patch("ci_tools.ci_runtime.patching.risky_pattern_in_diff") as mock_risky:
            mock_risky.return_value = "rm -rf"
            risky, reason = patch_looks_risky(patch_text, max_lines=1000)
            assert risky is True
            assert reason is not None
            assert "risky pattern" in reason.lower()

    def test_safe_patch_passes_checks(self):
        """Test safe patch passes all checks."""
        patch_text = """diff --git a/src/module.py b/src/module.py
--- a/src/module.py
+++ b/src/module.py
@@ -1 +1 @@
-def old():
+def new():
"""
        with patch("ci_tools.ci_runtime.patching.PROTECTED_PATH_PREFIXES", ("ci.py",)):
            with patch("ci_tools.ci_runtime.patching.risky_pattern_in_diff") as mock_risky:
                mock_risky.return_value = None
                risky, reason = patch_looks_risky(patch_text, max_lines=1000)
                assert risky is False
                assert reason is None

    def test_multiple_protected_paths_listed(self):
        """Test multiple protected paths are listed in reason."""
        patch_text = """diff --git a/ci.py b/ci.py
diff --git a/Makefile b/Makefile
"""
        with patch(
            "ci_tools.ci_runtime.patching.PROTECTED_PATH_PREFIXES",
            ("ci.py", "Makefile"),
        ):
            risky, reason = patch_looks_risky(patch_text, max_lines=1000)
            assert risky is True
            assert reason is not None
            assert "ci.py" in reason
            assert "Makefile" in reason


class TestEnsureTrailingNewline:
    """Tests for _ensure_trailing_newline helper."""

    def test_adds_newline_when_missing(self):
        """Test adds newline when not present."""
        result = _ensure_trailing_newline("patch content")
        assert result == "patch content\n"

    def test_preserves_existing_newline(self):
        """Test doesn't add extra newline when already present."""
        result = _ensure_trailing_newline("patch content\n")
        assert result == "patch content\n"

    def test_handles_empty_string(self):
        """Test handles empty string."""
        result = _ensure_trailing_newline("")
        assert result == "\n"

    def test_handles_multiple_trailing_newlines(self):
        """Test preserves multiple trailing newlines."""
        result = _ensure_trailing_newline("content\n\n")
        assert result == "content\n\n"


class TestApplyPatchWithGit:
    """Tests for _apply_patch_with_git function."""

    def test_successful_git_apply(self):
        """Test successful patch application via git."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="", stderr=""),  # git apply --check
                Mock(returncode=0, stdout="Applied patch", stderr=""),  # git apply
            ]
            applied, _diagnostics = _apply_patch_with_git("diff content")
            assert applied is True
            assert mock_run.call_count == 2

    def test_git_apply_check_fails(self):
        """Test when git apply --check fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="error: patch failed")
            applied, diagnostics = _apply_patch_with_git("diff content")
            assert applied is False
            assert "error: patch failed" in diagnostics

    def test_git_apply_fails_after_check_passes(self):
        """Test when git apply fails after check passes."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="", stderr=""),  # check passes
                Mock(returncode=1, stdout="", stderr="apply failed"),  # apply fails
            ]
            with pytest.raises(PatchApplyError) as exc_info:
                _apply_patch_with_git("diff content")
            assert exc_info.value.retryable is True

    def test_prints_stdout_on_success(self, capsys):
        """Test prints stdout when git apply succeeds."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="", stderr=""),
                Mock(returncode=0, stdout="Patched file.py", stderr=""),
            ]
            _apply_patch_with_git("diff")
            captured = capsys.readouterr()
            assert "Patched file.py" in captured.out

    def test_uses_whitespace_nowarn_flag(self):
        """Test uses --whitespace=nowarn flag."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),
            ]
            _apply_patch_with_git("diff")
            for call_obj in mock_run.call_args_list:
                args = call_obj[0][0]
                if "apply" in args:
                    assert "--whitespace=nowarn" in args


class TestPatchAlreadyApplied:
    """Tests for _patch_already_applied function."""

    def test_returns_true_when_reverse_check_succeeds(self, capsys):
        """Test returns True when reverse check passes."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
            result = _patch_already_applied("diff content")
            assert result is True
            captured = capsys.readouterr()
            assert "already applied" in captured.out.lower()

    def test_returns_false_when_reverse_check_fails(self):
        """Test returns False when reverse check fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="")
            result = _patch_already_applied("diff content")
            assert result is False

    def test_uses_reverse_flag(self):
        """Test uses --reverse flag for checking."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="")
            _patch_already_applied("diff")
            args = mock_run.call_args[0][0]
            assert "--reverse" in args


class TestApplyPatchWithPatchTool:
    """Tests for _apply_patch_with_patch_tool function."""

    def test_successful_patch_application(self):
        """Test successful patch using patch utility."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="", stderr=""),  # dry run
                Mock(returncode=0, stdout="patching file", stderr=""),  # actual
            ]
            _apply_patch_with_patch_tool("diff", check_output="git check failed")
            assert mock_run.call_count == 2

    def test_dry_run_failure_raises_error(self):
        """Test dry run failure raises PatchApplyError."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="dry run failed")
            with pytest.raises(PatchApplyError) as exc_info:
                _apply_patch_with_patch_tool("diff", check_output="check failed")
            assert "dry-run" in str(exc_info.value).lower()
            assert exc_info.value.retryable is True

    def test_actual_patch_failure_raises_error(self):
        """Test actual patch failure raises PatchApplyError."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="", stderr=""),  # dry run passes
                Mock(returncode=1, stdout="", stderr="patch failed"),  # actual fails
            ]
            with pytest.raises(PatchApplyError) as exc_info:
                _apply_patch_with_patch_tool("diff", check_output="")
            assert "exit" in str(exc_info.value).lower()

    def test_sets_patch_create_backup_env_var(self):
        """Test sets PATCH_CREATE_BACKUP=no environment variable."""
        with patch("subprocess.run") as mock_run:
            with patch("os.environ", {}):
                mock_run.side_effect = [
                    Mock(returncode=0, stdout="", stderr=""),
                    Mock(returncode=0, stdout="", stderr=""),
                ]
                _apply_patch_with_patch_tool("diff", check_output="")
                for call_obj in mock_run.call_args_list:
                    env = call_obj[1]["env"]
                    if "PATCH_CREATE_BACKUP" in env:
                        assert env["PATCH_CREATE_BACKUP"] == "no"

    def test_uses_batch_and_forward_flags(self):
        """Test uses --batch and --forward flags."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="", stderr=""),
                Mock(returncode=0, stdout="", stderr=""),
            ]
            _apply_patch_with_patch_tool("diff", check_output="")
            for call_obj in mock_run.call_args_list:
                args = call_obj[0][0]
                if "patch" in args:
                    assert "--batch" in args
                    assert "--forward" in args

    def test_prints_stdout_on_success(self, capsys):
        """Test prints stdout when patch succeeds."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="", stderr=""),
                Mock(returncode=0, stdout="patching file.py", stderr=""),
            ]
            _apply_patch_with_patch_tool("diff", check_output="")
            captured = capsys.readouterr()
            assert "patching file.py" in captured.out


class TestApplyPatch:
    """Tests for apply_patch public API."""

    def test_applies_with_git_when_possible(self):
        """Test prefers git apply when it works."""
        with patch("ci_tools.ci_runtime.patching._apply_patch_with_git") as mock_git_apply:
            mock_git_apply.return_value = (True, "")
            apply_patch("diff content")
            mock_git_apply.assert_called_once()

    def test_falls_back_to_patch_tool_when_git_fails(self):
        """Test falls back to patch utility when git fails."""
        with patch("ci_tools.ci_runtime.patching._apply_patch_with_git") as mock_git_apply:
            with patch("ci_tools.ci_runtime.patching._patch_already_applied") as mock_already:
                with patch(
                    "ci_tools.ci_runtime.patching._apply_patch_with_patch_tool"
                ) as mock_patch_tool:
                    mock_git_apply.return_value = (False, "git failed")
                    mock_already.return_value = False
                    apply_patch("diff content")
                    mock_patch_tool.assert_called_once()

    def test_skips_when_already_applied(self):
        """Test skips application when patch already applied."""
        with patch("ci_tools.ci_runtime.patching._apply_patch_with_git") as mock_git_apply:
            with patch("ci_tools.ci_runtime.patching._patch_already_applied") as mock_already:
                with patch(
                    "ci_tools.ci_runtime.patching._apply_patch_with_patch_tool"
                ) as mock_patch_tool:
                    mock_git_apply.return_value = (False, "")
                    mock_already.return_value = True
                    apply_patch("diff content")
                    mock_patch_tool.assert_not_called()

    def test_ensures_trailing_newline(self):
        """Test ensures patch has trailing newline."""
        with patch("ci_tools.ci_runtime.patching._apply_patch_with_git") as mock_git_apply:
            mock_git_apply.return_value = (True, "")
            apply_patch("diff without newline")
            call_args = mock_git_apply.call_args[0][0]
            assert call_args.endswith("\n")

    def test_propagates_patch_apply_errors(self):
        """Test propagates PatchApplyError exceptions."""
        with patch("ci_tools.ci_runtime.patching._apply_patch_with_git") as mock_git_apply:
            with patch("ci_tools.ci_runtime.patching._patch_already_applied") as mock_already:
                with patch(
                    "ci_tools.ci_runtime.patching._apply_patch_with_patch_tool"
                ) as mock_patch_tool:
                    mock_git_apply.return_value = (False, "check failed")
                    mock_already.return_value = False
                    mock_patch_tool.side_effect = PatchApplyError.patch_exit(
                        returncode=1, output="failed"
                    )
                    with pytest.raises(PatchApplyError):
                        apply_patch("diff")

    def test_handles_empty_check_output(self):
        """Test handles empty check output from git."""
        with patch("ci_tools.ci_runtime.patching._apply_patch_with_git") as mock_git_apply:
            with patch("ci_tools.ci_runtime.patching._patch_already_applied") as mock_already:
                with patch(
                    "ci_tools.ci_runtime.patching._apply_patch_with_patch_tool"
                ) as mock_patch_tool:
                    mock_git_apply.return_value = (False, "")
                    mock_already.return_value = False
                    mock_patch_tool.return_value = None
                    apply_patch("diff")
                    mock_patch_tool.assert_called_once()


class TestPatchApplyError:
    """Tests for PatchApplyError exception class."""

    def test_git_apply_failed_factory(self):
        """Test git_apply_failed factory method."""
        error = PatchApplyError.git_apply_failed(output="git error message")
        assert error.retryable is True
        assert "git apply" in str(error).lower()
        assert "git error message" in str(error)

    def test_preflight_failed_factory(self):
        """Test preflight_failed factory method."""
        error = PatchApplyError.preflight_failed(
            check_output="git check failed", dry_output="patch dry-run failed"
        )
        assert error.retryable is True
        assert "preflight" in str(error).lower() or "dry-run" in str(error).lower()

    def test_patch_exit_factory(self):
        """Test patch_exit factory method."""
        error = PatchApplyError.patch_exit(returncode=2, output="rejected")
        assert error.retryable is True
        assert "2" in str(error)

    def test_retryable_attribute_default_true(self):
        """Test retryable attribute defaults to True."""
        error = PatchApplyError(detail="test error")
        assert error.retryable is True

    def test_retryable_attribute_can_be_false(self):
        """Test retryable attribute can be set to False."""
        error = PatchApplyError(detail="test error", retryable=False)
        assert error.retryable is False
