# Repository Guidelines

## Project Structure & Module Organization
- `ci_tools/` – packaged Python modules for guard runners, automation helpers, and reusable scripts consumed by Zeus/Kalshi.
- `scripts/` – repo-specific utilities (e.g., `sync_project_configs.py`, `complexity_guard.py`) that are not shipped with the package.
- `ci_shared.mk` & `shared-tool-config.toml` – canonical CI targets and shared lint/test configuration synced into consuming repos.
- `tests/` – pytest suite covering guard behavior, config parsing, and helper utilities.
- `docs/` – operational guides (guard suite, automation, onboarding) plus security references.

## Build, Test, and Development Commands
- `make check` – runs the full shared CI pipeline via `ci_shared.mk` (formatters, lint, guards, tests, coverage, security scans).
- `python -m ci_tools.ci --model gpt-5-codex` – launches the Codex automation loop for CI repair tasks.
- `python scripts/sync_project_configs.py ~/zeus ~/aws ~/kalshi` – distributes synced config files into consuming repositories after updates.

## Coding Style & Naming Conventions
- Python 3.10+, PEP 8 with four-space indentation; format via `black` and import order enforced by `isort --profile black`.
- Linting stack: `ruff`, `pylint`, `pyright`, `bandit`, and guard scripts under `ci_tools/scripts/`.
- Use descriptive snake_case for modules/functions, PascalCase for classes; keep public APIs stable since consuming repos import these helpers.

## Testing Guidelines
- Tests live under `tests/` mirroring module structure; naming: `test_<module>.py` with pytest functions/classes prefixed `test_`.
- Run `pytest -n 7 tests/ --cov=ci_tools --cov-fail-under=80` (invoked automatically via `make check`).
- Use fixtures from `tests/conftest.py` for guard config/state; add regression tests alongside new guard scripts or config loaders.

## Commit & Pull Request Guidelines
- Follow existing history: imperative, descriptive summaries like `Improve policy guard messaging` or `Fix coverage guard path handling`.
- Include context in body (motivation, guard configs touched) and link issue references when applicable.
- Before opening a PR, run `make check` locally, attach relevant command output snippets, and call out any skipped guards, migrations, or manual follow-ups.

## Security & Configuration Tips
- Never commit secrets; `gitleaks` and `codespell` run automatically—add safe patterns to `ci_tools/config/*` if needed.
- Repository context for automation agents belongs in `ci_shared.config.json`; avoid duplicating secrets or protected paths elsewhere.
- When adding new guard scripts, document usage in `docs/guard-suite.md` and expose knobs via `shared-tool-config.toml` so consuming repos inherit them automatically.

## CI Pipeline Enforcement - Non-Negotiable Rules

Agents working in this repository must pass all CI checks by fixing code, not by bypassing checks.

### Prohibited Actions
1. Adding ignore/suppression directives (`# noqa`, `# pylint: disable`, `# type: ignore`, `policy_guard: allow-*`)
2. Modifying CI pipeline configuration to skip tests or weaken checks
3. Editing guard scripts to relax enforcement thresholds
4. Adding entries to ignore lists, allowlists, or exclusion files to bypass failures
5. Disabling, skipping, or commenting out failing tests

### Required Actions
1. Fix the root cause in the code
2. Refactor to meet architectural constraints (complexity, size, structure)
3. Correct type errors with proper type annotations
4. Improve code quality to satisfy linting rules
5. Increase test coverage by writing additional tests
6. Ask for human guidance when the correct fix approach is ambiguous

### Enforcement Examples

| CI Failure | ❌ Wrong Approach | ✅ Correct Approach |
|------------|------------------|---------------------|
| Too many arguments (>7) | Add `# pylint: disable` | Refactor to use dataclass/config object |
| Type error | Add `# type: ignore` | Fix the type annotation or refactor |
| Hardcoded secret detected | Add to `.gitleaks.toml` | Move to environment variable/config |
| Broad exception handler | Add `policy_guard: allow-broad-except` | Catch specific exception types |
| Coverage below 80% | Lower threshold in config | Write tests for uncovered code |
| Function too complex | Add complexity ignore | Extract smaller functions |
| Class too large (>100 lines) | Increase structure guard limit | Split into multiple classes |

If fixing a CI failure requires architectural changes and you're uncertain about the approach, stop and request human guidance before proceeding.

## CI Rules & Guard Contract
`ci_tools/scripts/ci.sh` (invoked by `make check`) enforces the rules below before any code lands. Treat them as non-negotiable when proposing changes or running automation.

### Formatting, Naming, and Layout
- Target Python 3.10+ with four-space indentation; modules/functions use `snake_case`, classes use `PascalCase`, and public APIs must stay backward compatible for downstream consumers.
- Keep `FORMAT_TARGETS=ci_tools scripts`; always run `isort --profile black` followed by `black` over those targets (tests are included automatically via the Makefile).
- Tests belong under `tests/test_<module>.py` with pytest objects prefixed `test_`; shared pytest defaults live in `shared-tool-config.toml` (`-q --tb=short PYTHONPATH=["."]`).

