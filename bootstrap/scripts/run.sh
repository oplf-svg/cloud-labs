#!/usr/bin/env bash
# Runs one bootstrap from start to finish, in that cloud's Cloud Shell or on a Mac.
#
#   run.sh aws | azure | gcp
#
# It shows the plan and asks before it creates anything, and stops if the plan is not the expected
# one or would delete something. It can be run again at any time: it continues where an earlier run
# stopped, and carries out what has changed here since. The runbook next to each stack explains every
# step.
#
# On a Mac it only carries on what is there already. RUN_TMP is a folder for Terraform that nobody else
# can open, RUN_RESULTS a folder for a file that says how it went, without an id or a name, and RUN_CHECKED
# a file in a closed folder that remembers for an hour that GitHub's side was right.
#
# The functions are called by name, as "${cloud}_setup", which shellcheck cannot see.
# shellcheck disable=SC2317,SC2329
set -euo pipefail

cloud=${1:-}
case "$cloud" in
  aws) expected=106 ;;
  azure) expected=97 ;;
  gcp) expected=55 ;;
  *)
    echo "usage: run.sh aws | azure | gcp" >&2
    exit 2
    ;;
esac

scripts=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$scripts/../$cloud"
system=$(uname -s)
if [ "$system" = Darwin ]; then
  # This user's own tools and Apple's. Other folders of a Mac belong to its administrators, and so to every program that
  # runs as one of them. DEVELOPER_DIR is where Apple's git and python3 look, and not in /Applications.
  export PATH="$HOME/tools/bin:/usr/bin:/bin:/usr/sbin:/sbin" DEVELOPER_DIR=/Library/Developer/CommandLineTools
fi
terminal=${RUN_TERMINAL:-/dev/tty}
result=""
made=""
ending=stopped
trap 'rm -rf tfplan ${made:+"$made"}; note "ended: $(date -u +%Y-%m-%dT%H:%MZ), $ending"' EXIT

# Only words of this script's own ever get into the result.
note() {
  if [ -n "$result" ]; then printf '%s\n' "$*" >> "$result"; fi
}

step() {
  printf '\n== %s\n' "$*"
  note "step: $*"
}

stop() {
  printf '\nSTOPPED: %s\n' "$*" >&2
  exit 1
}

# Throws away what was typed before a question is on the screen. It cannot be an answer to it.
forget_typing() {
  python3 -c 'import termios; termios.tcflush(0, termios.TCIFLUSH)' 2> /dev/null < "$terminal" || true
}

confirm() {
  local answer=""
  forget_typing
  printf '\n%s\nType yes to go on: ' "$1"
  read -r answer < "$terminal" || true
  [ "$answer" = yes ]
}

ask() {
  local answer=""
  forget_typing
  printf '%s' "$1" >&2
  read -r answer < "$terminal" || true
  printf '%s' "$answer"
}

# Whether a folder is this user's, and nobody else can look into it.
closed() {
  python3 -c 'import os, sys; s = os.lstat(sys.argv[1]); sys.exit(s.st_uid != os.getuid() or s.st_mode & 0o170077 != 0o040000)' "$1"
}

# Makes a new file that everybody may read, in a folder that only this user can change. Whoever else could change it
# could put a link there, and so choose what is written over.
open_result() {
  python3 - "$1" "$cloud" << 'EOF'
import os, stat, sys, time
folder = sys.argv[1]
try:
    os.mkdir(folder)
    os.chmod(folder, 0o755)
except FileExistsError:
    pass
about = os.lstat(folder)
if not stat.S_ISDIR(about.st_mode) or about.st_uid != os.getuid() or about.st_mode & 0o022:
    sys.exit(1)
file = os.path.join(folder, time.strftime("%Y-%m-%dT%H%M%SZ-", time.gmtime()) + sys.argv[2] + ".txt")
os.fchmod(os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW), 0o644)
print(file)
EOF
}

