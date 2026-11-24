#!/usr/bin/env python3
"""Stores what one bootstrap printed as GitHub Actions secrets, in every repo.

  pbpaste | load_secrets.py            from the clipboard
  load_secrets.py FILE                 from a file
  pbpaste | load_secrets.py --check    look at it only

Run it on your own computer, where gh is signed in. It checks every value, shows names and never
values, and asks before it writes. Running it again overwrites the same secrets.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

OWNER = "oplf-svg"
BOOTSTRAP = pathlib.Path(__file__).resolve().parent.parent
REPOS = list(json.loads((BOOTSTRAP / "subjects.json").read_text()))
COST = json.loads((BOOTSTRAP / "cost.json").read_text())

# Where a secret goes, and whose identity a job gets there. The environment plan has no secrets of its own,
# so its jobs get those of the repo.
TIERS = {"repository": "plan", "production": "apply", "nightly-destroy": "destroy"}


def scopes_of(repo):
    """Every place in this repo. One repo has an environment for its identity that reads costs."""
    return TIERS | {name: name for name in COST.get(repo, {})}


GUID = "[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}"

# What each cloud provides for a repository, and what it has to look like. No other name is accepted.
NAMES = {
    "aws": {
        "AWS_ACCOUNT_ID": "[0-9]{12}",
        "AWS_ROLE_ARN": "arn:aws:iam::[0-9]{12}:role/github-actions/gha-REPO-TIER",
        "AWS_STATE_BUCKET": "tfstate-[0-9a-f]{8}",
        "AWS_WORKLOAD_BOUNDARY_ARN": "arn:aws:iam::[0-9]{12}:policy/github-actions/workload-boundary",
    },
    "azure": {
        "AZURE_CLIENT_ID": GUID,
        "AZURE_STATE_ACCOUNT": "tfstate[0-9a-f]{8}",
        "AZURE_SUBSCRIPTION_ID": GUID,
        "AZURE_TENANT_ID": GUID,
    },
    "gcp": {
        "GCP_COST_PROJECT_ID": "[a-z][a-z0-9-]{4,28}[a-z0-9]",
        "GCP_PROJECT_ID": "[a-z][a-z0-9-]{4,28}[a-z0-9]",
        "GCP_PROJECT_NUMBER": "[0-9]{6,20}",
        "GCP_STATE_BUCKET": "tfstate-[0-9a-f]{8}",
        "GCP_WORKLOAD_IDENTITY_PROVIDER": "projects/[0-9]{6,20}/locations/global/workloadIdentityPools/[a-z0-9-]{4,32}/providers/github",
    },
}

# The one that differs per tier, so each environment has its own.
PER_TIER = {"aws": "AWS_ROLE_ARN", "azure": "AZURE_CLIENT_ID", "gcp": None}

# On Google Cloud the subject alone decides who it is. What the cost identity needs there is the place of the costs.
PLACE_OF_COSTS = "GCP_COST_PROJECT_ID"


class Unusable(Exception):
    """The input cannot be used. The message never contains a value."""


def read_input(text):
    """Takes what was copied from a terminal: lines may be wrapped, and there may be a prompt around it."""
    text = "".join(text.split())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise Unusable("There is no output in it. Copy everything between the two lines of dashes.")
    try:
        return json.loads(text[start : end + 1])
    except ValueError:
        raise Unusable("Part of the output is missing. Copy everything between the two lines of dashes.") from None


def names_in(cloud, scope):
    if scope == "repository":
        return set(NAMES[cloud]) - {PLACE_OF_COSTS}
    if scope not in TIERS and cloud == "gcp":
        return {PLACE_OF_COSTS}
    return {PER_TIER[cloud]} - {None}


def check(data):
    """Returns the cloud and a list of (repo, scope, name, value), or raises Unusable."""
    if not isinstance(data, dict) or set(data) != {"cloud", "repos"} or data["cloud"] not in NAMES:
        raise Unusable("This is not the output of a bootstrap.")
    cloud, repos = data["cloud"], data["repos"]
    if not isinstance(repos, dict) or set(repos) != set(REPOS):
        raise Unusable("It does not list exactly the repos in subjects.json.")

    found = []
    for repo in REPOS:
        scopes = repos[repo]
        if not isinstance(scopes, dict) or set(scopes) != set(scopes_of(repo)):
            raise Unusable(f"{repo} does not list exactly {', '.join(scopes_of(repo))}.")
        for scope, tier in scopes_of(repo).items():
            values = scopes[scope]
            if not isinstance(values, dict) or set(values) != names_in(cloud, scope):
                raise Unusable(f"{repo}, {scope}: the names are not the expected ones.")
            for name in sorted(values):
                pattern = NAMES[cloud][name].replace("REPO", re.escape(repo)).replace("TIER", tier)
                if not isinstance(values[name], str) or not re.fullmatch(pattern, values[name]):
                    raise Unusable(f"{repo}, {scope}: {name} does not look right.")
                found.append((repo, scope, name, values[name]))

    for name in NAMES[cloud]:
        distinct = {value for _, _, n, value in found if n == name}
        wanted = sum(len(scopes_of(repo)) for repo in REPOS) if name == PER_TIER[cloud] else 1
        if len(distinct) != wanted:
            raise Unusable(f"{name} should have {wanted} different value(s) and has {len(distinct)}.")

    accounts = {value for _, _, name, value in found if name == "AWS_ACCOUNT_ID"}
    if any(value.startswith("arn:") and value.split(":")[4] not in accounts for _, _, _, value in found):
        raise Unusable("The role names belong to another AWS account.")
    if len({value for _, _, name, value in found if name in ("GCP_PROJECT_ID", PLACE_OF_COSTS)}) == 1:
        raise Unusable("The costs lie in the project that the repos deploy into.")
    return cloud, found


def gh(*args, value=None):
    """Runs gh. A value goes in on standard input, so that it never shows up in a process list."""
    return subprocess.run(["gh", *args], input=value, check=True, stdout=subprocess.PIPE, text=True).stdout


def place(repo, scope):
    return ["--repo", f"{OWNER}/{repo}"] + ([] if scope == "repository" else ["--env", scope])


def confirm(question):
    # The clipboard may be on standard input, so ask the terminal itself. Python cannot open it for
    # reading and writing at once: "r+" fails because a terminal cannot seek.
    with open("/dev/tty", "w", encoding="utf-8") as screen:
        screen.write(question)
    with open("/dev/tty", encoding="utf-8") as keyboard:
        return keyboard.readline().strip() == "yes"


def main(argv=None, stdin=sys.stdin, run=gh, ask=confirm):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", nargs="?", help="default: standard input")
    parser.add_argument("--check", action="store_true", help="only check it, write nothing")
    args = parser.parse_args(argv)

    try:
        text = pathlib.Path(args.file).read_text(encoding="utf-8") if args.file else stdin.read()
        cloud, found = check(read_input(text))
    except (Unusable, OSError) as problem:
        print(f"Not used: {problem}")
        return 1

    print(f"{cloud}: {len(found)} secrets in {len(REPOS)} repos. In each repo:")
    for scope, tier in TIERS.items():
        names = sorted(names_in(cloud, scope))
        if names:
            print(f"  {scope:16} {tier:8} {', '.join(names)}")
    for repo, others in COST.items():
        for scope in others:
            print(f"  {scope:16} {scope:8} {', '.join(sorted(names_in(cloud, scope)))} (only in {repo})")
    if args.check:
        print("Checked only. Nothing was written.")
        return 0

    try:
        if run("api", "user", "--jq", ".login").strip() != OWNER:
            print(f"gh is not signed in as {OWNER}. Nothing was written.")
            return 1
        if not ask("Store them now? Type yes: "):
            print("Nothing was written.")
            return 1
        for repo, scope, name, value in found:
            run("secret", "set", name, *place(repo, scope), value=value)
        missing = 0
        for repo in REPOS:
            counts = []
            for scope in scopes_of(repo):
                listed = set(run("secret", "list", *place(repo, scope), "--json", "name", "--jq", ".[].name").split())
                missing += len(names_in(cloud, scope) - listed)
                counts.append(f"{scope} {len(names_in(cloud, scope) & listed)}")
            print(f"  {repo:20} {', '.join(counts)}")
    except (subprocess.CalledProcessError, OSError) as problem:
        # Not the problem itself: it would name the command, and a value must never be in what is printed.
        print(f"gh failed ({type(problem).__name__}). Run this again: it overwrites what is already there.")
        return 1

    print("GitHub does not list some of them. Run this again." if missing else "All stored. Empty the clipboard with: pbcopy < /dev/null")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
