"""Unit tests for propagate_ci_shared module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from ci_tools.scripts.propagate_ci_shared import (
    _commit_and_push_update,
    _print_summary,
    _process_repositories,
    _update_and_check_submodule,
    _validate_repo_state,
    get_latest_commit_message,
    main,
    run_command,
    update_submodule_in_repo,
)


def test_run_command_success():
    """Test run_command with successful command."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["echo", "test"],
            returncode=0,
            stdout="output",
            stderr="",
        )
        result = run_command(["echo", "test"], Path("/tmp"))
        assert result.returncode == 0
        assert result.stdout == "output"


def test_run_command_failure_no_check():
    """Test run_command with failed command and check=False."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["false"],
            returncode=1,
            stdout="",
            stderr="error",
        )
        result = run_command(["false"], Path("/tmp"), check=False)
        assert result.returncode == 1


def test_run_command_failure_with_check():
    """Test run_command raises exception with check=True."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["false"],
            returncode=1,
            stdout="",
            stderr="error",
        )
        with pytest.raises(subprocess.CalledProcessError):
            run_command(["false"], Path("/tmp"), check=True)


def test_get_latest_commit_message():
    """Test get_latest_commit_message returns commit message."""
    with patch("ci_tools.scripts.propagate_ci_shared.run_command") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "log"],
            returncode=0,
            stdout="Fix: Update CI tooling",
            stderr="",
        )
        result = get_latest_commit_message(Path("/tmp"))
        assert result == "Fix: Update CI tooling"


def test_validate_repo_state_missing_repo(tmp_path):
    """Test _validate_repo_state with missing repository."""
    missing_repo = tmp_path / "missing"
    result = _validate_repo_state(missing_repo, "missing")
    assert result is False


def test_validate_repo_state_missing_submodule(tmp_path):
    """Test _validate_repo_state with missing submodule."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    result = _validate_repo_state(repo_path, "repo")
    assert result is False


def test_validate_repo_state_uncommitted_changes(tmp_path):
    """Test _validate_repo_state auto-commits uncommitted changes."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "ci_shared").mkdir()

    with patch("ci_tools.scripts.propagate_ci_shared.run_command") as mock_run:
        mock_run.side_effect = [
            # git status --porcelain (shows uncommitted changes)
            subprocess.CompletedProcess(
                args=["git", "status"],
                returncode=0,
                stdout=" M file.py\n",
                stderr="",
            ),
            # git add -A
            subprocess.CompletedProcess(
                args=["git", "add"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            # git commit
            subprocess.CompletedProcess(
                args=["git", "commit"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ]
        result = _validate_repo_state(repo_path, "repo")
        assert result is True
        assert mock_run.call_count == 3


def test_validate_repo_state_commit_failure(tmp_path):
    """Test _validate_repo_state handles commit failure."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "ci_shared").mkdir()

    with patch("ci_tools.scripts.propagate_ci_shared.run_command") as mock_run:
        mock_run.side_effect = [
            # git status --porcelain (shows uncommitted changes)
            subprocess.CompletedProcess(
                args=["git", "status"],
                returncode=0,
                stdout=" M file.py\n",
                stderr="",
            ),
            # git add -A
            subprocess.CompletedProcess(
                args=["git", "add"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            # git commit (fails)
            subprocess.CompletedProcess(
                args=["git", "commit"],
                returncode=1,
                stdout="",
                stderr="commit failed",
            ),
        ]
        result = _validate_repo_state(repo_path, "repo")
        assert result is False


def test_validate_repo_state_clean(tmp_path):
    """Test _validate_repo_state with clean repository."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "ci_shared").mkdir()

    with patch("ci_tools.scripts.propagate_ci_shared.run_command") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "status"],
            returncode=0,
            stdout="",
            stderr="",
        )
        result = _validate_repo_state(repo_path, "repo")
        assert result is True


def test_update_and_check_submodule_failure(tmp_path):
    """Test _update_and_check_submodule with update failure."""
    repo_path = tmp_path / "repo"

    with patch("ci_tools.scripts.propagate_ci_shared.run_command") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "submodule"],
            returncode=1,
            stdout="",
            stderr="error",
        )
        result = _update_and_check_submodule(repo_path, "repo")
        assert result is False


def test_update_and_check_submodule_no_changes(tmp_path):
    """Test _update_and_check_submodule with no changes."""
    repo_path = tmp_path / "repo"

    with patch("ci_tools.scripts.propagate_ci_shared.run_command") as mock_run:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["git", "submodule"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "diff"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ]
        result = _update_and_check_submodule(repo_path, "repo")
        assert result is False


def test_update_and_check_submodule_has_changes(tmp_path):
    """Test _update_and_check_submodule with changes."""
    repo_path = tmp_path / "repo"

    with patch("ci_tools.scripts.propagate_ci_shared.run_command") as mock_run:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["git", "submodule"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "diff"],
                returncode=0,
                stdout="diff --git a/ci_shared b/ci_shared",
                stderr="",
            ),
        ]
        result = _update_and_check_submodule(repo_path, "repo")
        assert result is True


def test_commit_and_push_update_commit_failure(tmp_path):
    """Test _commit_and_push_update with commit failure."""
    repo_path = tmp_path / "repo"

    with patch("ci_tools.scripts.propagate_ci_shared.run_command") as mock_run:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["git", "add"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "commit"],
                returncode=1,
                stdout="",
                stderr="error",
            ),
        ]
        result = _commit_and_push_update(repo_path, "repo", "Test commit")
        assert result is False