### Static Analysis Pipeline (exact order)
- `codespell` skips `.git`, `artifacts`, `trash`, `models`, `logs`, `htmlcov`, `*.json`, `*.csv`; extend `ci_tools/config/codespell_ignore_words.txt` for repo-specific vocabulary.
- `vulture $(FORMAT_TARGETS) --min-confidence 80` blocks unused code (≥80% confidence).
- `deptry --config pyproject.toml .` keeps the dependency graph honest.
- `gitleaks` scans `ci_tools`, `ci_tools_proxy`, `scripts`, `tests`, `docs`, `shared-tool-config.toml`, `pyproject.toml`, `Makefile`, `README.md`, `SECURITY.md`, etc.—update `.gitleaks.toml`/`ci_tools/config/*` for safe strings.
- `python -m ci_tools.scripts.bandit_wrapper -c pyproject.toml -r $(FORMAT_TARGETS) -q --exclude $(BANDIT_EXCLUDE)` handles the security lint.
- `python -m safety scan --json --cache tail` runs locally (CI_AUTOMATION skips it) to detect vulnerable dependencies.
- `ruff check --target-version=py310 --fix $(FORMAT_TARGETS) tests` enforces TRY, C90 (McCabe ≤10), PLR, and the rest of the shared lint stack.
- `pyright --warnings ci_tools` treats warnings as failures.
- `pylint -j 7 ci_tools` runs with Ruff’s strict profile (max args 7, branches 10, statements 50).

### Tests, Coverage, and Bytecode
- Run `pytest -n 7 tests/ --cov=ci_tools --cov-fail-under=80`; the same threshold is enforced by `python -m ci_tools.scripts.coverage_guard --threshold 80 --data-file .coverage`.
- `python -m compileall ci_tools tests scripts` executes last to catch syntax errors without executing code paths.

### Guard Thresholds
- `policy_guard` / `data_guard` / `documentation_guard`: defaults plus repo allowlists in `ci_tools/config/*`.
- `structure_guard --root ci_tools` keeps every class ≤100 lines.
- `complexity_guard --root ci_tools --max-cyclomatic 10 --max-cognitive 15`.
- `module_guard --root ci_tools --max-module-lines 400`.
- `function_size_guard --root ci_tools --max-function-lines 80`.
- `inheritance_guard --max-depth 2`, `method_count_guard` (≤15 public / ≤25 total methods).
- `dependency_guard --max-instantiations 5` inside `__init__` / `__post_init__`.
- `unused_module_guard --strict` blocks orphans and suspicious suffixes (`_refactored`, `_slim`, `_optimized`, `_old`, `_backup`, `_copy`, `_new`, `_temp`, `_v2`, `_2`); remove or legitimize those files.
- `documentation_guard` expects README.md, CLAUDE.md, docs/README.md, per-package READMEs, and the docs/* hierarchy described below.

### Policy Guard Rules (Highlights)
- Banned keywords/tokens anywhere: `legacy`, `fallback`, `default`, `catch_all`, `failover`, `backup`, `compat`, `backwards`, `deprecated`, `legacy_mode`, `old_api`, `legacy_flag`, plus TODO/FIXME/HACK/WORKAROUND strings. The only allowed suppressions are `policy_guard: allow-broad-except` and `policy_guard: allow-silent-handler`.
- Exception handling must never use bare `except` or catch `Exception/BaseException`; handlers have to re-raise instead of logging and continuing, and you cannot raise `Exception/BaseException` directly.
- Functions ≥80 lines trip `function_size_guard` first, but the policy guard still tracks the legacy 150-line cap and bans duplicate functions ≥6 lines across files.
- Literal fallbacks/defaults are disallowed in `.get`, `.setdefault`, `getattr`, `os.getenv`, ternaries, or `if x is None` blocks when the fallback is a literal. Forbidden synchronous calls (inside `ci_tools`): `time.sleep`, `subprocess.*`, `requests.*`.
- No `_legacy`, `_compat`, `_deprecated`, `legacy/`, or similar directories/files; config files cannot contain those tokens either. `.pyc` or `__pycache__` remnants fail CI.

### Data Guard
- Assigning or comparing numeric literals (except -1/0/1) to names containing `threshold`, `limit`, `timeout`, `default`, `max`, `min`, `retry`, `window`, `size`, `count`, etc., is blocked unless allowlisted in `config/data_guard_allowlist.json`.
- Creating pandas or numpy objects with literal datasets is forbidden unless allowlisted under the `["dataframe"]` section; only UPPER_SNAKE_CASE constants are exempt.

### Documentation Guard
- `README.md` and `CLAUDE.md` are mandatory. If `docs/` exists, `docs/README.md` must exist as well.
- Every top-level package containing `.py` files (e.g., `ci_tools/`, `ci_tools_proxy/`) needs its own `README.md`.
- Additional required READMEs: `docs/architecture/`, every `docs/domains/*/`, `docs/reference/*/`, and `docs/operations/` folders once they contain Markdown content.

### Miscellaneous Expectations
- Secrets are never allowed; rely on `.gitleaks.toml` or the shared ignore lists for sanctioned strings.
- The Makefile wipes `*.pyc` and `__pycache__` under `ci_tools`, `scripts`, `tests`, `docs`, and `ci_tools_proxy` every run—do not depend on bytecode.
- Guards (`policy_guard`, `data_guard`, `structure_guard`, `complexity_guard`, `module_guard`, `function_size_guard`, `inheritance_guard`, `method_count_guard`, `dependency_guard`, `unused_module_guard --strict`, `documentation_guard`) all run *before* tests; fix guard failures first.
- Repository/automation metadata belongs exclusively in `ci_shared.config.json`; never duplicate secrets or protected paths elsewhere.
