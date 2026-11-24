import contextlib
import copy
import datetime
import io
import unittest

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


GOOD = {
    BASE: {"id": 1469385611, "owner": {"id": 228823995}},
    f"{BASE}/environments": {"environments": [environment("production", True), environment("nightly-destroy", False)]},
    f"{BASE}/environments/production/deployment-branch-policies": {"branch_policies": [{"name": "main", "type": "branch"}]},
    f"{BASE}/environments/nightly-destroy/deployment-branch-policies": {"branch_policies": [{"name": "main", "type": "branch"}]},
    f"{BASE}/actions/workflows?per_page=100": {"workflows": [{"id": 7, "path": checks.DESTROY_WORKFLOW, "state": "active"}]},
    f"{BASE}/commits?sha=main&per_page=1": [{"commit": {"committer": {"date": "2026-11-28T12:00:00Z"}}}],
    f"{BASE}/actions/workflows/7/runs?event=schedule&per_page=1": {
        "workflow_runs": [{"created_at": "2026-12-01T03:37:00Z", "status": "completed", "conclusion": "success"}]
    },
}


class Environments(unittest.TestCase):
    def problems(self, change=None):
        data = copy.deepcopy(GOOD)
        if change:
            change(data)
        return checks.check_environments(REPO, data.get)

    def test_accepts_the_intended_setup(self):
        self.assertEqual(self.problems(), [])

    def test_missing_destroy_environment(self):
        self.assertEqual(
            self.problems(lambda d: d[f"{BASE}/environments"]["environments"].pop()),
            ["environment nightly-destroy does not exist"],
        )

    def test_unprotected_destroy_environment(self):
        # What GitHub creates by itself when a workflow names an environment that does not exist.
        def change(data):
            data[f"{BASE}/environments"]["environments"][1].update(
                protection_rules=[], can_admins_bypass=True, deployment_branch_policy=None
            )

        self.assertEqual(len(self.problems(change)), 2)

    def test_extra_branch(self):
        def change(data):
            data[f"{BASE}/environments/nightly-destroy/deployment-branch-policies"]["branch_policies"].append(
                {"name": "*", "type": "branch"}
            )

        self.assertEqual(self.problems(change), ["environment nightly-destroy allows more or less than the main branch"])

    def test_tag_named_main(self):
        def change(data):
            data[f"{BASE}/environments/production/deployment-branch-policies"]["branch_policies"][0]["type"] = "tag"

        self.assertEqual(self.problems(change), ["environment production allows more or less than the main branch"])

    def test_production_without_reviewer(self):
        def change(data):
            data[f"{BASE}/environments"]["environments"][0]["protection_rules"].pop()

        self.assertEqual(self.problems(change), ["environment production must have a required reviewer"])

    def test_recreated_repo_has_a_new_id(self):
        self.assertEqual(
            self.problems(lambda d: d[BASE].update(id=1)),
            ["subjects.json does not match the repo's ids"],
        )


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
            data[f"{BASE}/actions/workflows/7/runs?event=schedule&per_page=1"]["workflow_runs"][0]["created_at"] = "2026-11-29T03:37:00Z"

        self.assertEqual(self.problems(change), ["last nightly destroy was 56 hours ago"])

    def test_failed_run(self):
        def change(data):
            data[f"{BASE}/actions/workflows/7/runs?event=schedule&per_page=1"]["workflow_runs"][0]["conclusion"] = "failure"

        self.assertEqual(self.problems(change), ["last nightly destroy ended with failure"])

    def test_never_ran(self):
        self.assertEqual(
            self.problems(lambda d: d.pop(f"{BASE}/actions/workflows/7/runs?event=schedule&per_page=1")),
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
        self.assertEqual(len(asked), 4)

    def test_limit_reached_is_a_failure(self):
        def refuse(path):
            raise checks.LimitReached

        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(checks.main(["environments"], fetch=refuse), 1)
        self.assertNotIn("ok", out.getvalue().split())

    def test_unknown_repo(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_main("environments", "not-a-repo")


if __name__ == "__main__":
    unittest.main()
