"""Unit tests for documentation_guard module."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from ci_tools.scripts import documentation_guard


class TestParseArgs:
    """Test argument parsing."""

    def test_parse_args_defaults(self) -> None:
        """Test default argument values."""
        with patch.object(sys, "argv", ["documentation_guard.py"]):
            args = documentation_guard.parse_args()
            assert args.root == Path(".")

    def test_parse_args_custom_root(self) -> None:
        """Test custom root argument."""
        with patch.object(sys, "argv", ["documentation_guard.py", "--root", "/custom/path"]):
            args = documentation_guard.parse_args()
            assert args.root == Path("/custom/path")


class TestDiscoverSrcModules:
    """Test src module discovery."""

    def test_discover_src_modules_no_src_directory(self, tmp_path: Path) -> None:
        """Test when src directory doesn't exist."""
        result = documentation_guard.discover_src_modules(tmp_path)
        assert not result

    def test_discover_src_modules_empty_src(self, tmp_path: Path) -> None:
        """Test empty src directory."""
        src = tmp_path / "src"
        src.mkdir()
        result = documentation_guard.discover_src_modules(tmp_path)
        assert not result

    def test_discover_src_modules_with_python_files(self, tmp_path: Path) -> None:
        """Test discovering modules with Python files."""
        src = tmp_path / "src"
        module1 = src / "module1"
        module2 = src / "module2"

        module1.mkdir(parents=True)
        module2.mkdir(parents=True)

        (module1 / "code.py").write_text("# code")
        (module2 / "code.py").write_text("# code")

        result = documentation_guard.discover_src_modules(tmp_path)
        assert len(result) == 2
        assert "src/module1/README.md" in result
        assert "src/module2/README.md" in result

    def test_discover_src_modules_skip_underscore(self, tmp_path: Path) -> None:
        """Test skipping directories starting with underscore."""
        src = tmp_path / "src"
        module = src / "module"
        pycache = src / "__pycache__"

        module.mkdir(parents=True)
        pycache.mkdir(parents=True)

        (module / "code.py").write_text("# code")
        (pycache / "cached.pyc").write_text("# cached")

        result = documentation_guard.discover_src_modules(tmp_path)
        assert len(result) == 1
        assert "src/module/README.md" in result
        assert "__pycache__" not in str(result)

    def test_discover_src_modules_skip_git(self, tmp_path: Path) -> None:
        """Test skipping .git directory."""
        src = tmp_path / "src"
        module = src / "module"
        git = src / ".git"

        module.mkdir(parents=True)
        git.mkdir(parents=True)

        (module / "code.py").write_text("# code")
        (git / "config").write_text("# git")

        result = documentation_guard.discover_src_modules(tmp_path)
        assert len(result) == 1
        assert ".git" not in str(result)

    def test_discover_src_modules_ignore_files(self, tmp_path: Path) -> None:
        """Test that direct files in src are ignored."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "script.py").write_text("# script")

        result = documentation_guard.discover_src_modules(tmp_path)
        assert not result

    def test_discover_src_modules_no_python_files(self, tmp_path: Path) -> None:
        """Test that modules without Python files are not required."""
        src = tmp_path / "src"
        module = src / "module"
        module.mkdir(parents=True)
        (module / "data.txt").write_text("data")

        result = documentation_guard.discover_src_modules(tmp_path)
        assert not result


class TestDiscoverArchitectureDocs:
    """Test architecture documentation discovery."""

    def test_discover_architecture_docs_no_directory(self, tmp_path: Path) -> None:
        """Test when docs/architecture doesn't exist."""
        result = documentation_guard.discover_architecture_docs(tmp_path)
        assert not result

    def test_discover_architecture_docs_empty(self, tmp_path: Path) -> None:
        """Test empty architecture directory."""
        arch_dir = tmp_path / "docs" / "architecture"
        arch_dir.mkdir(parents=True)

        result = documentation_guard.discover_architecture_docs(tmp_path)
        assert not result

    def test_discover_architecture_docs_with_markdown(self, tmp_path: Path) -> None:
        """Test discovering architecture docs with markdown files."""
        arch_dir = tmp_path / "docs" / "architecture"
        arch_dir.mkdir(parents=True)
        (arch_dir / "system.md").write_text("# System")
        (arch_dir / "database.md").write_text("# Database")

        result = documentation_guard.discover_architecture_docs(tmp_path)
        assert result == ["docs/architecture/README.md"]

    def test_discover_architecture_docs_only_non_markdown(self, tmp_path: Path) -> None:
        """Test architecture directory with only non-markdown files."""
        arch_dir = tmp_path / "docs" / "architecture"
        arch_dir.mkdir(parents=True)
        (arch_dir / "diagram.png").write_text("image")

        result = documentation_guard.discover_architecture_docs(tmp_path)
        assert not result


