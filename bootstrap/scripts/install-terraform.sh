#!/usr/bin/env bash
# Puts one pinned Terraform release into a directory, after checking its SHA-256.
# Used in every Cloud Shell and in CI, so all of them run the same binary.
set -euo pipefail

version=1.17.2
dest=${1:?usage: install-terraform.sh DIRECTORY}

# From https://releases.hashicorp.com/terraform/1.17.2/terraform_1.17.2_SHA256SUMS
case "$(uname -s)/$(uname -m)" in
  Linux/x86_64)
    platform=linux_amd64
    sha256=e6f16b2f0b137ee5729caa8c4e79a3bae4ee261acd198a1fcfa8584a6296605b
    ;;
  Linux/aarch64)
    platform=linux_arm64
    sha256=858e08c181a76b6b223e8c767a8e983922eebe2d062db949a2de66ce040c368c
    ;;
  *)
    echo "No pinned Terraform for $(uname -s)/$(uname -m)." >&2
    exit 1
    ;;
esac

archive="terraform_${version}_${platform}.zip"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

curl --fail --silent --show-error --location --retry 3 \
  --output "$work/$archive" "https://releases.hashicorp.com/terraform/$version/$archive"
echo "$sha256  $work/$archive" | sha256sum --check --quiet -

mkdir -p "$dest"
unzip -q -o "$work/$archive" terraform -d "$dest"
"$dest/terraform" version
