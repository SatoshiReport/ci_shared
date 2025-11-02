from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from ci_tools.scripts import module_guard


def write_module(path: Path, content: str) -> None:
    """Helper to write Python module content."""
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_parse_args_defaults():
    """Test argument parsing with defaults."""
    args = module_guard.parse_args([])
    assert args.root == Path("src")
    assert args.max_module_lines == 600
    assert args.exclude == []


def test_parse_args_custom_values():
    """Test argument parsing with custom values."""
    args = module_guard.parse_args(
        ["--root", "custom", "--max-module-lines", "100", "--exclude", "tests", "--exclude", "vendor"]
    )
    assert args.root == Path("custom")
    assert args.max_module_lines == 100
    assert args.exclude == [Path("tests"), Path("vendor")]


def test_iter_python_files_single_file(tmp_path: Path):
    """Test iter_python_files with a single file."""
    py_file = tmp_path / "test.py"
    py_file.write_text("# test")

    files = list(module_guard.iter_python_files(py_file))
    assert len(files) == 1
    assert files[0] == py_file


def test_iter_python_files_non_python_file(tmp_path: Path):
    """Test iter_python_files with a non-Python file."""
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("# test")

    files = list(module_guard.iter_python_files(txt_file))
    assert len(files) == 0


def test_iter_python_files_directory(tmp_path: Path):
    """Test iter_python_files with a directory."""
    (tmp_path / "file1.py").write_text("# file1")
    (tmp_path / "file2.py").write_text("# file2")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "file3.py").write_text("# file3")
    (tmp_path / "readme.txt").write_text("# readme")

    files = list(module_guard.iter_python_files(tmp_path))
    assert len(files) == 3
    assert all(f.suffix == ".py" for f in files)


def test_is_excluded_basic():
    """Test basic exclusion logic."""
    path = Path("/project/src/module.py").resolve()
    exclusions = [Path("/project/src").resolve()]
    assert module_guard.is_excluded(path, exclusions) is True


def test_is_excluded_no_match():
    """Test exclusion with no match."""
    path = Path("/project/src/module.py").resolve()
    exclusions = [Path("/project/tests").resolve()]
    assert module_guard.is_excluded(path, exclusions) is False


def test_is_excluded_value_error():
    """Test exclusion handles ValueError correctly."""
    path = Path("/project/src/module.py")
    exclusions = [Path("/other/path")]
    result = module_guard.is_excluded(path, exclusions)
    assert result is False


def test_count_lines_basic():
    """Test line counting with basic content."""
    tmp_file = Path("/tmp/test_module.py")
    tmp_file.write_text("line1\nline2\nline3\n")

    count = module_guard.count_lines(tmp_file)
    assert count == 3

    tmp_file.unlink()


def test_count_lines_ignores_comments(tmp_path: Path):
    """Test line counting ignores comment-only lines."""
    py_file = tmp_path / "test.py"
    write_module(
        py_file,
        """
        # This is a comment
        def foo():
            # Another comment
            pass

        # More comments
        """,
    )

    count = module_guard.count_lines(py_file)
    assert count == 2  # Only "def foo():" and "pass" count


def test_count_lines_ignores_empty_lines(tmp_path: Path):
    """Test line counting ignores empty lines."""
    py_file = tmp_path / "test.py"
    py_file.write_text("\n\nline1\n\n\nline2\n\n")

    count = module_guard.count_lines(py_file)
    assert count == 2


def test_count_lines_with_inline_comments(tmp_path: Path):
    """Test line counting with inline comments."""
    py_file = tmp_path / "test.py"
    write_module(
        py_file,
        """
        def foo():  # inline comment
            x = 1  # another inline comment
            return x
        """,
    )

    count = module_guard.count_lines(py_file)
    assert count == 3  # All three lines have significant content


def test_scan_file_within_limit(tmp_path: Path):
    """Test scanning a file within the line limit."""
    py_file = tmp_path / "small.py"
    write_module(
        py_file,
        """
        def foo():
            return 1
        """,
    )

    result = module_guard.scan_file(py_file, limit=10)
    assert result is None


def test_scan_file_exceeds_limit(tmp_path: Path):
    """Test scanning a file that exceeds the limit."""
    py_file = tmp_path / "large.py"
    content = "\n".join([f"line_{i} = {i}" for i in range(20)])
    py_file.write_text(content)

    result = module_guard.scan_file(py_file, limit=10)
    assert result is not None
    assert result[0] == py_file
    assert result[1] == 20


def test_scan_file_oserror(tmp_path: Path):
    """Test scan_file raises RuntimeError on OSError."""
    py_file = tmp_path / "nonexistent.py"

    with pytest.raises(RuntimeError, match="failed to read Python source"):
        module_guard.scan_file(py_file, limit=10)


def test_scan_file_unicode_decode_error(tmp_path: Path):
    """Test scan_file raises RuntimeError on UnicodeDecodeError."""
    py_file = tmp_path / "bad_encoding.py"
    py_file.write_bytes(b"\xff\xfe\x00\x00")  # Invalid UTF-8

    with pytest.raises(RuntimeError, match="failed to read Python source"):
        module_guard.scan_file(py_file, limit=10)


