import contextlib
import copy
import datetime
import io
import json
import unittest
import unittest.mock

import github_checks as checks

NOW = datetime.datetime(2026, 12, 1, 12, 0, tzinfo=datetime.timezone.utc)
REPO = "cloud-labs"
BASE = "/repos/oplf-svg/cloud-labs"


def environment(name, reviewer):
    rules = [{"type": "branch_policy"}] + ([{"type": "required_reviewers"}] if reviewer else [])
    return {
        "name": name,
        "protection_rules": rules,
        "can_admins_bypass": False,
        "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
    }


PREFIX = "repo:oplf-svg@228823995/cloud-labs@1469385611"
NAMES = ("production", "nightly-destroy", "plan", "cost")
TEMPLATE = f"{BASE}/actions/oidc/customization/sub"

GOOD = {
    BASE: {"id": 1469385611, "owner": {"id": 228823995}, "private": False},
    TEMPLATE: {"use_default": False, "include_claim_keys": ["repo", "context", "ref"], "use_immutable_subject": True, "sub_claim_prefix": PREFIX},
    f"{BASE}/branches/main": {
        "protected": True,
        "protection": {"enabled": True, "required_status_checks": {"enforcement_level": "everyone", "contexts": ["ci"], "checks": [{"context": "ci", "app_id": 15368}]}},
    },
    f"{BASE}/environments": {"environments": [environment(name, name == "production") for name in NAMES]},
    **{f"{BASE}/environments/{name}/deployment-branch-policies": {"branch_policies": [{"name": "main", "type": "branch"}]} for name in NAMES},
    f"{BASE}/actions/workflows?per_page=100": {"workflows": [{"id": 7, "path": checks.DESTROY_WORKFLOW, "state": "active"}]},
    f"{BASE}/commits?sha=main&per_page=1": [{"commit": {"committer": {"date": "2026-11-28T12:00:00Z"}}}],
    f"{BASE}/actions/workflows/7/runs?event=schedule&status=completed&per_page=1": {
        "workflow_runs": [{"created_at": "2026-12-01T03:37:00Z", "status": "completed", "conclusion": "success"}]
    },
}


