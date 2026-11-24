"""Runs the shell of the job "tell" of the night run with a stand-in for gh. Nothing real is called."""

import json
import pathlib
import subprocess
import tempfile
import unittest

NIGHT = pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/nightly-destroy.yml"
GH = """#!/bin/bash
printf '%s\\n' "$(printf '%s|' "$@")" >> "$LOG"
[ "$2" = list ] && printf '%s' "$OPEN"
[ "$2" != "$FAILS" ]
"""
JOBS = ("github", "aws", "azure", "gcp")


class Tell(unittest.TestCase):
    def go(self, results, open_issue="", **more):
        script = NIGHT.read_text().partition("\n  tell:\n")[2].partition("        run: |\n")[2]
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            (folder / "job.sh").write_text("".join(line[10:] + "\n" for line in script.splitlines()))
            (folder / "gh").write_text(GH)
            (folder / "gh").chmod(0o755)
            (folder / "log").write_text("")
            text = results if isinstance(results, str) else json.dumps({name: {"result": result, "outputs": {}} for name, result in results.items()})
            env = {"PATH": f"{folder}:/usr/bin:/bin", "LOG": str(folder / "log"), "OPEN": open_issue, "RESULTS": text, "FAILS": ""}
            env |= {"GITHUB_REPOSITORY": "oplf-svg/cloud-labs", "GITHUB_RUN_ID": "7"}
            # As GitHub runs a step that names no shell.
            done = subprocess.run(["/bin/bash", "-e", str(folder / "job.sh")], env=env | more, capture_output=True, text=True)
            return done.returncode, (folder / "log").read_text().splitlines()

    def test_all_well_says_nothing(self):
        self.assertEqual(self.go(dict.fromkeys(JOBS, "success")), (0, []))

    def test_each_job_that_did_not_succeed(self):
        for name in JOBS:
            for result in ("failure", "cancelled", "skipped"):
                with self.subTest(job=name, result=result):
                    code, calls = self.go(dict.fromkeys(JOBS, "success") | {name: result})
                    self.assertEqual((code, len(calls)), (0, 2), calls)
                    self.assertTrue(calls[1].startswith("issue|create|--repo|oplf-svg/cloud-labs|--title|The night run is red|--body|"), calls)
                    self.assertIn(f"{name}. @oplf-svg: https://github.com/oplf-svg/cloud-labs/actions/runs/7", calls[1])

    def test_names_all_of_them(self):
        code, calls = self.go({"github": "success", "aws": "failure", "azure": "success", "gcp": "cancelled"})
        self.assertEqual(code, 0)
        self.assertIn("|aws, gcp. @oplf-svg:", calls[1])

    def test_an_open_issue_gets_a_comment(self):
        code, calls = self.go(dict.fromkeys(JOBS, "failure"), "12")
        self.assertEqual((code, len(calls)), (0, 2))
        self.assertTrue(calls[1].startswith("issue|comment|12|--repo|oplf-svg/cloud-labs|--body|github, aws, azure, gcp. @oplf-svg"), calls)

    def test_what_it_cannot_read_makes_it_red(self):
        one_more = json.dumps({name: {"result": "success"} for name in (*JOBS, "more")})
        for strange in ("x", "{}", json.dumps({"aws": {"result": "success"}}), one_more):
            with self.subTest(strange):
                self.assertNotEqual(self.go(strange)[0], 0)

    def test_what_github_refuses_makes_it_red(self):
        for fails, open_issue in (("list", ""), ("list", "12"), ("create", ""), ("comment", "12")):
            with self.subTest(fails=fails, open_issue=open_issue):
                self.assertNotEqual(self.go(dict.fromkeys(JOBS, "failure"), open_issue, FAILS=fails)[0], 0)


if __name__ == "__main__":
    unittest.main()
