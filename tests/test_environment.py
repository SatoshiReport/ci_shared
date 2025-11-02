"""Unit tests for ci_tools.ci_runtime.environment module."""

from __future__ import annotations

import os
from pathlib import Path


from ci_tools.ci_runtime.environment import load_env_file, load_env_settings


class TestLoadEnvFile:
    """Tests for load_env_file function."""

    def test_load_simple_env_file(self, tmp_path):
        """Test loading a simple KEY=VALUE env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=qux\n")

        result = load_env_file(str(env_file))
        assert result == {"FOO": "bar", "BAZ": "qux"}

    def test_load_env_file_with_spaces(self, tmp_path):
        """Test loading env file with spaces around equals."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1 = value1\nKEY2= value2\nKEY3 =value3\n")

        result = load_env_file(str(env_file))
        assert result["KEY1"] == "value1"
        assert result["KEY2"] == "value2"
        assert result["KEY3"] == "value3"

    def test_load_env_file_with_comments(self, tmp_path):
        """Test loading env file with comment lines."""
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nKEY=value\n# Another comment\n")

        result = load_env_file(str(env_file))
        assert result == {"KEY": "value"}

    def test_load_env_file_with_empty_lines(self, tmp_path):
        """Test loading env file with empty lines."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\n\nKEY2=value2\n\n")

        result = load_env_file(str(env_file))
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_load_env_file_with_values_containing_equals(self, tmp_path):
        """Test loading env file where values contain equals signs."""
        env_file = tmp_path / ".env"
        env_file.write_text("CONNECTION_STRING=server=localhost;port=5432\n")

        result = load_env_file(str(env_file))
        assert result["CONNECTION_STRING"] == "server=localhost;port=5432"

    def test_load_env_file_invalid_lines_skipped(self, tmp_path):
        """Test that lines without equals are skipped."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\nINVALIDLINE\nKEY2=value2\n")

        result = load_env_file(str(env_file))
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_load_env_file_nonexistent_returns_empty(self, tmp_path):
        """Test loading nonexistent file returns empty dict."""
        nonexistent = tmp_path / "nonexistent.env"
        result = load_env_file(str(nonexistent))
        assert result == {}

    def test_load_env_file_empty_file(self, tmp_path):
        """Test loading empty file returns empty dict."""
        env_file = tmp_path / ".env"
        env_file.write_text("")

        result = load_env_file(str(env_file))
        assert result == {}

    def test_load_env_file_only_comments(self, tmp_path):
        """Test loading file with only comments returns empty dict."""
        env_file = tmp_path / ".env"
        env_file.write_text("# Comment 1\n# Comment 2\n")

        result = load_env_file(str(env_file))
        assert result == {}

    def test_load_env_file_with_whitespace_only_lines(self, tmp_path):
        """Test loading file with whitespace-only lines."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\n   \n\t\nKEY2=value2\n")

        result = load_env_file(str(env_file))
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_load_env_file_expanduser(self, tmp_path, monkeypatch):
        """Test that path supports tilde expansion."""
        # Create a file in tmp_path
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_KEY=test_value\n")

        # Mock expanduser to return our tmp_path
        original_expanduser = Path.expanduser

        def mock_expanduser(self):
            if str(self) == "~/.env":
                return env_file
            return original_expanduser(self)

        monkeypatch.setattr(Path, "expanduser", mock_expanduser)

        result = load_env_file("~/.env")
        assert result == {"TEST_KEY": "test_value"}

    def test_load_env_file_utf8_encoding(self, tmp_path):
        """Test loading file with UTF-8 characters."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=café\n", encoding="utf-8")

        result = load_env_file(str(env_file))
        assert result["KEY"] == "café"

    def test_load_env_file_empty_value(self, tmp_path):
        """Test loading key with empty value."""
        env_file = tmp_path / ".env"
        env_file.write_text("EMPTY_KEY=\nKEY2=value2\n")

        result = load_env_file(str(env_file))
        assert result["EMPTY_KEY"] == ""
        assert result["KEY2"] == "value2"


class TestLoadEnvSettings:
    """Tests for load_env_settings function."""

    def test_load_env_settings_populates_environ(self, tmp_path, monkeypatch):
        """Test that load_env_settings populates os.environ."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR=test_value\nANOTHER=another_value\n")

        # Clear any existing values
        monkeypatch.delenv("TEST_VAR", raising=False)
        monkeypatch.delenv("ANOTHER", raising=False)

        load_env_settings(str(env_file))

        assert os.environ.get("TEST_VAR") == "test_value"
        assert os.environ.get("ANOTHER") == "another_value"

    def test_load_env_settings_preserves_existing(self, tmp_path, monkeypatch):
        """Test that load_env_settings doesn't override existing env vars."""
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING=from_file\n")

        # Set existing value
        monkeypatch.setenv("EXISTING", "original_value")

        load_env_settings(str(env_file))

        # Should preserve the original value
        assert os.environ["EXISTING"] == "original_value"

    def test_load_env_settings_adds_new_vars(self, tmp_path, monkeypatch):
        """Test that load_env_settings adds new variables."""
        env_file = tmp_path / ".env"
        env_file.write_text("NEW_VAR=new_value\n")

        monkeypatch.delenv("NEW_VAR", raising=False)

        load_env_settings(str(env_file))

        assert os.environ.get("NEW_VAR") == "new_value"

    def test_load_env_settings_nonexistent_file(self, tmp_path, monkeypatch):
        """Test that load_env_settings handles nonexistent file gracefully."""
        nonexistent = tmp_path / "nonexistent.env"

        # Should not raise an exception
        load_env_settings(str(nonexistent))

        # Env should remain unchanged (no crash)
        assert True

    def test_load_env_settings_empty_file(self, tmp_path):
        """Test that load_env_settings handles empty file."""
        env_file = tmp_path / ".env"
        env_file.write_text("")

        # Should not raise an exception
        load_env_settings(str(env_file))

    def test_load_env_settings_multiple_calls(self, tmp_path, monkeypatch):
        """Test multiple calls to load_env_settings."""
        env_file1 = tmp_path / ".env1"
        env_file1.write_text("VAR1=value1\n")

        env_file2 = tmp_path / ".env2"
        env_file2.write_text("VAR2=value2\nVAR1=override\n")

        monkeypatch.delenv("VAR1", raising=False)
        monkeypatch.delenv("VAR2", raising=False)

        load_env_settings(str(env_file1))
        assert os.environ["VAR1"] == "value1"

        load_env_settings(str(env_file2))
        # VAR1 should not be overridden (setdefault behavior)
        assert os.environ["VAR1"] == "value1"
        # VAR2 should be added
        assert os.environ["VAR2"] == "value2"
