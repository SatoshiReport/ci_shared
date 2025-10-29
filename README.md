# codex-ci-tools

Shared continuous-integration helpers used by the Zeus and Kalshi repositories. The package
bundles the Codex automation workflow (`ci_tools`) along with the `xci.sh` convenience script.

## Installation

Install the package in editable mode from each repository root so that the shared scripts are on
`PYTHONPATH` and the `xci.sh` wrapper is placed on your shell `PATH`:

```bash
python -m pip install -e ../ci_shared
```

## Usage

- `python -m ci_tools.ci` – run the automated Codex repair loop.
- `xci.sh` – bash wrapper that invokes the same workflow while preserving the legacy CLI surface.

Repository-specific configuration (repository description, source layout, etc.) can be supplied via
`ci_shared.config.json` at the repository root. See the Zeus or Kalshi repository for examples.