def test_commit_and_push_update_push_failure(tmp_path):
    """Test _commit_and_push_update with push failure."""
    repo_path = tmp_path / "repo"

    with patch("ci_tools.scripts.propagate_ci_shared.run_command") as mock_run:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["git", "add"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "commit"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "push"],
                returncode=1,
                stdout="",
                stderr="error",
            ),
        ]
        result = _commit_and_push_update(repo_path, "repo", "Test commit")
        assert result is False


def test_commit_and_push_update_success(tmp_path):
    """Test _commit_and_push_update with successful commit and push."""
    repo_path = tmp_path / "repo"

    with patch("ci_tools.scripts.propagate_ci_shared.run_command") as mock_run:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=["git", "add"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "commit"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "push"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ]
        result = _commit_and_push_update(repo_path, "repo", "Test commit")
        assert result is True


def test_update_submodule_in_repo_invalid_state(tmp_path):
    """Test update_submodule_in_repo with invalid state."""
    repo_path = tmp_path / "repo"
    with patch("ci_tools.scripts.propagate_ci_shared._validate_repo_state") as mock:
        mock.return_value = False
        result = update_submodule_in_repo(repo_path, "Test commit")
        assert result is False


def test_update_submodule_in_repo_no_changes(tmp_path):
    """Test update_submodule_in_repo with no changes."""
    repo_path = tmp_path / "repo"
    with patch("ci_tools.scripts.propagate_ci_shared._validate_repo_state") as mock1:
        with patch(
            "ci_tools.scripts.propagate_ci_shared._update_and_check_submodule"
        ) as mock2:
            mock1.return_value = True
            mock2.return_value = False
            result = update_submodule_in_repo(repo_path, "Test commit")
            assert result is False


def test_update_submodule_in_repo_success(tmp_path):
    """Test update_submodule_in_repo with successful update."""
    repo_path = tmp_path / "repo"
    with patch("ci_tools.scripts.propagate_ci_shared._validate_repo_state") as mock1:
        with patch(
            "ci_tools.scripts.propagate_ci_shared._update_and_check_submodule"
        ) as mock2:
            with patch(
                "ci_tools.scripts.propagate_ci_shared._commit_and_push_update"
            ) as mock3:
                mock1.return_value = True
                mock2.return_value = True
                mock3.return_value = True
                result = update_submodule_in_repo(repo_path, "Test commit")
                assert result is True


def test_process_repositories(tmp_path):
    """Test _process_repositories processes all repos."""
    parent_dir = tmp_path
    with patch(
        "ci_tools.scripts.propagate_ci_shared.update_submodule_in_repo"
    ) as mock_update:
        mock_update.side_effect = [True, False, Exception("error")]
        updated, skipped, failed = _process_repositories(
            parent_dir, ["zeus", "kalshi", "aws"], "Test commit"
        )
        assert updated == ["zeus"]
        assert skipped == ["kalshi"]
        assert failed == ["aws"]


def test_print_summary_all_types(capsys):
    """Test _print_summary prints all status types."""
    _print_summary(["zeus"], ["kalshi"], ["aws"])
    captured = capsys.readouterr()
    assert "zeus" in captured.out
    assert "kalshi" in captured.out
    assert "aws" in captured.out


def test_print_summary_empty_lists(capsys):
    """Test _print_summary with empty lists."""
    _print_summary([], [], [])
    captured = capsys.readouterr()
    assert "Summary" in captured.out


def test_main_not_in_ci_shared(tmp_path, monkeypatch):
    """Test main returns early when not in ci_shared."""
    monkeypatch.chdir(tmp_path)
    result = main()
    assert result == 0


def test_main_commit_message_failure(tmp_path, monkeypatch):
    """Test main handles commit message failure."""
    repo_dir = tmp_path / "ci_shared"
    repo_dir.mkdir()
    (repo_dir / "ci_tools").mkdir()
    (repo_dir / "ci_shared.mk").touch()
    monkeypatch.chdir(repo_dir)

    with patch("ci_tools.scripts.propagate_ci_shared.get_latest_commit_message") as mock:
        mock.side_effect = subprocess.CalledProcessError(1, "git")
        result = main()
        assert result == 1


def test_main_success_with_updates(tmp_path, monkeypatch):
    """Test main successfully propagates updates."""
    repo_dir = tmp_path / "ci_shared"
    repo_dir.mkdir()
    (repo_dir / "ci_tools").mkdir()
    (repo_dir / "ci_shared.mk").touch()
    monkeypatch.chdir(repo_dir)

    with patch("ci_tools.scripts.propagate_ci_shared.get_latest_commit_message") as mock1:
        with patch("ci_tools.scripts.propagate_ci_shared._process_repositories") as mock2:
            mock1.return_value = "Test commit"
            mock2.return_value = (["zeus"], ["kalshi"], [])
            result = main()
            assert result == 0


def test_main_with_failures(tmp_path, monkeypatch):
    """Test main returns error code when there are failures."""
    repo_dir = tmp_path / "ci_shared"
    repo_dir.mkdir()
    (repo_dir / "ci_tools").mkdir()
    (repo_dir / "ci_shared.mk").touch()
    monkeypatch.chdir(repo_dir)

    with patch("ci_tools.scripts.propagate_ci_shared.get_latest_commit_message") as mock1:
        with patch("ci_tools.scripts.propagate_ci_shared._process_repositories") as mock2:
            mock1.return_value = "Test commit"
            mock2.return_value = ([], [], ["aws"])
            result = main()
            assert result == 1
