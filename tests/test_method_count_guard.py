from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from ci_tools.scripts import method_count_guard


def write_module(path: Path, content: str) -> None:
    """Helper to write Python module content."""
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_parse_args_defaults():
    """Test argument parsing with defaults."""
    args = method_count_guard.parse_args([])
    assert args.root == Path("src")
    assert args.max_public_methods == 15
    assert args.max_total_methods == 25
    assert args.exclude == []


def test_parse_args_custom_values():
    """Test argument parsing with custom values."""
    args = method_count_guard.parse_args(
        [
            "--root",
            "custom",
            "--max-public-methods",
            "10",
            "--max-total-methods",
            "20",
            "--exclude",
            "tests",
        ]
    )
    assert args.root == Path("custom")
    assert args.max_public_methods == 10
    assert args.max_total_methods == 20
    assert args.exclude == [Path("tests")]


def test_iter_python_files_single_file(tmp_path: Path):
    """Test iter_python_files with a single file."""
    py_file = tmp_path / "test.py"
    py_file.write_text("# test")

    files = list(method_count_guard.iter_python_files(py_file))
    assert len(files) == 1
    assert files[0] == py_file


def test_iter_python_files_non_python_file(tmp_path: Path):
    """Test iter_python_files with a non-Python file."""
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("# test")

    files = list(method_count_guard.iter_python_files(txt_file))
    assert len(files) == 0


def test_is_excluded_basic():
    """Test basic exclusion logic."""
    path = Path("/project/src/module.py").resolve()
    exclusions = [Path("/project/src").resolve()]
    assert method_count_guard.is_excluded(path, exclusions) is True


def test_is_excluded_no_match():
    """Test exclusion with no match."""
    path = Path("/project/src/module.py").resolve()
    exclusions = [Path("/project/tests").resolve()]
    assert method_count_guard.is_excluded(path, exclusions) is False


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


def test_scan_file_within_limit(tmp_path: Path):
    """Test scanning a file within the method count limit."""
    py_file = tmp_path / "small.py"
    write_module(
        py_file,
        """
        class SmallClass:
            def method1(self):
                pass

            def method2(self):
                pass
        """,
    )

    violations = method_count_guard.scan_file(py_file, max_public=5, max_total=10)
    assert len(violations) == 0


def test_scan_file_exceeds_public_limit(tmp_path: Path):
    """Test scanning a file that exceeds public method limit."""
    py_file = tmp_path / "many_public.py"
    methods = "\n".join([f"    def method_{i}(self):\n        pass" for i in range(20)])
    content = f"class ManyMethods:\n{methods}"
    py_file.write_text(content)

    violations = method_count_guard.scan_file(py_file, max_public=10, max_total=30)
    assert len(violations) == 1
    assert violations[0][1] == "ManyMethods"
    assert violations[0][3] == 20  # public_count


def test_scan_file_exceeds_total_limit(tmp_path: Path):
    """Test scanning a file that exceeds total method limit."""
    py_file = tmp_path / "many_total.py"
    methods = "\n".join([f"    def _method_{i}(self):\n        pass" for i in range(30)])
    content = f"class ManyMethods:\n{methods}"
    py_file.write_text(content)

    violations = method_count_guard.scan_file(py_file, max_public=25, max_total=20)
    assert len(violations) == 1
    assert violations[0][1] == "ManyMethods"
    assert violations[0][4] == 30  # total_count


def test_scan_file_syntax_error(tmp_path: Path):
    """Test scan_file with syntax error."""
    py_file = tmp_path / "bad.py"
    py_file.write_text("class Foo:\n    def method(self\n")

    with pytest.raises(RuntimeError, match="failed to parse Python source"):
        method_count_guard.scan_file(py_file, max_public=10, max_total=20)


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


def test_format_method_violation_public():
    """Test formatting violation message for public methods."""
    violation = method_count_guard._format_method_violation(
        Path("/project/src/module.py"),
        class_name="BigClass",
        lineno=10,
        public_count=20,
        total_count=25,
        max_public=15,
        max_total=30,
        repo_root=Path("/project"),
    )

    assert "module.py:10" in violation or "module.py" in violation
    assert "BigClass" in violation
    assert "20 public methods" in violation
    assert "limit 15" in violation


def test_format_method_violation_total():
    """Test formatting violation message for total methods."""
    violation = method_count_guard._format_method_violation(
        Path("/project/src/module.py"),
        class_name="BigClass",
        lineno=10,
        public_count=10,
        total_count=30,
        max_public=15,
        max_total=25,
        repo_root=Path("/project"),
    )

    assert "BigClass" in violation
    assert "30 total methods" in violation
    assert "limit 25" in violation


def test_format_method_violation_both():
    """Test formatting violation message for both limits exceeded."""
    violation = method_count_guard._format_method_violation(
        Path("/project/src/module.py"),
        class_name="BigClass",
        lineno=10,
        public_count=20,
        total_count=30,
        max_public=15,
        max_total=25,
        repo_root=Path("/project"),
    )

    assert "BigClass" in violation
    assert "20 public methods" in violation
    assert "30 total methods" in violation


def test_collect_method_violations(tmp_path: Path):
    """Test collecting method violations."""
    py_file = tmp_path / "test.py"
    methods = "\n".join([f"    def method_{i}(self):\n        pass" for i in range(20)])
    content = f"class BigClass:\n{methods}"
    py_file.write_text(content)

    violations = method_count_guard._collect_method_violations(
        py_file, max_public=5, max_total=10, repo_root=tmp_path
    )

    assert len(violations) == 1
    assert "BigClass" in violations[0]


def test_print_method_report(capsys: pytest.CaptureFixture):
    """Test printing method count report."""
    violations = ["violation1", "violation2"]
    method_count_guard._print_method_report(violations)

    captured = capsys.readouterr()
    assert "too many methods" in captured.err
    assert "multi-concern indicator" in captured.err
    assert "service objects" in captured.err
    assert "violation1" in captured.err
    assert "violation2" in captured.err


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


def test_scan_file_multiple_classes(tmp_path: Path):
    """Test scanning file with multiple classes."""
    py_file = tmp_path / "multi.py"
    write_module(
        py_file,
        """
        class SmallClass:
            def method(self):
                pass

        class BigClass:
            def method1(self):
                pass
            def method2(self):
                pass
            def method3(self):
                pass
            def method4(self):
                pass
            def method5(self):
                pass
            def method6(self):
                pass
        """,
    )

    violations = method_count_guard.scan_file(py_file, max_public=3, max_total=5)
    assert len(violations) == 1
    assert violations[0][1] == "BigClass"


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


def test_scan_file_no_classes(tmp_path: Path):
    """Test scanning file with no classes."""
    py_file = tmp_path / "no_classes.py"
    write_module(
        py_file,
        """
        def function():
            pass
        """,
    )

    violations = method_count_guard.scan_file(py_file, max_public=5, max_total=10)
    assert len(violations) == 0


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
    files = list(method_count_guard.iter_python_files(tmp_path))
    assert len(files) == 0