class TestDiscoverDomainDocs:
    """Test domain documentation discovery."""

    def test_discover_domain_docs_no_directory(self, tmp_path: Path) -> None:
        """Test when docs/domains doesn't exist."""
        result = documentation_guard.discover_domain_docs(tmp_path)
        assert not result

    def test_discover_domain_docs_empty(self, tmp_path: Path) -> None:
        """Test empty domains directory."""
        domains_dir = tmp_path / "docs" / "domains"
        domains_dir.mkdir(parents=True)

        result = documentation_guard.discover_domain_docs(tmp_path)
        assert not result

    def test_discover_domain_docs_with_subdirs(self, tmp_path: Path) -> None:
        """Test discovering domain docs with subdirectories."""
        domains_dir = tmp_path / "docs" / "domains"
        domain1 = domains_dir / "trading"
        domain2 = domains_dir / "risk"

        domain1.mkdir(parents=True)
        domain2.mkdir(parents=True)

        result = documentation_guard.discover_domain_docs(tmp_path)
        assert len(result) == 2
        assert "docs/domains/trading/README.md" in result
        assert "docs/domains/risk/README.md" in result

    def test_discover_domain_docs_skip_underscore(self, tmp_path: Path) -> None:
        """Test skipping underscore directories."""
        domains_dir = tmp_path / "docs" / "domains"
        domain = domains_dir / "domain"
        internal = domains_dir / "_internal"

        domain.mkdir(parents=True)
        internal.mkdir(parents=True)

        result = documentation_guard.discover_domain_docs(tmp_path)
        assert len(result) == 1
        assert "_internal" not in str(result)

    def test_discover_domain_docs_ignore_files(self, tmp_path: Path) -> None:
        """Test that direct files in domains are ignored."""
        domains_dir = tmp_path / "docs" / "domains"
        domains_dir.mkdir(parents=True)
        (domains_dir / "overview.md").write_text("# Overview")

        result = documentation_guard.discover_domain_docs(tmp_path)
        assert not result


class TestDiscoverOperationsDocs:
    """Test operations documentation discovery."""

    def test_discover_operations_docs_no_directory(self, tmp_path: Path) -> None:
        """Test when docs/operations doesn't exist."""
        result = documentation_guard.discover_operations_docs(tmp_path)
        assert not result

    def test_discover_operations_docs_exists(self, tmp_path: Path) -> None:
        """Test when docs/operations exists."""
        ops_dir = tmp_path / "docs" / "operations"
        ops_dir.mkdir(parents=True)

        result = documentation_guard.discover_operations_docs(tmp_path)
        assert result == ["docs/operations/README.md"]


