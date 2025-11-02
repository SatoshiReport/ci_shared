"""AST-based collectors for policy enforcement."""

from __future__ import annotations

import ast
import shutil
from collections import defaultdict
from typing import Dict, Iterable, Iterator, List, Tuple

from .policy_context import (
    BROAD_EXCEPT_SUPPRESSION,
    BROAD_EXCEPTION_NAMES,
    FORBIDDEN_SYNC_CALLS,
    LEGACY_GUARD_TOKENS,
    LEGACY_SUFFIXES,
    ROOT,
    SILENT_HANDLER_SUPPRESSION,
    FunctionEntry,
    ModuleContext,
    _resolve_default_argument,
    classify_handler,
    get_call_qualname,
    handler_contains_suppression,
    is_literal_none_guard,
    is_non_none_literal,
    iter_module_contexts,
    normalize_function,
    normalize_path,
)


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


def collect_long_functions(threshold: int) -> Iterable[FunctionEntry]:
    src_root = ROOT / "src"
    for ctx in iter_module_contexts((src_root,)):
        if ctx.path.name == "__init__.py":
            continue
        for node in ast.walk(ctx.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not (node.end_lineno and node.lineno):
                continue
            length = node.end_lineno - node.lineno + 1
            if length > threshold:
                yield FunctionEntry(
                    path=ctx.path,
                    name=node.name,
                    lineno=node.lineno,
                    length=length,
                )


def collect_broad_excepts() -> List[Tuple[str, int]]:
    records: List[Tuple[str, int]] = []

    class BroadExceptVisitor(ast.NodeVisitor):
        def __init__(self, ctx: ModuleContext) -> None:
            self.ctx = ctx

        def visit_Try(self, node: ast.Try) -> None:
            for handler in node.handlers:
                if not _handler_catches_broad(handler):
                    continue
                lines = self.ctx.lines or []
                if handler_contains_suppression(
                    handler, lines, BROAD_EXCEPT_SUPPRESSION
                ):
                    continue
                records.append((self.ctx.rel_path, handler.lineno))
            self.generic_visit(node)

    for ctx in iter_module_contexts((ROOT / "src",), include_lines=True):
        if ctx.path.name == "__init__.py":
            continue
        BroadExceptVisitor(ctx).visit(ctx.tree)
    return records


def _handler_catches_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name):
        return handler.type.id in BROAD_EXCEPTION_NAMES
    if isinstance(handler.type, ast.Tuple):
        return any(
            isinstance(elt, ast.Name) and elt.id in BROAD_EXCEPTION_NAMES
            for elt in handler.type.elts
        )
    return False


def collect_silent_handlers() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []

    class SilentHandlerVisitor(ast.NodeVisitor):
        def __init__(self, ctx: ModuleContext) -> None:
            self.ctx = ctx

        def visit_Try(self, node: ast.Try) -> None:
            for handler in node.handlers:
                reason = classify_handler(handler)
                if reason is None:
                    continue
                lines = self.ctx.lines or []
                if handler_contains_suppression(
                    handler, lines, SILENT_HANDLER_SUPPRESSION
                ):
                    continue
                records.append((self.ctx.rel_path, handler.lineno, reason))
            self.generic_visit(node)

    for ctx in iter_module_contexts((ROOT / "src",), include_lines=True):
        if ctx.path.name == "__init__.py":
            continue
        SilentHandlerVisitor(ctx).visit(ctx.tree)
    return records


def collect_generic_raises() -> List[Tuple[str, int]]:
    records: List[Tuple[str, int]] = []

    class GenericRaiseVisitor(ast.NodeVisitor):
        def __init__(self, rel_path: str) -> None:
            self.rel_path = rel_path

        def visit_Raise(self, node: ast.Raise) -> None:
            exc = node.exc
            if exc is None:
                return
            if isinstance(exc, ast.Name) and exc.id in BROAD_EXCEPTION_NAMES:
                records.append((self.rel_path, node.lineno))
            elif (
                isinstance(exc, ast.Call)
                and isinstance(exc.func, ast.Name)
                and exc.func.id in BROAD_EXCEPTION_NAMES
            ):
                records.append((self.rel_path, node.lineno))
            self.generic_visit(node)

    for ctx in iter_module_contexts((ROOT / "src",)):
        if ctx.path.name == "__init__.py":
            continue
        GenericRaiseVisitor(ctx.rel_path).visit(ctx.tree)
    return records


