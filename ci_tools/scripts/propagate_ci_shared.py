#!/usr/bin/env python3
"""
Propagate ci_shared updates to consuming repositories.

After ci_shared is successfully pushed, this script updates the ci_shared
submodule in all consuming repositories (zeus, kalshi, aws) and pushes the changes.

This ensures all repos automatically get the latest CI tooling updates.
"""

import subprocess
import sys
from pathlib import Path


def run_command(
    cmd: list[str], cwd: Path, check: bool = True
) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}", file=sys.stderr)
        print(f"stdout: {result.stdout}", file=sys.stderr)
        print(f"stderr: {result.stderr}", file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result


def get_latest_commit_message(repo_path: Path) -> str:
    """Get the latest commit message from ci_shared."""
    result = run_command(
        ["git", "log", "-1", "--pretty=format:%s"],
        cwd=repo_path,
    )
    return result.stdout.strip()


def _validate_repo_state(repo_path: Path, repo_name: str) -> bool:
    """Check if repo and submodule exist, auto-commit any uncommitted changes."""
    if not repo_path.exists():
        print(f"⚠️  Repository not found: {repo_path}")
        return False

    submodule_path = repo_path / "ci_shared"
    if not submodule_path.exists():
        print(f"⚠️  ci_shared submodule not found in {repo_name}")
        return False

    result = run_command(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        check=False,
    )
    if result.stdout.strip():
        print(f"📝 {repo_name} has uncommitted changes, committing automatically...")

        # Stage all changes
        run_command(["git", "add", "-A"], cwd=repo_path, check=False)

        # Create commit message
        commit_msg = """Auto-commit before ci_shared update

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"""

        # Commit changes
        commit_result = run_command(
            ["git", "commit", "-m", commit_msg],
            cwd=repo_path,
            check=False,
        )

        if commit_result.returncode != 0:
            print(f"⚠️  Failed to commit changes in {repo_name}")
            print(f"   Error: {commit_result.stderr}")
            return False

        print(f"✓ Successfully committed changes in {repo_name}")

    return True


def _update_and_check_submodule(repo_path: Path, repo_name: str) -> bool:
    """Update submodule and check if there are changes."""
    print("Updating submodule to latest from origin/main...")
    result = run_command(
        ["git", "submodule", "update", "--remote", "--merge", "ci_shared"],
        cwd=repo_path,
        check=False,
    )
    if result.returncode != 0:
        print(f"⚠️  Failed to update submodule in {repo_name}")
        print(f"   Error: {result.stderr}")
        return False

    result = run_command(
        ["git", "diff", "HEAD", "ci_shared"],
        cwd=repo_path,
        check=False,
    )

    if not result.stdout.strip():
        print(f"✓ {repo_name} submodule already up to date")
        return False

    return True


def _commit_and_push_update(
    repo_path: Path, repo_name: str, ci_shared_commit_msg: str
) -> bool:
    """Stage, commit, and push the submodule update."""
    run_command(["git", "add", "ci_shared"], cwd=repo_path)

    commit_msg = (
        f"Update ci_shared submodule\n\nLatest ci_shared change: {ci_shared_commit_msg}"
    )

    result = run_command(
        ["git", "commit", "-m", commit_msg],
        cwd=repo_path,
        check=False,
    )
    if result.returncode != 0:
        print(f"⚠️  Failed to commit submodule update in {repo_name}")
        return False

    print(f"✓ Committed submodule update in {repo_name}")

    result = run_command(
        ["git", "push"],
        cwd=repo_path,
        check=False,
    )
    if result.returncode != 0:
        print(f"⚠️  Failed to push submodule update in {repo_name}")
        print(f"   Run 'cd {repo_path} && git push' to push manually")
        return False

    print(f"✓ Pushed submodule update to {repo_name}")
    return True


def update_submodule_in_repo(repo_path: Path, ci_shared_commit_msg: str) -> bool:
    """
    Update ci_shared submodule in a consuming repository.

    Returns:
        True if update was successful, False if skipped or failed
    """
    repo_name = repo_path.name
    print(f"\n{'='*70}")
    print(f"Updating ci_shared submodule in {repo_name}...")
    print(f"{'='*70}")

    if not _validate_repo_state(repo_path, repo_name):
        return False

    if not _update_and_check_submodule(repo_path, repo_name):
        return False

    return _commit_and_push_update(repo_path, repo_name, ci_shared_commit_msg)


def _process_repositories(
    parent_dir: Path, consuming_repos: list[str], commit_msg: str
) -> tuple[list[str], list[str], list[str]]:
    """Process all consuming repositories and return results."""
    updated = []
    skipped = []
    failed = []

    for repo_name in consuming_repos:
        repo_path = parent_dir / repo_name
        try:
            success = update_submodule_in_repo(repo_path, commit_msg)
            if success:
                updated.append(repo_name)
            else:
                skipped.append(repo_name)
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"❌ Error updating {repo_name}: {e}", file=sys.stderr)
            failed.append(repo_name)

    return updated, skipped, failed


def _print_summary(updated: list[str], skipped: list[str], failed: list[str]) -> None:
    """Print propagation summary."""
    print("\n" + "=" * 70)
    print("Propagation Summary")
    print("=" * 70)

    if updated:
        print(f"✅ Updated and pushed: {', '.join(updated)}")
    if skipped:
        print(f"⊘  Skipped: {', '.join(skipped)}")
    if failed:
        print(f"❌ Failed: {', '.join(failed)}")

    print()


def main() -> int:
    """Main entry point."""
    # Verify we're in ci_shared repository
    cwd = Path.cwd()

    # Check if this is the ci_shared repo
    if not (cwd / "ci_tools").exists() or not (cwd / "ci_shared.mk").exists():
        print("⚠️  Not running from ci_shared repository, skipping propagation")
        return 0

    print("\n" + "=" * 70)
    print("Propagating ci_shared updates to consuming repositories")
    print("=" * 70)

    # Get the latest commit message
    try:
        commit_msg = get_latest_commit_message(cwd)
        print(f"\nLatest ci_shared commit: {commit_msg}")
    except subprocess.CalledProcessError:
        print("⚠️  Failed to get latest commit message", file=sys.stderr)
        return 1

    # Find consuming repositories (siblings of ci_shared)
    parent_dir = cwd.parent
    consuming_repos = ["zeus", "kalshi", "aws"]

    updated, skipped, failed = _process_repositories(
        parent_dir, consuming_repos, commit_msg
    )

    _print_summary(updated, skipped, failed)

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
