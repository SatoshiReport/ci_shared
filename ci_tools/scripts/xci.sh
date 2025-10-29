#!/usr/bin/env bash
# Automate the "run ci.sh, capture failure, ask Codex for a patch, retry" loop.
set -euo pipefail

DEFAULT_MAX_ATTEMPTS=5
DEFAULT_TAIL_LINES=200
DEFAULT_CODEX_CLI=codex
DEFAULT_MODEL=gpt-5-codex
DEFAULT_REASONING_EFFORT=""
DEFAULT_LOG_FILE=.xci.log
DEFAULT_ARCHIVE_DIR=.xci/archive
DEFAULT_TMP_DIR=.xci/tmp

# Load configuration overrides from JSON to avoid exporting env vars.
CONFIG_PATH=${XCI_CONFIG:-xci.config.json}
if [[ -f "${CONFIG_PATH}" ]]; then
  while IFS= read -r line; do
    [[ -n "${line}" ]] && eval "${line}"
  done < <(python - "${CONFIG_PATH}" <<'PY'
import json
import shlex
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
except OSError:
    sys.exit(0)


def emit_int(var_name, value):
    if value is None:
        return
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise SystemExit(f"Invalid integer for {var_name}: {value!r}")
    print(f"{var_name}={number}")


def emit_str(var_name, value):
    if value is None:
        return
    text = str(value)
    print(f"{var_name}={shlex.quote(text)}")

emit_int("CFG_MAX_ATTEMPTS", data.get("max_attempts"))
emit_int("CFG_TAIL_LINES", data.get("log_tail"))
emit_str("CFG_CODEX_CLI", data.get("codex_cli"))
emit_str("CFG_MODEL", data.get("model"))
emit_str("CFG_REASONING_EFFORT", data.get("reasoning_effort"))
emit_str("CFG_LOG_FILE", data.get("log_file"))
emit_str("CFG_ARCHIVE_DIR", data.get("archive_dir"))
emit_str("CFG_TMP_DIR", data.get("tmp_dir"))
PY
)
else
  echo "[xci] Config file '${CONFIG_PATH}' not found; using defaults."
fi

MAX_ATTEMPTS=${XCI_MAX_ATTEMPTS:-${CFG_MAX_ATTEMPTS:-$DEFAULT_MAX_ATTEMPTS}}
TAIL_LINES=${XCI_LOG_TAIL:-${CFG_TAIL_LINES:-$DEFAULT_TAIL_LINES}}
CODEX_CLI=${XCI_CLI:-${CFG_CODEX_CLI:-$DEFAULT_CODEX_CLI}}
MODEL=${XCI_MODEL:-${CFG_MODEL:-$DEFAULT_MODEL}}
REASONING_EFFORT=${XCI_REASONING_EFFORT:-${CFG_REASONING_EFFORT:-$DEFAULT_REASONING_EFFORT}}
LOG_FILE=${XCI_LOG_FILE:-${CFG_LOG_FILE:-$DEFAULT_LOG_FILE}}
ARCHIVE_DIR=${XCI_ARCHIVE_DIR:-${CFG_ARCHIVE_DIR:-$DEFAULT_ARCHIVE_DIR}}
TMP_DIR=${XCI_TMP_DIR:-${CFG_TMP_DIR:-$DEFAULT_TMP_DIR}}

mkdir -p "${ARCHIVE_DIR}"
if ! find "${ARCHIVE_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null; then
  true
fi
echo "[xci] Archiving Codex exchanges under ${ARCHIVE_DIR}"

mkdir -p "${TMP_DIR}"
if ! find "${TMP_DIR}" -mindepth 1 -maxdepth 1 -exec rm -f {} + 2>/dev/null; then
  true
fi

if ! command -v "${CODEX_CLI}" >/dev/null 2>&1; then
  echo "[xci] Codex CLI '${CODEX_CLI}' not found in PATH." >&2
  exit 2
fi

