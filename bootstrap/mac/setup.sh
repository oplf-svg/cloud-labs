#!/bin/bash
# Gives a closed Mac user its own cloud tools. It needs no administrator and changes nothing outside of this home
# folder. Everything is checked before it is unpacked. It can be run again at any time.
#
# Why its own tools: an administrator may change /Applications, Homebrew and python.org's Python without a password,
# and so may every program that runs as that administrator. This user takes nothing from there.
set -euo pipefail
umask 077
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH DEVELOPER_DIR=/Library/Developer/CommandLineTools

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
tools=$HOME/tools

stop() {
  printf '\nSTOPPED: %s\n' "$*" >&2
  exit 1
}

[ "$(uname -s)/$(uname -m)" = Darwin/arm64 ] || stop "This is for a Mac with Apple silicon."
case " $(id -Gn) " in
  *" admin "*) stop "This Mac user is an administrator. Make a standard user for the clouds. Nothing was changed." ;;
esac
[ -x "$DEVELOPER_DIR/usr/bin/git" ] || stop "Apple's Command Line Tools are missing. Nothing was changed."

# Every user of a Mac is in the group "staff", and a new home folder is open to that group.
chmod 700 "$HOME"
mkdir -p "$tools/bin"

work=$(mktemp -d "$tools/.new.XXXXXX")
trap 'rm -rf "$work"' EXIT

# fetch ADDRESS BYTES FILE
fetch() {
  echo "getting $1"
  curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --retry 3 --output "$3" "$1" ||
    stop "This could not be loaded."
  [ "$(stat -f %z "$3")" = "$2" ] || stop "It has another size than expected. Nothing of it was used."
}

# fingerprint FILE SHA256
fingerprint() {
  echo "$2  $1" | shasum -a 256 --check --quiet - > /dev/null 2>&1 || stop "It has another fingerprint than expected. Nothing of it was used."
}

# keep NAME: the finished folder appears at once or not at all
keep() { mv "$work/$1" "$tools/$1"; }

# ---- Python, for az and gcloud -------------------------------------------------------------------
python=python-3.14.10
if [ ! -d "$tools/$python" ]; then
  fetch 'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.14.10%2B20261026-aarch64-apple-darwin-install_only_stripped.tar.gz' 26753457 "$work/python.tar.gz"
  fingerprint "$work/python.tar.gz" 95eb8c87d16af37c54e9765e31d8c56c0d8ffa9968ea0f704f73a9b83f84e9f9
  mkdir "$work/$python"
  tar -xzf "$work/python.tar.gz" -C "$work/$python"
  keep $python
fi

# ---- AWS CLI. AWS publishes no fingerprint for a Mac. Apple's signature takes its place. ---------
aws=aws-2.40.0
if [ ! -d "$tools/$aws" ]; then
  fetch 'https://awscli.amazonaws.com/AWSCLIV2-2.40.0.pkg' 61141180 "$work/aws.pkg"
  signature=$(pkgutil --check-signature "$work/aws.pkg") || stop "The package of AWS is not signed. Nothing of it was used."
  case "$signature" in
    *"Developer ID Installer: AMZN Mobile LLC (94KV3E626L)"*) ;;
    *) stop "The package of AWS is signed by somebody else. Nothing of it was used." ;;
  esac
  mkdir "$work/$aws"
  cat > "$work/choices.xml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <array>
    <dict>
      <key>choiceAttribute</key>
      <string>customLocation</string>
      <key>attributeSetting</key>
      <string>$work/$aws</string>
      <key>choiceIdentifier</key>
      <string>default</string>
    </dict>
  </array>
</plist>
EOF
  installer -pkg "$work/aws.pkg" -target CurrentUserHomeDirectory -applyChoiceChangesXML "$work/choices.xml" > /dev/null ||
    stop "The package of AWS could not be installed."
  [ -x "$work/$aws/aws-cli/aws" ] || stop "The package of AWS is not where it should be."
  keep $aws
fi

# ---- Azure CLI: Microsoft's own archive, the one that Homebrew takes too -------------------------
az=az-2.92.0
if [ ! -d "$tools/$az" ]; then
  fetch 'https://github.com/Azure/azure-cli/releases/download/azure-cli-2.92.0/azure-cli-2.92.0-macos-arm64.tar.gz' 46713373 "$work/az.tar.gz"
  fingerprint "$work/az.tar.gz" 6fb7d8d6d3db65098e259d5d1d6364359b4b54b5aef4ea6b18bddddd9468407a
  mkdir "$work/$az"
  tar -xzf "$work/az.tar.gz" -C "$work/$az"
  [ -e "$work/$az/bin/az" ] || stop "Microsoft's archive looks different than expected."
  keep $az
fi

