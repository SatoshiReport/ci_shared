#!/usr/bin/env bash
set -euo pipefail

# Delegate to the shared CI script that we provide to consuming repositories.
# This ensures ci_shared uses the same CI flow it provides to Zeus and Kalshi.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SHARED_CI_SCRIPT="${ROOT_DIR}/ci_tools/scripts/ci.sh"

if [[ ! -x "${SHARED_CI_SCRIPT}" ]]; then
  echo "[ci.sh] Shared CI script not found at ${SHARED_CI_SCRIPT}" >&2
  exit 1
fi

exec "${SHARED_CI_SCRIPT}" "$@"