if [[ $# -gt 0 ]]; then
  CI_COMMAND=("$@")
else
  if [[ -x "./ci.sh" ]]; then
    CI_COMMAND=(./ci.sh)
  elif [[ -x "scripts/ci.sh" ]]; then
    CI_COMMAND=(scripts/ci.sh)
  elif [[ -x "scripts/dev/ci.sh" ]]; then
    CI_COMMAND=(scripts/dev/ci.sh)
  else
    echo "[xci] Unable to locate an executable ci.sh in the current directory." >&2
    echo "[xci] Provide a command explicitly, e.g. ./xci.sh ./scripts/dev/ci.sh" >&2
    exit 2
  fi
fi

# Helper to create temp files in our local tmp directory
mktmp() {
  mktemp "${TMP_DIR}/xci.XXXXXX"
}

attempt=1
while true; do
  echo "[xci] Attempt ${attempt}: ${CI_COMMAND[*]}"

  set +e
  "${CI_COMMAND[@]}" 2>&1 | tee "${LOG_FILE}"
  ci_status=${PIPESTATUS[0]}
  set -e

  if [[ ${ci_status} -eq 0 ]]; then
    echo "[xci] CI passed on attempt ${attempt}."
    status_after_ci=$(git status --short 2>/dev/null || true)
    if [[ -n "${status_after_ci}" ]]; then
      diff_after_ci=$(git diff 2>/dev/null || true)
      timestamp=$(date +"%Y%m%dT%H%M%S")
      commit_prefix="${ARCHIVE_DIR}/commit_${timestamp}"
      commit_prompt=$(mktmp)
      cat >"${commit_prompt}" <<EOF_COMMIT
You are preparing an imperative, single-line git commit message (<=72 characters)
for the current working tree. Provide only the commit summary line; do not
include additional commentary unless a short body is absolutely necessary.

Repository status (git status --short):
${status_after_ci}

Diff (git diff):
```diff
${diff_after_ci}
```
Use the provided diff for context. Do not run shell commands such as `diff --git`.
EOF_COMMIT

      cp "${commit_prompt}" "${commit_prefix}_prompt.txt"

      commit_response=$(mktmp)
      if [[ -n "${REASONING_EFFORT}" ]]; then
        set +e
        "${CODEX_CLI}" exec --model "${MODEL}" -c "model_reasoning_effort=${REASONING_EFFORT}" - <"${commit_prompt}" >"${commit_response}"
        commit_status=$?
        set -e
      else
        set +e
        "${CODEX_CLI}" exec --model "${MODEL}" - <"${commit_prompt}" >"${commit_response}"
        commit_status=$?
        set -e
      fi

      if [[ ${commit_status} -ne 0 ]]; then
        echo "[xci] Codex commit message request failed (exit ${commit_status}); skipping suggestion." >&2
      else
        cp "${commit_response}" "${commit_prefix}_response.txt"
        commit_message_file=$(mktmp)
        if python - "${commit_response}" "${commit_message_file}" <<'PY'
import pathlib
import sys

response_path = pathlib.Path(sys.argv[1])
out_path = pathlib.Path(sys.argv[2])

text = response_path.read_text().strip()
if text.startswith("assistant:"):
    text = text.partition("\n")[2]

text = text.strip()
if text:
    out_path.write_text(text)
else:
    out_path.write_text("")
PY
        then
          commit_message=$(head -n 1 "${commit_message_file}" | tr -d '\r')
          if [[ -n "${commit_message}" ]]; then
            echo "[xci] Suggested commit message:"
            echo "  ${commit_message}"
            cp "${commit_message_file}" "${commit_prefix}_message.txt"
          else
            echo "[xci] Codex response did not contain a commit summary."
          fi
        else
          echo "[xci] Failed to parse Codex commit response; see ${commit_prefix}_response.txt." >&2
        fi
      fi
    else
      echo "[xci] Working tree clean; skipping commit message request."
    fi
    echo ""
    echo "========================================"
    echo "[xci] ✓ SUCCESS: CI passed on attempt ${attempt}!"
    echo "========================================"
    break
  fi

  if (( attempt >= MAX_ATTEMPTS )); then
    echo "" >&2
    echo "========================================"  >&2
    echo "[xci] ✗ FAILED: Maximum attempts (${MAX_ATTEMPTS}) reached" >&2
    echo "========================================"  >&2
    exit 1
  fi

  echo "[xci] CI failed (exit ${ci_status}); preparing Codex prompt..."

  log_tail=$(tail -n "${TAIL_LINES}" "${LOG_FILE}" 2>/dev/null || true)
  git_status=$(git status --short 2>/dev/null || true)
  git_diff=$(git diff 2>/dev/null || true)

  prompt_file=$(mktmp)
  cat >"${prompt_file}" <<EOF_PROMPT
You are assisting with automated CI repairs for the repository at $(pwd).

Run details:
- Attempt: ${attempt}
- CI command: ${CI_COMMAND[*]}

Git status:
${git_status:-<clean>}

Current diff:
\`\`\`diff
${git_diff:-/* no diff */}
\`\`\`

Most recent CI log tail:
\`\`\`
${log_tail}
\`\`\`

Please respond with a unified diff (starting with \`diff --git\`) that fixes the failure.
If no change is needed, respond with NOOP.
EOF_PROMPT

  response_file=$(mktmp)
  if [[ -n "${REASONING_EFFORT}" ]]; then
    set +e
    "${CODEX_CLI}" exec --model "${MODEL}" -c "model_reasoning_effort=${REASONING_EFFORT}" - <"${prompt_file}" >"${response_file}"
    codex_status=$?
    set -e
  else
    set +e
    "${CODEX_CLI}" exec --model "${MODEL}" - <"${prompt_file}" >"${response_file}"
    codex_status=$?
    set -e
  fi

  if [[ ${codex_status} -ne 0 ]]; then
    echo "" >&2
    echo "========================================"  >&2
    echo "[xci] ✗ FAILED: Codex CLI error (exit ${codex_status})" >&2
    echo "========================================"  >&2
    exit 3
  fi

  timestamp=$(date +"%Y%m%dT%H%M%S")
  archive_prefix="${ARCHIVE_DIR}/attempt${attempt}_${timestamp}"
  cp "${prompt_file}" "${archive_prefix}_prompt.txt"
  cp "${response_file}" "${archive_prefix}_response.txt"

  if grep -qi '^NOOP$' "${response_file}"; then
    echo "" >&2
    echo "========================================"  >&2
    echo "[xci] ✗ FAILED: Codex returned NOOP (no fix suggested)" >&2
    echo "Response saved at: ${archive_prefix}_response.txt" >&2
    echo "========================================"  >&2
    exit 4
  fi

  patch_file=$(mktmp)
  if ! python - "${response_file}" "${patch_file}" <<'PY'
import pathlib
import sys

response_path = pathlib.Path(sys.argv[1])
patch_path = pathlib.Path(sys.argv[2])

text = response_path.read_text()
if text.startswith("assistant:"):
    text = text.partition("\n")[2]

marker = "diff --git "
idx = text.find(marker)
if idx == -1:
    sys.exit(1)

patch_path.write_text(text[idx:])
PY
  then
    echo "[xci] Unable to extract diff from Codex response; will retry. (Response saved at ${archive_prefix}_response.txt)" >&2
    ((attempt+=1))
    continue
  fi

  cp "${patch_file}" "${archive_prefix}_patch.diff"

  if git apply --check --whitespace=nowarn "${patch_file}" 2>/dev/null; then
    git apply --allow-empty --whitespace=nowarn "${patch_file}"
    echo "[xci] Applied patch from Codex (see ${patch_file})."
  elif git apply --check --reverse --whitespace=nowarn "${patch_file}" 2>/dev/null; then
    echo "[xci] Patch already applied; rerunning CI with existing changes."
    ((attempt+=1))
    continue
  else
    echo "[xci] Patch failed dry-run; will retry with fresh Codex request. (Response saved at ${archive_prefix}_response.txt)" >&2
    ((attempt+=1))
    continue
  fi

  ((attempt+=1))
done