def test_main_success_no_violations(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function with no violations."""
    root = tmp_path / "src"
    root.mkdir()
    write_module(
        root / "small.py",
        """
        def foo():
            return 1
        """,
    )

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = module_guard.main(["--root", str(root), "--max-module-lines", "10"])

    assert result == 0
    captured = capsys.readouterr()
    assert captured.err == ""


def test_main_detects_violations(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function detects violations."""
    root = tmp_path / "src"
    root.mkdir()
    py_file = root / "large.py"
    content = "\n".join([f"line_{i} = {i}" for i in range(20)])
    py_file.write_text(content)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = module_guard.main(["--root", str(root), "--max-module-lines", "10"])

    assert result == 1
    captured = capsys.readouterr()
    assert "Oversized modules detected" in captured.err
    assert "large.py" in captured.err
    assert "20 lines" in captured.err


def test_main_respects_exclusions(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function respects exclusion patterns."""
    root = tmp_path / "src"
    excluded = root / "excluded"
    root.mkdir()
    excluded.mkdir(parents=True)

    large_content = "\n".join([f"line_{i} = {i}" for i in range(20)])
    (root / "included.py").write_text(large_content)
    (excluded / "excluded.py").write_text(large_content)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = module_guard.main(
            ["--root", str(root), "--max-module-lines", "10", "--exclude", str(excluded)]
        )

    assert result == 1
    captured = capsys.readouterr()
    assert "included.py" in captured.err
    assert "excluded.py" not in captured.err


def test_main_handles_multiple_violations(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function handles multiple violations."""
    root = tmp_path / "src"
    root.mkdir()

    large_content = "\n".join([f"line_{i} = {i}" for i in range(20)])
    (root / "large1.py").write_text(large_content)
    (root / "large2.py").write_text(large_content)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = module_guard.main(["--root", str(root), "--max-module-lines", "10"])

    assert result == 1
    captured = capsys.readouterr()
    assert "large1.py" in captured.err
    assert "large2.py" in captured.err


def test_main_prints_violations_sorted(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function prints violations in sorted order."""
    root = tmp_path / "src"
    root.mkdir()

    large_content = "\n".join([f"line_{i} = {i}" for i in range(20)])
    (root / "zebra.py").write_text(large_content)
    (root / "alpha.py").write_text(large_content)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = module_guard.main(["--root", str(root), "--max-module-lines", "10"])

    assert result == 1
    captured = capsys.readouterr()
    err_lines = [line for line in captured.err.split("\n") if "alpha.py" in line or "zebra.py" in line]
    assert len(err_lines) == 2
    assert "alpha.py" in err_lines[0]
    assert "zebra.py" in err_lines[1]


def test_main_handles_relative_paths(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function handles relative paths correctly."""
    root = tmp_path / "src"
    root.mkdir()

    large_content = "\n".join([f"line_{i} = {i}" for i in range(20)])
    (root / "module.py").write_text(large_content)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = module_guard.main(["--root", str(root), "--max-module-lines", "10"])

    assert result == 1
    captured = capsys.readouterr()
    assert "src/module.py" in captured.err or "src\\module.py" in captured.err


def test_main_scan_file_error(tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch):
    """Test main function handles scan_file errors."""
    root = tmp_path / "src"
    root.mkdir()
    (root / "test.py").write_text("# test")

    def mock_scan_file(path, limit):
        raise RuntimeError("Test error")

    monkeypatch.setattr(module_guard, "scan_file", mock_scan_file)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = module_guard.main(["--root", str(root)])

    assert result == 1
    captured = capsys.readouterr()
    assert "Test error" in captured.err


def test_iter_python_files_empty_directory(tmp_path: Path):
    """Test iter_python_files with empty directory."""
    files = list(module_guard.iter_python_files(tmp_path))
    assert len(files) == 0


def test_count_lines_only_comments(tmp_path: Path):
    """Test line counting with only comments."""
    py_file = tmp_path / "comments.py"
    py_file.write_text("# comment1\n# comment2\n# comment3\n")

    count = module_guard.count_lines(py_file)
    assert count == 0


def test_count_lines_mixed_content(tmp_path: Path):
    """Test line counting with mixed content."""
    py_file = tmp_path / "mixed.py"
    write_module(
        py_file,
        """
        # Header comment

        def foo():
            # Function comment
            x = 1

            # Another comment
            return x

        # Footer comment
        """,
    )

    count = module_guard.count_lines(py_file)
    assert count == 3  # def foo():, x = 1, return x (empty lines don't count)


def test_is_excluded_multiple_exclusions():
    """Test exclusion with multiple patterns."""
    path = Path("/project/tests/test_module.py").resolve()
    exclusions = [
        Path("/project/vendor").resolve(),
        Path("/project/tests").resolve(),
        Path("/project/docs").resolve(),
    ]
    assert module_guard.is_excluded(path, exclusions) is True


def test_is_excluded_partial_match():
    """Test exclusion doesn't match partial paths."""
    path = Path("/project/src/tests_helper.py").resolve()
    exclusions = [Path("/project/tests").resolve()]
    assert module_guard.is_excluded(path, exclusions) is False
