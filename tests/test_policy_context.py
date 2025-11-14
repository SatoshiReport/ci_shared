"""Unit tests for policy_context module."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from ci_tools.scripts.guard_common import parse_python_ast, relative_path
from ci_tools.scripts.policy_visitors import _resolve_default_argument
from ci_tools.scripts.policy_context import (
    BANNED_KEYWORDS,
    BROAD_EXCEPT_SUPPRESSION,
    BROAD_EXCEPTION_NAMES,
    CONFIG_EXTENSIONS,
    FLAGGED_TOKENS,
    FORBIDDEN_SYNC_CALLS,
    FUNCTION_LENGTH_THRESHOLD,
    LEGACY_CONFIG_TOKENS,
    LEGACY_GUARD_TOKENS,
    LEGACY_SUFFIXES,
    ROOT,
    SCAN_DIRECTORIES,
    SILENT_HANDLER_SUPPRESSION,
    SUPPRESSION_PATTERNS,
    FunctionEntry,
    FunctionNormalizer,
    ModuleContext,
    classify_handler,
    get_call_qualname,
    handler_contains_suppression,
    handler_has_raise,
    is_literal_none_guard,
    is_logging_call,
    is_non_none_literal,
    iter_module_contexts,
    iter_python_files,
    normalize_function,
)


def test_constants_are_defined():
    """Test that all expected constants are defined."""
    assert isinstance(ROOT, Path)
    assert isinstance(SCAN_DIRECTORIES, tuple)
    assert isinstance(BANNED_KEYWORDS, tuple)
    assert isinstance(FLAGGED_TOKENS, tuple)
    assert isinstance(FUNCTION_LENGTH_THRESHOLD, int)
    assert isinstance(BROAD_EXCEPT_SUPPRESSION, str)
    assert isinstance(SILENT_HANDLER_SUPPRESSION, str)
    assert isinstance(SUPPRESSION_PATTERNS, tuple)
    assert isinstance(FORBIDDEN_SYNC_CALLS, tuple)
    assert isinstance(LEGACY_GUARD_TOKENS, tuple)
    assert isinstance(LEGACY_SUFFIXES, tuple)
    assert isinstance(LEGACY_CONFIG_TOKENS, tuple)
    assert isinstance(CONFIG_EXTENSIONS, tuple)
    assert isinstance(BROAD_EXCEPTION_NAMES, set)


def test_function_entry_dataclass():
    """Test FunctionEntry dataclass creation."""
    entry = FunctionEntry(
        path=Path("/test/file.py"),
        name="test_func",
        lineno=10,
        length=20,
    )
    assert entry.path == Path("/test/file.py")
    assert entry.name == "test_func"
    assert entry.lineno == 10
    assert entry.length == 20


def test_function_entry_is_frozen():
    """Test FunctionEntry is immutable."""
    entry = FunctionEntry(
        path=Path("/test/file.py"),
        name="test_func",
        lineno=10,
        length=20,
    )
    with pytest.raises(AttributeError):
        setattr(entry, "name", "other")


def test_module_context_dataclass():
    """Test ModuleContext dataclass creation."""
    tree = ast.parse("x = 1")
    ctx = ModuleContext(
        path=Path("/test/file.py"),
        rel_path="test/file.py",
        tree=tree,
        source="x = 1",
        lines=["x = 1"],
    )
    assert ctx.path == Path("/test/file.py")
    assert ctx.rel_path == "test/file.py"
    assert ctx.tree is tree
    assert ctx.source == "x = 1"
    assert ctx.lines == ["x = 1"]


def test_module_context_optional_fields():
    """Test ModuleContext with optional fields omitted."""
    tree = ast.parse("x = 1")
    ctx = ModuleContext(
        path=Path("/test/file.py"),
        rel_path="test/file.py",
        tree=tree,
    )
    assert ctx.source is None
    assert ctx.lines is None


def test_function_normalizer_visit_name():
    """Test FunctionNormalizer normalizes Name nodes."""
    source = "x = y + z"
    tree = ast.parse(source)
    normalizer = FunctionNormalizer()
    normalized = normalizer.visit(tree)
    code = ast.unparse(normalized)
    assert "var" in code


def test_function_normalizer_visit_arg():
    """Test FunctionNormalizer normalizes arg nodes."""
    source = "def foo(bar: int, baz: str) -> None: pass"
    tree = ast.parse(source)
    normalizer = FunctionNormalizer()
    normalized = normalizer.visit(tree)
    func = normalized.body[0]
    assert all(arg.arg == "arg" for arg in func.args.args)


def test_normalize_function_simple():
    """Test normalize_function with simple function."""
    source = textwrap.dedent(
        """
        def foo(x, y):
            return x + y
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.FunctionDef)
    result = normalize_function(stmt)
    assert isinstance(result, str)
    assert "FunctionDef" in result


