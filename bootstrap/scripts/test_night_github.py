"""Runs the part of the night that looks at GitHub against stand-ins. Nothing real is called."""

import contextlib
import copy
import io
import unittest
import unittest.mock

import night
import night_github
from test_github_checks import GOOD

REPO = "cloud-labs"


class Rules(unittest.TestCase):
    def test_the_rules_on_github(self):
        fine, asked = "in place", []

        def check(answers, token="github-token"):
            def fetch(path):
                asked.append(path)
                return answers[path.split("/")[3]]

            screen = io.StringIO()
            with contextlib.redirect_stdout(screen), unittest.mock.patch.object(night_github, "check_environments", lambda repo, fetch: fetch(f"/repos/oplf-svg/{repo}")):
                # No cloud, so nothing of one is there.
                code = night.main(["github"], env={"GITHUB_TOKEN": token, "GITHUB_REPOSITORY": f"oplf-svg/{REPO}"}, run=None, send=None, fetch=fetch)
            self.assertNotIn("github-token", screen.getvalue())
            return code, screen.getvalue().splitlines()

        good = {repo: [] for repo in night_github.SUBJECTS}
        self.assertEqual(check(good), (0, [f"ok   find the rules of {repo}: {fine}" for repo in night_github.SUBJECTS]))
        self.assertEqual(asked, [f"/repos/oplf-svg/{repo}" for repo in night_github.SUBJECTS])
        for repo in night_github.SUBJECTS:
            code, output = check(good | {repo: ["environment plan does not exist", "repo is not public"]})
            self.assertEqual((code, [line for line in output if line.startswith("FAIL")]), (1, [f"FAIL find the rules of {repo}: environment plan does not exist; repo is not public, should be {fine}"]))
            self.assertEqual(len(output), len(night_github.SUBJECTS))
        self.assertEqual(check(good, token=""), (1, ["Not checked. Not set: GITHUB_TOKEN."]))

    def test_a_refusal_by_github_is_no_success(self):
        for problem, line in ((night_github.LimitReached(), "Not checked. GitHub did not show the rules of webhook-platform: not allowed, or asked too often."), (TimeoutError("x"), "Stopped by TimeoutError.")):
            def fetch(path, problem=problem):
                raise problem

            screen = io.StringIO()
            with contextlib.redirect_stdout(screen):
                code = night.main(["github"], env={"GITHUB_TOKEN": "x"}, fetch=fetch)
            self.assertEqual((code, screen.getvalue().splitlines()), (1, [line]))

    def test_with_the_real_checks(self):
        # Everything as it should be in the one repo that the stand-in knows, and nothing known about the others.
        def look(change=None):
            data = copy.deepcopy(GOOD)
            if change:
                change(data)
            screen = io.StringIO()
            with contextlib.redirect_stdout(screen):
                code = night.main(["github"], env={"GITHUB_TOKEN": "x"}, fetch=data.get)
            return code, dict(line[5:].rsplit(": ", 1) for line in screen.getvalue().splitlines() if REPO in line), screen.getvalue()

        code, found, screen = look()
        self.assertEqual((code, found), (1, {f"find the rules of {REPO}": "in place"}))
        self.assertEqual(screen.count("repo does not exist or is not public"), 4)
        _, found, _ = look(lambda d: d[f"/repos/oplf-svg/{REPO}/environments"]["environments"][0].update(protection_rules=[{"type": "branch_policy"}]))
        self.assertEqual(found, {f"find the rules of {REPO}": "environment production must have a required reviewer, should be in place"})


if __name__ == "__main__":
    unittest.main()