class Environments(unittest.TestCase):
    def problems(self, change=None):
        data = copy.deepcopy(GOOD)
        if change:
            change(data)
        return checks.check_environments(REPO, data.get)

    def each(self, change, rules=False):
        """Changes one environment after the other, or the list of branches that it allows, and says what is wrong then."""
        for number, name in enumerate(NAMES):
            with self.subTest(name):
                path = f"{BASE}/environments/{name}/deployment-branch-policies"
                part = lambda data: data[path]["branch_policies"] if rules else data[f"{BASE}/environments"]["environments"][number]
                yield name, self.problems(lambda data: change(part(data)))

    def test_accepts_the_intended_setup(self):
        self.assertEqual(self.problems(), [])

    def test_the_environments_are_those_that_the_subjects_name(self):
        branch = ":ref:refs/heads/main"
        for tiers in checks.SUBJECTS.values():
            self.assertEqual({tier: subject.partition(":environment:")[2] for tier, subject in tiers.items()}, {"plan": f"plan{branch}", "apply": f"production{branch}", "destroy": f"nightly-destroy{branch}"})
        self.assertEqual(checks.COST, {REPO: {"cost": f"{PREFIX}:environment:cost{branch}"}})

    def test_another_repo_needs_no_environment_for_costs(self):
        repo, subjects = "webhook-platform", checks.SUBJECTS
        data = json.loads(json.dumps(GOOD).replace("cloud-labs", repo).replace("1469385611", "1469384538"))
        data[f"/repos/oplf-svg/{repo}/environments"]["environments"].pop()
        del data[f"/repos/oplf-svg/{repo}/environments/cost/deployment-branch-policies"]
        self.assertIn(repo, subjects)
        self.assertEqual(checks.check_environments(repo, data.get), [])

    def test_missing_environment(self):
        for name, problems in self.each(lambda environment: environment.update(name="another")):
            self.assertEqual(problems, [f"environment {name} does not exist"])

    def test_unprotected_environment(self):
        # What GitHub creates by itself when a workflow names an environment that does not exist.
        for name, problems in self.each(lambda environment: environment.update(protection_rules=[], can_admins_bypass=True, deployment_branch_policy=None)):
            expected = [f"environment {name} lets admins bypass its rules", f"environment {name} does not restrict branches"]
            self.assertEqual(problems, (["environment production must have a required reviewer"] if name == "production" else []) + expected)

    def test_admin_bypass(self):
        for name, problems in self.each(lambda environment: environment.update(can_admins_bypass=True)):
            self.assertEqual(problems, [f"environment {name} lets admins bypass its rules"])
        for name, problems in self.each(lambda environment: environment.pop("can_admins_bypass")):
            self.assertEqual(problems, [f"environment {name} lets admins bypass its rules"])

    def test_any_protected_branch(self):
        for name, problems in self.each(lambda environment: environment["deployment_branch_policy"].update(protected_branches=True, custom_branch_policies=False)):
            self.assertEqual(problems, [f"environment {name} does not restrict branches"])

    def test_other_branches(self):
        changes = (
            lambda rules: rules.append({"name": "*", "type": "branch"}),
            # What would let a pull request in.
            lambda rules: rules.append({"name": "refs/pull/*/merge", "type": "branch"}),
            lambda rules: rules[0].update(name="ma*"),
            lambda rules: rules.clear(),
            # A tag can be made from any commit.
            lambda rules: rules[0].update(type="tag"),
        )
        for change in changes:
            for name, problems in self.each(change, rules=True):
                self.assertEqual(problems, [f"environment {name} allows more or less than the main branch"])

    def test_reviewers(self):
        for name, problems in self.each(lambda environment: environment.update(protection_rules=[{"type": "branch_policy"}])):
            self.assertEqual(problems, ["environment production must have a required reviewer"] if name == "production" else [])
        for name, problems in self.each(lambda environment: environment.update(protection_rules=[{"type": "branch_policy"}, {"type": "required_reviewers"}])):
            self.assertEqual(problems, [] if name == "production" else [f"environment {name} must not have a required reviewer"])

    def test_a_subject_that_no_environment_guards(self):
        for tier in ("plan", "apply", "destroy"):
            right = f"environment:{checks.ENVIRONMENTS[tier][0]}"
            for ending in ("pull_request", "ref:refs/heads/main", "environment:another:ref:refs/heads/main", right, f"{right}:ref:refs/heads/another"):
                with self.subTest(tier=tier, ending=ending):
                    subjects = copy.deepcopy(checks.SUBJECTS)
                    subjects[REPO][tier] = f"repo:oplf-svg@228823995/cloud-labs@1469385611:{ending}"
                    with unittest.mock.patch.object(checks, "SUBJECTS", subjects):
                        self.assertEqual(self.problems(), ["subjects.json does not match the repo's ids"])

    def test_a_cost_subject_that_no_environment_guards(self):
        for ending in ("pull_request", "environment:cost", "environment:plan:ref:refs/heads/main", "environment:cost:ref:refs/heads/another"):
            with self.subTest(ending), unittest.mock.patch.object(checks, "COST", {REPO: {"cost": f"{PREFIX}:{ending}"}}):
                self.assertEqual(self.problems(), ["cost.json does not match the repo's ids"])

    def test_recreated_repo_has_a_new_id(self):
        self.assertEqual(
            self.problems(lambda d: (d[BASE].update(id=1), d[TEMPLATE].update(sub_claim_prefix=PREFIX.replace("1469385611", "1")))),
            ["subjects.json does not match the repo's ids", "cost.json does not match the repo's ids"],
        )

    def test_a_repo_that_is_not_public(self):
        # GitHub ignores the rules of its environments then.
        for change in (lambda d: d[BASE].update(private=True), lambda d: d[BASE].pop("private")):
            self.assertEqual(self.problems(change), ["repo is not public"])

    def test_the_subject_has_to_end_with_the_branch(self):
        changes = (
            # As it was before, and what is left if someone takes the setting away.
            lambda t: t.update(use_default=True),
            lambda t: t.pop("use_default"),
            lambda t: t.update(include_claim_keys=["repo", "context"]),
            lambda t: t.update(include_claim_keys=["repo", "ref", "context"]),
            lambda t: t.update(include_claim_keys=["repo", "context", "ref", "actor"]),
            lambda t: t.update(include_claim_keys=["context", "ref"]),
            lambda t: t.pop("include_claim_keys"),
        )
        for number, change in enumerate(changes):
            with self.subTest(number):
                self.assertEqual(self.problems(lambda d: change(d[TEMPLATE])), ["GitHub's subject does not end with the branch"])
        self.assertEqual(self.problems(lambda d: d.pop(TEMPLATE)), ["GitHub's subject does not end with the branch"])

    def test_the_subject_has_to_hold_the_ids(self):
        for change in (lambda t: t.update(use_immutable_subject=False), lambda t: t.update(sub_claim_prefix="repo:oplf-svg/cloud-labs")):
            self.assertEqual(self.problems(lambda d: change(d[TEMPLATE])), ["GitHub's subject does not hold the repo's ids"])
        # GitHub's documentation calls both of them optional.
        self.assertEqual(self.problems(lambda d: (d[TEMPLATE].pop("use_immutable_subject"), d[TEMPLATE].pop("sub_claim_prefix"))), [])

    def test_main_has_to_be_protected(self):
        path = f"{BASE}/branches/main"
        required = lambda d: d[path]["protection"]["required_status_checks"]
        changes = (
            lambda d: d[path].update(protected=False),
            lambda d: d[path].pop("protection"),
            lambda d: d[path]["protection"].pop("required_status_checks"),
            # Not for administrators.
            lambda d: required(d).update(enforcement_level="non_admins"),
            lambda d: required(d).update(checks=[]),
            lambda d: required(d).update(checks=[{"context": "another", "app_id": 15368}]),
            # From anyone who may report a check, and not only from GitHub Actions.
            lambda d: required(d).update(checks=[{"context": "ci", "app_id": None}]),
            lambda d: d.pop(path),
        )
        for number, change in enumerate(changes):
            with self.subTest(number):
                self.assertEqual(self.problems(change), ["main does not need the check ci from everyone"])
        # More than that is fine.
        self.assertEqual(self.problems(lambda d: required(d)["checks"].append({"context": "more", "app_id": 1})), [])
        self.assertEqual(self.problems(lambda d: required(d)["checks"][0].update(another="word")), [])