def test_normalize_function_with_docstring():
    """Test normalize_function removes docstring."""
    source = textwrap.dedent(
        """
        def foo(x):
            \"\"\"Docstring here.\"\"\"
            return x + 1
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.FunctionDef)
    result = normalize_function(stmt)
    # Docstring should be removed from normalized form
    assert isinstance(result, str)


def test_normalize_function_async():
    """Test normalize_function with async function."""
    source = textwrap.dedent(
        """
        async def foo(x, y):
            return x + y
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.AsyncFunctionDef)
    result = normalize_function(stmt)
    assert isinstance(result, str)
    assert "AsyncFunctionDef" in result


def test_normalize_path(tmp_path):
    """Test relative_path converts to relative path."""
    test_file = tmp_path / "subdir" / "file.py"
    result = relative_path(test_file, tmp_path, as_string=True)
    assert result == "subdir/file.py"


def test_iter_python_files_finds_files(tmp_path):
    """Test iter_python_files finds Python files."""
    (tmp_path / "file1.py").write_text("x = 1")
    (tmp_path / "file2.py").write_text("y = 2")
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "file3.py").write_text("z = 3")

    files = list(iter_python_files([tmp_path]))
    assert len(files) == 3
    assert all(f.suffix == ".py" for f in files)


def test_iter_python_files_ignores_non_python(tmp_path):
    """Test iter_python_files ignores non-Python files."""
    (tmp_path / "file.py").write_text("x = 1")
    (tmp_path / "file.txt").write_text("text")
    (tmp_path / "file.md").write_text("markdown")

    files = list(iter_python_files([tmp_path]))
    assert len(files) == 1
    assert files[0].suffix == ".py"


def test_iter_python_files_handles_nonexistent_path(tmp_path):
    """Test iter_python_files handles non-existent base path."""
    missing = tmp_path / "missing"
    files = list(iter_python_files([missing]))
    assert not files


def test_parse_ast_valid_syntax(tmp_path):
    """Test parse_python_ast with valid Python syntax."""
    test_file = tmp_path / "valid.py"
    test_file.write_text("x = 1\ny = 2")
    result = parse_python_ast(test_file, raise_on_error=False)
    assert isinstance(result, ast.Module)


def test_parse_ast_invalid_syntax(tmp_path):
    """Test parse_python_ast with invalid Python syntax."""
    test_file = tmp_path / "invalid.py"
    test_file.write_text("def foo(\n  syntax error")
    result = parse_python_ast(test_file, raise_on_error=False)
    assert result is None


def test_iter_module_contexts(tmp_path, monkeypatch):
    """Test iter_module_contexts yields contexts."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    (tmp_path / "file1.py").write_text("x = 1")
    (tmp_path / "file2.py").write_text("y = 2")

    contexts = list(iter_module_contexts([tmp_path]))
    assert len(contexts) == 2
    assert all(isinstance(ctx.tree, ast.Module) for ctx in contexts)
    assert all(ctx.source is None for ctx in contexts)
    assert all(ctx.lines is None for ctx in contexts)


def test_iter_module_contexts_with_source(tmp_path, monkeypatch):
    """Test iter_module_contexts with include_source."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    (tmp_path / "file.py").write_text("x = 1")

    contexts = list(iter_module_contexts([tmp_path], include_source=True))
    assert len(contexts) == 1
    assert contexts[0].source == "x = 1"


def test_iter_module_contexts_with_lines(tmp_path, monkeypatch):
    """Test iter_module_contexts with include_lines."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    (tmp_path / "file.py").write_text("x = 1\ny = 2")

    contexts = list(iter_module_contexts([tmp_path], include_lines=True))
    assert len(contexts) == 1
    assert contexts[0].lines == ["x = 1", "y = 2"]


def test_iter_module_contexts_skips_syntax_errors(tmp_path, monkeypatch):
    """Test iter_module_contexts skips files with syntax errors."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    (tmp_path / "valid.py").write_text("x = 1")
    (tmp_path / "invalid.py").write_text("def foo(\n  syntax error")

    contexts = list(iter_module_contexts([tmp_path]))
    assert len(contexts) == 1