class TestDiscoverReferenceDocs:
    """Test reference documentation discovery."""

    def test_discover_reference_docs_no_directory(self, tmp_path: Path) -> None:
        """Test when docs/reference doesn't exist."""
        result = documentation_guard.discover_reference_docs(tmp_path)
        assert not result

    def test_discover_reference_docs_empty(self, tmp_path: Path) -> None:
        """Test empty reference directory."""
        ref_dir = tmp_path / "docs" / "reference"
        ref_dir.mkdir(parents=True)

        result = documentation_guard.discover_reference_docs(tmp_path)
        assert not result

    def test_discover_reference_docs_with_subdirs(self, tmp_path: Path) -> None:
        """Test discovering reference docs with subdirectories."""
        ref_dir = tmp_path / "docs" / "reference"
        api = ref_dir / "api"
        cli = ref_dir / "cli"

        api.mkdir(parents=True)
        cli.mkdir(parents=True)

        result = documentation_guard.discover_reference_docs(tmp_path)
        assert len(result) == 2
        assert "docs/reference/api/README.md" in result
        assert "docs/reference/cli/README.md" in result

    def test_discover_reference_docs_skip_underscore(self, tmp_path: Path) -> None:
        """Test skipping underscore directories."""
        ref_dir = tmp_path / "docs" / "reference"
        api = ref_dir / "api"
        private = ref_dir / "_private"

        api.mkdir(parents=True)
        private.mkdir(parents=True)

        result = documentation_guard.discover_reference_docs(tmp_path)
        assert len(result) == 1
        assert "_private" not in str(result)


