from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from ci_tools.scripts import structure_guard
from ci_tools.scripts.guard_common import is_excluded, iter_python_files, get_class_line_span

from conftest import write_module


def test_iter_python_files_single_file(tmp_path: Path):
    """Test iter_python_files with a single file."""
    py_file = tmp_path / "test.py"
    py_file.write_text("# test")

    files = list(iter_python_files(py_file))
    assert len(files) == 1
    assert files[0] == py_file


def test_iter_python_files_non_python_file(tmp_path: Path):
    """Test iter_python_files with a non-Python file."""
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("# test")

    files = list(iter_python_files(txt_file))
    assert len(files) == 0


def test_iter_python_files_directory(tmp_path: Path):
    """Test iter_python_files with a directory."""
    (tmp_path / "file1.py").write_text("# file1")
    (tmp_path / "file2.py").write_text("# file2")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "file3.py").write_text("# file3")

    files = list(iter_python_files(tmp_path))
    assert len(files) == 3


def test_is_excluded_basic():
    """Test basic exclusion logic."""
    path = Path("/project/src/module.py").resolve()
    exclusions = [Path("/project/src").resolve()]
    assert is_excluded(path, exclusions) is True


def test_is_excluded_no_match():
    """Test exclusion with no match."""
    path = Path("/project/src/module.py").resolve()
    exclusions = [Path("/project/tests").resolve()]
    assert is_excluded(path, exclusions) is False


def test_class_line_span_basic(tmp_path: Path):
    """Test class_line_span with basic class."""
    source = textwrap.dedent(
        """
        class Foo:
            def method(self):
                pass
        """
    ).strip()

    tree = structure_guard.ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, structure_guard.ast.ClassDef)
    start, end = get_class_line_span(stmt)

    assert start == 1
    assert end == 3


def test_class_line_span_no_end_lineno(tmp_path: Path):
    """Test class_line_span when end_lineno is None."""
    source = "class Foo: pass"
    tree = structure_guard.ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, structure_guard.ast.ClassDef)

    # Simulate missing end_lineno
    if hasattr(stmt, "end_lineno"):
        delattr(stmt, "end_lineno")

    start, end = get_class_line_span(stmt)
    assert start == 1
    assert end >= start


def test_class_line_span_nested_content(tmp_path: Path):
    """Test class_line_span with nested content."""
    source = textwrap.dedent(
        """
        class Foo:
            def method1(self):
                x = 1
                return x

            def method2(self):
                y = 2
                return y
        """
    ).strip()

    tree = structure_guard.ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, structure_guard.ast.ClassDef)
    start, end = get_class_line_span(stmt)

    assert start == 1
    assert end == 8


def test_main_success_no_violations(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function with no violations."""
    root = tmp_path / "src"
    root.mkdir()
    write_module(
        root / "small.py",
        """
        class SmallClass:
            def method(self):
                return 1
        """,
    )

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = structure_guard.StructureGuard.main(["--root", str(root), "--max-class-lines", "10"])

    assert result == 0
    captured = capsys.readouterr()
    assert captured.err == ""


def test_main_detects_violations(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function detects violations."""
    root = tmp_path / "src"
    root.mkdir()
    py_file = root / "large.py"

    methods = "\n".join([f"    def method_{i}(self):\n        pass" for i in range(20)])
    content = f"class LargeClass:\n{methods}"
    py_file.write_text(content)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = structure_guard.StructureGuard.main(["--root", str(root), "--max-class-lines", "10"])

    assert result == 1
    captured = capsys.readouterr()
    assert "Oversized classes detected" in captured.err
    assert "LargeClass" in captured.err


def test_main_respects_exclusions(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function respects exclusion patterns."""
    root = tmp_path / "src"
    excluded = root / "excluded"
    root.mkdir()
    excluded.mkdir(parents=True)

    large_class = "class LargeClass:\n" + "\n".join(
        [f"    def method_{i}(self):\n        pass" for i in range(20)]
    )
    (root / "included.py").write_text(large_class)
    (excluded / "excluded.py").write_text(large_class)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = structure_guard.StructureGuard.main(
            ["--root", str(root), "--max-class-lines", "10", "--exclude", str(excluded)]
        )

    assert result == 1
    captured = capsys.readouterr()
    assert "included.py" in captured.err
    assert "excluded.py" not in captured.err


def test_main_handles_multiple_violations(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function handles multiple violations."""
    root = tmp_path / "src"
    root.mkdir()

    large_class = "class LargeClass:\n" + "\n".join(
        [f"    def method_{i}(self):\n        pass" for i in range(20)]
    )
    (root / "file1.py").write_text(large_class)
    (root / "file2.py").write_text(large_class)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = structure_guard.StructureGuard.main(["--root", str(root), "--max-class-lines", "10"])

    assert result == 1
    captured = capsys.readouterr()
    assert "file1.py" in captured.err
    assert "file2.py" in captured.err


def test_main_prints_violations_sorted(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function prints violations in sorted order."""
    root = tmp_path / "src"
    root.mkdir()

    large_class = "class LargeClass:\n" + "\n".join(
        [f"    def method_{i}(self):\n        pass" for i in range(20)]
    )
    (root / "zebra.py").write_text(large_class)
    (root / "alpha.py").write_text(large_class)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = structure_guard.StructureGuard.main(["--root", str(root), "--max-class-lines", "10"])

    assert result == 1
    captured = capsys.readouterr()
    err_lines = [
        line for line in captured.err.split("\n") if "alpha.py" in line or "zebra.py" in line
    ]
    assert len(err_lines) == 2
    assert "alpha.py" in err_lines[0]
    assert "zebra.py" in err_lines[1]


def test_main_scan_file_error(tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch):
    """Test main function handles scan_file errors."""
    root = tmp_path / "src"
    root.mkdir()
    (root / "test.py").write_text("class Foo: pass")

    def mock_scan_file(self, path, args):
        raise RuntimeError("Test error")

    monkeypatch.setattr(structure_guard.StructureGuard, "scan_file", mock_scan_file)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = structure_guard.StructureGuard.main(["--root", str(root)])

    assert result == 1
    captured = capsys.readouterr()
    assert "Test error" in captured.err


def test_class_line_span_single_line_class():
    """Test class_line_span with single-line class."""
    source = "class Foo: pass"
    tree = structure_guard.ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, structure_guard.ast.ClassDef)
    start, end = get_class_line_span(stmt)

    assert start == 1
    assert end == 1


def test_main_handles_relative_paths(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function handles relative paths correctly."""
    root = tmp_path / "src"
    root.mkdir()

    large_class = "class LargeClass:\n" + "\n".join(
        [f"    def method_{i}(self):\n        pass" for i in range(20)]
    )
    (root / "module.py").write_text(large_class)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = structure_guard.StructureGuard.main(["--root", str(root), "--max-class-lines", "10"])

    assert result == 1
    captured = capsys.readouterr()
    assert "module.py" in captured.err
    assert "LargeClass" in captured.err


def test_iter_python_files_empty_directory(tmp_path: Path):
    """Test iter_python_files with empty directory."""
    files = list(iter_python_files(tmp_path))
    assert len(files) == 0


def test_is_excluded_multiple_exclusions():
    """Test exclusion with multiple patterns."""
    path = Path("/project/tests/test_module.py").resolve()
    exclusions = [
        Path("/project/vendor").resolve(),
        Path("/project/tests").resolve(),
    ]
    assert is_excluded(path, exclusions) is True