def test_iter_module_contexts_skips_unicode_errors(tmp_path, monkeypatch):
    """Test iter_module_contexts skips files with unicode errors."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    (tmp_path / "valid.py").write_text("x = 1")
    invalid = tmp_path / "invalid.py"
    invalid.write_bytes(b"\xff\xfe\xff\xfe")

    contexts = list(iter_module_contexts([tmp_path]))
    assert len(contexts) == 1


def test_resolve_default_argument_positional():
    """Test _resolve_default_argument with positional args."""
    source = "func(1, 2, 3)"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Expr)
    assert isinstance(stmt.value, ast.Call)
    call = stmt.value
    result = _resolve_default_argument(call, positional_index=1, keyword_names={"key"})
    assert isinstance(result, ast.Constant)
    assert result.value == 2


def test_resolve_default_argument_keyword():
    """Test _resolve_default_argument with keyword args."""
    source = "func(1, default=42)"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Expr)
    assert isinstance(stmt.value, ast.Call)
    call = stmt.value
    result = _resolve_default_argument(call, positional_index=5, keyword_names={"default"})
    assert isinstance(result, ast.Constant)
    assert result.value == 42


def test_resolve_default_argument_not_found():
    """Test _resolve_default_argument when argument not found."""
    source = "func(1, 2)"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Expr)
    assert isinstance(stmt.value, ast.Call)
    call = stmt.value
    result = _resolve_default_argument(call, positional_index=5, keyword_names={"missing"})
    assert result is None


def test_get_call_qualname_simple():
    """Test get_call_qualname with simple name."""
    source = "foo()"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Expr)
    assert isinstance(stmt.value, ast.Call)
    call = stmt.value
    result = get_call_qualname(call.func)
    assert result == "foo"


def test_get_call_qualname_attribute():
    """Test get_call_qualname with attribute access."""
    source = "obj.method()"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Expr)
    assert isinstance(stmt.value, ast.Call)
    call = stmt.value
    result = get_call_qualname(call.func)
    assert result == "obj.method"


def test_get_call_qualname_nested_attribute():
    """Test get_call_qualname with nested attribute access."""
    source = "a.b.c.d()"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Expr)
    assert isinstance(stmt.value, ast.Call)
    call = stmt.value
    result = get_call_qualname(call.func)
    assert result == "a.b.c.d"


def test_get_call_qualname_unsupported():
    """Test get_call_qualname with unsupported node type."""
    source = "(lambda: None)()"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Expr)
    assert isinstance(stmt.value, ast.Call)
    call = stmt.value
    result = get_call_qualname(call.func)
    assert result is None


def test_is_non_none_literal_constant():
    """Test is_non_none_literal with non-None constant."""
    source = "42"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Expr)
    assert is_non_none_literal(stmt.value) is True


def test_is_non_none_literal_none():
    """Test is_non_none_literal with None."""
    source = "None"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Expr)
    assert is_non_none_literal(stmt.value) is False


def test_is_non_none_literal_not_constant():
    """Test is_non_none_literal with non-constant."""
    source = "x + 1"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Expr)
    assert is_non_none_literal(stmt.value) is False


def test_is_logging_call_true():
    """Test is_logging_call recognizes logging calls."""
    source = "logging.info('message')"
    tree = ast.parse(source)
    node = tree.body[0]
    assert is_logging_call(node) is True


def test_is_logging_call_false():
    """Test is_logging_call returns false for non-logging calls."""
    source = "print('message')"
    tree = ast.parse(source)
    node = tree.body[0]
    assert is_logging_call(node) is False


def test_is_logging_call_not_expr():
    """Test is_logging_call with non-Expr node."""
    source = "x = 1"
    tree = ast.parse(source)
    node = tree.body[0]
    assert is_logging_call(node) is False


def test_handler_has_raise_true():
    """Test handler_has_raise detects raise statement."""
    source = textwrap.dedent(
        """
        try:
            risky()
        except Exception as e:
            process(e)
            raise
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Try)
    handler = stmt.handlers[0]
    assert handler_has_raise(handler) is True


def test_handler_has_raise_false():
    """Test handler_has_raise returns false without raise."""
    source = textwrap.dedent(
        """
        try:
            risky()
        except Exception:
            pass
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Try)
    handler = stmt.handlers[0]
    assert handler_has_raise(handler) is False


def test_classify_handler_with_raise():
    """Test classify_handler returns None for handlers with raise."""
    source = textwrap.dedent(
        """
        try:
            risky()
        except Exception:
            raise
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Try)
    handler = stmt.handlers[0]
    assert classify_handler(handler) is None


