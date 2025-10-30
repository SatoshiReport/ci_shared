# Getting Started

This guide walks through installing the shared tooling, configuring a consuming
repository, and running the automation loop for the first time.

## Prerequisites
- Python 3.10 or newer
- `pip` and `virtualenv` (recommended for isolated installs)
- Access to the [Codex CLI](https://github.com/kalshi-trading/codex-cli) with a
  valid `OPENAI_API_KEY`
- Git repository with one of:
  - `scripts/ci.sh` (legacy automation entrypoint)
  - or a custom CI command compatible with `ci_tools.ci`

## Install the Package
From the consuming repository root, install `codex-ci-tools` in editable mode so
that the Python package and helper scripts resolve correctly:

```bash
python -m pip install -e ../ci_shared
```

This exposes:
- The `ci_tools` Python package on `PYTHONPATH`
- The `xci.sh` wrapper on your shell `PATH`

## Configure Repository Context (Optional)
Place a `ci_shared.config.json` at the repository root when you need custom
metadata for the automation loop:

```json
{
  "repo_context": "Brief description of the codebase and its CI quirks",
  "protected_path_prefixes": [
    "ci.py",
    "ci_tools/",
    "scripts/ci.sh",
    "Makefile"
  ],
  "coverage_threshold": 80.0
}
```

Values are read by `ci_tools.ci` to tighten safety rails and tailor coverage
messages.

## Quick Usage

### Python Interface (preferred)
```bash
python -m ci_tools.ci --model gpt-5-codex --reasoning-effort high
```

- Runs the configured CI command (default: `./scripts/ci.sh`)
- Streams logs to Codex when failures occur
- Applies Codex patches while enforcing protected path rules
- Generates a commit message (and optionally pushes) when checks pass

### Bash Wrapper (legacy)
```bash
xci.sh               # Uses the same automation loop
xci.sh pytest -q     # Override the command executed inside the loop
```

The wrapper mirrors the Python interface but preserves the legacy CLI workflow
used by existing automation scripts.

## Integrate Shared Makefile Targets

Include `ci_shared.mk` inside your repository’s `Makefile` to adopt the shared
check pipeline:

```make
include ci_shared.mk

.PHONY: check
check: shared-checks
```

The `shared-checks` target runs formatters, static analyzers, the guard suite,
and pytest with coverage. Customize high-level knobs such as `FORMAT_TARGETS` or
`PYTEST_NODES` by overriding the variables before including the file.

## Verify the Installation
1. `python -m ci_tools.ci --dry-run --command "echo ok"` – ensures CLI wiring
2. `xci.sh --help` – confirms the shim is on your `PATH`
3. `make shared-checks` – validates the guard scripts can be imported and run

If any command fails, see the [Development Guide](development.md) for debugging
tips and dependency notes.
