# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is `codex-ci-tools`, a shared continuous-integration toolkit used by the Zeus and Kalshi repositories. The package bundles the Codex automation workflow (`ci_tools`) along with the `xci.sh` convenience script for automated CI repair loops.

## Installation & Setup

Install the package in editable mode from the consuming repository root:

```bash
python -m pip install -e ../ci_shared
```

This places the shared scripts on `PYTHONPATH` and the `xci.sh` wrapper on your shell `PATH`.

## Key Commands

### Running CI Automation

**Python interface (modern):**
```bash
python -m ci_tools.ci --model gpt-5-codex --reasoning-effort high
```

**Bash wrapper (legacy CLI surface):**
```bash
xci.sh [optional-ci-command]
```

Both interfaces:
- Run the CI command (defaults to `scripts/ci.sh` or `./ci.sh`)
- On failure, send logs to Codex for a patch suggestion
- Apply patches and loop until CI passes or max iterations reached
- Generate commit messages when CI succeeds

**Common options for `ci_tools.ci`:**
- `--command <cmd>`: Custom CI command (default: `./scripts/ci.sh`)
- `--max-iterations <n>`: Max fix attempts (default: 5)
- `--patch-approval-mode {prompt,auto}`: Control patch approval (default: prompt)
- `--dry-run`: Run CI once without invoking Codex
- `--auto-stage`: Run `git add -A` after CI passes
- `--commit-message`: Request commit message from Codex

### Running Individual Guard Scripts

Each guard script can be invoked directly:

```bash
python -m ci_tools.scripts.policy_guard --root src
python -m ci_tools.scripts.module_guard --root src --max-module-lines 600
python -m ci_tools.scripts.function_size_guard --root src --max-function-lines 150
python -m ci_tools.scripts.structure_guard --root src
python -m ci_tools.scripts.coverage_guard --min-coverage 80
python -m ci_tools.scripts.dependency_guard --root src
```

## Architecture

### Core Modules

**`ci_tools/ci.py`** (1400+ lines)
- Main automation loop that orchestrates CI fixes
- Calls CI command, captures failures, and requests patches from Codex
- Implements safety guards (risky pattern detection, protected paths)
- Handles coverage deficit detection and targeted file diffs
- Model requirement: `gpt-5-codex` with configurable reasoning effort

Key workflow stages:
1. **Preflight**: Validate model, reasoning effort, repository state
2. **Iteration loop**: Run CI → capture failure → request patch → apply → retry
3. **Coverage handling**: Special logic for coverage deficits below threshold
4. **Commit phase**: Auto-stage changes and generate commit messages

**`ci_tools/scripts/xci.sh`**
- Bash wrapper providing legacy CLI compatibility
- Loops on CI failures, archives Codex exchanges under `.xci/archive/`
- Enforces strict rules in prompts (no baseline files, no exemptions, fix code not tests)
- Validates patches don't modify protected CI infrastructure
- Generates detailed success/failure reports with statistics

**`ci_tools/scripts/ci.sh`**
- Shared CI shell helper used by consuming repositories
- Ensures test dependencies are installed (pytest-cov, ruff, codespell, etc.)
- Runs `make check` to execute all guards
- In non-automation mode: stages changes, requests commit message, commits and pushes

### Guard Scripts

The toolkit includes specialized guard scripts that enforce code quality policies:

- **`policy_guard.py`**: Enforces code policies (banned keywords, oversized functions, fail-fast violations, broad exception handlers)
- **`module_guard.py`**: Detects oversized Python modules that need refactoring (default: 600 lines)
- **`function_size_guard.py`**: Detects oversized functions (default: 150 lines)
- **`structure_guard.py`**: Enforces structural constraints (directory depth, class structure)
- **`coverage_guard.py`**: Ensures test coverage meets threshold (default: 80%)
- **`dependency_guard.py`**: Validates dependency usage and imports
- **`method_count_guard.py`**: Limits methods per class
- **`inheritance_guard.py`**: Enforces inheritance depth limits
- **`directory_depth_guard.py`**: Limits directory nesting depth
- **`data_guard.py`**: Validates data handling patterns
- **`documentation_guard.py`**: Ensures documentation standards

### Configuration

Repository-specific configuration is supplied via `ci_shared.config.json` at the repository root:

```json
{
  "repo_context": "Custom repository description...",
  "protected_path_prefixes": ["ci.py", "ci_tools/", "scripts/ci.sh", "Makefile"],
  "coverage_threshold": 80.0
}
```

### Vendored Dependencies

The package includes a lightweight `packaging` shim under `ci_tools/vendor/` to avoid external dependencies. This provides version parsing and specifier utilities for guard scripts.

## Key Design Principles

1. **Protected Infrastructure**: Patches cannot modify CI tooling itself (`ci_tools/`, `scripts/ci.sh`, `Makefile`, `xci.sh`, `ci.py`)
2. **No Workarounds**: The automation refuses to add baseline files, exemption comments (`# noqa`, `policy_guard: allow-*`), or `--exclude` arguments
3. **Fix Code, Not Tests**: The workflow is designed to fix underlying code issues, not bypass quality checks
4. **Safety Guards**: Multiple heuristics prevent dangerous patches (risky patterns, protected paths, line count limits)
5. **Model Enforcement**: Requires `gpt-5-codex` with configurable reasoning effort (low/medium/high)

## Error Handling

The `ci.py` module defines a hierarchy of typed exceptions:

- **`CiError`**: Base class for CI automation runtime failures
  - `CodexCliError`: Codex CLI invocation failures
  - `CommitMessageError`: Empty commit message responses
  - `PatchApplyError`: Patch application failures (retryable vs non-retryable)

- **`CiAbort`**: Base class for deliberate workflow exits
  - `GitCommandAbort`: Git operation failures
  - `RepositoryStateAbort`: Invalid repository state (e.g., detached HEAD)
  - `ModelSelectionAbort`: Unsupported model configuration
  - `ReasoningEffortAbort`: Invalid reasoning effort value
  - `PatchLifecycleAbort`: Patch workflow cannot continue

## Patch Application Strategy

The workflow uses a multi-stage patch application approach:

1. Try `git apply --check` (preferred)
2. If that fails, check if already applied with `git apply --check --reverse`
3. Fall back to `patch -p1` with dry run validation
4. Apply patch with safety guards enabled

## Coverage Deficit Handling

When CI passes but coverage falls below threshold:
1. Parse pytest coverage table from output
2. Extract modules below threshold
3. Generate focused failure summary for Codex
4. Request patches that add/expand tests for those modules

## Logs & Archiving

- **`logs/codex_ci.log`**: Appended log of all Codex interactions (prompt + response)
- **`.xci/archive/`**: Timestamped archives of prompts, responses, and patches from `xci.sh`
- **`.xci/tmp/`**: Temporary files during execution (cleaned on each run)

## Development Workflow

When working on this codebase:

1. The automation scripts are designed to be used by consuming repositories (Zeus, Kalshi), not run directly here
2. Changes to guard scripts should maintain backward compatibility with existing consumers
3. Protected paths must never be modified by automated patches
4. All guard scripts follow a similar CLI pattern: `--root`, exclusions, thresholds
5. Python 3.10+ required (uses `is_relative_to` and other modern APIs)