class Schedules(unittest.TestCase):
    def problems(self, change=None):
        data = copy.deepcopy(GOOD)
        if change:
            change(data)
        return checks.check_schedules(REPO, data.get, NOW)

    def test_accepts_a_healthy_schedule(self):
        self.assertEqual(self.problems(), [])

    def test_no_workflow(self):
        self.assertEqual(
            self.problems(lambda d: d[f"{BASE}/actions/workflows?per_page=100"].update(workflows=[])),
            ["has no nightly destroy workflow"],
        )

    def test_disabled_after_60_days(self):
        def change(data):
            data[f"{BASE}/actions/workflows?per_page=100"]["workflows"][0]["state"] = "disabled_inactivity"

        self.assertEqual(self.problems(change), ["nightly destroy is off (disabled_inactivity)"])

    def test_quiet_repo_fails_before_github_disables_it(self):
        def change(data):
            data[f"{BASE}/commits?sha=main&per_page=1"][0]["commit"]["committer"]["date"] = "2026-10-12T11:00:00Z"

        self.assertEqual(self.problems(change), ["no commit on main for 50 days, GitHub turns the schedule off at 60"])

    def test_missed_nights(self):
        def change(data):
            data[f"{BASE}/actions/workflows/7/runs?event=schedule&status=completed&per_page=1"]["workflow_runs"][0]["created_at"] = "2026-11-29T03:37:00Z"

        self.assertEqual(self.problems(change), ["last nightly destroy was 56 hours ago"])

    def test_failed_run(self):
        def change(data):
            data[f"{BASE}/actions/workflows/7/runs?event=schedule&status=completed&per_page=1"]["workflow_runs"][0]["conclusion"] = "failure"

        self.assertEqual(self.problems(change), ["last nightly destroy ended with failure"])

    def test_never_ran(self):
        self.assertEqual(
            self.problems(lambda d: d.pop(f"{BASE}/actions/workflows/7/runs?event=schedule&status=completed&per_page=1")),
            ["nightly destroy has never run on schedule"],
        )


class Main(unittest.TestCase):
    def run_main(self, *argv, data=GOOD):
        with contextlib.redirect_stdout(io.StringIO()):
            return checks.main(list(argv), fetch=data.get)

    def test_exit_codes(self):
        self.assertEqual(self.run_main("environments", REPO), 0)
        self.assertEqual(self.run_main("environments", REPO, data={}), 1)

    def test_few_requests(self):
        asked = []
        checks.check_environments(REPO, lambda path: asked.append(path) or GOOD.get(path))
        self.assertEqual(len(asked), 8)

    def test_limit_reached_is_a_failure(self):
        def refuse(path):
            raise checks.LimitReached

        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(checks.main(["environments"], fetch=refuse), 3)
        self.assertNotIn("ok", out.getvalue().split())

    def test_unknown_repo(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_main("environments", "not-a-repo")


if __name__ == "__main__":
    unittest.main()
