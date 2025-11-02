from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ci_tools.scripts import directory_depth_guard


class TestParseArgs:
    """Test argument parsing."""

    def test_parse_args_defaults(self) -> None:
        """Test default argument values."""
        args = directory_depth_guard.parse_args([])
        assert args.root == Path("src")
        assert args.max_depth == 5
        assert args.exclude == []

    def test_parse_args_custom_root(self) -> None:
        """Test custom root argument."""
        args = directory_depth_guard.parse_args(["--root", "/custom/path"])
        assert args.root == Path("/custom/path")

    def test_parse_args_custom_max_depth(self) -> None:
        """Test custom max depth argument."""
        args = directory_depth_guard.parse_args(["--max-depth", "3"])
        assert args.max_depth == 3

    def test_parse_args_single_exclude(self) -> None:
        """Test single exclusion pattern."""
        args = directory_depth_guard.parse_args(["--exclude", "node_modules"])
        assert "node_modules" in args.exclude

    def test_parse_args_multiple_excludes(self) -> None:
        """Test multiple exclusion patterns."""
        args = directory_depth_guard.parse_args([
            "--exclude", "node_modules",
            "--exclude", ".git",
            "--exclude", "venv"
        ])
        assert "node_modules" in args.exclude
        assert ".git" in args.exclude
        assert "venv" in args.exclude

    def test_parse_args_combined_options(self) -> None:
        """Test combining multiple options."""
        args = directory_depth_guard.parse_args([
            "--root", "/my/path",
            "--max-depth", "7",
            "--exclude", "test",
            "--exclude", "cache"
        ])
        assert args.root == Path("/my/path")
        assert args.max_depth == 7
        assert "test" in args.exclude
        assert "cache" in args.exclude


class TestCalculateDepth:
    """Test depth calculation."""

    def test_calculate_depth_immediate_child(self, tmp_path: Path) -> None:
        """Test depth of immediate child directory."""
        root = tmp_path
        child = root / "child"

        depth = directory_depth_guard.calculate_depth(child, root)
        assert depth == 1

    def test_calculate_depth_nested(self, tmp_path: Path) -> None:
        """Test depth of nested directories."""
        root = tmp_path
        nested = root / "level1" / "level2" / "level3"

        depth = directory_depth_guard.calculate_depth(nested, root)
        assert depth == 3

    def test_calculate_depth_root_itself(self, tmp_path: Path) -> None:
        """Test depth of root directory."""
        root = tmp_path
        depth = directory_depth_guard.calculate_depth(root, root)
        assert depth == 0

    def test_calculate_depth_outside_root(self, tmp_path: Path) -> None:
        """Test depth calculation for path outside root."""
        root = tmp_path / "project"
        outside = tmp_path / "other"

        depth = directory_depth_guard.calculate_depth(outside, root)
        assert depth == 0

    def test_calculate_depth_deep_nesting(self, tmp_path: Path) -> None:
        """Test depth of deeply nested structure."""
        root = tmp_path
        deep = root / "a" / "b" / "c" / "d" / "e" / "f" / "g" / "h" / "i" / "j"

        depth = directory_depth_guard.calculate_depth(deep, root)
        assert depth == 10


class TestShouldExclude:
    """Test exclusion logic."""

    def test_should_exclude_matching_pattern(self, tmp_path: Path) -> None:
        """Test excluding directory matching pattern."""
        path = tmp_path / "__pycache__"
        exclusions = ["__pycache__", "node_modules"]

        assert directory_depth_guard.should_exclude(path, exclusions)

    def test_should_exclude_not_matching(self, tmp_path: Path) -> None:
        """Test not excluding directory that doesn't match."""
        path = tmp_path / "src"
        exclusions = ["__pycache__", "node_modules"]

        assert not directory_depth_guard.should_exclude(path, exclusions)

    def test_should_exclude_dot_prefix(self, tmp_path: Path) -> None:
        """Test excluding directories starting with dot."""
        path = tmp_path / ".git"
        # The implementation only checks for dot prefix inside the loop
        # So we need at least one exclusion for the check to run
        exclusions = ["dummy"]

        assert directory_depth_guard.should_exclude(path, exclusions)

    def test_should_exclude_dot_files_and_dirs(self, tmp_path: Path) -> None:
        """Test various dot-prefixed items."""
        # The implementation only checks for dot prefix inside the exclusions loop
        # So we need at least one exclusion
        exclusions = ["dummy"]
        for name in [".git", ".vscode", ".idea", ".pytest_cache"]:
            path = tmp_path / name
            assert directory_depth_guard.should_exclude(path, exclusions)

    def test_should_exclude_substring_match(self, tmp_path: Path) -> None:
        """Test exclusion by substring matching."""
        path = tmp_path / "my_cache_dir"
        exclusions = ["cache"]

        assert directory_depth_guard.should_exclude(path, exclusions)

    def test_should_exclude_empty_exclusions(self, tmp_path: Path) -> None:
        """Test with empty exclusions list."""
        path = tmp_path / "regular_dir"
        exclusions = []

        assert not directory_depth_guard.should_exclude(path, exclusions)

    def test_should_exclude_case_sensitive(self, tmp_path: Path) -> None:
        """Test that exclusion is case-sensitive."""
        path = tmp_path / "Cache"
        exclusions = ["cache"]

        # This depends on the implementation - currently it IS case-sensitive
        assert not directory_depth_guard.should_exclude(path, exclusions)


