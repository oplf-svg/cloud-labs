#!/usr/bin/env bash
# Runs checks.sh of every folder that has one. ci.yml calls this after the blocked terms, with no rights
# but to read the code.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

found=0
for checks in */checks.sh; do
  [ -e "$checks" ] || continue
  found=$((found + 1))
  echo "== $checks"
  bash "$checks"
done
echo "$found folder(s) checked"
