#!/usr/bin/env bash
# Everything about the site that can be tested without a cloud. CI runs this on every pull request.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -n "${CI:-}" ]; then
  tools=$(mktemp -d)
  ../bootstrap/scripts/install-terraform.sh "$tools"
  export PATH="$tools:$PATH"
  shellcheck checks.sh deploy/*.sh
fi

bash deploy/build.sh
npm run check
npm test
npm run e2e
python3 -m unittest discover --start-directory deploy

for stack in aws azure; do
  (
    cd "infra/$stack"
    # -lockfile=readonly works only where the lock file has that platform's own checksums.
    if [ -n "${CI:-}" ]; then
      terraform providers lock -platform=linux_amd64 -platform=linux_arm64 -platform=darwin_arm64
      git diff --exit-code .terraform.lock.hcl
    fi
    terraform fmt -check -diff -recursive
    terraform init -backend=false -input=false -lockfile=readonly
    terraform validate
    terraform test
  )
done
