"""Unit tests for policy_collectors_ast module."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path


from ci_tools.scripts.policy_collectors_ast import (
    collect_backward_compat_blocks,
    collect_bool_fallbacks,
    collect_broad_excepts,
    collect_bytecode_artifacts,
    collect_conditional_literal_returns,
    collect_duplicate_functions,
    collect_forbidden_sync_calls,
    collect_generic_raises,
    collect_literal_fallbacks,
    collect_long_functions,
    collect_silent_handlers,
    purge_bytecode_artifacts,
)
from ci_tools.scripts.policy_context import contains_literal_dataset

from conftest import write_module


def test_contains_literal_dataset_constant():
    """Test contains_literal_dataset with simple constant."""
    source = "42"
    tree = ast.parse(source)
    node = tree.body[0].value
    assert contains_literal_dataset(node) is True


def test_contains_literal_dataset_string():
    """Test contains_literal_dataset with string."""
    source = "'hello'"
    tree = ast.parse(source)
    node = tree.body[0].value
    assert contains_literal_dataset(node) is True


def test_contains_literal_dataset_list():
    """Test contains_literal_dataset with list."""
    source = "[1, 2, 3]"
    tree = ast.parse(source)
    node = tree.body[0].value
    assert contains_literal_dataset(node) is True


def test_contains_literal_dataset_tuple():
    """Test contains_literal_dataset with tuple."""
    source = "(1, 2, 3)"
    tree = ast.parse(source)
    node = tree.body[0].value
    assert contains_literal_dataset(node) is True


def test_contains_literal_dataset_set():
    """Test contains_literal_dataset with set."""
    source = "{1, 2, 3}"
    tree = ast.parse(source)
    node = tree.body[0].value
    assert contains_literal_dataset(node) is True


def test_contains_literal_dataset_dict():
    """Test contains_literal_dataset with dict."""
    source = "{'a': 1, 'b': 2}"
    tree = ast.parse(source)
    node = tree.body[0].value
    assert contains_literal_dataset(node) is True


def test_contains_literal_dataset_nested():
    """Test contains_literal_dataset with nested structures."""
    source = "{'key': [1, 2, {'nested': 3}]}"
    tree = ast.parse(source)
    node = tree.body[0].value
    assert contains_literal_dataset(node) is True


def test_contains_literal_dataset_false():
    """Test contains_literal_dataset returns false for non-literals."""
    source = "x + 1"
    tree = ast.parse(source)
    node = tree.body[0].value
    assert contains_literal_dataset(node) is False


def test_collect_long_functions(tmp_path, monkeypatch):
    """Test collect_long_functions finds oversized functions."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        def short():
            return 1

        def long_function():
            line1 = 1
            line2 = 2
            line3 = 3
            line4 = 4
            line5 = 5
            line6 = 6
            line7 = 7
            line8 = 8
            line9 = 9
            line10 = 10
            line11 = 11
            line12 = 12
            line13 = 13
            line14 = 14
            line15 = 15
            return line15
        """,
    )

    results = list(collect_long_functions(threshold=10))
    assert len(results) >= 1
    assert any(entry.name == "long_function" for entry in results)


def test_collect_long_functions_skips_init(tmp_path, monkeypatch):
    """Test collect_long_functions skips __init__.py files."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        src_root / "__init__.py",
        """
        def long_function():
            line1 = 1
            line2 = 2
            line3 = 3
            line4 = 4
            line5 = 5
            line6 = 6
            line7 = 7
            line8 = 8
            line9 = 9
            line10 = 10
            return line10
        """,
    )

    results = list(collect_long_functions(threshold=5))
    assert len(results) == 0


def test_collect_broad_excepts(tmp_path, monkeypatch):
    """Test collect_broad_excepts finds broad exception handlers."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        try:
            risky()
        except Exception:
            handle()
        """,
    )

    results = collect_broad_excepts()
    assert len(results) >= 1


def test_collect_broad_excepts_with_suppression(tmp_path, monkeypatch):
    """Test collect_broad_excepts respects suppression comments."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        try:
            risky()
        except Exception:  # policy_guard: allow-broad-except
            handle()
        """,
    )

    results = collect_broad_excepts()
    # Should not include the suppressed handler
    matching = [r for r in results if "module.py" in r[0]]
    assert len(matching) == 0


def test_collect_broad_excepts_bare_except(tmp_path, monkeypatch):
    """Test collect_broad_excepts finds bare except."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        try:
            risky()
        except:
            handle()
        """,
    )

    results = collect_broad_excepts()
    assert len(results) >= 1


