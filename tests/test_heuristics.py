"""Unit tests for ci_tools.ci_runtime.heuristics module."""

from __future__ import annotations

from ci_tools.ci_runtime.heuristics import (
    detect_attribute_error,
    detect_missing_symbol_error,
    summarize_failure,
    tail_text,
)


class TestDetectMissingSymbolError:
    """Tests for detect_missing_symbol_error function."""

    def test_import_error_detected(self):
        """Test detection of ImportError with missing symbol."""
        log = "ImportError: cannot import name 'MyClass' from 'mymodule'"
        result = detect_missing_symbol_error(log)
        assert result is not None
        assert "ImportError detected" in result
        assert "MyClass" in result
        assert "mymodule" in result

    def test_no_import_error(self):
        """Test returns None when no ImportError present."""
        log = "Some other error occurred"
        result = detect_missing_symbol_error(log)
        assert result is None

    def test_import_error_multiline_log(self):
        """Test ImportError detection in multiline logs."""
        log = """
        Traceback (most recent call last):
          File "test.py", line 5, in <module>
        ImportError: cannot import name 'foo' from 'bar'
        """
        result = detect_missing_symbol_error(log)
        assert result is not None
        assert "foo" in result
        assert "bar" in result

    def test_empty_log(self):
        """Test empty log returns None."""
        result = detect_missing_symbol_error("")
        assert result is None


class TestDetectAttributeError:
    """Tests for detect_attribute_error function."""

    def test_attribute_error_with_repo_file(self):
        """Test AttributeError detection with file from repository."""
        from ci_tools.ci_runtime.config import REPO_ROOT

        # Create a log with a file that is in the repo
        test_file = REPO_ROOT / "ci_tools" / "ci_runtime" / "models.py"

        log = f'''
        Traceback (most recent call last):
          File "{test_file}", line 10, in test_function
            obj.missing_attribute()
        AttributeError: 'MyClass' object has no attribute 'missing_attribute'
        '''
        result = detect_attribute_error(log)
        # Should successfully detect the error with a repo file
        assert result is not None
        assert "AttributeError detected" in result
        assert "missing_attribute" in result
        assert "ci_tools" in result or "models.py" in result

    def test_attribute_error_no_file_match(self):
        """Test AttributeError without matching repository file."""
        log = """
        AttributeError: 'str' object has no attribute 'nonexistent'
        """
        result = detect_attribute_error(log)
        # Without a File line, should return None
        assert result is None

    def test_no_attribute_error(self):
        """Test returns None when no AttributeError present."""
        log = "ValueError: invalid value provided"
        result = detect_attribute_error(log)
        assert result is None

    def test_empty_log(self):
        """Test empty log returns None."""
        result = detect_attribute_error("")
        assert result is None

    def test_attribute_error_pattern_matching(self):
        """Test attribute error pattern matching."""
        log = "AttributeError: 'NoneType' object has no attribute 'value'"
        result = detect_attribute_error(log)
        # Without file frame, returns None
        assert result is None

    def test_attribute_error_with_oserror(self, monkeypatch):
        """Test AttributeError handling when resolve() raises OSError."""
        from pathlib import Path

        # Create a log with a file path that will trigger OSError
        log = '''
        Traceback (most recent call last):
          File "/invalid/path/that/does/not/exist.py", line 10, in test_function
            obj.missing_method()
        AttributeError: 'MyClass' object has no attribute 'missing_method'
        '''

        # Mock Path.resolve to raise OSError
        original_resolve = Path.resolve

        def mock_resolve(self):
            if "does/not/exist" in str(self):
                raise OSError("Cannot resolve path")
            return original_resolve(self)

        monkeypatch.setattr(Path, "resolve", mock_resolve)

        result = detect_attribute_error(log)
        # Should return None when OSError occurs and no valid candidate found
        assert result is None

    def test_attribute_error_outside_repo(self):
        """Test AttributeError with file outside repository."""
        # Using a path that's definitely not in the repo
        log = '''
        Traceback (most recent call last):
          File "/usr/lib/python3.12/site-packages/test.py", line 10, in test_function
            obj.bad_attr()
        AttributeError: 'dict' object has no attribute 'bad_attr'
        '''
        result = detect_attribute_error(log)
        # Should return None for files outside the repo
        assert result is None


