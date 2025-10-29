# Security Guidelines

## Protected Files

This repository uses `.gitignore` to prevent committing sensitive files:

### Private Keys & Certificates
- `*.key`, `*.pem`, `*.p12`, `*.pfx`
- `*.crt`, `*.cer`, `*.der`
- SSH keys (`id_rsa`, `id_ed25519`, etc.)

### Secrets & Credentials
- `.env` files and variants
- Files containing `secret`, `credential`, `password` in name
- API tokens and keys

### Runtime & Temporary Files
- `.xci/` directory (logs and temp files)
- `.xci.log`
- Python cache files

## Before Committing

Always verify no sensitive data is being committed:

```bash
# Check what will be staged
git add -n .

# Review changes
git diff --cached

# Check for accidentally staged secrets
git diff --cached | grep -i "password\|secret\|key\|token"
```

## XCI Configuration

If you create an `xci.config.json` file with custom settings:
- Add it to `.gitignore` if it contains sensitive paths or credentials
- Consider creating an `xci.config.json.example` with dummy values for documentation

## Reporting Security Issues

If you discover sensitive data was accidentally committed:
1. Do NOT push to remote
2. Use `git reset` or `git rm --cached` to unstage
3. Consider using BFG Repo-Cleaner or git-filter-repo if already pushed