def test_collect_broad_excepts_tuple(tmp_path, monkeypatch):
    """Test collect_broad_excepts finds Exception in tuple."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        try:
            risky()
        except (ValueError, Exception):
            handle()
        """,
    )

    results = collect_broad_excepts()
    assert len(results) >= 1


def test_collect_silent_handlers(tmp_path, monkeypatch):
    """Test collect_silent_handlers finds silent exception handlers."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        try:
            risky()
        except ValueError:
            pass
        """,
    )

    results = collect_silent_handlers()
    assert len(results) >= 1
    assert any("pass" in reason for _, _, reason in results)


def test_collect_silent_handlers_with_suppression(tmp_path, monkeypatch):
    """Test collect_silent_handlers respects suppression comments."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        try:
            risky()
        except ValueError:  # policy_guard: allow-silent-handler
            pass
        """,
    )

    results = collect_silent_handlers()
    matching = [r for r in results if "module.py" in r[0]]
    assert len(matching) == 0


def test_collect_generic_raises(tmp_path, monkeypatch):
    """Test collect_generic_raises finds generic exception raises."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        def foo():
            raise Exception("generic error")
        """,
    )

    results = collect_generic_raises()
    assert len(results) >= 1


def test_collect_generic_raises_base_exception(tmp_path, monkeypatch):
    """Test collect_generic_raises finds BaseException."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        def foo():
            raise BaseException()
        """,
    )

    results = collect_generic_raises()
    assert len(results) >= 1


def test_collect_literal_fallbacks_dict_get(tmp_path, monkeypatch):
    """Test collect_literal_fallbacks finds dict.get with literal default."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        tmp_path / "module.py",
        """
        x = data.get('key', 'default')
        """,
    )

    results = collect_literal_fallbacks()
    assert len(results) >= 1
    assert any("get literal fallback" in reason for _, _, reason in results)


def test_collect_literal_fallbacks_getattr(tmp_path, monkeypatch):
    """Test collect_literal_fallbacks finds getattr with literal default."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        tmp_path / "module.py",
        """
        x = getattr(obj, 'attr', 'default')
        """,
    )

    results = collect_literal_fallbacks()
    assert len(results) >= 1


def test_collect_literal_fallbacks_os_getenv(tmp_path, monkeypatch):
    """Test collect_literal_fallbacks finds os.getenv with literal default."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        tmp_path / "module.py",
        """
        import os
        x = os.getenv('VAR', 'default')
        """,
    )

    results = collect_literal_fallbacks()
    assert len(results) >= 1


def test_collect_literal_fallbacks_setdefault(tmp_path, monkeypatch):
    """Test collect_literal_fallbacks finds setdefault with literal."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        data.setdefault('key', 'default')
        """,
    )

    results = collect_literal_fallbacks()
    assert len(results) >= 1


def test_collect_bool_fallbacks_or(tmp_path, monkeypatch):
    """Test collect_bool_fallbacks finds literal fallback via or."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        tmp_path / "module.py",
        """
        x = value or 'default'
        """,
    )

    results = collect_bool_fallbacks()
    assert len(results) >= 1


def test_collect_bool_fallbacks_ternary(tmp_path, monkeypatch):
    """Test collect_bool_fallbacks finds literal in ternary."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        tmp_path / "module.py",
        """
        x = 'yes' if condition else 'no'
        """,
    )

    results = collect_bool_fallbacks()
    assert len(results) >= 1


def test_collect_conditional_literal_returns(tmp_path, monkeypatch):
    """Test collect_conditional_literal_returns finds literal returns after None check."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        tmp_path / "module.py",
        """
        def foo(x):
            if x is None:
                return 'default'
        """,
    )

    results = collect_conditional_literal_returns()
    assert len(results) >= 1


def test_collect_backward_compat_blocks_if_statement(tmp_path, monkeypatch):
    """Test collect_backward_compat_blocks finds legacy if statements."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        tmp_path / "module.py",
        """
        if legacy_mode:
            handle_legacy()
        """,
    )

    results = collect_backward_compat_blocks()
    assert len(results) >= 1
    assert any("conditional legacy guard" in reason for _, _, reason in results)


def test_collect_backward_compat_blocks_attribute(tmp_path, monkeypatch):
    """Test collect_backward_compat_blocks finds legacy attributes."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        tmp_path / "module.py",
        """
        x = obj.method_legacy()
        """,
    )

    results = collect_backward_compat_blocks()
    assert len(results) >= 1
    assert any("legacy attribute" in reason for _, _, reason in results)


