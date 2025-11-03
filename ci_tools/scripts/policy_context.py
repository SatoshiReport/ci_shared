"""Shared constants and AST utilities for policy enforcement."""

from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence

from ci_tools.scripts.guard_common import iter_python_files, normalize_path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRECTORIES: Sequence[Path] = (ROOT / "src", ROOT / "tests")
BANNED_KEYWORDS = (
    "legacy",
    "fallback",
    "default",
    "catch_all",
    "failover",
    "backup",
    "compat",
    "backwards",
    "deprecated",
    "legacy_mode",
    "old_api",
    "legacy_flag",
)
FLAGGED_TOKENS = ("TODO", "FIXME", "HACK", "WORKAROUND", "LEGACY", "DEPRECATED")
FUNCTION_LENGTH_THRESHOLD = 150
BROAD_EXCEPT_SUPPRESSION = "policy_guard: allow-broad-except"
SILENT_HANDLER_SUPPRESSION = "policy_guard: allow-silent-handler"
SUPPRESSION_PATTERNS: tuple[str, ...] = ("# noqa", "pylint: disable")
FORBIDDEN_SYNC_CALLS: tuple[str, ...] = (
    "time.sleep",
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "requests.get",
    "requests.post",
    "requests.put",
    "requests.delete",
    "requests.request",
)
LEGACY_GUARD_TOKENS: tuple[str, ...] = ("legacy", "compat", "deprecated")
LEGACY_SUFFIXES: tuple[str, ...] = ("_legacy", "_compat", "_deprecated")
LEGACY_CONFIG_TOKENS: tuple[str, ...] = (
    "legacy",
    "compat",
    "deprecated",
    "legacy_mode",
    "old_api",
    "legacy_flag",
)
CONFIG_EXTENSIONS: tuple[str, ...] = (".json", ".toml", ".yaml", ".yml", ".ini")
BROAD_EXCEPTION_NAMES = {"Exception", "BaseException"}


@dataclass(frozen=True)
class FunctionEntry:
    path: Path
    name: str
    lineno: int
    length: int


@dataclass
class ModuleContext:
    path: Path
    rel_path: str
    tree: ast.AST
    source: Optional[str] = None
    lines: Optional[List[str]] = None


