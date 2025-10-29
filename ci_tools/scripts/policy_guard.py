#!/usr/bin/env python3
"""
Enforce Zeus code policy by checking for banned keywords, oversized functions,
and fail-fast violations (broad exception handlers and generic Exception raises).
"""

from __future__ import annotations

import ast
import copy
import io
import shutil
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence, Tuple

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
SUPPRESSION_PATTERNS: Tuple[str, ...] = ("# noqa", "pylint: disable")
FORBIDDEN_SYNC_CALLS: Tuple[str, ...] = (
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
LEGACY_GUARD_TOKENS: Tuple[str, ...] = ("legacy", "compat", "deprecated")
LEGACY_SUFFIXES: Tuple[str, ...] = ("_legacy", "_compat", "_deprecated")
LEGACY_CONFIG_TOKENS: Tuple[str, ...] = (
    "legacy",
    "compat",
    "deprecated",
    "legacy_mode",
    "old_api",
    "legacy_flag",
)
CONFIG_EXTENSIONS: Tuple[str, ...] = (".json", ".toml", ".yaml", ".yml", ".ini")


@dataclass(frozen=True)
class FunctionEntry:
    path: Path
    name: str
    lineno: int
    length: int


class FunctionNormalizer(ast.NodeTransformer):
    def visit_Name(self, node: ast.Name) -> ast.AST:
        ctx = node.ctx.__class__()
        new_node = ast.Name(id="var", ctx=ctx)
        return ast.copy_location(new_node, node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        annotation = self.visit(node.annotation) if node.annotation else None
        new_node = ast.arg(arg="arg", annotation=annotation)
        return ast.copy_location(new_node, node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
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


class PolicyViolation(Exception):
    """Raised when the policy guard detects a violation."""


def normalize_path(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def iter_python_files(bases: Sequence[Path]) -> Iterator[Path]:
    for base in bases:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            yield path


def parse_ast(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text())
    except Exception:
        return None


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


def get_call_qualname(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = get_call_qualname(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


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


def scan_keywords() -> Dict[str, Dict[str, List[int]]]:
    found: Dict[str, Dict[str, List[int]]] = {kw: {} for kw in BANNED_KEYWORDS}
    for path in iter_python_files(SCAN_DIRECTORIES):
        try:
            source = path.read_text()
        except UnicodeDecodeError:
            continue
        rel_path = normalize_path(path)
        keyword_hits: Dict[str, set[int]] = {kw: set() for kw in BANNED_KEYWORDS}
        try:
            tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        except tokenize.TokenError:
            continue
        for token in tokens:
            if token.type != tokenize.NAME:
                continue
            token_lower = token.string.lower()
            for keyword in BANNED_KEYWORDS:
                if token_lower == keyword:
                    keyword_hits[keyword].add(token.start[0])
        for keyword, lines in keyword_hits.items():
            if lines:
                found[keyword][rel_path] = sorted(lines)
    return found


def collect_flagged_tokens() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []
    for path in iter_python_files(SCAN_DIRECTORIES):
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        rel_path = normalize_path(path)
        for lineno, line in enumerate(lines, start=1):
            for token in FLAGGED_TOKENS:
                if token in line:
                    records.append((rel_path, lineno, token))
    return records


def enforce_keywords(found: Dict[str, Dict[str, List[int]]]) -> None:
    violations: List[str] = []

    for keyword, files in found.items():
        for path, lines in files.items():
            for lineno in lines:
                violations.append(f"{path}:{lineno} -> keyword '{keyword}'")

    if violations:
        raise PolicyViolation(
            "Banned keyword policy violations detected:\n"
            + "\n".join(sorted(violations))
        )


def collect_long_functions(threshold: int) -> Iterable[FunctionEntry]:
    src_root = ROOT / "src"
    for path in iter_python_files((src_root,)):
        if path.name == "__init__.py":
            continue
        tree = parse_ast(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno and node.lineno:
                    length = node.end_lineno - node.lineno + 1
                    if length > threshold:
                        yield FunctionEntry(
                            path=path,
                            name=node.name,
                            lineno=node.lineno,
                            length=length,
                        )


def enforce_function_lengths(
    found: Iterable[FunctionEntry], threshold: int = FUNCTION_LENGTH_THRESHOLD
) -> None:
    violations: List[str] = []

    for entry in found:
        rel_path = normalize_path(entry.path)
        violations.append(
            f"{rel_path}:{entry.lineno} -> function '{entry.name}' length {entry.length} exceeds {threshold}"
        )

    if violations:
        raise PolicyViolation(
            "Function length policy violations detected:\n"
            + "\n".join(sorted(violations))
        )


def collect_broad_excepts() -> List[Tuple[str, int]]:
    records: List[Tuple[str, int]] = []
    src_root = ROOT / "src"
    for path in iter_python_files((src_root,)):
        if path.name == "__init__.py":
            continue
        tree = parse_ast(path)
        if tree is None:
            continue
        rel_path = normalize_path(path)
        lines: List[str] = path.read_text().splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    record = False
                    if handler.type is None:
                        record = True
                    elif isinstance(handler.type, ast.Name) and handler.type.id in {
                        "Exception",
                        "BaseException",
                    }:
                        record = True
                    elif isinstance(handler.type, ast.Tuple):
                        for elt in handler.type.elts:
                            if isinstance(elt, ast.Name) and elt.id in {
                                "Exception",
                                "BaseException",
                            }:
                                record = True
                                break
                    if record:
                        # Allow explicitly documented broad handlers.
                        if handler_contains_suppression(handler, lines, BROAD_EXCEPT_SUPPRESSION):
                            continue
                        records.append((rel_path, handler.lineno))
    return records


def handler_contains_suppression(
    handler: ast.ExceptHandler, lines: Sequence[str], token: str
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


def collect_silent_handlers() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []
    src_root = ROOT / "src"
    for path in iter_python_files((src_root,)):
        if path.name == "__init__.py":
            continue
        tree = parse_ast(path)
        if tree is None:
            continue
        rel_path = normalize_path(path)
        lines: List[str] = path.read_text().splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    reason = classify_handler(handler)
                    if reason is not None:
                        if handler_contains_suppression(handler, lines, SILENT_HANDLER_SUPPRESSION):
                            continue
                        records.append((rel_path, handler.lineno, reason))
    return records


def collect_generic_raises() -> List[Tuple[str, int]]:
    records: List[Tuple[str, int]] = []
    src_root = ROOT / "src"
    for path in iter_python_files((src_root,)):
        if path.name == "__init__.py":
            continue
        tree = parse_ast(path)
        if tree is None:
            continue
        rel_path = normalize_path(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and node.exc is not None:
                exc = node.exc
                record = False
                if isinstance(exc, ast.Name) and exc.id in {
                    "Exception",
                    "BaseException",
                }:
                    record = True
                elif (
                    isinstance(exc, ast.Call)
                    and isinstance(exc.func, ast.Name)
                    and exc.func.id in {"Exception", "BaseException"}
                ):
                    record = True
                if record:
                    records.append((rel_path, node.lineno))
    return records


def collect_suppressions() -> List[Tuple[str, int, str]]:
    suppressions: List[Tuple[str, int, str]] = []
    for base in SCAN_DIRECTORIES:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            try:
                lines = path.read_text().splitlines()
            except UnicodeDecodeError:
                continue
            rel_path = normalize_path(path)
            for lineno, line in enumerate(lines, start=1):
                for token in SUPPRESSION_PATTERNS:
                    if token in line:
                        suppressions.append((rel_path, lineno, token))
    return suppressions


def collect_literal_fallbacks() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []
    for path in iter_python_files(SCAN_DIRECTORIES):
        tree = parse_ast(path)
        if tree is None:
            continue
        rel_path = normalize_path(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                qualname = get_call_qualname(node.func) or ""
                if qualname.endswith(".get"):
                    default_arg = None
                    if len(node.args) >= 2:
                        default_arg = node.args[1]
                    else:
                        for kw in node.keywords:
                            if kw.arg in {"default", "fallback"}:
                                default_arg = kw.value
                                break
                    if is_non_none_literal(default_arg):
                        records.append(
                            (rel_path, node.lineno, f"{qualname} literal fallback")
                        )
                        continue
                if (
                    qualname == "getattr"
                    and len(node.args) >= 3
                    and is_non_none_literal(node.args[2])
                ):
                    records.append((rel_path, node.lineno, "getattr literal fallback"))
                    continue
                if qualname in {"os.getenv", "os.environ.get"}:
                    default_arg = None
                    if len(node.args) >= 2:
                        default_arg = node.args[1]
                    else:
                        for kw in node.keywords:
                            if kw.arg == "default":
                                default_arg = kw.value
                                break
                    if is_non_none_literal(default_arg):
                        records.append(
                            (rel_path, node.lineno, f"{qualname} literal fallback")
                        )
                        continue
                if (
                    qualname.endswith(".setdefault")
                    and len(node.args) >= 2
                    and is_non_none_literal(node.args[1])
                ):
                    records.append(
                        (rel_path, node.lineno, f"{qualname} literal fallback")
                    )
    return records


def collect_bool_fallbacks() -> List[Tuple[str, int]]:
    records: List[Tuple[str, int]] = []
    for path in iter_python_files(SCAN_DIRECTORIES):
        tree = parse_ast(path)
        if tree is None:
            continue
        rel_path = normalize_path(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                for value in node.values[1:]:
                    if is_non_none_literal(value):
                        records.append((rel_path, node.lineno))
                        break
            if isinstance(node, ast.IfExp):
                if is_non_none_literal(node.body) or is_non_none_literal(node.orelse):
                    records.append((rel_path, node.lineno))
    return records


def collect_conditional_literal_returns() -> List[Tuple[str, int]]:
    records: List[Tuple[str, int]] = []
    for path in iter_python_files(SCAN_DIRECTORIES):
        tree = parse_ast(path)
        if tree is None:
            continue
        rel_path = normalize_path(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                if is_literal_none_guard(node.test):
                    for stmt in node.body:
                        if isinstance(stmt, ast.Return) and is_non_none_literal(
                            stmt.value
                        ):
                            records.append((rel_path, stmt.lineno))
    return records


def collect_backward_compat_blocks() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []
    for path in iter_python_files(SCAN_DIRECTORIES):
        tree = parse_ast(path)
        if tree is None:
            continue
        rel_path = normalize_path(path)
        source_text = path.read_text()
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                segment = ast.get_source_segment(source_text, node) or ""
                lowered = segment.lower()
                if any(token in lowered for token in LEGACY_GUARD_TOKENS):
                    records.append((rel_path, node.lineno, "conditional legacy guard"))
            if isinstance(node, ast.Attribute):
                attr_name = node.attr.lower()
                if attr_name.endswith(LEGACY_SUFFIXES):
                    records.append((rel_path, node.lineno, "legacy attribute access"))
            if isinstance(node, ast.Name):
                name_id = node.id.lower()
                if name_id.endswith(LEGACY_SUFFIXES):
                    records.append(
                        (
                            rel_path,
                            getattr(node, "lineno", 0),
                            "legacy symbol reference",
                        )
                    )
    return records


def collect_legacy_modules() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []
    forbidden_suffixes = tuple(f"{suffix}.py" for suffix in LEGACY_SUFFIXES)
    dir_tokens = tuple(token.strip("_") for token in LEGACY_SUFFIXES)
    forbidden_parts = tuple(f"/{token}/" for token in dir_tokens) + tuple(
        f"\\{token}\\" for token in dir_tokens
    )
    for path in iter_python_files(SCAN_DIRECTORIES):
        rel_path = normalize_path(path)
        lowered = rel_path.lower()
        if any(suffix in lowered for suffix in forbidden_suffixes) or any(
            part in lowered for part in forbidden_parts
        ):
            records.append((rel_path, 1, "legacy module path"))
    return records


def collect_legacy_configs() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []
    config_root = ROOT / "config"
    if not config_root.exists():
        return records
    for path in config_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in CONFIG_EXTENSIONS:
            continue
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        rel_path = normalize_path(path)
        for lineno, line in enumerate(lines, start=1):
            lower = line.lower()
            if any(token in lower for token in LEGACY_CONFIG_TOKENS):
                records.append((rel_path, lineno, "legacy toggle in config"))
    return records


def collect_forbidden_sync_calls() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []
    for path in iter_python_files((ROOT / "src",)):
        tree = parse_ast(path)
        if tree is None:
            continue
        rel_path = normalize_path(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                qualname = get_call_qualname(node.func)
                if not qualname:
                    continue
                for pattern in FORBIDDEN_SYNC_CALLS:
                    if qualname == pattern or qualname.startswith(f"{pattern}."):
                        records.append(
                            (
                                rel_path,
                                node.lineno,
                                f"forbidden synchronous call '{qualname}'",
                            )
                        )
                        break
    return records


def collect_duplicate_functions(min_length: int = 6) -> List[List[FunctionEntry]]:
    mapping: Dict[str, List[FunctionEntry]] = {}
    for path in iter_python_files(SCAN_DIRECTORIES):
        if path.name == "__init__.py":
            continue
        tree = parse_ast(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno and node.lineno:
                    length = node.end_lineno - node.lineno + 1
                    if length < min_length:
                        continue
                else:
                    continue
                key = normalize_function(node)
                entry = FunctionEntry(
                    path=path,
                    name=node.name,
                    lineno=node.lineno,
                    length=length,
                )
                mapping.setdefault(key, []).append(entry)

    duplicates: List[List[FunctionEntry]] = []
    for entries in mapping.values():
        unique_paths = {normalize_path(entry.path) for entry in entries}
        if len(entries) > 1 and len(unique_paths) > 1:
            duplicates.append(entries)
    return duplicates


def enforce_occurrences(discovered: List[Tuple[str, int]], message: str) -> None:
    if not discovered:
        return

    violations = [f"{path}:{lineno} -> {message}" for path, lineno in discovered]
    raise PolicyViolation(
        "Policy violations detected:\n" + "\n".join(sorted(violations))
    )


def enforce_duplicate_functions(duplicates: List[List[FunctionEntry]]) -> None:
    if not duplicates:
        return
    messages: List[str] = []
    for group in duplicates:
        details = ", ".join(
            f"{normalize_path(entry.path)}:{entry.lineno} ({entry.name})"
            for entry in sorted(
                group, key=lambda item: (normalize_path(item.path), item.lineno)
            )
        )
        messages.append(f"Duplicate function implementations detected: {details}")
    raise PolicyViolation(
        "Duplicate helper policy violations detected:\n" + "\n".join(messages)
    )


def collect_bytecode_artifacts() -> List[str]:
    offenders: List[str] = []
    for path in ROOT.rglob("*.pyc"):
        offenders.append(normalize_path(path))
    for path in ROOT.rglob("__pycache__"):
        offenders.append(normalize_path(path))
    return sorted(set(offenders))


def purge_bytecode_artifacts() -> None:
    """Delete transient bytecode outputs so they never fail policy checks."""

    for path in ROOT.rglob("*.pyc"):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
    for path in ROOT.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def main() -> int:
    purge_bytecode_artifacts()

    keyword_hits = scan_keywords()
    enforce_keywords(keyword_hits)

    flagged_tokens = collect_flagged_tokens()
    if flagged_tokens:
        details = "\n".join(
            f"{path}:{lineno} -> flagged token '{token}' detected"
            for path, lineno, token in sorted(flagged_tokens)
        )
        raise PolicyViolation("Flagged annotations detected:\n" + details)

    long_functions = list(collect_long_functions(FUNCTION_LENGTH_THRESHOLD))
    enforce_function_lengths(long_functions)

    broad_excepts = collect_broad_excepts()
    enforce_occurrences(broad_excepts, "broad exception handler")

    silent_handlers = collect_silent_handlers()
    if silent_handlers:
        details = "\n".join(
            f"{path}:{lineno} -> {reason}"
            for path, lineno, reason in sorted(silent_handlers)
        )
        raise PolicyViolation("Silent exception handler detected:\n" + details)

    generic_raises = collect_generic_raises()
    enforce_occurrences(generic_raises, "generic Exception raise")

    literal_fallbacks = collect_literal_fallbacks()
    if literal_fallbacks:
        details = "\n".join(
            f"{path}:{lineno} -> {reason}"
            for path, lineno, reason in sorted(literal_fallbacks)
        )
        raise PolicyViolation("Fallback default usage detected:\n" + details)

    bool_fallbacks = collect_bool_fallbacks()
    enforce_occurrences(bool_fallbacks, "literal fallback via boolean 'or'")

    conditional_literals = collect_conditional_literal_returns()
    enforce_occurrences(conditional_literals, "literal return inside None guard")

    backward_compat = collect_backward_compat_blocks()
    if backward_compat:
        details = "\n".join(
            f"{path}:{lineno} -> {reason}"
            for path, lineno, reason in sorted(backward_compat)
        )
        raise PolicyViolation("Backward compatibility code detected:\n" + details)

    legacy_modules = collect_legacy_modules()
    if legacy_modules:
        details = "\n".join(
            f"{path}:{lineno} -> {reason}"
            for path, lineno, reason in sorted(legacy_modules)
        )
        raise PolicyViolation("Legacy module paths detected:\n" + details)

    legacy_configs = collect_legacy_configs()
    if legacy_configs:
        details = "\n".join(
            f"{path}:{lineno} -> {reason}"
            for path, lineno, reason in sorted(legacy_configs)
        )
        raise PolicyViolation("Legacy config toggles detected:\n" + details)

    forbidden_sync = collect_forbidden_sync_calls()
    if forbidden_sync:
        details = "\n".join(
            f"{path}:{lineno} -> {reason}"
            for path, lineno, reason in sorted(forbidden_sync)
        )
        raise PolicyViolation(
            "Synchronous call policy violations detected:\n" + details
        )

    suppressions = collect_suppressions()
    if suppressions:
        details = "\n".join(
            f"{path}:{lineno} -> suppression token '{token}' detected"
            for path, lineno, token in sorted(suppressions)
        )
        raise PolicyViolation("Suppression policy violations detected:\n" + details)

    duplicates = collect_duplicate_functions()
    enforce_duplicate_functions(duplicates)

    bytecode_artifacts = collect_bytecode_artifacts()
    if bytecode_artifacts:
        details = "\n".join(
            f"{path} -> compiled artifact committed" for path in bytecode_artifacts
        )
        raise PolicyViolation("Compiled Python artifacts detected:\n" + details)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PolicyViolation as err:
        print(err, file=sys.stderr)
        sys.exit(1)