def collect_literal_fallbacks() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []

    class LiteralFallbackVisitor(ast.NodeVisitor):
        def __init__(self, rel_path: str) -> None:
            self.rel_path = rel_path

        def visit_Call(self, node: ast.Call) -> None:
            self._check_get_method(node)
            self._check_getattr(node)
            self._check_os_getenv(node)
            self._check_setdefault(node)
            self.generic_visit(node)

        def _check_get_method(self, node: ast.Call) -> None:
            qualname = get_call_qualname(node.func) or ""
            if not qualname.endswith(".get"):
                return
            default_arg = _resolve_default_argument(
                node,
                positional_index=1,
                keyword_names={"default", "fallback"},
            )
            self._maybe_record(node, default_arg, f"{qualname} literal fallback")

        def _check_getattr(self, node: ast.Call) -> None:
            qualname = get_call_qualname(node.func) or ""
            if qualname == "getattr" and len(node.args) >= 3:
                self._maybe_record(node, node.args[2], "getattr literal fallback")

        def _check_os_getenv(self, node: ast.Call) -> None:
            qualname = get_call_qualname(node.func) or ""
            if qualname not in {"os.getenv", "os.environ.get"}:
                return
            default_arg = _resolve_default_argument(
                node,
                positional_index=1,
                keyword_names={"default"},
            )
            self._maybe_record(node, default_arg, f"{qualname} literal fallback")

        def _check_setdefault(self, node: ast.Call) -> None:
            qualname = get_call_qualname(node.func) or ""
            if qualname.endswith(".setdefault") and len(node.args) >= 2:
                self._maybe_record(node, node.args[1], f"{qualname} literal fallback")

        def _maybe_record(
            self,
            node: ast.Call,
            default_arg: ast.AST | None,
            message: str,
        ) -> None:
            if is_non_none_literal(default_arg):
                records.append((self.rel_path, node.lineno, message))

    for ctx in iter_module_contexts():
        if ctx.rel_path.startswith(("scripts/", "ci_runtime/", "vendor/")):
            continue
        LiteralFallbackVisitor(ctx.rel_path).visit(ctx.tree)
    return records


def collect_bool_fallbacks() -> List[Tuple[str, int]]:
    records: List[Tuple[str, int]] = []

    class BoolFallbackVisitor(ast.NodeVisitor):
        def __init__(self, rel_path: str) -> None:
            self.rel_path = rel_path

        def visit_BoolOp(self, node: ast.BoolOp) -> None:
            if isinstance(node.op, ast.Or):
                if any(is_non_none_literal(value) for value in node.values[1:]):
                    records.append((self.rel_path, node.lineno))
            self.generic_visit(node)

        def visit_IfExp(self, node: ast.IfExp) -> None:
            if is_non_none_literal(node.body) or is_non_none_literal(node.orelse):
                records.append((self.rel_path, node.lineno))
            self.generic_visit(node)

    for ctx in iter_module_contexts():
        if ctx.rel_path.startswith(("scripts/", "ci_runtime/", "vendor/")):
            continue
        BoolFallbackVisitor(ctx.rel_path).visit(ctx.tree)
    return records


def collect_conditional_literal_returns() -> List[Tuple[str, int]]:
    records: List[Tuple[str, int]] = []

    class ConditionalLiteralVisitor(ast.NodeVisitor):
        def __init__(self, rel_path: str) -> None:
            self.rel_path = rel_path

        def visit_If(self, node: ast.If) -> None:
            if is_literal_none_guard(node.test):
                for stmt in node.body:
                    if isinstance(stmt, ast.Return) and is_non_none_literal(stmt.value):
                        records.append((self.rel_path, stmt.lineno))
            self.generic_visit(node)

    for ctx in iter_module_contexts():
        if ctx.rel_path.startswith(("scripts/", "ci_runtime/", "vendor/")):
            continue
        ConditionalLiteralVisitor(ctx.rel_path).visit(ctx.tree)
    return records


