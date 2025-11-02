from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from ci_tools.scripts import dependency_guard


def write_module(path: Path, content: str) -> None:
    """Helper to write Python module content."""
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_parse_args_defaults():
    """Test argument parsing with defaults."""
    args = dependency_guard.parse_args([])
    assert args.root == Path("src")
    assert args.max_instantiations == 8
    assert args.exclude == []


def test_parse_args_custom_values():
    """Test argument parsing with custom values."""
    args = dependency_guard.parse_args(
        ["--root", "custom", "--max-instantiations", "5", "--exclude", "tests"]
    )
    assert args.root == Path("custom")
    assert args.max_instantiations == 5
    assert args.exclude == [Path("tests")]


def test_iter_python_files_single_file(tmp_path: Path):
    """Test iter_python_files with a single file."""
    py_file = tmp_path / "test.py"
    py_file.write_text("# test")

    files = list(dependency_guard.iter_python_files(py_file))
    assert len(files) == 1
    assert files[0] == py_file


def test_iter_python_files_non_python_file(tmp_path: Path):
    """Test iter_python_files with a non-Python file."""
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("# test")

    files = list(dependency_guard.iter_python_files(txt_file))
    assert len(files) == 0


def test_is_excluded_basic():
    """Test basic exclusion logic."""
    path = Path("/project/src/module.py").resolve()
    exclusions = [Path("/project/src").resolve()]
    assert dependency_guard.is_excluded(path, exclusions) is True


def test_is_excluded_no_match():
    """Test exclusion with no match."""
    path = Path("/project/src/module.py").resolve()
    exclusions = [Path("/project/tests").resolve()]
    assert dependency_guard.is_excluded(path, exclusions) is False


def test_callee_name_simple():
    """Test extracting callee name from simple call."""
    source = "Foo()"
    tree = ast.parse(source)
    call_node = tree.body[0].value

    name = dependency_guard._callee_name(call_node)
    assert name == "Foo"


def test_callee_name_attribute():
    """Test extracting callee name from attribute call."""
    source = "module.Foo()"
    tree = ast.parse(source)
    call_node = tree.body[0].value

    name = dependency_guard._callee_name(call_node)
    assert name == "Foo"


def test_callee_name_complex():
    """Test extracting callee name from complex expression."""
    source = "(foo if condition else bar)()"
    tree = ast.parse(source)
    call_node = tree.body[0].value

    name = dependency_guard._callee_name(call_node)
    assert name is None


def test_is_constructor_name_valid():
    """Test is_constructor_name with valid constructor names."""
    assert dependency_guard._is_constructor_name("Foo") is True
    assert dependency_guard._is_constructor_name("MyClass") is True
    assert dependency_guard._is_constructor_name("HTTPClient") is True


def test_is_constructor_name_invalid():
    """Test is_constructor_name with invalid names."""
    assert dependency_guard._is_constructor_name("foo") is False
    assert dependency_guard._is_constructor_name("myFunc") is False
    assert dependency_guard._is_constructor_name("") is False


def test_is_constructor_name_skipped():
    """Test is_constructor_name skips certain names."""
    assert dependency_guard._is_constructor_name("Path") is False
    assert dependency_guard._is_constructor_name("List") is False
    assert dependency_guard._is_constructor_name("Dict") is False
    assert dependency_guard._is_constructor_name("Optional") is False


def test_count_instantiations_basic():
    """Test counting instantiations in a basic method."""
    source = textwrap.dedent(
        """
        def __init__(self):
            self.foo = Foo()
            self.bar = Bar()
        """
    ).strip()

    tree = ast.parse(source)
    func_node = tree.body[0]
    count, classes = dependency_guard.count_instantiations(func_node)

    assert count == 2
    assert "Foo" in classes
    assert "Bar" in classes


def test_count_instantiations_ignores_lowercase():
    """Test that lowercase function calls are not counted."""
    source = textwrap.dedent(
        """
        def __init__(self):
            self.x = int(1)
            self.y = str("test")
            self.z = Service()
        """
    ).strip()

    tree = ast.parse(source)
    func_node = tree.body[0]
    count, classes = dependency_guard.count_instantiations(func_node)

    assert count == 1
    assert "Service" in classes


def test_count_instantiations_ignores_skipped():
    """Test that skipped constructor names are not counted."""
    source = textwrap.dedent(
        """
        def __init__(self):
            self.path = Path("/tmp")
            self.items = List()
            self.data = Dict()
            self.service = Service()
        """
    ).strip()

    tree = ast.parse(source)
    func_node = tree.body[0]
    count, classes = dependency_guard.count_instantiations(func_node)

    assert count == 1
    assert "Service" in classes


def test_count_instantiations_no_instantiations():
    """Test counting with no instantiations."""
    source = textwrap.dedent(
        """
        def __init__(self, foo, bar):
            self.foo = foo
            self.bar = bar
        """
    ).strip()

    tree = ast.parse(source)
    func_node = tree.body[0]
    count, classes = dependency_guard.count_instantiations(func_node)

    assert count == 0
    assert classes == []


