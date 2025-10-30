# Guard Suite

codex-ci-tools ships a collection of guard scripts designed to enforce
consistency and code quality across repositories. Each guard is a standalone
module that can be executed directly (`python -m ci_tools.scripts.<name>`) or
via the shared Makefile target `shared-checks` in `ci_shared.mk`.

## Guard Overview

| Script | Purpose | Key Options |
| ------ | ------- | ----------- |
| `policy_guard.py` | Enforces Zeus policy rules: banned keywords, TODO markers, oversized functions, broad exception handlers, and risky synchronous calls. | `--root` defaults to `src` + `tests`; use suppression tags like `policy_guard: allow-broad-except` sparingly. |
| `module_guard.py` | Flags Python modules whose line count exceeds a threshold to encourage splitting. | `--root`, `--max-module-lines` (default: 600). |
| `function_size_guard.py` | Detects functions longer than the configured limit. | `--root`, `--max-function-lines` (default: 150). |
| `coverage_guard.py` | Fails when any measured file dips below the coverage threshold using `.coverage` data. | `--threshold`, `--data-file`, `--include`. |
| `dependency_guard.py` | Caps instantiations/imports from sensitive modules to deter tight coupling. | `--root`, `--max-instantiations`, `--allow`. |
| `data_guard.py` | Protects data-handling patterns (forbids inline secrets, unsafe file usage, etc.). | `--root`, `--allow-pattern`. |
| `structure_guard.py` | Enforces directory layout, class counts, and other structural invariants. | `--root`, `--max-class-lines`, `--max-depth`. |
| `method_count_guard.py` | Limits public and total methods per class to keep APIs manageable. | `--root`, `--max-public-methods`, `--max-total-methods`, `--exclude`. |
| `inheritance_guard.py` | Rejects class hierarchies deeper than a safe maximum. | `--root`, `--max-depth`. |
| `directory_depth_guard.py` | Prevents nested package hierarchies beyond the configured depth. | `--root`, `--max-depth`. |
| `documentation_guard.py` | Ensures foundational docs exist (`README.md`, `CLAUDE.md`, per-module docs, architecture guides). | `--root`. |
| `complexity_guard.py` (`scripts/complexity_guard.py`) | Enforces cyclomatic and cognitive complexity ceilings using Radon heuristics. | `--root`, `--max-cyclomatic`, `--max-cognitive`. |

> All guards exit with non-zero status when violations are found—perfect for
> inclusion in CI pipelines.

### Related Helpers
- `ci_tools/scripts/ci.sh` – wraps `make check`, installs missing test deps, and orchestrates commit/push when automation succeeds.
- `ci_tools/scripts/xci.sh` – legacy bash interface that shells out to CI, archives Codex conversations, and requests commit messages.
- `ci_tools/scripts/generate_commit_message.py` – shared helper that asks Codex for a commit summary/body given the staged diff.

## Makefile Integration

`ci_shared.mk` bundles the guard suite with formatters, linters, and pytest:

```make
.PHONY: shared-checks
shared-checks:
	@echo "Running shared CI checks..."
	isort --profile black $(FORMAT_TARGETS)
	black $(FORMAT_TARGETS)
	python -m compileall src tests
	# …
	$(PYTHON) -m ci_tools.scripts.policy_guard
	$(PYTHON) -m ci_tools.scripts.data_guard
	$(PYTHON) -m ci_tools.scripts.structure_guard --root src --max-class-lines $(MAX_CLASS_LINES)
	$(PYTHON) ci_shared/scripts/complexity_guard.py --root src --max-cyclomatic 10 --max-cognitive 15
	# …
```

Override helper variables before including the file to tailor the pipeline:

```make
FORMAT_TARGETS := src backend tests
PYTEST_NODES := 4
MAX_CLASS_LINES := 160
include ci_shared.mk
```

## Working with Violations

1. Run the offending guard directly with verbose flags (e.g.,
   `python -m ci_tools.scripts.policy_guard --root src`)
2. Apply targeted fixes—guards do **not** support bypass comments aside from
   documented suppression tokens (policy guard only)
3. Re-run `make shared-checks` or the specific guard to confirm resolution

## Extending the Guard Suite

When adding new guards:
- Place reusable logic under `ci_tools/scripts/`
- Expose CLI entry points via `python -m ...` so the Makefile can call them
- Document thresholds and expected output in the new script’s module docstring
- Add the guard to `ci_shared.mk` if it should run for every repository
- Update [`docs/development.md`](development.md) with any extra setup steps

This approach keeps the guard suite discoverable and consistent across projects
sharing the toolkit.