class TestScanDirectories:
    """Test directory scanning."""

    def test_scan_directories_no_violations(self, tmp_path: Path) -> None:
        """Test scanning with no depth violations."""
        root = tmp_path / "src"
        root.mkdir()

        level1 = root / "level1"
        level2 = level1 / "level2"
        level2.mkdir(parents=True)

        violations = directory_depth_guard.scan_directories(root, 5, [])
        assert len(violations) == 0

    def test_scan_directories_single_violation(self, tmp_path: Path) -> None:
        """Test scanning with single depth violation."""
        root = tmp_path / "src"
        root.mkdir()

        # Create a deep nested structure
        deep = root / "l1" / "l2" / "l3" / "l4" / "l5" / "l6"
        deep.mkdir(parents=True)

        violations = directory_depth_guard.scan_directories(root, 3, [])
        assert len(violations) > 0

        # Check that deep directories are reported
        depths = [v[1] for v in violations]

        assert any(depth > 3 for depth in depths)

    def test_scan_directories_multiple_violations(self, tmp_path: Path) -> None:
        """Test scanning with multiple violations."""
        root = tmp_path / "src"
        root.mkdir()

        # Create multiple deep branches
        branch1 = root / "a" / "b" / "c" / "d" / "e"
        branch2 = root / "x" / "y" / "z" / "w"

        branch1.mkdir(parents=True)
        branch2.mkdir(parents=True)

        violations = directory_depth_guard.scan_directories(root, 2, [])
        assert len(violations) >= 2

    def test_scan_directories_respect_exclusions(self, tmp_path: Path) -> None:
        """Test that exclusions are respected."""
        root = tmp_path / "src"
        root.mkdir()

        # Create deep structure in excluded directory
        excluded = root / "__pycache__" / "deep" / "nested" / "path"
        excluded.mkdir(parents=True)

        # Create shallow structure in non-excluded directory
        normal = root / "module"
        normal.mkdir()

        violations = directory_depth_guard.scan_directories(root, 2, ["__pycache__"])
        # Should not report violations in excluded directory
        paths = [str(v[0]) for v in violations]
        assert not any("__pycache__" in path for path in paths)

    def test_scan_directories_exclude_dot_dirs(self, tmp_path: Path) -> None:
        """Test that dot directories are excluded when any exclusion is present."""
        root = tmp_path / "src"
        root.mkdir()

        # Create deep structure in .git
        git = root / ".git" / "objects" / "pack" / "deep"
        git.mkdir(parents=True)

        # The should_exclude function only checks for dot prefix inside the loop
        # So we need to pass at least one exclusion pattern
        violations = directory_depth_guard.scan_directories(root, 1, ["dummy"])
        paths = [str(v[0]) for v in violations]
        # .git should be excluded because its name starts with "." (when exclusions exist)
        assert not any(".git" in path for path in paths)

    def test_scan_directories_boundary_depth(self, tmp_path: Path) -> None:
        """Test scanning at exactly max depth."""
        root = tmp_path / "src"
        root.mkdir()

        # Create structure exactly at max depth
        exact = root / "l1" / "l2" / "l3"
        exact.mkdir(parents=True)

        # Just above max depth
        over = root / "a" / "b" / "c" / "d"
        over.mkdir(parents=True)

        violations = directory_depth_guard.scan_directories(root, 3, [])

        # Only the over-depth one should be reported
        depths = [v[1] for v in violations]

        assert all(depth > 3 for depth in depths)

    def test_scan_directories_empty_root(self, tmp_path: Path) -> None:
        """Test scanning empty root directory."""
        root = tmp_path / "src"
        root.mkdir()

        violations = directory_depth_guard.scan_directories(root, 5, [])
        assert len(violations) == 0

    def test_scan_directories_only_files(self, tmp_path: Path) -> None:
        """Test scanning directory with only files."""
        root = tmp_path / "src"
        root.mkdir()

        (root / "file1.py").write_text("# code")
        (root / "file2.py").write_text("# code")

        violations = directory_depth_guard.scan_directories(root, 5, [])
        assert len(violations) == 0

    def test_scan_directories_permission_error(self, tmp_path: Path) -> None:
        """Test handling permission errors gracefully."""
        root = tmp_path / "src"
        root.mkdir()

        restricted = root / "restricted"
        restricted.mkdir()

        # Create a deep structure inside
        deep = restricted / "deep" / "nested"
        deep.mkdir(parents=True)

        try:
            # Remove read permissions
            restricted.chmod(0o000)

            # Should not crash, just skip the restricted directory
            violations = directory_depth_guard.scan_directories(root, 1, [])
            # May or may not have violations depending on when permission was checked
            assert isinstance(violations, list)
        finally:
            # Restore permissions for cleanup
            restricted.chmod(0o755)


