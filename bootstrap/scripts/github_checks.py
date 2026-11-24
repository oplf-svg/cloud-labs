#!/usr/bin/env python3
"""Read-only checks of the GitHub side. Uses GitHub's public API and needs no sign-in.

  github_checks.py environments        before running a bootstrap
  github_checks.py schedules [REPO..]  weekly, and before any apply that creates resources

Set GITHUB_TOKEN only inside GitHub Actions, where it raises the rate limit.
"""

import argparse
import datetime
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

OWNER = "oplf-svg"
BOOTSTRAP = pathlib.Path(__file__).resolve().parent.parent
SUBJECTS = json.loads((BOOTSTRAP / "subjects.json").read_text())
COST = json.loads((BOOTSTRAP / "cost.json").read_text())
DESTROY_WORKFLOW = ".github/workflows/nightly-destroy.yml"

# What each tier trusts: the environment that its subject names, and whether a person has to approve every job in it.
ENVIRONMENTS = {"plan": ("plan", False), "apply": ("production", True), "destroy": ("nightly-destroy", False)}

# What GitHub puts into every subject, in this order, and how a subject has to end because of it. Without it, the subject
# of a job in an environment does not say which branch the job is from.
TEMPLATE = ["repo", "context", "ref"]
BRANCH = "ref:refs/heads/main"

# What has to pass before anything gets into main, and who reports it: GitHub Actions.
CHECK = {"context": "ci", "app_id": 15368}

# GitHub turns off schedules in a public repo after 60 days without activity. Stopping at 50
# means that any stack created today still has at least ten nights of working schedule ahead.
MAX_QUIET_DAYS = 50
MAX_HOURS_SINCE_DESTROY = 36


class LimitReached(Exception):
    pass