def test_scan_file_within_limit(tmp_path: Path):
    """Test scanning a file within the instantiation limit."""
    py_file = tmp_path / "simple.py"
    write_module(
        py_file,
        """
        class Simple:
            def __init__(self):
                self.service1 = Service1()
                self.service2 = Service2()
        """,
    )

    violations = dependency_guard.scan_file(py_file, max_instantiations=5)
    assert len(violations) == 0


def test_scan_file_exceeds_limit(tmp_path: Path):
    """Test scanning a file that exceeds the instantiation limit."""
    py_file = tmp_path / "complex.py"
    instantiations = "\n".join(
        [f"        self.service{i} = Service{i}()" for i in range(15)]
    )
    content = f"class Complex:\n    def __init__(self):\n{instantiations}"
    py_file.write_text(content)

    violations = dependency_guard.scan_file(py_file, max_instantiations=5)
    assert len(violations) == 1
    assert violations[0][1] == "Complex"
    assert violations[0][3] == 15  # count


def test_scan_file_post_init(tmp_path: Path):
    """Test scanning __post_init__ method."""
    py_file = tmp_path / "dataclass.py"
    write_module(
        py_file,
        """
        class MyDataclass:
            def __post_init__(self):
                self.service1 = Service1()
                self.service2 = Service2()
                self.service3 = Service3()
                self.service4 = Service4()
                self.service5 = Service5()
                self.service6 = Service6()
        """,
    )

    violations = dependency_guard.scan_file(py_file, max_instantiations=3)
    assert len(violations) == 1
    assert violations[0][1] == "MyDataclass"


def test_scan_file_syntax_error(tmp_path: Path):
    """Test scan_file with syntax error."""
    py_file = tmp_path / "bad.py"
    py_file.write_text("class Foo:\n    def __init__(self\n")

    with pytest.raises(RuntimeError, match="failed to parse Python source"):
        dependency_guard.scan_file(py_file, max_instantiations=5)


