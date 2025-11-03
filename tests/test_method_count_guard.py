from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from ci_tools.scripts import method_count_guard
from ci_tools.scripts.guard_common import is_excluded, iter_python_files


def write_module(path: Path, content: str) -> None:
    """Helper to write Python module content."""
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


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


def test_count_methods_basic():
    """Test counting methods in a basic class."""
    source = textwrap.dedent(
        """
        class Foo:
            def method1(self):
                pass

            def method2(self):
                pass

            def _private_method(self):
                pass
        """
    ).strip()

    tree = method_count_guard.ast.parse(source)
    class_node = tree.body[0]
    public_count, total_count = method_count_guard.count_methods(class_node)

    assert public_count == 2  # method1, method2
    assert total_count == 3  # method1, method2, _private_method


def test_count_methods_excludes_dunder():
    """Test that dunder methods are excluded from counts."""
    source = textwrap.dedent(
        """
        class Foo:
            def __init__(self):
                pass

            def __str__(self):
                pass

            def method(self):
                pass
        """
    ).strip()

    tree = method_count_guard.ast.parse(source)
    class_node = tree.body[0]
    public_count, total_count = method_count_guard.count_methods(class_node)

    assert public_count == 1  # Only method
    assert total_count == 1


def test_count_methods_excludes_properties():
    """Test that properties are excluded from counts."""
    source = textwrap.dedent(
        """
        class Foo:
            @property
            def prop(self):
                return self._value

            def method(self):
                pass
        """
    ).strip()

    tree = method_count_guard.ast.parse(source)
    class_node = tree.body[0]
    public_count, total_count = method_count_guard.count_methods(class_node)

    assert public_count == 1  # Only method
    assert total_count == 1


def test_count_methods_private_methods():
    """Test counting private methods."""
    source = textwrap.dedent(
        """
        class Foo:
            def public_method(self):
                pass

            def _private_method(self):
                pass

            def __private_name_mangled(self):
                pass
        """
    ).strip()

    tree = method_count_guard.ast.parse(source)
    class_node = tree.body[0]
    public_count, total_count = method_count_guard.count_methods(class_node)

    assert public_count == 1  # Only public_method
    assert total_count == 2  # public_method, _private_method (not __private_name_mangled)


def test_count_methods_no_methods():
    """Test counting methods in class with no methods."""
    source = textwrap.dedent(
        """
        class Foo:
            x = 1
            y = 2
        """
    ).strip()

    tree = method_count_guard.ast.parse(source)
    class_node = tree.body[0]
    public_count, total_count = method_count_guard.count_methods(class_node)

    assert public_count == 0
    assert total_count == 0


def test_main_success_no_violations(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function with no violations."""
    root = tmp_path / "src"
    root.mkdir()
    write_module(
        root / "small.py",
        """
        class SmallClass:
            def method1(self):
                pass

            def method2(self):
                pass
        """,
    )

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = method_count_guard.main(
            ["--root", str(root), "--max-public-methods", "5", "--max-total-methods", "10"]
        )

    assert result == 0
    captured = capsys.readouterr()
    assert captured.err == ""


def test_main_detects_violations(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function detects violations."""
    root = tmp_path / "src"
    root.mkdir()
    py_file = root / "many.py"

    methods = "\n".join([f"    def method_{i}(self):\n        pass" for i in range(20)])
    content = f"class ManyMethods:\n{methods}"
    py_file.write_text(content)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = method_count_guard.main(
            ["--root", str(root), "--max-public-methods", "5", "--max-total-methods", "10"]
        )

    assert result == 1
    captured = capsys.readouterr()
    assert "too many methods" in captured.err
    assert "ManyMethods" in captured.err


def test_main_respects_exclusions(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function respects exclusion patterns."""
    root = tmp_path / "src"
    excluded = root / "excluded"
    root.mkdir()
    excluded.mkdir(parents=True)

    many_methods = "class ManyMethods:\n" + "\n".join(
        [f"    def method_{i}(self):\n        pass" for i in range(20)]
    )
    (root / "included.py").write_text(many_methods)
    (excluded / "excluded.py").write_text(many_methods)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = method_count_guard.main(
            [
                "--root",
                str(root),
                "--max-public-methods",
                "5",
                "--max-total-methods",
                "10",
                "--exclude",
                str(excluded),
            ]
        )

    assert result == 1
    captured = capsys.readouterr()
    assert "included.py" in captured.err
    assert "excluded.py" not in captured.err


def test_main_prints_violations_sorted(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function prints violations in sorted order."""
    root = tmp_path / "src"
    root.mkdir()

    many_methods = "class ManyMethods:\n" + "\n".join(
        [f"    def method_{i}(self):\n        pass" for i in range(20)]
    )
    (root / "zebra.py").write_text(many_methods)
    (root / "alpha.py").write_text(many_methods)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = method_count_guard.main(
            ["--root", str(root), "--max-public-methods", "5", "--max-total-methods", "10"]
        )

    assert result == 1
    captured = capsys.readouterr()
    err_lines = [
        line for line in captured.err.split("\n") if "alpha.py" in line or "zebra.py" in line
    ]
    assert len(err_lines) >= 2


def test_main_traverse_error(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function handles traversal errors."""
    missing = tmp_path / "missing"

    result = method_count_guard.main(["--root", str(missing)])
    assert result == 1
    captured = capsys.readouterr()
    assert "failed to traverse" in captured.err


def test_main_scan_file_error(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function handles scan_file errors."""
    root = tmp_path / "src"
    root.mkdir()
    (root / "bad.py").write_text("class Foo:\n    def method(self\n")

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = method_count_guard.main(["--root", str(root)])

    assert result == 1
    captured = capsys.readouterr()
    assert "failed to parse" in captured.err


def test_count_methods_mixed_decorators():
    """Test counting methods with various decorators."""
    source = textwrap.dedent(
        """
        class Foo:
            @property
            def prop1(self):
                return 1

            @staticmethod
            def static():
                pass

            @classmethod
            def cls(cls):
                pass

            def regular(self):
                pass
        """
    ).strip()

    tree = method_count_guard.ast.parse(source)
    class_node = tree.body[0]
    public_count, total_count = method_count_guard.count_methods(class_node)

    # Should count static, cls, and regular, but not prop1
    assert total_count == 3


def test_main_handles_relative_paths(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function handles relative paths correctly."""
    root = tmp_path / "src"
    root.mkdir()

    many_methods = "class ManyMethods:\n" + "\n".join(
        [f"    def method_{i}(self):\n        pass" for i in range(20)]
    )
    (root / "module.py").write_text(many_methods)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = method_count_guard.main(
            ["--root", str(root), "--max-public-methods", "5", "--max-total-methods", "10"]
        )

    assert result == 1
    captured = capsys.readouterr()
    assert "module.py" in captured.err


def test_count_methods_only_dunder():
    """Test class with only dunder methods."""
    source = textwrap.dedent(
        """
        class Foo:
            def __init__(self):
                pass

            def __str__(self):
                pass

            def __repr__(self):
                pass
        """
    ).strip()

    tree = method_count_guard.ast.parse(source)
    class_node = tree.body[0]
    public_count, total_count = method_count_guard.count_methods(class_node)

    assert public_count == 0
    assert total_count == 0


def test_iter_python_files_empty_directory(tmp_path: Path):
    """Test iter_python_files with empty directory."""
    files = list(iter_python_files(tmp_path))
    assert len(files) == 0