def test_classify_handler_empty():
    """Test classify_handler detects empty handler."""
    source = textwrap.dedent(
        """
        try:
            risky()
        except Exception:
            pass
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Try)
    handler = stmt.handlers[0]
    result = classify_handler(handler)
    assert result is not None
    assert "suppresses exception with pass" in result


def test_classify_handler_continue():
    """Test classify_handler detects continue."""
    source = textwrap.dedent(
        """
        for i in range(10):
            try:
                risky()
            except Exception:
                continue
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.For)
    try_stmt = stmt.body[0]
    assert isinstance(try_stmt, ast.Try)
    handler = try_stmt.handlers[0]
    result = classify_handler(handler)
    assert result is not None
    assert "suppresses exception with continue" in result


def test_classify_handler_break():
    """Test classify_handler detects break."""
    source = textwrap.dedent(
        """
        while True:
            try:
                risky()
            except Exception:
                break
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.While)
    try_stmt = stmt.body[0]
    assert isinstance(try_stmt, ast.Try)
    handler = try_stmt.handlers[0]
    result = classify_handler(handler)
    assert result is not None
    assert "suppresses exception with break" in result


def test_classify_handler_literal_return():
    """Test classify_handler detects literal return."""
    source = textwrap.dedent(
        """
        def foo():
            try:
                risky()
            except Exception:
                return None
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.FunctionDef)
    try_stmt = stmt.body[0]
    assert isinstance(try_stmt, ast.Try)
    handler = try_stmt.handlers[0]
    result = classify_handler(handler)
    assert result is not None
    assert "suppresses exception with literal return" in result


def test_classify_handler_logging():
    """Test classify_handler detects logging without re-raise."""
    source = textwrap.dedent(
        """
        def foo():
            try:
                risky()
            except Exception as e:
                logging.error(str(e))
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.FunctionDef)
    try_stmt = stmt.body[0]
    assert isinstance(try_stmt, ast.Try)
    handler = try_stmt.handlers[0]
    result = classify_handler(handler)
    assert result is not None
    assert "logs exception without re-raising" in result


def test_classify_handler_no_reraise():
    """Test classify_handler detects handler without re-raise."""
    source = textwrap.dedent(
        """
        def foo():
            try:
                risky()
            except Exception:
                handle_error()
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.FunctionDef)
    try_stmt = stmt.body[0]
    assert isinstance(try_stmt, ast.Try)
    handler = try_stmt.handlers[0]
    result = classify_handler(handler)
    assert result is not None
    assert "exception handler without re-raise" in result


def test_is_literal_none_guard_is():
    """Test is_literal_none_guard with 'is None' check."""
    source = "if x is None: pass"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.If)
    assert is_literal_none_guard(stmt.test) is True


def test_is_literal_none_guard_eq():
    """Test is_literal_none_guard with '== None' check."""
    source = "if x == None: pass"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.If)
    assert is_literal_none_guard(stmt.test) is True


def test_is_literal_none_guard_false():
    """Test is_literal_none_guard with non-None check."""
    source = "if x > 0: pass"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.If)
    assert is_literal_none_guard(stmt.test) is False


def test_is_literal_none_guard_multiple_comparators():
    """Test is_literal_none_guard with multiple comparators."""
    source = "if 0 < x < 10: pass"
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.If)
    assert is_literal_none_guard(stmt.test) is False


def test_handler_contains_suppression_true():
    """Test handler_contains_suppression finds suppression token."""
    source = textwrap.dedent(
        """
        try:
            risky()
        except Exception:  # policy_guard: allow-broad-except
            pass
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Try)
    handler = stmt.handlers[0]
    lines = source.splitlines()
    result = handler_contains_suppression(handler, lines, "policy_guard: allow-broad-except")
    assert result is True


def test_handler_contains_suppression_false():
    """Test handler_contains_suppression returns false without token."""
    source = textwrap.dedent(
        """
        try:
            risky()
        except Exception:
            pass
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Try)
    handler = stmt.handlers[0]
    lines = source.splitlines()
    result = handler_contains_suppression(handler, lines, "policy_guard: allow-broad-except")
    assert result is False


def test_handler_contains_suppression_empty_lines():
    """Test handler_contains_suppression with empty lines."""
    source = textwrap.dedent(
        """
        try:
            risky()
        except Exception:
            pass
    """
    )
    tree = ast.parse(source)
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Try)
    handler = stmt.handlers[0]
    result = handler_contains_suppression(handler, [], "token")
    assert result is False


