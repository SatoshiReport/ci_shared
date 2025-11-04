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
