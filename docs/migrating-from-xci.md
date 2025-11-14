# Migrating from xci.sh to Python Interface

This guide helps teams migrate from the legacy `xci.sh` bash wrapper to the more powerful Python interface (`python -m ci_tools.ci`).

## Why Migrate?

The Python interface offers significant advantages:

- **More control**: Fine-grained options for patch approval, staging, and retries
- **Better testability**: Python code is easier to unit test than bash scripts
- **Dry-run mode**: Test CI without invoking Codex
- **Better error handling**: Typed exceptions and structured error reporting
- **Active development**: New features are added to the Python interface first
- **Direct integration**: Can be imported and used programmatically

The bash wrapper remains supported for backwards compatibility but receives minimal enhancements.

## Feature Comparison

| Feature | xci.sh | python -m ci_tools.ci |
|---------|--------|----------------------|
| Auto-detect CI command | ✅ | ✅ |
| Custom CI command | ✅ | ✅ |
| Max iterations | ✅ (env/config) | ✅ (CLI flag) |
| Model selection | ✅ (env/config) | ✅ (CLI flag) |
| Reasoning effort | ✅ (env/config) | ✅ (CLI flag) |
| Log tail size | ✅ (env/config) | ✅ (CLI flag) |
| Dry-run mode | ❌ | ✅ |
| Patch approval control | ❌ | ✅ (prompt/auto) |
| Auto-stage changes | ❌ | ✅ |
| Custom commit context | ❌ | ✅ |
| Max patch size limit | ❌ | ✅ |
| Patch retry count | ❌ (fixed) | ✅ |
| Dotenv support | ❌ | ✅ |
| Archived exchanges | ✅ | ✅ (via logs) |
| Help documentation | ✅ | ✅ |
| Version info | ✅ | ✅ |

## Migration Steps

### Step 1: Understand Current Configuration

If you're using `xci.config.json`, note your settings:

```json
{
  "max_attempts": 5,
  "log_tail": 200,
  "model": "gpt-5-codex",
  "reasoning_effort": "high"
}
```

### Step 2: Convert to CLI Flags

Replace `xci.sh` invocations with equivalent Python commands:

**Before (xci.sh):**
```bash
xci.sh
```

**After (Python):**
```bash
python -m ci_tools.ci \
  --model gpt-5-codex \
  --reasoning-effort high \
  --max-iterations 5 \
  --log-tail 200
```

### Step 3: Use Environment File (Optional)

Instead of CLI flags, create `~/.env` with defaults:

```bash
OPENAI_MODEL=gpt-5-codex
OPENAI_REASONING_EFFORT=high
```

Then simplify invocations:

```bash
python -m ci_tools.ci  # Uses values from ~/.env
```

### Step 4: Add Advanced Features

Take advantage of new capabilities:

**Dry-run before committing:**
```bash
python -m ci_tools.ci --dry-run --command "make check"
```

**Auto-approve patches for trusted CI:**
```bash
python -m ci_tools.ci --patch-approval-mode auto
```

**Control commit behavior:**
```bash
python -m ci_tools.ci \
  --auto-stage \
  --commit-message \
  --commit-extra-context "Automated fixes from CI pipeline"
```

### Step 5: Update Documentation

Update team documentation and CI scripts to reference the new interface:

```bash
# Old
./xci.sh pytest tests/

# New
python -m ci_tools.ci --command "pytest tests/"
```

## Environment Variable Mapping

| xci.sh | Python Interface | Notes |
|--------|------------------|-------|
| `XCI_MAX_ATTEMPTS` | `--max-iterations` | Or set in ~/.env |
| `XCI_LOG_TAIL` | `--log-tail` | Or set in ~/.env |
| `XCI_MODEL` | `--model` or `OPENAI_MODEL` | Must be gpt-5-codex |
| `XCI_REASONING_EFFORT` | `--reasoning-effort` or `OPENAI_REASONING_EFFORT` | low, medium, high |
| `XCI_CLI` | N/A (always uses codex) | Codex CLI path |
| `XCI_LOG_FILE` | N/A (uses logs/ dir) | Different logging approach |
| `XCI_ARCHIVE_DIR` | N/A (uses logs/ dir) | Archives in structured logs |
| `XCI_TMP_DIR` | N/A (managed internally) | Temp files |

## Common Migration Patterns

### Pattern 1: Simple CI Loop

**Before:**
```bash
#!/bin/bash
xci.sh
```

**After:**
```bash
#!/bin/bash
python -m ci_tools.ci \
  --model gpt-5-codex \
  --reasoning-effort high
```

### Pattern 2: Custom Command with Config

**Before:**
```bash
export XCI_MAX_ATTEMPTS=10
export XCI_REASONING_EFFORT=high
xci.sh pytest -x tests/
```

**After:**
```bash
python -m ci_tools.ci \
  --command "pytest -x tests/" \
  --max-iterations 10 \
  --reasoning-effort high
```

### Pattern 3: CI Pipeline Integration

**Before:**
```bash
if ! xci.sh ./scripts/ci.sh; then
  echo "CI repair failed"
  exit 1
fi
```

**After:**
```bash
if ! python -m ci_tools.ci \
  --command "./scripts/ci.sh" \
  --patch-approval-mode auto; then
  echo "CI repair failed"
  exit 1
fi
```

## Rollback Plan

If you encounter issues, you can revert to xci.sh:

1. Keep `xci.config.json` until migration is stable
2. Document any custom workflows that depend on xci.sh
3. Test Python interface in development before production
4. Keep both interfaces available during transition period

## Getting Help

- Run `python -m ci_tools.ci --help` for all available options
- See [Automation Workflow](automation.md) for detailed documentation
- Check [Getting Started](getting-started.md) for setup instructions
- Review `xci.config.json.example` for legacy configuration reference

## Timeline Recommendation

- **Week 1-2**: Test Python interface in development
- **Week 3**: Update CI scripts in feature branches
- **Week 4**: Deploy to production, monitor closely
- **Week 5+**: Remove xci.sh dependencies once stable

The legacy wrapper will remain available indefinitely for backwards compatibility, so there's no urgent deadline for migration.