class TestSummarizeFailure:
    """Tests for summarize_failure function."""

    def test_pyright_errors_detected(self):
        """Test summarization of pyright type errors."""
        log = """
        /Users/john/project/src/module.py:42: error: Type mismatch
        /Users/john/project/src/helper.py:10: error: Missing type annotation
        """
        summary, files = summarize_failure(log)
        assert "pyright reported type errors" in summary
        # The regex captures everything after /Users/[^:]+/
        assert "module.py:42" in summary or "src/module.py:42" in summary
        assert "helper.py:10" in summary or "src/helper.py:10" in summary
        # Files list contains the relative paths
        assert any("module.py" in f for f in files)
        assert any("helper.py" in f for f in files)
        assert len(files) == 2

    def test_duplicate_files_deduplicated(self):
        """Test that duplicate files are deduplicated."""
        log = """
        /Users/john/project/src/module.py:42: error: Type mismatch
        /Users/john/project/src/module.py:50: error: Another error
        """
        summary, files = summarize_failure(log)
        assert len(files) == 1
        # The file path is extracted as everything after /Users/[^:]+/
        assert any("module.py" in f for f in files)

    def test_pyright_lines_skipped(self):
        """Test that lines containing 'pyright' are skipped."""
        log = """
        Running pyright analysis...
        /Users/john/project/src/module.py:42: error: Type mismatch
        pyright: finished in 1.2s
        """
        summary, files = summarize_failure(log)
        assert "pyright reported type errors" in summary
        assert any("module.py" in f for f in files)

    def test_no_errors_found(self):
        """Test empty summary when no errors found."""
        log = "All tests passed successfully"
        summary, files = summarize_failure(log)
        assert summary == ""
        assert files == []

    def test_empty_log(self):
        """Test empty log returns empty results."""
        summary, files = summarize_failure("")
        assert summary == ""
        assert files == []

    def test_mixed_content(self):
        """Test log with mixed content."""
        log = """
        Starting tests...
        /Users/jane/myrepo/tests/test_foo.py:15: assertion failed
        Some other output
        /Users/jane/myrepo/src/core.py:99: error message
        """
        summary, files = summarize_failure(log)
        if files:  # If pattern matches
            # Files contain paths after /Users/jane/myrepo/
            assert any("test_foo.py" in f for f in files) or any("core.py" in f for f in files)


class TestTailText:
    """Tests for tail_text function."""

    def test_tail_single_line(self):
        """Test tail with single line text."""
        text = "single line"
        result = tail_text(text, 5)
        assert result == "single line"

    def test_tail_exact_lines(self):
        """Test tail with exact number of lines requested."""
        text = "line1\nline2\nline3"
        result = tail_text(text, 3)
        assert result == "line1\nline2\nline3"

    def test_tail_fewer_lines(self):
        """Test tail requesting fewer lines than available."""
        text = "line1\nline2\nline3\nline4\nline5"
        result = tail_text(text, 3)
        assert result == "line3\nline4\nline5"

    def test_tail_more_lines_than_available(self):
        """Test tail requesting more lines than available."""
        text = "line1\nline2"
        result = tail_text(text, 10)
        assert result == "line1\nline2"

    def test_tail_zero_lines(self):
        """Test tail with zero lines requested."""
        text = "line1\nline2\nline3"
        result = tail_text(text, 0)
        # Python list[-0:] returns the entire list
        assert result == "line1\nline2\nline3"

    def test_tail_empty_text(self):
        """Test tail with empty text."""
        result = tail_text("", 5)
        assert result == ""

    def test_tail_with_trailing_newline(self):
        """Test tail with text ending in newline."""
        text = "line1\nline2\nline3\n"
        result = tail_text(text, 2)
        # splitlines() doesn't include trailing empty string
        assert "line2" in result
        assert "line3" in result

    def test_tail_single_line_request(self):
        """Test tail requesting single line."""
        text = "line1\nline2\nline3"
        result = tail_text(text, 1)
        assert result == "line3"

    def test_tail_negative_lines(self):
        """Test tail with negative line count."""
        text = "line1\nline2\nline3"
        result = tail_text(text, -1)
        # Python list[-(-1):] = list[1:] which skips the first element
        assert result == "line2\nline3"