def get(path):
    """GET a GitHub API path. Returns None when it does not exist."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "github-checks"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    request = urllib.request.Request("https://api.github.com" + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        if error.code in (403, 429):
            raise LimitReached from error
        raise


def parse_time(text):
    return datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))


def environment_problems(repo, name, listing, fetch, reviewer_wanted):
    env = next((e for e in listing.get("environments", []) if e["name"] == name), None)
    if env is None:
        return [f"environment {name} does not exist"]

    problems = []
    rules = {rule["type"] for rule in env.get("protection_rules", [])}
    if ("required_reviewers" in rules) != reviewer_wanted:
        problems.append(f"environment {name} must {'' if reviewer_wanted else 'not '}have a required reviewer")
    if env.get("can_admins_bypass") is not False:
        problems.append(f"environment {name} lets admins bypass its rules")
    if not (env.get("deployment_branch_policy") or {}).get("custom_branch_policies"):
        problems.append(f"environment {name} does not restrict branches")
        return problems

    policies = fetch(f"/repos/{OWNER}/{repo}/environments/{name}/deployment-branch-policies") or {}
    allowed = [(p["name"], p.get("type", "branch")) for p in policies.get("branch_policies", [])]
    if allowed != [("main", "branch")]:
        problems.append(f"environment {name} allows more or less than the main branch")
    return problems


def subject_problems(repo, prefix, fetch):
    """What the clouds compare has to be what GitHub writes."""
    problems = []
    if SUBJECTS[repo] != {tier: f"{prefix}:environment:{name}:{BRANCH}" for tier, (name, _) in ENVIRONMENTS.items()}:
        problems.append("subjects.json does not match the repo's ids")
    if any(subject != f"{prefix}:environment:{name}:{BRANCH}" for name, subject in COST.get(repo, {}).items()):
        problems.append("cost.json does not match the repo's ids")
    template = fetch(f"/repos/{OWNER}/{repo}/actions/oidc/customization/sub") or {}
    if template.get("use_default") is not False or template.get("include_claim_keys") != TEMPLATE:
        problems.append("GitHub's subject does not end with the branch")
    # Both are left out of some answers. The clouds compare the ids anyway.
    if template.get("use_immutable_subject") is False or template.get("sub_claim_prefix", prefix) != prefix:
        problems.append("GitHub's subject does not hold the repo's ids")
    return problems


def main_problems(repo, fetch):
    """All of it rests on what gets into main. How many have to approve, GitHub shows to administrators only."""
    branch = fetch(f"/repos/{OWNER}/{repo}/branches/main") or {}
    required = (branch.get("protection") or {}).get("required_status_checks") or {}
    needed = any(CHECK.items() <= check.items() for check in required.get("checks", []))
    if branch.get("protected") is not True or required.get("enforcement_level") != "everyone" or not needed:
        return ["main does not need the check ci from everyone"]
    return []


def check_environments(repo, fetch):
    """The trust is only as strong as the rules behind it."""
    info = fetch(f"/repos/{OWNER}/{repo}")
    if info is None:
        return ["repo does not exist or is not public"]

    problems = []
    # In a private repo of a free account, GitHub ignores the rules of an environment.
    if info.get("private") is not False:
        problems.append("repo is not public")
    problems += subject_problems(repo, f"repo:{OWNER}@{info['owner']['id']}/{repo}@{info['id']}", fetch)
    problems += main_problems(repo, fetch)
    listing = fetch(f"/repos/{OWNER}/{repo}/environments") or {}
    for name, reviewer_wanted in [*ENVIRONMENTS.values(), *((name, False) for name in COST.get(repo, {}))]:
        problems += environment_problems(repo, name, listing, fetch, reviewer_wanted)
    return problems


def check_schedules(repo, fetch, now):
    """A stack must never exist while nothing is scheduled to destroy it."""
    workflows = (fetch(f"/repos/{OWNER}/{repo}/actions/workflows?per_page=100") or {}).get("workflows", [])
    workflow = next((w for w in workflows if w["path"] == DESTROY_WORKFLOW), None)
    if workflow is None:
        return ["has no nightly destroy workflow"]

    problems = []
    if workflow["state"] != "active":
        problems.append(f"nightly destroy is off ({workflow['state']})")

    commits = fetch(f"/repos/{OWNER}/{repo}/commits?sha=main&per_page=1") or []
    if not commits:
        problems.append("main has no commits")
    else:
        quiet = (now - parse_time(commits[0]["commit"]["committer"]["date"])).days
        if quiet >= MAX_QUIET_DAYS:
            problems.append(f"no commit on main for {quiet} days, GitHub turns the schedule off at 60")

    # The last one that has ended: one that still waits or runs has not shown anything yet.
    runs = fetch(f"/repos/{OWNER}/{repo}/actions/workflows/{workflow['id']}/runs?event=schedule&status=completed&per_page=1") or {}
    latest = next(iter(runs.get("workflow_runs", [])), None)
    if latest is None:
        problems.append("nightly destroy has never run on schedule")
    else:
        hours = (now - parse_time(latest["created_at"])).total_seconds() / 3600
        if hours > MAX_HOURS_SINCE_DESTROY:
            problems.append(f"last nightly destroy was {hours:.0f} hours ago")
        if latest["conclusion"] != "success":
            problems.append(f"last nightly destroy ended with {latest['conclusion']}")
    return problems


def main(argv=None, fetch=get):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("check", choices=["environments", "schedules"])
    parser.add_argument("repos", nargs="*", metavar="REPO", help="default: every repo in subjects.json")
    args = parser.parse_args(argv)

    unknown = set(args.repos) - set(SUBJECTS)
    if unknown:
        parser.error("not in subjects.json: " + ", ".join(sorted(unknown)))

    now = datetime.datetime.now(datetime.timezone.utc)
    failed = False
    for repo in args.repos or SUBJECTS:
        try:
            problems = check_environments(repo, fetch) if args.check == "environments" else check_schedules(repo, fetch, now)
        except LimitReached:
            print("GitHub refused: anonymous requests are limited to 60 an hour per address, and a Cloud Shell")
            print("shares its address. Wait, or run this on your own computer. It needs only Python 3.")
            return 3
        except (urllib.error.URLError, TimeoutError) as error:
            problems = [f"could not be checked: {error}"]
        failed = failed or bool(problems)
        print(f"{'FAIL' if problems else 'ok  '} {repo}")
        for problem in problems:
            print(f"       {problem}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
