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
SUBJECTS = json.loads((pathlib.Path(__file__).resolve().parent.parent / "subjects.json").read_text())
DESTROY_WORKFLOW = ".github/workflows/nightly-destroy.yml"

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


def check_environments(repo, fetch):
    """The trust is only as strong as the environments behind it."""
    info = fetch(f"/repos/{OWNER}/{repo}")
    if info is None:
        return ["repo does not exist or is not public"]

    problems = []
    prefix = f"repo:{OWNER}@{info['owner']['id']}/{repo}@{info['id']}:"
    expected = {
        "plan": prefix + "pull_request",
        "apply": prefix + "environment:production",
        "destroy": prefix + "environment:nightly-destroy",
    }
    if SUBJECTS[repo] != expected:
        problems.append("subjects.json does not match the repo's ids")
    listing = fetch(f"/repos/{OWNER}/{repo}/environments") or {}
    problems += environment_problems(repo, "production", listing, fetch, reviewer_wanted=True)
    problems += environment_problems(repo, "nightly-destroy", listing, fetch, reviewer_wanted=False)
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
