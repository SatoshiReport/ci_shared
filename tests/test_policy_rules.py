"""Unit tests for policy_rules module."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from ci_tools.scripts.policy_context import FunctionEntry
from ci_tools.scripts.policy_rules import (
    PolicyViolation,
    _check_backward_compat,
    _check_boolean_fallbacks,
    _check_broad_excepts,
    _check_bytecode_artifacts,
    _check_conditional_literals,
    _check_duplicate_functions,
    _check_flagged_tokens,
    _check_function_lengths,
    _check_generic_raises,
    _check_keyword_policy,
    _check_legacy_artifacts,
    _check_literal_fallbacks,
    _check_silent_handlers,
    _check_suppressions,
    _check_sync_calls,
    enforce_duplicate_functions,
    enforce_function_lengths,
    enforce_occurrences,
    purge_bytecode_artifacts,
)

from conftest import write_module


def test_policy_violation_exception():
    """Test PolicyViolation is an Exception."""
    exc = PolicyViolation("test message")
    assert isinstance(exc, Exception)
    assert str(exc) == "test message"


def test_enforce_occurrences_no_violations():
    """Test enforce_occurrences with no violations."""
    enforce_occurrences([], "test message")
    # Should not raise


def test_enforce_occurrences_with_violations():
    """Test enforce_occurrences with violations."""
    discovered = [("file.py", 10), ("file.py", 20)]
    with pytest.raises(PolicyViolation) as exc:
        enforce_occurrences(discovered, "test issue")
    assert "Policy violations detected" in str(exc.value)
    assert "file.py:10" in str(exc.value)
    assert "test issue" in str(exc.value)


def test_enforce_occurrences_sorts_violations():
    """Test enforce_occurrences sorts violations."""
    discovered = [("z.py", 10), ("a.py", 5), ("m.py", 15)]
    with pytest.raises(PolicyViolation) as exc:
        enforce_occurrences(discovered, "issue")
    message = str(exc.value)
    # Check that a.py appears before z.py in sorted output
    a_pos = message.index("a.py")
    z_pos = message.index("z.py")
    assert a_pos < z_pos


def test_enforce_duplicate_functions_no_duplicates():
    """Test enforce_duplicate_functions with no duplicates."""
    enforce_duplicate_functions([])
    # Should not raise


def test_enforce_duplicate_functions_with_duplicates():
    """Test enforce_duplicate_functions with duplicates."""
    duplicates = [
        [
            FunctionEntry(Path("file1.py"), "helper", 10, 5),
            FunctionEntry(Path("file2.py"), "helper", 20, 5),
        ]
    ]
    with pytest.raises(PolicyViolation) as exc:
        enforce_duplicate_functions(duplicates)
    assert "Duplicate helper policy violations detected" in str(exc.value)
    assert "file1.py:10" in str(exc.value)
    assert "file2.py:20" in str(exc.value)


def test_enforce_duplicate_functions_multiple_groups():
    """Test enforce_duplicate_functions with multiple groups."""
    duplicates = [
        [
            FunctionEntry(Path("a.py"), "func1", 10, 5),
            FunctionEntry(Path("b.py"), "func1", 20, 5),
        ],
        [
            FunctionEntry(Path("c.py"), "func2", 30, 5),
            FunctionEntry(Path("d.py"), "func2", 40, 5),
        ],
    ]
    with pytest.raises(PolicyViolation) as exc:
        enforce_duplicate_functions(duplicates)
    message = str(exc.value)
    assert "func1" in message
    assert "func2" in message


def test_check_keyword_policy_no_violations():
    """Test _check_keyword_policy with no violations."""
    with patch("ci_tools.scripts.policy_rules.scan_keywords", return_value={}):
        _check_keyword_policy()
        # Should not raise


def test_check_keyword_policy_with_violations():
    """Test _check_keyword_policy with violations."""
    mock_hits = {"legacy": {"file.py": [10, 20]}}
    with patch("ci_tools.scripts.policy_rules.scan_keywords", return_value=mock_hits):
        with pytest.raises(PolicyViolation) as exc:
            _check_keyword_policy()
        assert "Banned keyword policy violations detected" in str(exc.value)
        assert "keyword 'legacy'" in str(exc.value)


def test_check_flagged_tokens_no_violations():
    """Test _check_flagged_tokens with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_flagged_tokens", return_value=[]):
        _check_flagged_tokens()
        # Should not raise


def test_check_flagged_tokens_with_violations():
    """Test _check_flagged_tokens with violations."""
    mock_tokens = [("file.py", 10, "TODO"), ("file.py", 20, "FIXME")]
    with patch("ci_tools.scripts.policy_rules.collect_flagged_tokens", return_value=mock_tokens):
        with pytest.raises(PolicyViolation) as exc:
            _check_flagged_tokens()
        assert "Flagged annotations detected" in str(exc.value)
        assert "TODO" in str(exc.value)
        assert "FIXME" in str(exc.value)


