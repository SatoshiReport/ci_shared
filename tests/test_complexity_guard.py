from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import complexity_guard


def write_module(path: Path, source: str) -> None:
    path.write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")


def test_calculate_cognitive_complexity_counts_nested_branches() -> None:
    source = textwrap.dedent(
        """
        def sample(x: int) -> int:
            if x > 10:
                for value in range(x):
                    if value % 2 == 0:
                        return value
            return 0
        """
    )
    tree = complexity_guard.ast.parse(source)
    func = next(node for node in tree.body if isinstance(node, complexity_guard.ast.FunctionDef))
    score = complexity_guard.calculate_cognitive_complexity(func)
    assert score >= 3


def test_check_file_complexity_detects_violation(tmp_path: Path) -> None:
    target = tmp_path / "violations.py"
    write_module(
        target,
        """
        def risky(value: int) -> int:
            if value > 0:
                if value > 1:
                    if value > 2:
                        return value
            return 0
        """,
    )
    results = complexity_guard.check_file_complexity(target, max_cyclomatic=1, max_cognitive=1)
    assert results, "Expected complexity violations to be reported"
    assert results[0].function_name == "risky"


def test_check_file_complexity_ignores_simple_function(tmp_path: Path) -> None:
    target = tmp_path / "clean.py"
    write_module(
        target,
        """
        def clean() -> int:
            return 1
        """,
    )
    results = complexity_guard.check_file_complexity(target, max_cyclomatic=2, max_cognitive=2)
    assert results == []


def run_main(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["complexity_guard.py", *args])
    with pytest.raises(SystemExit) as exc:
        complexity_guard.main()
    return int(exc.value.code)


def test_main_rejects_missing_root(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "missing"
    code = run_main(monkeypatch, ["--root", str(missing)])
    assert code == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.err


def test_main_reports_violation(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "pkg"
    root.mkdir()
    write_module(
        root / "bad.py",
        """
        def bad(value: int) -> int:
            if value > 0:
                if value > 1:
                    return value
            return 0
        """,
    )
    code = run_main(
        monkeypatch,
        ["--root", str(root), "--max-cyclomatic", "1", "--max-cognitive", "1"],
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "bad.py" in captured.out


def test_main_succeeds_without_violations(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "pkg"
    root.mkdir()
    write_module(
        root / "ok.py",
        """
        def ok() -> int:
            return 1
        """,
    )
    code = run_main(monkeypatch, ["--root", str(root)])
    assert code == 0
    captured = capsys.readouterr()
    assert "All functions meet complexity limits" in captured.out