def collect_backward_compat_blocks() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []

    class LegacyVisitor(ast.NodeVisitor):
        def __init__(self, ctx: ModuleContext) -> None:
            self.ctx = ctx

        def visit_If(self, node: ast.If) -> None:
            if self.ctx.source is None:
                return
            segment = ast.get_source_segment(self.ctx.source, node) or ""
            lowered = segment.lower()
            if any(token in lowered for token in LEGACY_GUARD_TOKENS):
                records.append(
                    (self.ctx.rel_path, node.lineno, "conditional legacy guard")
                )
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            attr_name = node.attr.lower()
            if attr_name.endswith(LEGACY_SUFFIXES):
                records.append(
                    (self.ctx.rel_path, node.lineno, "legacy attribute access")
                )
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            name_id = node.id.lower()
            if name_id.endswith(LEGACY_SUFFIXES):
                records.append(
                    (
                        self.ctx.rel_path,
                        getattr(node, "lineno", 0),
                        "legacy symbol reference",
                    )
                )

    for ctx in iter_module_contexts(include_source=True):
        if ctx.rel_path.startswith(("scripts/", "ci_runtime/", "vendor/")):
            continue
        LegacyVisitor(ctx).visit(ctx.tree)
    return records


def collect_forbidden_sync_calls() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []

    class SyncCallVisitor(ast.NodeVisitor):
        def __init__(self, rel_path: str) -> None:
            self.rel_path = rel_path

        def visit_Call(self, node: ast.Call) -> None:
            qualname = get_call_qualname(node.func)
            if not qualname:
                self.generic_visit(node)
                return
            for pattern in FORBIDDEN_SYNC_CALLS:
                if qualname == pattern or qualname.startswith(f"{pattern}."):
                    records.append(
                        (
                            self.rel_path,
                            node.lineno,
                            f"forbidden synchronous call '{qualname}'",
                        )
                    )
                    break
            self.generic_visit(node)

    for ctx in iter_module_contexts((ROOT / "src",)):
        SyncCallVisitor(ctx.rel_path).visit(ctx.tree)
    return records


def _function_entries_from_context(
    ctx: ModuleContext,
    *,
    min_length: int,
) -> Iterator[Tuple[str, FunctionEntry]]:
    for node in ast.walk(ctx.tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not (node.end_lineno and node.lineno):
            continue
        length = node.end_lineno - node.lineno + 1
        if length < min_length:
            continue
        key = normalize_function(node)
        entry = FunctionEntry(
            path=ctx.path,
            name=node.name,
            lineno=node.lineno,
            length=length,
        )
        yield key, entry


def _build_duplicate_mapping(min_length: int) -> Dict[str, List[FunctionEntry]]:
    mapping: Dict[str, List[FunctionEntry]] = defaultdict(list)
    for ctx in iter_module_contexts():
        if ctx.rel_path.startswith(("scripts/", "ci_runtime/", "vendor/")):
            continue
        if ctx.path.name == "__init__.py":
            continue
        for key, entry in _function_entries_from_context(ctx, min_length=min_length):
            mapping[key].append(entry)
    return mapping


def _filter_duplicate_entries(
    mapping: Dict[str, List[FunctionEntry]],
) -> List[List[FunctionEntry]]:
    duplicates: List[List[FunctionEntry]] = []
    for entries in mapping.values():
        unique_paths = {normalize_path(entry.path) for entry in entries}
        if len(entries) > 1 and len(unique_paths) > 1:
            duplicates.append(entries)
    return duplicates


def collect_duplicate_functions(min_length: int = 6) -> List[List[FunctionEntry]]:
    mapping = _build_duplicate_mapping(min_length)
    return _filter_duplicate_entries(mapping)


def collect_bytecode_artifacts() -> List[str]:
    offenders: List[str] = []
    for path in ROOT.rglob("*.pyc"):
        offenders.append(normalize_path(path))
    for path in ROOT.rglob("__pycache__"):
        offenders.append(normalize_path(path))
    return sorted(set(offenders))


def purge_bytecode_artifacts() -> None:
    for path in ROOT.rglob("*.pyc"):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
    for path in ROOT.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "collect_long_functions",
    "collect_broad_excepts",
    "collect_silent_handlers",
    "collect_generic_raises",
    "collect_literal_fallbacks",
    "collect_bool_fallbacks",
    "collect_conditional_literal_returns",
    "collect_backward_compat_blocks",
    "collect_forbidden_sync_calls",
    "collect_duplicate_functions",
    "collect_bytecode_artifacts",
    "purge_bytecode_artifacts",
]