def test_check_function_lengths_no_violations():
    """Test _check_function_lengths with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_long_functions", return_value=[]):
        _check_function_lengths()
        # Should not raise


def test_check_function_lengths_with_violations():
    """Test _check_function_lengths with violations."""
    long_funcs = [FunctionEntry(Path("file.py"), "big_func", 10, 200)]
    with patch("ci_tools.scripts.policy_rules.collect_long_functions", return_value=long_funcs):
        with pytest.raises(PolicyViolation) as exc:
            _check_function_lengths()
        assert "Function length policy violations detected" in str(exc.value)
        assert "big_func" in str(exc.value)


def test_enforce_function_lengths_no_violations():
    """Test enforce_function_lengths with no violations."""
    enforce_function_lengths([])
    # Should not raise


def test_enforce_function_lengths_with_violations():
    """Test enforce_function_lengths with violations."""
    entries = [FunctionEntry(Path("file.py"), "long_func", 10, 200)]
    with pytest.raises(PolicyViolation) as exc:
        enforce_function_lengths(entries, threshold=150)
    assert "Function length policy violations detected" in str(exc.value)
    assert "long_func" in str(exc.value)
    assert "length 200 exceeds 150" in str(exc.value)


def test_check_broad_excepts_no_violations():
    """Test _check_broad_excepts with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_broad_excepts", return_value=[]):
        _check_broad_excepts()
        # Should not raise


def test_check_broad_excepts_with_violations():
    """Test _check_broad_excepts with violations."""
    mock_excepts = [("file.py", 10), ("file.py", 20)]
    with patch("ci_tools.scripts.policy_rules.collect_broad_excepts", return_value=mock_excepts):
        with pytest.raises(PolicyViolation) as exc:
            _check_broad_excepts()
        assert "Policy violations detected" in str(exc.value)
        assert "broad exception handler" in str(exc.value)


def test_check_silent_handlers_no_violations():
    """Test _check_silent_handlers with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_silent_handlers", return_value=[]):
        _check_silent_handlers()
        # Should not raise


def test_check_silent_handlers_with_violations():
    """Test _check_silent_handlers with violations."""
    mock_handlers = [("file.py", 10, "suppresses exception with pass")]
    with patch("ci_tools.scripts.policy_rules.collect_silent_handlers", return_value=mock_handlers):
        with pytest.raises(PolicyViolation) as exc:
            _check_silent_handlers()
        assert "Silent exception handler detected" in str(exc.value)
        assert "suppresses exception with pass" in str(exc.value)


def test_check_generic_raises_no_violations():
    """Test _check_generic_raises with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_generic_raises", return_value=[]):
        _check_generic_raises()
        # Should not raise


def test_check_generic_raises_with_violations():
    """Test _check_generic_raises with violations."""
    mock_raises = [("file.py", 10), ("file.py", 20)]
    with patch("ci_tools.scripts.policy_rules.collect_generic_raises", return_value=mock_raises):
        with pytest.raises(PolicyViolation) as exc:
            _check_generic_raises()
        assert "Policy violations detected" in str(exc.value)
        assert "generic Exception raise" in str(exc.value)


def test_check_literal_fallbacks_no_violations():
    """Test _check_literal_fallbacks with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_literal_fallbacks", return_value=[]):
        _check_literal_fallbacks()
        # Should not raise


def test_check_literal_fallbacks_with_violations():
    """Test _check_literal_fallbacks with violations."""
    mock_fallbacks = [("file.py", 10, "dict.get literal fallback")]
    with patch("ci_tools.scripts.policy_rules.collect_literal_fallbacks", return_value=mock_fallbacks):
        with pytest.raises(PolicyViolation) as exc:
            _check_literal_fallbacks()
        assert "Fallback default usage detected" in str(exc.value)
        assert "dict.get literal fallback" in str(exc.value)


def test_check_boolean_fallbacks_no_violations():
    """Test _check_boolean_fallbacks with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_bool_fallbacks", return_value=[]):
        _check_boolean_fallbacks()
        # Should not raise


def test_check_boolean_fallbacks_with_violations():
    """Test _check_boolean_fallbacks with violations."""
    mock_fallbacks = [("file.py", 10), ("file.py", 20)]
    with patch("ci_tools.scripts.policy_rules.collect_bool_fallbacks", return_value=mock_fallbacks):
        with pytest.raises(PolicyViolation) as exc:
            _check_boolean_fallbacks()
        assert "Policy violations detected" in str(exc.value)
        assert "literal fallback via boolean 'or'" in str(exc.value)


def test_check_conditional_literals_no_violations():
    """Test _check_conditional_literals with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_conditional_literal_returns", return_value=[]):
        _check_conditional_literals()
        # Should not raise


def test_check_conditional_literals_with_violations():
    """Test _check_conditional_literals with violations."""
    mock_literals = [("file.py", 10), ("file.py", 20)]
    with patch("ci_tools.scripts.policy_rules.collect_conditional_literal_returns", return_value=mock_literals):
        with pytest.raises(PolicyViolation) as exc:
            _check_conditional_literals()
        assert "Policy violations detected" in str(exc.value)
        assert "literal return inside None guard" in str(exc.value)


def test_check_backward_compat_no_violations():
    """Test _check_backward_compat with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_backward_compat_blocks", return_value=[]):
        _check_backward_compat()
        # Should not raise