# ---- Google Cloud CLI: the archive, without its installer, which would want an administrator -----
gcloud=gcloud-593.0.0
if [ ! -d "$tools/$gcloud" ]; then
  fetch 'https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-593.0.0-darwin-arm.tar.gz' 54790650 "$work/gcloud.tar.gz"
  # Two sources: the recipe of Homebrew has the first, Google's storage the second.
  fingerprint "$work/gcloud.tar.gz" 3351dba1dbed21be0bc77c47462d6ba5d28a25ecc31e878ab1c0f32cc442741b
  [ "$(md5 -q "$work/gcloud.tar.gz")" = f599965e75c24651870973310ddfd77f ] || stop "Google's own fingerprint differs. Nothing of it was used."
  mkdir "$work/$gcloud"
  tar -xzf "$work/gcloud.tar.gz" -C "$work/$gcloud"
  [ -x "$work/$gcloud/google-cloud-sdk/bin/gcloud" ] || stop "Google's archive looks different than expected."
  keep $gcloud
fi

# ---- The four commands ---------------------------------------------------------------------------
# tool NAME LINE...: a small file in tools/bin that starts the right copy, whatever is set outside
tool() {
  local name=$1
  shift
  printf '#!/bin/bash\n' > "$work/$name.sh"
  printf '%s\n' "$@" >> "$work/$name.sh"
  chmod 700 "$work/$name.sh"
  mv -f "$work/$name.sh" "$tools/bin/$name"
}
tool python3 "exec \"$tools/$python/python/bin/python3.14\" \"\$@\""
tool aws "export AWS_PAGER= AWS_CLI_AUTO_PROMPT=off AWS_EC2_METADATA_DISABLED=true" \
  "exec \"$tools/$aws/aws-cli/aws\" \"\$@\""
# PYTHONSAFEPATH: Microsoft's starter would otherwise take a folder called "azure" in the current folder for its own.
tool az "export AZ_PYTHON=\"$tools/$python/python/bin/python3.14\" PYTHONSAFEPATH=1 AZURE_CORE_COLLECT_TELEMETRY=no" \
  "export AZURE_CORE_LOGIN_EXPERIENCE_V2=off AZURE_EXTENSION_USE_DYNAMIC_INSTALL=no" \
  "exec \"$tools/$az/bin/az\" \"\$@\""
# File logging off: gcloud would write what it prints into a file, also a token. The refused commands open a door on
# localhost that every user of this Mac can walk through, or store a second sign-in as readable text.
# shellcheck disable=SC2016
tool gcloud "export CLOUDSDK_PYTHON=\"$tools/$python/python/bin/python3.14\" CLOUDSDK_CORE_DISABLE_FILE_LOGGING=true" \
  "export CLOUDSDK_CORE_DISABLE_USAGE_REPORTING=true CLOUDSDK_COMPONENT_MANAGER_DISABLE_UPDATE_CHECK=true CLOUDSDK_SURVEY_DISABLE_PROMPTS=true" \
  "unset CLOUDSDK_PYTHON_SITEPACKAGES" \
  'for word in "$@"; do' \
  '  case "$word" in cloud-shell | proxy | start-iap-tunnel | application-default) echo "Not on this Mac: gcloud $word" >&2; exit 2 ;; esac' \
  'done' \
  "exec \"$tools/$gcloud/google-cloud-sdk/bin/gcloud\" \"\$@\""

# ---- What every terminal of this user starts with ------------------------------------------------
cat > "$work/zprofile" << 'EOF'
# Written by setup.sh: this user's own tools and Apple's, and nothing that an administrator could have changed.
export PATH="$HOME/tools/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export DEVELOPER_DIR=/Library/Developer/CommandLineTools
umask 077
EOF
if [ -e "$HOME/.zprofile" ] && ! cmp -s "$work/zprofile" "$HOME/.zprofile"; then
  stop "There is another .zprofile in this home folder. Look at it first. The tools are in place."
fi
mv -f "$work/zprofile" "$HOME/.zprofile"

if [ -f "$here/clouds.command" ]; then
  mkdir -p "$HOME/Desktop"
  cp "$here/clouds.command" "$HOME/Desktop/Clouds.command"
  chmod 700 "$HOME/Desktop/Clouds.command"
fi

# ---- A look ----------------------------------------------------------------------------------------
PATH=$tools/bin:$PATH
echo
echo "home     $(stat -f '%Sp' "$HOME")    (has to be drwx------)"
echo "python   $(python3 --version)"
echo "aws      $(aws --version)"
echo "az       $(az version --query '"azure-cli"' --output tsv)"
rm -rf "$HOME/.azure" # az makes it when it is asked for its version, and Clouds takes it for a sign-in
echo "gcloud   $(gcloud version --format='value("Google Cloud SDK")')"
rm -rf "$HOME/.config/gcloud"
echo "git      $(git --version)"
echo "jq       $(jq --version)"
echo
echo "Done. Double-click \"Clouds\" on the desktop."