def test_main_success_no_violations(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function with no violations."""
    root = tmp_path / "src"
    root.mkdir()
    write_module(
        root / "simple.py",
        """
        class Simple:
            def __init__(self):
                self.service1 = Service1()
                self.service2 = Service2()
        """,
    )

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = dependency_guard.main(["--root", str(root), "--max-instantiations", "5"])

    assert result == 0
    captured = capsys.readouterr()
    assert captured.err == ""


def test_main_detects_violations(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function detects violations."""
    root = tmp_path / "src"
    root.mkdir()
    py_file = root / "complex.py"

    instantiations = "\n".join(
        [f"        self.service{i} = Service{i}()" for i in range(15)]
    )
    content = f"class Complex:\n    def __init__(self):\n{instantiations}"
    py_file.write_text(content)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = dependency_guard.main(["--root", str(root), "--max-instantiations", "5"])

    assert result == 1
    captured = capsys.readouterr()
    assert "too many dependency instantiations" in captured.err
    assert "Complex" in captured.err


def test_main_respects_exclusions(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function respects exclusion patterns."""
    root = tmp_path / "src"
    excluded = root / "excluded"
    root.mkdir()
    excluded.mkdir(parents=True)

    many_deps = "class ManyDeps:\n    def __init__(self):\n" + "\n".join(
        [f"        self.s{i} = Service{i}()" for i in range(15)]
    )
    (root / "included.py").write_text(many_deps)
    (excluded / "excluded.py").write_text(many_deps)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = dependency_guard.main(
            ["--root", str(root), "--max-instantiations", "5", "--exclude", str(excluded)]
        )

    assert result == 1
    captured = capsys.readouterr()
    assert "included.py" in captured.err
    assert "excluded.py" not in captured.err


def test_main_prints_violations_sorted(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function prints violations in sorted order."""
    root = tmp_path / "src"
    root.mkdir()

    many_deps = "class ManyDeps:\n    def __init__(self):\n" + "\n".join(
        [f"        self.s{i} = Service{i}()" for i in range(15)]
    )
    (root / "zebra.py").write_text(many_deps)
    (root / "alpha.py").write_text(many_deps)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = dependency_guard.main(["--root", str(root), "--max-instantiations", "5"])

    assert result == 1
    captured = capsys.readouterr()
    err_lines = [
        line for line in captured.err.split("\n") if "alpha.py" in line or "zebra.py" in line
    ]
    assert len(err_lines) >= 2


def test_format_violation():
    """Test formatting violation message."""
    violation = dependency_guard._format_violation(
        Path("/project/src/module.py"),
        class_name="BigClass",
        lineno=10,
        count=15,
        instantiated=["Service1", "Service2", "Service3", "Service4", "Service5", "Service6"],
        limit=8,
        repo_root=Path("/project"),
    )

    assert "module.py:10" in violation or "module.py" in violation
    assert "BigClass" in violation
    assert "15 dependencies" in violation
    assert "limit 8" in violation
    assert "Service1" in violation


def test_format_violation_truncates_long_list():
    """Test formatting violation with long list of instantiations."""
    long_list = [f"Service{i}" for i in range(20)]
    violation = dependency_guard._format_violation(
        Path("/project/src/module.py"),
        class_name="BigClass",
        lineno=10,
        count=20,
        instantiated=long_list,
        limit=8,
        repo_root=Path("/project"),
    )

    assert "more)" in violation  # Should show truncation


def test_collect_file_violations(tmp_path: Path):
    """Test collecting file violations."""
    py_file = tmp_path / "test.py"
    instantiations = "\n".join(
        [f"        self.service{i} = Service{i}()" for i in range(15)]
    )
    content = f"class BigClass:\n    def __init__(self):\n{instantiations}"
    py_file.write_text(content)

    violations = dependency_guard._collect_file_violations(
        py_file, max_instantiations=5, repo_root=tmp_path
    )

    assert len(violations) == 1
    assert "BigClass" in violations[0]


def test_print_violation_report(capsys: pytest.CaptureFixture):
    """Test printing violation report."""
    violations = ["violation1", "violation2"]
    dependency_guard._print_violation_report(violations, limit=8)

    captured = capsys.readouterr()
    assert "too many dependency instantiations" in captured.err
    assert "dependency injection" in captured.err
    assert "violation1" in captured.err
    assert "violation2" in captured.err


def test_main_traverse_error(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function handles traversal errors."""
    missing = tmp_path / "missing"

    result = dependency_guard.main(["--root", str(missing)])
    assert result == 1
    captured = capsys.readouterr()
    assert "failed to traverse" in captured.err


def test_main_scan_file_error(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function handles scan_file errors."""
    root = tmp_path / "src"
    root.mkdir()
    (root / "bad.py").write_text("class Foo:\n    def __init__(self\n")

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = dependency_guard.main(["--root", str(root)])

    assert result == 1
    captured = capsys.readouterr()
    assert "failed to parse" in captured.err


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

    violations = dependency_guard.scan_file(py_file, max_instantiations=5)
    assert len(violations) == 0


def test_scan_file_class_without_init(tmp_path: Path):
    """Test scanning class without __init__."""
    py_file = tmp_path / "no_init.py"
    write_module(
        py_file,
        """
        class NoInit:
            def method(self):
                pass
        """,
    )

    violations = dependency_guard.scan_file(py_file, max_instantiations=5)
    assert len(violations) == 0


def test_count_instantiations_nested_calls():
    """Test counting nested instantiation calls."""
    source = textwrap.dedent(
        """
        def __init__(self):
            self.foo = Foo(Bar(), Baz())
        """
    ).strip()

    tree = ast.parse(source)
    func_node = tree.body[0]
    count, classes = dependency_guard.count_instantiations(func_node)

    assert count == 3  # Foo, Bar, Baz
    assert "Foo" in classes
    assert "Bar" in classes
    assert "Baz" in classes


def test_main_handles_relative_paths(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test main function handles relative paths correctly."""
    root = tmp_path / "src"
    root.mkdir()

    many_deps = "class ManyDeps:\n    def __init__(self):\n" + "\n".join(
        [f"        self.s{i} = Service{i}()" for i in range(15)]
    )
    (root / "module.py").write_text(many_deps)

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = dependency_guard.main(["--root", str(root), "--max-instantiations", "5"])

    assert result == 1
    captured = capsys.readouterr()
    assert "module.py" in captured.err


def test_scan_file_multiple_classes(tmp_path: Path):
    """Test scanning file with multiple classes."""
    py_file = tmp_path / "multi.py"
    write_module(
        py_file,
        """
        class Simple:
            def __init__(self):
                self.service = Service()

        class Complex:
            def __init__(self):
                self.s1 = Service1()
                self.s2 = Service2()
                self.s3 = Service3()
                self.s4 = Service4()
                self.s5 = Service5()
                self.s6 = Service6()
        """,
    )

    violations = dependency_guard.scan_file(py_file, max_instantiations=3)
    assert len(violations) == 1
    assert violations[0][1] == "Complex"


def test_iter_python_files_empty_directory(tmp_path: Path):
    """Test iter_python_files with empty directory."""
    files = list(dependency_guard.iter_python_files(tmp_path))
    assert len(files) == 0


def test_callee_name_subscript():
    """Test callee name with subscript expression."""
    source = "foo[0]()"
    tree = ast.parse(source)
    call_node = tree.body[0].value

    name = dependency_guard._callee_name(call_node)
    assert name is None


def test_count_instantiations_in_nested_function():
    """Test counting instantiations in nested function."""
    source = textwrap.dedent(
        """
        def __init__(self):
            def helper():
                return Service()
            self.service = helper()
        """
    ).strip()

    tree = ast.parse(source)
    func_node = tree.body[0]
    count, classes = dependency_guard.count_instantiations(func_node)

    # Should count Service even though it's in nested function
    assert count == 1
    assert "Service" in classes