# checked look FILE: whether the same check has found GitHub's side right within this hour, with the same lists. checked
# keep FILE: that it has. Every look asks GitHub 25 questions, and it answers 60 an hour to one address.
checked() {
  python3 - "$1" "$2" "$scripts/github_checks.py" "$scripts"/../*.json << 'EOF'
import hashlib, os, stat, sys, time
what, file, *sources = sys.argv[1:]
mark = hashlib.sha256(b"".join(open(source, "rb").read() for source in sources)).hexdigest()
if what == "keep":
    os.umask(0o077)
    with open(file, "w") as out:
        out.write(mark)
    sys.exit()
about = os.lstat(file)
own = stat.S_ISREG(about.st_mode) and about.st_uid == os.getuid() and not about.st_mode & 0o077
sys.exit(not (own and 0 <= time.time() - about.st_mtime < 3600 and open(file).read() == mark))
EOF
}

# ---- What differs per cloud ----------------------------------------------------------------------
# <cloud>_setup     signs in, sets the variables, "where" and "bucket" (empty if there is none yet)
# <cloud>_fresh     checks that nothing is in the way of a first run
# <cloud>_has_state true if the bucket already holds this stack's state
# <cloud>_backend   prints the backend block for that bucket
# <cloud>_subjects  prints every subject the cloud trusts
# <cloud>_last      a last check of its own

where=""
bucket=""

aws_setup() {
  local identity
  identity=$(aws sts get-caller-identity --query Arn --output text) || stop "AWS does not answer. Are you signed in?"
  TF_VAR_account_id=$(aws sts get-caller-identity --query Account --output text)
  export TF_VAR_account_id
  where="AWS account $TF_VAR_account_id, signed in as $identity"
  bucket=$(aws s3api list-buckets --query "Buckets[?starts_with(Name, 'tfstate-')].Name | [0]" --output text)
  if [ "$bucket" = None ]; then bucket=""; fi
}

aws_fresh() {
  local providers
  providers=$(aws iam list-open-id-connect-providers --output text) ||
    stop "This account may not work with identity providers, so it cannot trust GitHub. Nothing was changed. See \"Which account\" in the runbook."
  if grep -q token.actions.githubusercontent.com <<< "$providers"; then
    stop "This account already trusts GitHub, but there is no state bucket. See step 5 of the runbook."
  fi
  aws ec2 describe-availability-zones --region eu-west-2 > /dev/null ||
    stop "This account may not use London (eu-west-2). Nothing was changed. See \"Which account\" in the runbook."
}

aws_has_state() {
  aws s3api head-object --bucket "$bucket" --key bootstrap/terraform.tfstate > /dev/null 2>&1
}

aws_backend() {
  cat << EOF
terraform {
  backend "s3" {
    bucket       = "$bucket"
    key          = "bootstrap/terraform.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
EOF
}

aws_subjects() {
  aws iam list-roles --output json | jq -r '.Roles[].AssumeRolePolicyDocument.Statement
    | if type == "array" then .[] else . end
    | select(tostring | contains("token.actions.githubusercontent.com"))
    | .Condition.StringEquals["token.actions.githubusercontent.com:sub"] // "a role without one exact subject"'
}

aws_last() { :; }

azure_setup() {
  local name user
  name=$(az account show --query name --output tsv) || stop "Azure does not answer. Run az login and start again."
  user=$(az account show --query user.name --output tsv)
  TF_VAR_subscription_id=$(az account show --query id --output tsv)
  export TF_VAR_subscription_id
  where="Azure subscription \"$name\", signed in as $user"
  bucket=$(az storage account list --resource-group rg-github-bootstrap --query '[0].name' --output tsv 2> /dev/null || true)
}

azure_fresh() {
  if [ "$(az group exists --name rg-github-bootstrap)" = true ]; then
    stop "An earlier run was cut off and its state is gone, so this cannot continue safely. See the runbook."
  fi
}

azure_has_state() {
  [ "$(az storage blob exists --account-name "$bucket" --container-name bootstrap --name terraform.tfstate --auth-mode login --query exists --output tsv 2> /dev/null)" = true ]
}

azure_backend() {
  cat << EOF
terraform {
  backend "azurerm" {
    storage_account_name = "$bucket"
    container_name       = "bootstrap"
    key                  = "terraform.tfstate"
    use_azuread_auth     = true
    use_cli              = true
  }
}
EOF
}

azure_subjects() {
  local identity
  for identity in $(az identity list --resource-group rg-github-bootstrap --query '[].name' --output tsv); do
    az identity federated-credential list --resource-group rg-github-bootstrap --identity-name "$identity" --query '[].subject' --output tsv
  done
}

azure_last() { :; }

gcp_editors() {
  gcloud projects get-iam-policy "$TF_VAR_project_id" --flatten='bindings[].members' --filter='bindings.role=roles/editor' \
    --format='value(bindings.members)' | grep '^serviceAccount:' | grep -v '@cloudservices.gserviceaccount.com$' || true
}

gcp_last() {
  local editors
  editors=$(gcp_editors)
  [ -z "$editors" ] || stop "These accounts have Editor again, see step 6 of the runbook: $editors"
}

gcp_setup() {
  local project number account
  TF_VAR_project_id=${TF_VAR_project_id:-$(ask "Id of the project that the repos deploy into: ")}
  TF_VAR_bootstrap_project_id=${TF_VAR_bootstrap_project_id:-$(ask "Id of the other, empty project for the trust and the state: ")}
  export TF_VAR_project_id TF_VAR_bootstrap_project_id
  [ "$TF_VAR_project_id" != "$TF_VAR_bootstrap_project_id" ] || stop "These have to be two different projects."

  for project in "$TF_VAR_project_id" "$TF_VAR_bootstrap_project_id"; do
    if [ "$(gcloud billing projects describe "$project" --format='value(billingEnabled)')" != True ]; then
      stop "Project $project does not exist or is not linked to billing. See step 4 of the runbook."
    fi
  done
  where="Google Cloud projects $TF_VAR_project_id and $TF_VAR_bootstrap_project_id"

  confirm "This turns on the Google APIs the bootstrap needs, and takes the Editor role away from the default service account of $TF_VAR_project_id." || stop "Nothing was changed."
  gcloud services enable bigquery.googleapis.com cloudresourcemanager.googleapis.com iam.googleapis.com storage.googleapis.com sts.googleapis.com --project "$TF_VAR_bootstrap_project_id"
  gcloud services enable cloudasset.googleapis.com cloudresourcemanager.googleapis.com compute.googleapis.com iam.googleapis.com logging.googleapis.com serviceusage.googleapis.com --project "$TF_VAR_project_id"
  number=$(gcloud projects describe "$TF_VAR_project_id" --format='value(projectNumber)')
  account="$number-compute@developer.gserviceaccount.com"
  # Compute Engine creates it, and its Editor role, a moment after being turned on.
  for _ in 1 2 3 4 5 6; do
    if gcloud iam service-accounts describe "$account" --project "$TF_VAR_project_id" > /dev/null 2>&1; then break; fi
    sleep "${RUN_WAIT:-10}"
  done
  gcloud projects remove-iam-policy-binding "$TF_VAR_project_id" --condition=None --role=roles/editor \
    --member="serviceAccount:$account" > /dev/null 2>&1 || true
  gcp_last

  bucket=$(gcloud storage buckets list --project "$TF_VAR_bootstrap_project_id" --filter='name~^tfstate-' --format='value(name)' | head -n 1)
}

gcp_fresh() { :; }

gcp_has_state() {
  gcloud storage ls "gs://$bucket/bootstrap/default.tfstate" > /dev/null 2>&1
}

gcp_backend() {
  cat << EOF
terraform {
  backend "gcs" {
    bucket = "$bucket"
    prefix = "bootstrap"
  }
}
EOF
}

gcp_subjects() {
  gcloud iam workload-identity-pools providers describe github --workload-identity-pool="${TF_VAR_pool_id:-github-actions}" \
    --location=global --project "$TF_VAR_bootstrap_project_id" --format='value(attributeCondition)' | grep -o 'repo:[^"]*'
}

# ---- The run -------------------------------------------------------------------------------------

if [ "$system" = Darwin ]; then
  # All users of a Mac share /tmp, and what lies in this folder is run with your rights.
  if [ -z "${RUN_TMP:-}" ]; then made=$(mktemp -d); fi
  work=${RUN_TMP:-$made}
  closed "$work" || stop "RUN_TMP has to be a folder that only you can open. Nothing was changed."
else
  work=${RUN_TMP:-/tmp}
fi
if [ -n "${RUN_RESULTS:-}" ]; then
  result=$(open_result "$RUN_RESULTS" 2> /dev/null) || echo "No result is written: RUN_RESULTS is not a folder that only you can change."
fi
note "cloud: $cloud"
note "code: $(git -C "$scripts" rev-parse HEAD 2> /dev/null || echo 'not known')"
note "began: $(date -u +%Y-%m-%dT%H:%MZ)"

step "GitHub: the environments behind the trust"
code=0
remembered=${RUN_CHECKED:-}
if [ -n "$remembered" ] && ! closed "$(dirname "$remembered")" 2> /dev/null; then
  echo "RUN_CHECKED is not in a folder that only you can open, so nothing is remembered."
  remembered=""
fi
if [ -n "$remembered" ] && checked look "$remembered" 2> /dev/null; then
  echo "ok   it was right less than an hour ago"
  note "GitHub was right less than an hour ago"
else
  python3 "$scripts/github_checks.py" environments || code=$?
  if [ "$code" = 0 ] && [ -n "$remembered" ]; then checked keep "$remembered"; fi
fi
case "$code" in
  0) ;;
  3)
    if [ "$system" = Darwin ]; then
      confirm "GitHub answers no more questions from this address for up to an hour. Did this check print ok five times since the environments were last changed?" || stop "Start again in an hour. Nothing was changed."
    else
      confirm "Have you run that check somewhere else, for example on your own computer, and did it print ok five times?" || stop "Run it there first: python3 bootstrap/scripts/github_checks.py environments"
    fi
    ;;
  *) stop "Put the environments right first. Nothing was changed." ;;
esac

step "Terraform"
"$scripts/install-terraform.sh" "$work/tf-bin"
export PATH="$work/tf-bin:$PATH" TF_DATA_DIR="$work/tf-$cloud" TF_IN_AUTOMATION=1
# Forget where an earlier run kept its state. This finds it again below.
rm -f "$TF_DATA_DIR/terraform.tfstate"

step "Sign-in"
"${cloud}_setup"
echo "$where"

# The state is either still here, already in the bucket, or not there yet.
if [ -s terraform.tfstate ]; then
  step "An earlier run stopped halfway. Continuing with the state it left here."
  rm -f backend.tf
  local_state=yes
  first_run=no
elif [ -n "$bucket" ]; then
  "${cloud}_has_state" || stop "There is a state store ($bucket), but this stack's state is not in it or you cannot read it. Do not go on: see the runbook."
  "${cloud}_backend" > backend.tf
  local_state=no
  first_run=no
else
  # Until it is moved, the only state of a first run lies in this folder, which may be gone tomorrow.
  [ "$system" != Darwin ] || stop "There is no bootstrap in this place. Is it the right account? A first run belongs into that cloud's own shell. Nothing was changed."
  "${cloud}_fresh"
  rm -f backend.tf
  local_state=yes
  first_run=yes
fi

step "Plan"
terraform init -input=false -lockfile=readonly > /dev/null || stop "terraform init failed. Nothing was changed."
code=0
terraform plan -input=false -detailed-exitcode -out=tfplan || code=$?
[ "$code" = 0 ] || [ "$code" = 2 ] || stop "The plan failed. Nothing was changed."

counts=$(terraform show -json tfplan | python3 -c '
import json, sys
actions = [r["change"]["actions"] for r in json.load(sys.stdin).get("resource_changes", []) if r["mode"] == "managed"]
print(*(sum(verb in a for a in actions) for verb in ("create", "update", "delete")))
')
read -r create update delete <<< "$counts"
note "plan: $create to create, $update to change, $delete to delete"
# A plan that creates and changes nothing has new values for GitHub, or nothing at all.
new=no
if [ "$create" != 0 ] || { [ "$code" = 2 ] && [ "$update" = 0 ]; }; then new=yes; fi
[ "$delete" = 0 ] || stop "The plan would delete or replace $delete resource(s). Nothing was changed. See the runbook."
if [ "$first_run" = yes ] && [ "$create" != "$expected" ]; then
  stop "The plan would create $create resources and should create $expected. Nothing was changed."
fi

if [ "$code" = 2 ]; then
  confirm "This will create $create and change $update resources, and delete none, in:
  $where" || stop "Nothing was changed."
  note "you said yes"
  step "Apply"
  terraform apply -input=false tfplan || stop "The apply stopped halfway. Keep this window open, wait a minute and run the same command again: it continues."
fi
rm -f tfplan

if [ "$local_state" = yes ]; then
  step "Moving the state into the new bucket"
  terraform output -raw backend_tf > backend.tf
  moved=no
  for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if terraform init -input=false -lockfile=readonly -migrate-state -force-copy > /dev/null; then
      moved=yes
      break
    fi
    echo "Waiting for your access to the bucket to take effect ($attempt of 20)"
    sleep "${RUN_WAIT:-30}"
  done
  [ "$moved" = yes ] || stop "The state could not be moved yet. Keep this window open and run the same command again."
  found=$(terraform state list | wc -l | tr -d ' ')
  [ "$found" -ge "$expected" ] || stop "Only $found of $expected resources arrived in the bucket. The full state is still here, in terraform.tfstate.backup: keep this window open."
  rm -f terraform.tfstate terraform.tfstate.backup
fi

step "Check: nothing left to change"
code=0
terraform plan -input=false -detailed-exitcode > /dev/null || code=$?
case "$code" in
  0)
    echo "ok"
    note "nothing is left to change"
    ;;
  2)
    echo "Terraform still wants to change something. Run the same command again and read the plan."
    note "something is left to change"
    ;;
  *) stop "The check failed. Everything was created: run the same command again." ;;
esac
"${cloud}_last"

step "Check: every subject this cloud trusts"
if diff <(jq -r '.[][]' ../subjects.json ../cost.json | sort) <("${cloud}_subjects" | sort); then
  echo "ok   16 subjects match"
  note "every subject matches"
else
  stop "The list above differs from subjects.json and cost.json (< expected, > found). Everything was created, but look into this before you use it."
fi

ending=ok
step "For GitHub"
if [ "$system" = Darwin ] && [ "$new" = no ]; then
  echo "Nothing new: GitHub has these ids already."
  exit 0
fi
cat << 'EOF'
Copy everything between the two lines. It holds ids, not passwords, so keep it off public pages.
Then run this on your own computer, in your clone of the repo:

  pbpaste | python3 bootstrap/scripts/load_secrets.py
EOF
echo "--------------------------------------------------"
terraform output -json github_secrets | fold -w 100
echo
echo "--------------------------------------------------"
# The one for the costs by itself. It can be typed into GitHub's page where the clipboard of that computer does not reach.
cost=$(terraform output -json github_secrets | jq -r '.repos["cloud-labs"].cost // {} | to_entries[] | "\(.key) = \(.value)"')
if [ -n "$cost" ]; then
  printf '\nIt also holds this one, for the settings of cloud-labs, environment cost:\n\n  %s\n' "$cost"
fi