class FunctionNormalizer(ast.NodeTransformer):
    def visit_Name(self, node: ast.Name) -> ast.AST:  # pragma: no cover - trivial
        ctx = node.ctx.__class__()
        new_node = ast.Name(id="var", ctx=ctx)
        return ast.copy_location(new_node, node)

    def visit_arg(self, node: ast.arg) -> ast.AST:  # pragma: no cover - trivial
        annotation = self.visit(node.annotation) if node.annotation else None
        new_node = ast.arg(arg="arg", annotation=annotation)
        return ast.copy_location(new_node, node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:  # pragma: no cover
        if isinstance(node.value, (int, float, complex, str, bytes, bool)):
            new_node = ast.Constant(value="CONST")
            return ast.copy_location(new_node, node)
        return self.generic_visit(node)


def normalize_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    clone = copy.deepcopy(node)
    if (
        clone.body
        and isinstance(clone.body[0], ast.Expr)
        and isinstance(clone.body[0].value, ast.Constant)
        and isinstance(clone.body[0].value.value, str)
    ):
        clone.body = clone.body[1:]
    normalizer = FunctionNormalizer()
    normalizer.visit(clone)
    return ast.dump(clone, annotate_fields=False, include_attributes=False)


def parse_ast(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text())
    except Exception:  # pragma: no cover - defensive
        return None


def iter_module_contexts(
    bases: Sequence[Path] | None = None,
    *,
    include_source: bool = False,
    include_lines: bool = False,
) -> Iterator[ModuleContext]:
    if bases is None:
        src_dir = ROOT / "src"
        tests_dir = ROOT / "tests"
        if src_dir.exists() or tests_dir.exists():
            bases = (src_dir, tests_dir)
        else:
            bases = (ROOT,)
    for path in iter_python_files(bases):
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        rel_path = normalize_path(path, ROOT)
        source = text if include_source else None
        lines = text.splitlines() if include_lines else None
        yield ModuleContext(
            path=path,
            rel_path=rel_path,
            tree=tree,
            source=source,
            lines=lines,
        )


def _resolve_default_argument(
    call: ast.Call,
    *,
    positional_index: int,
    keyword_names: set[str],
) -> ast.AST | None:
    if len(call.args) > positional_index:
        return call.args[positional_index]
    for keyword in call.keywords:
        if keyword.arg in keyword_names:
            return keyword.value
    return None


def get_call_qualname(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = get_call_qualname(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _sequence_element_has_literal(elt: ast.AST) -> bool:
    if isinstance(elt, ast.Constant):
        return isinstance(elt.value, (int, float, str))
    if isinstance(elt, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return contains_literal_dataset(elt)
    return False


def contains_literal_dataset(node: ast.AST) -> bool:
    if isinstance(node, ast.Dict):
        return any(contains_literal_dataset(value) for value in node.values)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_sequence_element_has_literal(elt) for elt in node.elts)
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str))


def is_non_none_literal(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Constant):
        return node.value is not None
    return False


def is_logging_call(node: ast.AST) -> bool:
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        qualname = get_call_qualname(node.value.func)
        if qualname and qualname.startswith("logging."):
            return True
    return False


def handler_has_raise(handler: ast.ExceptHandler) -> bool:
    for stmt in handler.body:
        for inner in ast.walk(stmt):
            if isinstance(inner, ast.Raise):
                return True
    return False


def classify_handler(handler: ast.ExceptHandler) -> str | None:
    if handler_has_raise(handler):
        return None
    if not handler.body:
        return "empty exception handler"
    for stmt in handler.body:
        if isinstance(stmt, (ast.Pass, ast.Continue, ast.Break)):
            return f"suppresses exception with {stmt.__class__.__name__.lower()}"
        if isinstance(stmt, ast.Return):
            if stmt.value is None or isinstance(stmt.value, ast.Constant):
                return "suppresses exception with literal return"
        if is_logging_call(stmt):
            return "logs exception without re-raising"
    return "exception handler without re-raise"


def is_literal_none_guard(test: ast.AST) -> bool:
    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and len(test.comparators) == 1
    ):
        comparator = test.comparators[0]
        if isinstance(comparator, ast.Constant) and comparator.value is None:
            if isinstance(test.ops[0], (ast.Is, ast.Eq)):
                return True
    return False


def handler_contains_suppression(
    handler: ast.ExceptHandler,
    lines: Sequence[str],
    token: str,
) -> bool:
    if not lines:
        return False
    header_start = max(handler.lineno - 1, 0)
    if handler.body:
        header_end = handler.body[0].lineno - 1
    else:
        header_end = getattr(handler, "end_lineno", handler.lineno)
    header_end = max(header_end, header_start)
    header_end = min(header_end, len(lines) - 1)
    for idx in range(header_start, header_end + 1):
        if token in lines[idx]:
            return True
    return False


__all__ = [
    "ROOT",
    "SCAN_DIRECTORIES",
    "BANNED_KEYWORDS",
    "FLAGGED_TOKENS",
    "FUNCTION_LENGTH_THRESHOLD",
    "BROAD_EXCEPT_SUPPRESSION",
    "SILENT_HANDLER_SUPPRESSION",
    "SUPPRESSION_PATTERNS",
    "FORBIDDEN_SYNC_CALLS",
    "LEGACY_GUARD_TOKENS",
    "LEGACY_SUFFIXES",
    "LEGACY_CONFIG_TOKENS",
    "CONFIG_EXTENSIONS",
    "BROAD_EXCEPTION_NAMES",
    "FunctionEntry",
    "ModuleContext",
    "FunctionNormalizer",
    "normalize_function",
    "parse_ast",
    "iter_module_contexts",
    "get_call_qualname",
    "contains_literal_dataset",
    "is_non_none_literal",
    "is_logging_call",
    "handler_has_raise",
    "classify_handler",
    "is_literal_none_guard",
    "handler_contains_suppression",
]