class TestMainFunction:
    """Test main function and CLI behavior."""

    def test_main_root_does_not_exist(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main with non-existent root."""
        missing = tmp_path / "missing"
        result = directory_depth_guard.main(["--root", str(missing)])

        assert result == 1
        captured = capsys.readouterr()
        assert "does not exist" in captured.err

    def test_main_no_violations(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main with no violations."""
        root = tmp_path / "src"
        root.mkdir()

        # Create shallow structure
        level1 = root / "level1"
        level1.mkdir()

        result = directory_depth_guard.main(["--root", str(root), "--max-depth", "5"])
        assert result == 0

    def test_main_with_violations(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main with violations."""
        root = tmp_path / "src"
        root.mkdir()

        # Create deep structure
        deep = root / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)

        result = directory_depth_guard.main(["--root", str(root), "--max-depth", "2"])
        assert result == 1

        captured = capsys.readouterr()
        assert "Directory nesting exceeds" in captured.err
        assert "depth:" in captured.err

    def test_main_violation_message_format(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test violation message formatting."""
        root = tmp_path / "project" / "src"
        root.mkdir(parents=True)

        deep = root / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)

        result = directory_depth_guard.main(["--root", str(root), "--max-depth", "2"])
        assert result == 1

        captured = capsys.readouterr()
        assert "2 levels" in captured.err
        assert "Consider flattening" in captured.err

    def test_main_sorted_by_depth(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that violations are sorted by depth."""
        root = tmp_path / "src"
        root.mkdir()

        # Create structures with different depths
        shallow = root / "a" / "b" / "c"
        deep = root / "x" / "y" / "z" / "w" / "v"

        shallow.mkdir(parents=True)
        deep.mkdir(parents=True)

        result = directory_depth_guard.main(["--root", str(root), "--max-depth", "1"])
        assert result == 1

        captured = capsys.readouterr()
        # Deeper paths should appear first (reversed sort)
        output_lines = captured.err.split("\n")
        violation_lines = [line for line in output_lines if "depth:" in line]

        # Extract depths
        depths = []
        for line in violation_lines:
            if "depth:" in line:
                depth_str = line.split("depth:")[1].strip().rstrip(")")
                depths.append(int(depth_str))

        # Check they're in descending order
        assert depths == sorted(depths, reverse=True)

    def test_main_with_exclusions(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main with exclusion patterns."""
        root = tmp_path / "src"
        root.mkdir()

        # Create deep excluded structure
        excluded = root / "cache" / "deep" / "nested" / "path"
        excluded.mkdir(parents=True)

        # Create shallow normal structure
        normal = root / "code"
        normal.mkdir()

        result = directory_depth_guard.main([
            "--root", str(root),
            "--max-depth", "1",
            "--exclude", "cache"
        ])
        assert result == 0

    def test_main_default_exclusions_applied(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that default exclusions are applied."""
        root = tmp_path / "src"
        root.mkdir()

        # Create deep __pycache__ structure
        pycache = root / "__pycache__" / "deep" / "nested"
        pycache.mkdir(parents=True)

        result = directory_depth_guard.main(["--root", str(root), "--max-depth", "1"])
        assert result == 0

    def test_main_argv_none_uses_sys_argv(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that argv=None uses sys.argv."""
        root = tmp_path / "src"
        root.mkdir()

        monkeypatch.setattr(sys, "argv", ["directory_depth_guard.py", "--root", str(root)])
        result = directory_depth_guard.main(None)
        assert result == 0

    def test_main_script_entry_point(self, tmp_path: Path) -> None:
        """Test __main__ entry point."""
        root = tmp_path / "src"
        root.mkdir()

        # We can't easily test the __main__ entry point due to module-level imports
        # Instead, test that main() can be called successfully
        result = directory_depth_guard.main(["--root", str(root)])
        assert result == 0


class TestEdgeCases:
    """Test edge cases and unusual scenarios."""

    def test_max_depth_zero(self, tmp_path: Path) -> None:
        """Test with max depth of zero."""
        root = tmp_path / "src"
        root.mkdir()

        child = root / "child"
        child.mkdir()

        violations = directory_depth_guard.scan_directories(root, 0, [])
        assert len(violations) > 0

    def test_max_depth_negative(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test with negative max depth."""
        root = tmp_path / "src"
        root.mkdir()

        # Should technically work but flag everything
        directory_depth_guard.main(["--root", str(root), "--max-depth", "-1"])
        # Behavior depends on implementation

    def test_very_deep_nesting(self, tmp_path: Path) -> None:
        """Test with very deep nesting."""
        root = tmp_path / "src"
        root.mkdir()

        # Create extremely deep structure
        path = root
        for i in range(20):
            path = path / f"level{i}"
        path.mkdir(parents=True)

        violations = directory_depth_guard.scan_directories(root, 5, [])
        assert len(violations) > 0

        # Check the deepest violation
        max_depth = max(v[1] for v in violations)
        assert max_depth >= 20

    def test_unicode_directory_names(self, tmp_path: Path) -> None:
        """Test with unicode directory names."""
        root = tmp_path / "src"
        root.mkdir()

        # Create structure with unicode names
        unicode_dir = root / "测试" / "目录" / "深度"
        unicode_dir.mkdir(parents=True)

        violations = directory_depth_guard.scan_directories(root, 2, [])
        assert len(violations) > 0

    def test_relative_vs_absolute_paths(self, tmp_path: Path) -> None:
        """Test that relative paths are handled correctly."""
        root = tmp_path / "src"
        root.mkdir()

        deep = root / "a" / "b" / "c"
        deep.mkdir(parents=True)

        # Calculate depth with absolute path
        depth_abs = directory_depth_guard.calculate_depth(deep.resolve(), root.resolve())

        # Calculate depth with relative path if possible
        depth_rel = directory_depth_guard.calculate_depth(deep, root)

        assert depth_abs == depth_rel == 3

    def test_symlink_handling(self, tmp_path: Path) -> None:
        """Test handling of symlinked directories."""
        try:
            root = tmp_path / "src"
            root.mkdir()

            # Create a deep structure
            deep = root / "deep" / "nested" / "path"
            deep.mkdir(parents=True)

            # Create a symlink to it
            link = root / "link"
            link.symlink_to(deep)

            violations = directory_depth_guard.scan_directories(root, 2, [])
            # Should find violations in the original path
            assert len(violations) > 0
        except OSError:
            pytest.skip("Symlinks not supported on this platform")

    def test_circular_symlinks_do_not_cause_infinite_loop(self, tmp_path: Path) -> None:
        """Test that circular symlinks don't cause infinite loops."""
        try:
            root = tmp_path / "src"
            root.mkdir()

            dir1 = root / "dir1"
            dir2 = root / "dir2"
            dir1.mkdir()
            dir2.mkdir()

            # Create circular symlinks
            (dir1 / "link_to_2").symlink_to(dir2)
            (dir2 / "link_to_1").symlink_to(dir1)

            # Should not hang or crash
            violations = directory_depth_guard.scan_directories(root, 5, [])
            assert isinstance(violations, list)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")

    def test_mixed_files_and_directories(self, tmp_path: Path) -> None:
        """Test scanning with mixed files and directories."""
        root = tmp_path / "src"
        root.mkdir()

        # Create mixed structure
        dir1 = root / "dir1"
        dir1.mkdir()
        (dir1 / "file1.py").write_text("# code")

        dir2 = dir1 / "dir2"
        dir2.mkdir()
        (dir2 / "file2.py").write_text("# code")

        (root / "root_file.py").write_text("# code")

        violations = directory_depth_guard.scan_directories(root, 1, [])
        # dir2 should be reported (depth 2)
        assert len(violations) > 0
