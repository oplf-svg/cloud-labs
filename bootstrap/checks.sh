#!/usr/bin/env bash
# What ci.yml does not run by itself. CI calls this with every other checks.sh.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -n "${CI:-}" ]; then
  shellcheck checks.sh mac/setup.sh mac/clouds.command
fi
python3 -m unittest discover --start-directory mac
