#!/bin/bash
# One cloud, from the sign-in to the sign-out. Double-click it in the closed Mac user. It refuses to run anywhere else.
#
# It gets the code fresh from main, lets you sign in, then runs the bootstrap or gives you a shell, and signs out when
# that ends, however it ends: done, failed, stopped with Control-C, or the window closed.
#
# Signing out cleans this disk. At AWS and Microsoft a sign-in lives on until its time is over, so the wall is this
# closed user, and not the end of this file.
#
# The functions are called by name, as "${cloud}_in", which shellcheck cannot see.
# shellcheck disable=SC2317,SC2329
set -uo pipefail
umask 077

# Start with nothing but what stands here, so that no setting from outside leads a tool somewhere else.
if [ "${CLOUDS_CLEAN:-}" != yes ]; then
  exec /usr/bin/env -i CLOUDS_CLEAN=yes HOME="$HOME" USER="${USER:-}" LOGNAME="${LOGNAME:-}" TERM="${TERM:-dumb}" \
    LANG="${LANG:-en_US.UTF-8}" TMPDIR="${TMPDIR:-$(getconf DARWIN_USER_TEMP_DIR)}" \
    PATH="$HOME/tools/bin:/usr/bin:/bin:/usr/sbin:/sbin" DEVELOPER_DIR=/Library/Developer/CommandLineTools \
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 \
    AWS_REGION=eu-west-2 AWS_PAGER= AWS_CLI_AUTO_PROMPT=off AWS_EC2_METADATA_DISABLED=true \
    AZURE_CORE_COLLECT_TELEMETRY=no AZURE_CORE_LOGIN_EXPERIENCE_V2=off AZURE_EXTENSION_USE_DYNAMIC_INSTALL=no \
    TF_PLUGIN_CACHE_DIR="$HOME/runs/.plugins" \
    /bin/bash "$0"
fi

cloud=""
name=""
touched=no
locked=no
interrupted=""
lock=$HOME/runs/.open

stop() {
  printf '\nSTOPPED: %s\n' "$*"
  exit 1
}

# Throws away what was typed before a question is on the screen. It cannot be an answer to it.
forget_typing() {
  python3 -c 'import termios; termios.tcflush(0, termios.TCIFLUSH)' 2> /dev/null || true
}

ask() {
  forget_typing
  printf '%s' "$1"
  answer=""
  read -r answer || true
}

# ---- Signing in and out --------------------------------------------------------------------------------
# <cloud>_in    the sign-in, in the browser
# <cloud>_who   who and where that is
# <cloud>_out   the sign-out. Everything that the tool has written goes with it
# <cloud>_left  prints what still is a sign-in, and nothing if there is none

aws_in() { aws configure set region eu-west-2 && aws login; }
aws_who() { aws account get-account-information --query AccountName --output text; }
aws_out() {
  aws logout --all
  rm -rf "$HOME/.aws"
}
aws_left() {
  if [ -e "$HOME/.aws" ]; then echo "$HOME/.aws"; fi
}

azure_in() { az login --output none; }
azure_who() { az account show --query '[name, user.name]' --output tsv; }
azure_out() {
  az logout
  az account clear
  rm -rf "$HOME/.azure"
}
azure_left() {
  if [ -e "$HOME/.azure" ]; then
    echo "$HOME/.azure"
  elif az account get-access-token --output none > /dev/null 2>&1; then
    echo "az still gets a token"
  else
    rm -rf "$HOME/.azure" # the question itself has made it again
  fi
}

gcp_in() { gcloud auth login --no-launch-browser --brief; }
gcp_who() { gcloud auth list --filter=status:ACTIVE --format='value(account)'; }
gcp_out() {
  local accounts
  # At Google it can really be ended, and for that the tool needs what it has stored. So the folder goes last, and only
  # if the tool says that it is ended. Without a connection it cannot end anything.
  accounts=$(gcloud auth list --format='value(account)') || return 1
  if [ -n "$accounts" ]; then gcloud auth revoke --all --quiet || return 1; fi
  if gcloud auth print-access-token > /dev/null 2>&1; then return 1; fi
  rm -rf "$HOME/.config/gcloud"
}
gcp_left() {
  if [ -e "$HOME/.config/gcloud" ]; then
    echo "$HOME/.config/gcloud"
    echo "Not ended at Google. If it stays so: myaccount.google.com/permissions, remove Google Cloud CLI."
  fi
}
# Terraform gets a token of an hour, so that no second sign-in has to be stored.
gcp_token() {
  GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token) || return 1
  export GOOGLE_OAUTH_ACCESS_TOKEN
}

sign_out() {
  "$1_out" > /dev/null 2>&1
  left=$("$1_left")
  [ -z "$left" ]
}