def test_normalize_function_exception_variable_names():
    """Test that functions with different exception variable names are considered identical."""
    source1 = textwrap.dedent(
        """
        def foo():
            try:
                risky()
            except ValueError as e:
                handle(e)
    """
    )
    source2 = textwrap.dedent(
        """
        def foo():
            try:
                risky()
            except ValueError as err:
                handle(err)
    """
    )
    tree1 = ast.parse(source1)
    tree2 = ast.parse(source2)
    stmt1 = tree1.body[0]
    stmt2 = tree2.body[0]
    assert isinstance(stmt1, ast.FunctionDef)
    assert isinstance(stmt2, ast.FunctionDef)
    result1 = normalize_function(stmt1)
    result2 = normalize_function(stmt2)
    assert result1 == result2


def test_normalize_function_different_decorators():
    """Test that functions with different decorators are considered identical."""
    source1 = textwrap.dedent(
        """
        @decorator1
        def foo(x):
            return x + 1
    """
    )
    source2 = textwrap.dedent(
        """
        @decorator2
        @decorator3
        def foo(x):
            return x + 1
    """
    )
    tree1 = ast.parse(source1)
    tree2 = ast.parse(source2)
    stmt1 = tree1.body[0]
    stmt2 = tree2.body[0]
    assert isinstance(stmt1, ast.FunctionDef)
    assert isinstance(stmt2, ast.FunctionDef)
    result1 = normalize_function(stmt1)
    result2 = normalize_function(stmt2)
    assert result1 == result2


def test_normalize_function_no_decorators_vs_decorators():
    """Test that functions with and without decorators are considered identical."""
    source1 = textwrap.dedent(
        """
        def foo(x):
            return x + 1
    """
    )
    source2 = textwrap.dedent(
        """
        @decorator
        def foo(x):
            return x + 1
    """
    )
    tree1 = ast.parse(source1)
    tree2 = ast.parse(source2)
    stmt1 = tree1.body[0]
    stmt2 = tree2.body[0]
    assert isinstance(stmt1, ast.FunctionDef)
    assert isinstance(stmt2, ast.FunctionDef)
    result1 = normalize_function(stmt1)
    result2 = normalize_function(stmt2)
    assert result1 == result2


def test_normalize_function_different_type_annotations():
    """Test that functions with different type annotations are considered identical."""
    source1 = textwrap.dedent(
        """
        def foo(x: int, y: str) -> int:
            return x + 1
    """
    )
    source2 = textwrap.dedent(
        """
        def foo(x: str, y: int) -> str:
            return x + 1
    """
    )
    tree1 = ast.parse(source1)
    tree2 = ast.parse(source2)
    stmt1 = tree1.body[0]
    stmt2 = tree2.body[0]
    assert isinstance(stmt1, ast.FunctionDef)
    assert isinstance(stmt2, ast.FunctionDef)
    result1 = normalize_function(stmt1)
    result2 = normalize_function(stmt2)
    assert result1 == result2


def test_normalize_function_no_annotations_vs_annotations():
    """Test that functions with and without type annotations are considered identical."""
    source1 = textwrap.dedent(
        """
        def foo(x, y):
            return x + y
    """
    )
    source2 = textwrap.dedent(
        """
        def foo(x: int, y: int) -> int:
            return x + y
    """
    )
    tree1 = ast.parse(source1)
    tree2 = ast.parse(source2)
    stmt1 = tree1.body[0]
    stmt2 = tree2.body[0]
    assert isinstance(stmt1, ast.FunctionDef)
    assert isinstance(stmt2, ast.FunctionDef)
    result1 = normalize_function(stmt1)
    result2 = normalize_function(stmt2)
    assert result1 == result2


def test_normalize_function_vararg_kwarg_annotations():
    """Test that *args and **kwargs annotations are normalized."""
    source1 = textwrap.dedent(
        """
        def foo(*args: int, **kwargs: str):
            return sum(args)
    """
    )
    source2 = textwrap.dedent(
        """
        def foo(*args: str, **kwargs: int):
            return sum(args)
    """
    )
    tree1 = ast.parse(source1)
    tree2 = ast.parse(source2)
    stmt1 = tree1.body[0]
    stmt2 = tree2.body[0]
    assert isinstance(stmt1, ast.FunctionDef)
    assert isinstance(stmt2, ast.FunctionDef)
    result1 = normalize_function(stmt1)
    result2 = normalize_function(stmt2)
    assert result1 == result2
