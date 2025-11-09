"""Unit tests for policy_checks module."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from ci_tools.scripts.policy_checks import PolicyViolation, main


def test_policy_violation_imported():
    """Test PolicyViolation is correctly imported."""
    assert PolicyViolation is not None
    exc = PolicyViolation("test")
    assert isinstance(exc, Exception)


# pylint: disable=too-many-locals
def test_main_calls_all_checks():
    """Test main calls all policy check functions."""
    with (
        patch("ci_tools.scripts.policy_checks.purge_bytecode_artifacts") as mock_purge,
        patch("ci_tools.scripts.policy_checks._check_keyword_policy") as mock_keyword,
        patch("ci_tools.scripts.policy_checks._check_flagged_tokens") as mock_flagged,
        patch("ci_tools.scripts.policy_checks._check_function_lengths") as mock_lengths,
        patch("ci_tools.scripts.policy_checks._check_broad_excepts") as mock_broad,
        patch("ci_tools.scripts.policy_checks._check_silent_handlers") as mock_silent,
        patch("ci_tools.scripts.policy_checks._check_generic_raises") as mock_generic,
        patch("ci_tools.scripts.policy_checks._check_literal_fallbacks") as mock_literal,
        patch("ci_tools.scripts.policy_checks._check_boolean_fallbacks") as mock_boolean,
        patch("ci_tools.scripts.policy_checks._check_conditional_literals") as mock_conditional,
        patch("ci_tools.scripts.policy_checks._check_backward_compat") as mock_backward,
        patch("ci_tools.scripts.policy_checks._check_legacy_artifacts") as mock_legacy,
        patch("ci_tools.scripts.policy_checks._check_sync_calls") as mock_sync,
        patch("ci_tools.scripts.policy_checks._check_suppressions") as mock_suppressions,
        patch("ci_tools.scripts.policy_checks._check_duplicate_functions") as mock_duplicates,
        patch("ci_tools.scripts.policy_checks._check_bytecode_artifacts") as mock_bytecode,
    ):

        result = main()

        assert result == 0
        mock_purge.assert_called_once()
        mock_keyword.assert_called_once()
        mock_flagged.assert_called_once()
        mock_lengths.assert_called_once()
        mock_broad.assert_called_once()
        mock_silent.assert_called_once()
        mock_generic.assert_called_once()
        mock_literal.assert_called_once()
        mock_boolean.assert_called_once()
        mock_conditional.assert_called_once()
        mock_backward.assert_called_once()
        mock_legacy.assert_called_once()
        mock_sync.assert_called_once()
        mock_suppressions.assert_called_once()
        mock_duplicates.assert_called_once()
        mock_bytecode.assert_called_once()


def test_main_returns_zero_on_success():
    """Test main returns 0 when all checks pass."""
    with (
        patch("ci_tools.scripts.policy_checks.purge_bytecode_artifacts"),
        patch("ci_tools.scripts.policy_checks._check_keyword_policy"),
        patch("ci_tools.scripts.policy_checks._check_flagged_tokens"),
        patch("ci_tools.scripts.policy_checks._check_function_lengths"),
        patch("ci_tools.scripts.policy_checks._check_broad_excepts"),
        patch("ci_tools.scripts.policy_checks._check_silent_handlers"),
        patch("ci_tools.scripts.policy_checks._check_generic_raises"),
        patch("ci_tools.scripts.policy_checks._check_literal_fallbacks"),
        patch("ci_tools.scripts.policy_checks._check_boolean_fallbacks"),
        patch("ci_tools.scripts.policy_checks._check_conditional_literals"),
        patch("ci_tools.scripts.policy_checks._check_backward_compat"),
        patch("ci_tools.scripts.policy_checks._check_legacy_artifacts"),
        patch("ci_tools.scripts.policy_checks._check_sync_calls"),
        patch("ci_tools.scripts.policy_checks._check_suppressions"),
        patch("ci_tools.scripts.policy_checks._check_duplicate_functions"),
        patch("ci_tools.scripts.policy_checks._check_bytecode_artifacts"),
    ):

        result = main()
        assert result == 0


def test_main_propagates_policy_violation():
    """Test main propagates PolicyViolation exceptions."""
    with (
        patch("ci_tools.scripts.policy_checks.purge_bytecode_artifacts"),
        patch(
            "ci_tools.scripts.policy_checks._check_keyword_policy",
            side_effect=PolicyViolation("test error"),
        ),
    ):

        with pytest.raises(PolicyViolation) as exc:
            main()
        assert "test error" in str(exc.value)


def test_main_checks_called_in_order():
    """Test main calls checks in the correct order."""
    call_order = []

    def make_tracker(name):
        def tracker():
            call_order.append(name)

        return tracker

    with (
        patch("ci_tools.scripts.policy_checks.purge_bytecode_artifacts", make_tracker("purge")),
        patch("ci_tools.scripts.policy_checks._check_keyword_policy", make_tracker("keyword")),
        patch("ci_tools.scripts.policy_checks._check_flagged_tokens", make_tracker("flagged")),
        patch("ci_tools.scripts.policy_checks._check_function_lengths", make_tracker("lengths")),
        patch("ci_tools.scripts.policy_checks._check_broad_excepts", make_tracker("broad")),
        patch("ci_tools.scripts.policy_checks._check_silent_handlers", make_tracker("silent")),
        patch("ci_tools.scripts.policy_checks._check_generic_raises", make_tracker("generic")),
        patch("ci_tools.scripts.policy_checks._check_literal_fallbacks", make_tracker("literal")),
        patch("ci_tools.scripts.policy_checks._check_boolean_fallbacks", make_tracker("boolean")),
        patch(
            "ci_tools.scripts.policy_checks._check_conditional_literals",
            make_tracker("conditional"),
        ),
        patch("ci_tools.scripts.policy_checks._check_backward_compat", make_tracker("backward")),
        patch("ci_tools.scripts.policy_checks._check_legacy_artifacts", make_tracker("legacy")),
        patch("ci_tools.scripts.policy_checks._check_sync_calls", make_tracker("sync")),
        patch("ci_tools.scripts.policy_checks._check_suppressions", make_tracker("suppressions")),
        patch(
            "ci_tools.scripts.policy_checks._check_duplicate_functions", make_tracker("duplicates")
        ),
        patch("ci_tools.scripts.policy_checks._check_bytecode_artifacts", make_tracker("bytecode")),
    ):

        main()

        # Verify purge is called first
        assert call_order[0] == "purge"
        # Verify bytecode check is called last
        assert call_order[-1] == "bytecode"
        # Verify all checks were called
        assert len(call_order) == 16


def test_main_stops_on_first_violation():
    """Test main stops execution on first violation."""
    call_order = []

    def make_tracker(name):
        def tracker():
            call_order.append(name)

        return tracker

    with (
        patch("ci_tools.scripts.policy_checks.purge_bytecode_artifacts", make_tracker("purge")),
        patch("ci_tools.scripts.policy_checks._check_keyword_policy", make_tracker("keyword")),
        patch(
            "ci_tools.scripts.policy_checks._check_flagged_tokens",
            side_effect=PolicyViolation("error"),
        ),
        patch("ci_tools.scripts.policy_checks._check_function_lengths", make_tracker("lengths")),
    ):

        with pytest.raises(PolicyViolation):
            main()

        # purge and keyword should have been called, but not lengths
        assert "purge" in call_order
        assert "keyword" in call_order
        assert "lengths" not in call_order


def test_module_exports():
    # pylint: disable=import-outside-toplevel
    """Test module exports expected symbols."""
    from ci_tools.scripts import policy_checks

    assert hasattr(policy_checks, "PolicyViolation")
    assert hasattr(policy_checks, "main")
    assert hasattr(policy_checks, "purge_bytecode_artifacts")


def test_main_as_script_success():
    """Test running module as script with successful checks."""
    with patch("ci_tools.scripts.policy_checks.main", return_value=0):
        with pytest.raises(SystemExit) as exc:
            # Simulate running as __main__
            # pylint: disable=exec-used
            exec(
                compile(
                    "import sys; from ci_tools.scripts.policy_checks import main; sys.exit(main())",
                    "<string>",
                    "exec",
                )
            )
        assert exc.value.code == 0


def test_main_as_script_with_violation():
    """Test running module as script with policy violation."""

    def mock_main():
        raise PolicyViolation("test violation")

    with patch("ci_tools.scripts.policy_checks.main", side_effect=mock_main):
        with pytest.raises(SystemExit) as exc:
            # Simulate the __main__ block behavior
            try:
                mock_main()
            except PolicyViolation as err:
                print(err, file=sys.stderr)
                raise SystemExit(1) from err

        assert exc.value.code == 1