def test_check_backward_compat_with_violations():
    """Test _check_backward_compat with violations."""
    mock_compat = [("file.py", 10, "conditional legacy guard")]
    with patch("ci_tools.scripts.policy_rules.collect_backward_compat_blocks", return_value=mock_compat):
        with pytest.raises(PolicyViolation) as exc:
            _check_backward_compat()
        assert "Backward compatibility code detected" in str(exc.value)
        assert "conditional legacy guard" in str(exc.value)


def test_check_legacy_artifacts_no_violations():
    """Test _check_legacy_artifacts with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_legacy_modules", return_value=[]):
        with patch("ci_tools.scripts.policy_rules.collect_legacy_configs", return_value=[]):
            _check_legacy_artifacts()
            # Should not raise


def test_check_legacy_artifacts_modules():
    """Test _check_legacy_artifacts with legacy modules."""
    mock_modules = [("legacy_module.py", 1, "legacy module path")]
    with patch("ci_tools.scripts.policy_rules.collect_legacy_modules", return_value=mock_modules):
        with patch("ci_tools.scripts.policy_rules.collect_legacy_configs", return_value=[]):
            with pytest.raises(PolicyViolation) as exc:
                _check_legacy_artifacts()
            assert "Legacy module detected" in str(exc.value)
            assert "legacy module path" in str(exc.value)


def test_check_legacy_artifacts_configs():
    """Test _check_legacy_artifacts with legacy configs."""
    mock_configs = [("config.json", 5, "legacy toggle in config")]
    with patch("ci_tools.scripts.policy_rules.collect_legacy_modules", return_value=[]):
        with patch("ci_tools.scripts.policy_rules.collect_legacy_configs", return_value=mock_configs):
            with pytest.raises(PolicyViolation) as exc:
                _check_legacy_artifacts()
            assert "Legacy toggle detected in config" in str(exc.value)


def test_check_sync_calls_no_violations():
    """Test _check_sync_calls with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_forbidden_sync_calls", return_value=[]):
        _check_sync_calls()
        # Should not raise


def test_check_sync_calls_with_violations():
    """Test _check_sync_calls with violations."""
    mock_calls = [("file.py", 10, "forbidden synchronous call 'time.sleep'")]
    with patch("ci_tools.scripts.policy_rules.collect_forbidden_sync_calls", return_value=mock_calls):
        with pytest.raises(PolicyViolation) as exc:
            _check_sync_calls()
        assert "Synchronous call policy violations detected" in str(exc.value)
        assert "time.sleep" in str(exc.value)


def test_check_suppressions_no_violations():
    """Test _check_suppressions with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_suppressions", return_value=[]):
        _check_suppressions()
        # Should not raise


def test_check_suppressions_with_violations():
    """Test _check_suppressions with violations."""
    mock_suppressions = [("file.py", 10, "# noqa")]
    with patch("ci_tools.scripts.policy_rules.collect_suppressions", return_value=mock_suppressions):
        with pytest.raises(PolicyViolation) as exc:
            _check_suppressions()
        assert "Suppression policy violations detected" in str(exc.value)
        assert "# noqa" in str(exc.value)


def test_check_duplicate_functions_no_violations():
    """Test _check_duplicate_functions with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_duplicate_functions", return_value=[]):
        _check_duplicate_functions()
        # Should not raise


def test_check_duplicate_functions_with_violations():
    """Test _check_duplicate_functions with violations."""
    mock_duplicates = [
        [
            FunctionEntry(Path("file1.py"), "helper", 10, 5),
            FunctionEntry(Path("file2.py"), "helper", 20, 5),
        ]
    ]
    with patch("ci_tools.scripts.policy_rules.collect_duplicate_functions", return_value=mock_duplicates):
        with pytest.raises(PolicyViolation) as exc:
            _check_duplicate_functions()
        assert "Duplicate helper policy violations detected" in str(exc.value)


def test_check_bytecode_artifacts_no_violations():
    """Test _check_bytecode_artifacts with no violations."""
    with patch("ci_tools.scripts.policy_rules.collect_bytecode_artifacts", return_value=[]):
        _check_bytecode_artifacts()
        # Should not raise


def test_check_bytecode_artifacts_with_violations():
    """Test _check_bytecode_artifacts with violations."""
    mock_artifacts = ["module.pyc", "__pycache__"]
    with patch("ci_tools.scripts.policy_rules.collect_bytecode_artifacts", return_value=mock_artifacts):
        with pytest.raises(PolicyViolation) as exc:
            _check_bytecode_artifacts()
        assert "Bytecode artifacts detected" in str(exc.value)
        assert "module.pyc" in str(exc.value)


def test_purge_bytecode_artifacts_delegates():
    """Test purge_bytecode_artifacts delegates to collector."""
    with patch("ci_tools.scripts.policy_rules.purge_bytecode_artifacts"):
        purge_bytecode_artifacts()
        # Function should exist and be callable