class TestGetBaseRequirements:
    """Test base documentation requirements."""

    def test_get_base_requirements_minimal(self, tmp_path: Path) -> None:
        """Test minimal base requirements."""
        result = documentation_guard.get_base_requirements(tmp_path)
        assert "README.md" in result
        assert "CLAUDE.md" not in result

    def test_get_base_requirements_with_claude_md(self, tmp_path: Path) -> None:
        """Test when CLAUDE.md exists."""
        (tmp_path / "CLAUDE.md").write_text("# Claude")

        result = documentation_guard.get_base_requirements(tmp_path)
        assert "README.md" in result
        assert "CLAUDE.md" in result

    def test_get_base_requirements_with_docs_dir(self, tmp_path: Path) -> None:
        """Test when docs directory exists."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        result = documentation_guard.get_base_requirements(tmp_path)
        assert "README.md" in result
        assert "docs/README.md" in result


class TestDiscoverAllRequirements:
    """Test comprehensive requirements discovery."""

    def test_discover_all_requirements_minimal(self, tmp_path: Path) -> None:
        """Test minimal repository structure."""
        required, info = documentation_guard.discover_all_requirements(tmp_path)

        assert "README.md" in required
        assert "base" in info
        assert "modules" in info
        assert "architecture" in info
        assert "domains" in info
        assert "operations" in info
        assert "reference" in info

    def test_discover_all_requirements_comprehensive(self, tmp_path: Path) -> None:
        """Test comprehensive repository structure."""
        # Create various directories
        (tmp_path / "CLAUDE.md").write_text("# Claude")
        (tmp_path / "docs").mkdir()

        src = tmp_path / "src" / "module1"
        src.mkdir(parents=True)
        (src / "code.py").write_text("# code")

        arch = tmp_path / "docs" / "architecture"
        arch.mkdir(parents=True)
        (arch / "system.md").write_text("# System")

        domains = tmp_path / "docs" / "domains" / "trading"
        domains.mkdir(parents=True)

        ops = tmp_path / "docs" / "operations"
        ops.mkdir(parents=True)

        ref = tmp_path / "docs" / "reference" / "api"
        ref.mkdir(parents=True)

        required, _info = documentation_guard.discover_all_requirements(tmp_path)

        assert "README.md" in required
        assert "CLAUDE.md" in required
        assert "docs/README.md" in required
        assert "src/module1/README.md" in required
        assert "docs/architecture/README.md" in required
        assert "docs/domains/trading/README.md" in required
        assert "docs/operations/README.md" in required
        assert "docs/reference/api/README.md" in required

    def test_discover_all_requirements_info_structure(self, tmp_path: Path) -> None:
        """Test that discovery info has correct structure."""
        _required, info = documentation_guard.discover_all_requirements(tmp_path)

        assert isinstance(info["base"], list)
        assert isinstance(info["modules"], list)
        assert isinstance(info["architecture"], list)
        assert isinstance(info["domains"], list)
        assert isinstance(info["operations"], list)
        assert isinstance(info["reference"], list)


class TestCheckRequiredDocs:
    """Test checking for missing documentation."""

    def test_check_required_docs_all_present(self, tmp_path: Path) -> None:
        """Test when all required docs are present."""
        (tmp_path / "README.md").write_text("# README")
        (tmp_path / "CLAUDE.md").write_text("# CLAUDE")

        required = ["README.md", "CLAUDE.md"]
        missing = documentation_guard.check_required_docs(tmp_path, required)
        assert not missing

    def test_check_required_docs_some_missing(self, tmp_path: Path) -> None:
        """Test when some required docs are missing."""
        (tmp_path / "README.md").write_text("# README")

        required = ["README.md", "CLAUDE.md", "docs/README.md"]
        missing = documentation_guard.check_required_docs(tmp_path, required)
        assert len(missing) == 2
        assert "CLAUDE.md" in missing
        assert "docs/README.md" in missing

    def test_check_required_docs_all_missing(self, tmp_path: Path) -> None:
        """Test when all required docs are missing."""
        required = ["README.md", "CLAUDE.md"]
        missing = documentation_guard.check_required_docs(tmp_path, required)
        assert len(missing) == 2
        assert set(missing) == set(required)


class TestGroupMissingDocs:
    """Test grouping missing documentation."""

    def testgroup_missing_docs_by_category(self) -> None:
        """Test grouping missing docs by category."""
        missing = ["README.md", "src/module1/README.md", "docs/architecture/README.md"]
        discovery_info = {
            "base": ["README.md"],
            "modules": ["src/module1/README.md"],
            "architecture": ["docs/architecture/README.md"],
            "domains": [],
            "operations": [],
            "reference": [],
        }

        grouped = documentation_guard.group_missing_docs(missing, discovery_info)

        assert "README.md" in grouped["Base"]
        assert "src/module1/README.md" in grouped["Modules"]
        assert "docs/architecture/README.md" in grouped["Architecture"]

    def testgroup_missing_docs_empty(self) -> None:
        """Test grouping with no missing docs."""
        missing = []
        discovery_info = {
            "base": [],
            "modules": [],
            "architecture": [],
            "domains": [],
            "operations": [],
            "reference": [],
        }

        grouped = documentation_guard.group_missing_docs(missing, discovery_info)

        assert all(len(docs) == 0 for docs in grouped.values())


class TestPrintFunctions:
    """Test output printing functions."""

    def testprint_failure_report(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test failure report printing."""
        grouped = {
            "Base": ["README.md"],
            "Modules": ["src/module1/README.md"],
            "Architecture": [],
            "Domains": [],
            "Operations": [],
            "Reference": [],
        }

        documentation_guard.print_failure_report(grouped)
        captured = capsys.readouterr()

        assert "Documentation Guard: FAILED" in captured.err
        assert "README.md" in captured.err
        assert "src/module1/README.md" in captured.err

    def testprint_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test success message printing."""
        documentation_guard.print_success(5)
        captured = capsys.readouterr()

        assert "documentation_guard" in captured.err
        assert "All required documentation present" in captured.err
        assert "5 docs verified" in captured.err


class TestMainFunction:
    """Test main function and CLI behavior."""

    def test_main_root_does_not_exist(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main with non-existent root."""
        with patch.object(
            sys, "argv", ["documentation_guard.py", "--root", str(tmp_path / "missing")]
        ):
            result = documentation_guard.main()
            assert result == 1

            captured = capsys.readouterr()
            assert "does not exist" in captured.err

    def test_main_all_docs_present(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main when all required docs are present."""
        (tmp_path / "README.md").write_text("# README")

        with patch.object(sys, "argv", ["documentation_guard.py", "--root", str(tmp_path)]):
            result = documentation_guard.main()
            assert result == 0

            captured = capsys.readouterr()
            assert "All required documentation present" in captured.err

    def test_main_missing_docs(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main when docs are missing."""
        src = tmp_path / "src" / "module1"
        src.mkdir(parents=True)
        (src / "code.py").write_text("# code")

        with patch.object(sys, "argv", ["documentation_guard.py", "--root", str(tmp_path)]):
            result = documentation_guard.main()
            assert result == 1

            captured = capsys.readouterr()
            assert "Documentation Guard: FAILED" in captured.err
            assert "README.md" in captured.err
            assert "src/module1/README.md" in captured.err

    def test_main_complex_structure(
        self, tmp_path: Path    ) -> None:
        """Test main with complex directory structure."""
        # Create required base docs
        (tmp_path / "README.md").write_text("# README")
        (tmp_path / "CLAUDE.md").write_text("# Claude")
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "README.md").write_text("# Docs")

        # Create src modules
        module1 = tmp_path / "src" / "module1"
        module2 = tmp_path / "src" / "module2"
        module1.mkdir(parents=True)
        module2.mkdir(parents=True)
        (module1 / "code.py").write_text("# code")
        (module2 / "code.py").write_text("# code")
        (module1 / "README.md").write_text("# Module 1")
        (module2 / "README.md").write_text("# Module 2")

        # Create architecture docs
        arch = tmp_path / "docs" / "architecture"
        arch.mkdir(parents=True)
        (arch / "system.md").write_text("# System")
        (arch / "README.md").write_text("# Architecture")

        with patch.object(sys, "argv", ["documentation_guard.py", "--root", str(tmp_path)]):
            result = documentation_guard.main()
            assert result == 0

    def test_main_script_entry_point(self, tmp_path: Path) -> None:
        """Test __main__ entry point."""
        (tmp_path / "README.md").write_text("# README")

        # We can't easily test the __main__ entry point due to module-level imports
        # Instead, test that main() can be called successfully
        with patch.object(sys, "argv", ["documentation_guard.py", "--root", str(tmp_path)]):
            result = documentation_guard.main()
            assert result == 0