# Whatever happens, this runs last. The sign-out comes before any text: the window may be gone.
end() {
  local code=$?
  # What is started from here on cannot be interrupted any more.
  trap '' HUP INT TERM
  trap - EXIT
  unset GOOGLE_OAUTH_ACCESS_TOKEN
  if [ "$touched" = yes ]; then
    if sign_out "$cloud"; then
      printf '\nSigned out of %s. No sign-in is left on this disk.\n' "$name"
      printf 'Now sign out in Safari too, and log out of this Mac user: Apple menu, Log Out.\n'
    else
      printf '\nSTILL SIGNED IN to %s:\n%s\n' "$name" "$left"
      printf 'Open this file again: it signs out first. If that does not help, end the session in the browser.\n'
      code=1
    fi
  fi
  if [ "$locked" = yes ]; then rm -rf "$lock"; fi
  exit "$code"
}
trap end EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# ---- Only in the closed user -----------------------------------------------------------------------------
case " $(id -Gn) " in
  *" admin "*) stop "This Mac user is an administrator. Sign-ins of the clouds belong into the closed user. Nothing was done." ;;
esac
[ "$(stat -f '%Lp %u' "$HOME")" = "700 $(id -u)" ] || stop "This home folder is not closed. Run setup.sh again. Nothing was done."
if pgrep -U "$(id -u)" -i claude > /dev/null; then
  stop "Claude is open in this Mac user. Quit it first. Nothing was done."
fi
for tool in aws az gcloud python3; do
  [ -x "$HOME/tools/bin/$tool" ] || stop "The tools are not here yet. Run setup.sh first. Nothing was done."
done

# ---- One window at a time --------------------------------------------------------------------------------
# A second one would take the sign-in away from the first, in the middle of its work.
mkdir -p "$HOME/runs/.plugins"
if ! mkdir "$lock" 2> /dev/null; then
  other=$(cat "$lock/window" 2> /dev/null)
  if [ -n "$other" ] && ps -p "$other" -o command= 2> /dev/null | grep -qi 'clouds\.command'; then
    stop "Another Clouds window is open. One at a time. Nothing was done."
  fi
fi
locked=yes
echo $$ > "$lock/window"

# ---- Left from an earlier time? ----------------------------------------------------------------------------
for cloud in aws azure gcp; do
  if [ -n "$("${cloud}_left")" ]; then
    echo "An earlier sign-in ($cloud) is still here. Signing out."
    sign_out "$cloud" || stop "That did not work. End it in the browser, then start again."
  fi
done

# ---- Which cloud, which code --------------------------------------------------------------------------------
printf '\n  1  AWS\n  2  Azure\n  3  Google Cloud\n\n'
ask 'Which one? '
case "$answer" in
  1) cloud=aws name=AWS ;;
  2) cloud=azure name=Azure ;;
  3) cloud=gcp name="Google Cloud" ;;
  *) stop "Nothing was done." ;;
esac

run=$(mktemp -d "$HOME/runs/$(date -u +%Y-%m-%d-%H%M)-$cloud.XXXXXX") || stop "No folder could be made."
git clone --quiet --depth 1 --branch main https://github.com/oplf-svg/cloud-labs.git "$run/cloud-labs" || stop "The code could not be loaded."
printf '\nThe code on main:  '
git -C "$run/cloud-labs" log -1 --format='%h of %cd, %s' --date=format:'%d %B %H:%M'

printf '\n  r  run the bootstrap\n  s  only a shell that is signed in\n\n'
ask "With this code in $name: r, s, or anything else to stop? "
case "$answer" in
  r | s) what=$answer ;;
  *) stop "Nothing was done." ;;
esac

# ---- From here on it signs out at the end ----------------------------------------------------------------
# No signal ends this file any more, only what it has started. A closed window is told twice: if the first time ended
# this file, the second could cut off the sign-out. So it is only noted, and everything goes its way to the end.
trap 'interrupted=129' HUP
trap 'interrupted=130' INT
trap 'interrupted=143' TERM
touched=yes
printf '\nOnly confirm the page that opens now. Never a link or a code from a file, a mail or a chat.\n\n'
"${cloud}_in" || stop "The sign-in did not work."
[ -z "$interrupted" ] || stop "Interrupted."
printf '\nSigned in to %s as: %s\n' "$name" "$("${cloud}_who" 2> /dev/null || echo 'the tool does not say')"
ask "Is that the right account? Type yes to go on: "
[ "$answer$interrupted" = yes ] || stop "Nothing was done there."
if [ "$cloud" = gcp ]; then gcp_token || stop "Google gave no token."; fi

if [ "$what" = r ]; then
  # The result says how it went, without an id. It goes into a folder of this user that others can only read. Nothing is
  # ever read or started from there.
  RUN_TMP=$run RUN_RESULTS=/Users/Shared/clouds RUN_CHECKED=$HOME/runs/.checked \
    "$run/cloud-labs/bootstrap/scripts/run.sh" "$cloud"
else
  printf '\nA shell, signed in to %s. Type exit to sign out.\n' "$name"
  (cd "$run/cloud-labs" && PS1="[$name] \\W \\$ " /bin/bash --noprofile --norc -i)
fi
