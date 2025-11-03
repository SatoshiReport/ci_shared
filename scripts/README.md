# Scripts Directory

This directory contains standalone scripts that are **not** part of the main `ci_tools` package distribution.

## Why separate from ci_tools/scripts/?

Scripts in this directory have characteristics that make them unsuitable for inclusion in the main package:

### complexity_guard.py

**Location rationale:**
- **External dependency**: Requires `radon` package (optional dev dependency)
- **Not distributed**: Not included in the `ci_tools` package for consuming repositories
- **Standalone tool**: Does not use the `GuardRunner` framework
- **Development-only**: Used for internal quality checks on this repository, not intended for Zeus/Kalshi

The complexity guard enforces cyclomatic and cognitive complexity limits using the `radon` library. Since this is a heavier dependency and not all consuming repositories need complexity checking, it remains a standalone script in `/scripts/` rather than being packaged with the core ci_tools.

**Usage:**
```bash
python scripts/complexity_guard.py --root src --max-cyclomatic 10 --max-cognitive 15
```

## Adding new scripts

If you're adding a new script, consider:
- **Add to ci_tools/scripts/** if it should be distributed to consuming repos (Zeus, Kalshi)
- **Add to scripts/** if it's repo-specific or has external dependencies not required by consumers
