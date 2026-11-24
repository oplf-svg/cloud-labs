#!/usr/bin/env bash
# Builds the site into site/out, which is what both clouds serve.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

npm ci --no-audit --no-fund
npm run build
rm -rf out
cp -R pages/dist out
node scripts/list-files.mjs out
