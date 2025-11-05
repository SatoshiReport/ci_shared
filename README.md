# codex-ci-tools

Shared continuous-integration helpers used across the Zeus and Kalshi
repositories. The toolkit packages the Codex automation workflow (`ci_tools`),
guard scripts, Makefile snippets, and legacy shell glue to keep CI pipelines
stable.

## Features
- Codex-powered CI repair loop with configurable safety rails
- Legacy-compatible `xci.sh` wrapper that archives Codex prompts/responses
- Extensive guard suite (policy, coverage, module size, structure, etc.)
- **Security scanning**: gitleaks (secrets), bandit (security issues), safety (CVE database)
- Reusable `ci_shared.mk` target bundling linters, formatters, and guards
- Lightweight vendored dependencies for reproducible automation environments

## Quick Start

1. Install from the consuming repository root:
   ```bash
   python -m pip install -e ../ci_shared
   ```
2. Run the automation loop:
   ```bash
   python -m ci_tools.ci --model gpt-5-codex --reasoning-effort high
   ```
   or use the legacy wrapper:
   ```bash
   xci.sh
   ```
3. Optional: include the shared Makefile target to adopt the full guard suite:
   ```make
   include ci_shared.mk

   .PHONY: check
   check: shared-checks
   ```

## Configuration
- `ci_shared.config.json` supplies repository context, protected path prefixes,
  coverage thresholds, **and the `consuming_repositories` list** that drives
  config sync + propagation into API, Zeus, Kalshi, AWS, etc.
- Environment variables such as `OPENAI_MODEL`, `OPENAI_REASONING_EFFORT`, and
  `GIT_REMOTE` customize Codex behavior and push targets.
- `xci.config.json` fine-tunes the legacy shell wrapper (attempt counts, log
  tails, archive paths).

## Guard Suite
Key guard scripts live under `ci_tools/scripts/` and `scripts/`:
- `policy_guard.py` – enforces banned keywords, TODO markers, and fail-fast rules
- `module_guard.py`, `function_size_guard.py` – prevent oversize modules/functions
- `coverage_guard.py` – enforces per-file coverage thresholds
- `documentation_guard.py` – verifies that required docs exist
- `scripts/complexity_guard.py` – limits cyclomatic and cognitive complexity
- **Security**: gitleaks (secret detection), bandit (security linting), safety (dependency CVEs)

See the [Guard Suite reference](docs/guard-suite.md) and [Security Guidelines](SECURITY.md) for details.

## Documentation
- [Getting Started](docs/getting-started.md)
- [Automation Workflow](docs/automation.md)
- [Guard Suite](docs/guard-suite.md)
- [Development Guide](docs/development.md)
- [Claude Guidance](CLAUDE.md)

For security practices, review [`SECURITY.md`](SECURITY.md).