def test_collect_backward_compat_blocks_name(tmp_path, monkeypatch):
    """Test collect_backward_compat_blocks finds legacy symbols."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        tmp_path / "module.py",
        """
        x = func_deprecated()
        """,
    )

    results = collect_backward_compat_blocks()
    assert len(results) >= 1
    assert any("legacy symbol" in reason for _, _, reason in results)


def test_collect_forbidden_sync_calls_time_sleep(tmp_path, monkeypatch):
    """Test collect_forbidden_sync_calls finds time.sleep."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        import time
        time.sleep(1)
        """,
    )

    results = collect_forbidden_sync_calls()
    assert len(results) >= 1
    assert any("time.sleep" in reason for _, _, reason in results)


def test_collect_forbidden_sync_calls_subprocess(tmp_path, monkeypatch):
    """Test collect_forbidden_sync_calls finds subprocess.run."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        import subprocess
        subprocess.run(['ls'])
        """,
    )

    results = collect_forbidden_sync_calls()
    assert len(results) >= 1
    assert any("subprocess.run" in reason for _, _, reason in results)


def test_collect_forbidden_sync_calls_requests(tmp_path, monkeypatch):
    """Test collect_forbidden_sync_calls finds requests.get."""
    src_root = tmp_path / "src"
    src_root.mkdir()
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    write_module(
        src_root / "module.py",
        """
        import requests
        requests.get('http://example.com')
        """,
    )

    results = collect_forbidden_sync_calls()
    assert len(results) >= 1
    assert any("requests.get" in reason for _, _, reason in results)


def test_collect_duplicate_functions(tmp_path, monkeypatch):
    """Test collect_duplicate_functions finds duplicate implementations."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        tmp_path / "module1.py",
        """
        def helper(x):
            result = x + 1
            return result
        """,
    )

    write_module(
        tmp_path / "module2.py",
        """
        def helper(y):
            output = y + 1
            return output
        """,
    )

    results = collect_duplicate_functions(min_length=3)
    assert len(results) >= 1


def test_collect_duplicate_functions_min_length(tmp_path, monkeypatch):
    """Test collect_duplicate_functions respects min_length."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        tmp_path / "module1.py",
        """
        def tiny():
            return 1
        """,
    )

    write_module(
        tmp_path / "module2.py",
        """
        def tiny():
            return 1
        """,
    )

    results = collect_duplicate_functions(min_length=10)
    assert len(results) == 0


def test_collect_duplicate_functions_same_file(tmp_path, monkeypatch):
    """Test collect_duplicate_functions ignores duplicates in same file."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    write_module(
        tmp_path / "module.py",
        """
        def helper1(x):
            result = x + 1
            return result

        def helper2(y):
            output = y + 1
            return output
        """,
    )

    results = collect_duplicate_functions(min_length=3)
    # Should not report duplicates from same file
    matching = [
        group for group in results
        if all("module.py" in str(entry.path) for entry in group)
    ]
    assert len(matching) == 0


def test_collect_bytecode_artifacts(tmp_path, monkeypatch):
    """Test collect_bytecode_artifacts finds .pyc files."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    (tmp_path / "module.pyc").write_bytes(b"fake bytecode")
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()

    results = collect_bytecode_artifacts()
    assert len(results) >= 2
    assert any(".pyc" in path for path in results)
    assert any("__pycache__" in path for path in results)


def test_purge_bytecode_artifacts(tmp_path, monkeypatch):
    """Test purge_bytecode_artifacts removes .pyc files."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)
    monkeypatch.setattr("ci_tools.scripts.policy_collectors_ast.ROOT", tmp_path)

    pyc_file = tmp_path / "module.pyc"
    pyc_file.write_bytes(b"fake bytecode")
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "test.pyc").write_bytes(b"fake")

    assert pyc_file.exists()
    assert pycache.exists()

    purge_bytecode_artifacts()

    assert not pyc_file.exists()
    assert not pycache.exists()


def test_purge_bytecode_artifacts_handles_missing(tmp_path, monkeypatch):
    """Test purge_bytecode_artifacts handles already deleted files."""
    monkeypatch.setattr("ci_tools.scripts.policy_context.ROOT", tmp_path)

    # Run on empty directory
    purge_bytecode_artifacts()
    # Should not raise any errors