# pylint: disable=too-few-public-methods
class TestCategoryKeys:
    """Test CATEGORY_KEYS constant."""

    def test_category_keys_structure(self) -> None:
        """Test that CATEGORY_KEYS has expected structure."""
        assert len(documentation_guard.CATEGORY_KEYS) == 6

        labels = [label for label, _ in documentation_guard.CATEGORY_KEYS]
        keys = [key for _, key in documentation_guard.CATEGORY_KEYS]

        assert "Base" in labels
        assert "Modules" in labels
        assert "Architecture" in labels
        assert "Domains" in labels
        assert "Operations" in labels
        assert "Reference" in labels

        assert "base" in keys
        assert "modules" in keys
        assert "architecture" in keys
        assert "domains" in keys
        assert "operations" in keys
        assert "reference" in keys


class TestEdgeCases:
    """Test edge cases and unusual scenarios."""

    def test_nested_modules_in_src(self, tmp_path: Path) -> None:
        """Test deeply nested modules in src."""
        deep_module = tmp_path / "src" / "package" / "subpackage" / "module"
        deep_module.mkdir(parents=True)
        (deep_module / "code.py").write_text("# code")

        # Only top-level should be detected
        result = documentation_guard.discover_src_modules(tmp_path)
        assert "src/package/README.md" in result
        assert len(result) == 1

    def test_multiple_file_types_in_module(self, tmp_path: Path) -> None:
        """Test module with various file types."""
        module = tmp_path / "src" / "module"
        module.mkdir(parents=True)
        (module / "code.py").write_text("# python")
        (module / "data.json").write_text("{}")
        (module / "config.yaml").write_text("key: value")

        result = documentation_guard.discover_src_modules(tmp_path)
        assert "src/module/README.md" in result

    def test_empty_python_file(self, tmp_path: Path) -> None:
        """Test module with empty Python file."""
        module = tmp_path / "src" / "module"
        module.mkdir(parents=True)
        (module / "empty.py").write_text("")

        result = documentation_guard.discover_src_modules(tmp_path)
        assert "src/module/README.md" in result

    def test_symlinks_if_supported(self, tmp_path: Path) -> None:
        """Test handling of symlinked directories."""
        try:
            module = tmp_path / "src" / "module"
            module.mkdir(parents=True)
            (module / "code.py").write_text("# code")

            link = tmp_path / "src" / "link"
            link.symlink_to(module)

            result = documentation_guard.discover_src_modules(tmp_path)
            # Should find both the original and the link
            assert "src/module/README.md" in result
        except OSError:
            # Skip if symlinks not supported
            pytest.skip("Symlinks not supported on this platform")
