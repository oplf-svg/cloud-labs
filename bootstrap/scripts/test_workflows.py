"""What every workflow has to keep to, so that no code gets a cloud token before a person has approved it into main."""

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBJECTS = json.loads((ROOT / "bootstrap/subjects.json").read_text())

# The only places where the clouds trust a job. GitHub lets only main into them, which github_checks.py checks.
ENVIRONMENTS = {subject.partition(":environment:")[2] for tiers in SUBJECTS.values() for subject in tiers.values()}

# No others: some run what is on main for whoever sends something in, and some run what was sent in.
TRIGGERS = {"pull_request", "push", "schedule", "workflow_dispatch"}

RIGHTS = {"actions: read", "contents: read", "id-token: write", "pull-requests: read"}


def block(text):
    """The keys of a block and what belongs to each, two columns further to the left."""
    found = re.findall(r"^([A-Za-z_-]+):(.*(?:\n(?: .*)?)*)", text, re.M)
    return {key: re.sub(r"(?m)^  ", "", value).strip() for key, value in found}


class Workflows(unittest.TestCase):
    def setUp(self):
        self.texts = {path.name: re.sub(r"(?m)^ *#.*\n", "", path.read_text()) for path in (ROOT / ".github/workflows").iterdir()}
        self.assertEqual(set(self.texts), {"ci.yml", "nightly-destroy.yml", "sign-in.yml", "site.yml"})
        self.workflows = {file: block(text) for file, text in self.texts.items()}

    def each_job(self):
        for file, workflow in self.workflows.items():
            jobs = {name: block(text) for name, text in block(workflow["jobs"]).items()}
            # None is missed, however it is written.
            self.assertEqual(sum("runs-on" in job for job in jobs.values()), self.texts[file].count("runs-on:"), file)
            for name, job in jobs.items():
                with self.subTest(file=file, job=name):
                    yield file, name, job, jobs

    def test_the_environments_are_the_three(self):
        self.assertEqual(ENVIRONMENTS, {"plan", "production", "nightly-destroy"})

    def test_nothing_else_starts_a_workflow(self):
        for file, workflow in self.workflows.items():
            with self.subTest(file):
                starts = block(workflow["on"])
                self.assertGreater(len(starts), 0)
                self.assertLessEqual(set(starts), TRIGGERS)
                if "push" in starts:
                    self.assertEqual(block(starts["push"])["branches"], "[main]")
                    self.assertLessEqual(set(block(starts["push"])), {"branches", "paths"})

    def test_no_job_has_other_rights(self):
        for file, workflow in self.workflows.items():
            self.assertEqual(workflow["permissions"], "{}", file)
            self.assertNotRegex(self.texts[file], "write-all|read-all")
        for file, name, job, _ in self.each_job():
            self.assertLessEqual(set(filter(None, job.get("permissions", "").split("\n"))), RIGHTS)
            # What another workflow would ask for cannot be seen here.
            self.assertNotIn("uses", job)

    def test_a_token_is_only_for_jobs_in_an_environment(self):
        found = {file: set() for file in self.workflows}
        for file, name, job, _ in self.each_job():
            if "id-token" in job.get("permissions", ""):
                found[file].add(name)
                self.assertIn(job.get("environment"), ENVIRONMENTS)
        clouds = {"aws", "azure", "gcp"}
        site = {"look-aws", "look-azure", "deploy-aws", "deploy-azure"}
        self.assertEqual(found, {"ci.yml": set(), "nightly-destroy.yml": clouds, "sign-in.yml": clouds, "site.yml": site})
        for file, text in self.texts.items():
            self.assertEqual(text.count("id-token"), len(found[file]), file)

    def test_a_pull_request_skips_every_job_that_could_ask_for_one(self):
        def skipped(job, jobs):
            condition = job.get("if", "")
            needed = re.findall(r"needs\.([a-z-]+)\.result == 'success'", condition)
            return condition == "${{ github.event_name != 'pull_request' }}" or any(skipped(jobs[name], jobs) for name in needed)

        for file, name, job, jobs in self.each_job():
            if "id-token" in job.get("permissions", "") and "pull_request" in block(self.workflows[file]["on"]):
                self.assertTrue(skipped(job, jobs))

    def test_ids_of_a_cloud_are_only_for_jobs_in_an_environment(self):
        for file, name, job, _ in self.each_job():
            if re.search(r"secrets(?:\.|\[')(?:AWS|AZURE|GCP)_", "\n".join(job.values())):
                self.assertIn(job.get("environment"), ENVIRONMENTS)
        for file, workflow in self.workflows.items():
            self.assertNotIn("env", workflow, file)
            self.assertNotIn("toJSON(secrets)", self.texts[file])


    def test_what_reads_the_private_terms_was_approved(self):
        """A pull request could otherwise change the check, and print the terms into a public log."""
        for file, name, job, _ in self.each_job():
            held = re.findall(r"secrets(?:\.|\[)[^}]*", "\n".join(job.values()))
            if (file, name) != ("ci.yml", "blocked-terms"):
                self.assertNotRegex("\n".join(job.values()), r"(?i)BLOCKED_TERMS|PRIVATE_TERMS")
                if file == "ci.yml":
                    self.assertEqual(held, [])
                continue
            self.assertEqual([one.strip() for one in held], ["secrets.PRIVATE_TERMS"])
            steps = re.split(r"(?m)^- ", job["steps"])[1:]
            approved, aside, pull, title, look = steps
            self.assertRegex(approved, r"\Auses: actions/checkout@[0-9a-f]{40} # v[0-9.]+\n  with:\n    ref: [0-9a-f]{40}\n    persist-credentials: false\s*\Z")
            self.assertEqual(aside.strip(), 'run: cp .github/scripts/blocked_terms.py "$RUNNER_TEMP/blocked_terms.py"')
            self.assertRegex(pull, r"\Auses: actions/checkout@[0-9a-f]{40} # v[0-9.]+\n  with:\n    fetch-depth: 0\n    persist-credentials: false\s*\Z")
            self.assertEqual(re.findall(r"run: (.*)", title), ['gh api "repos/$GITHUB_REPOSITORY/pulls/$NUMBER" > "$RUNNER_TEMP/pull.json"'])
            self.assertEqual(re.findall(r"run: (.*)", look), ['python3 -I "$RUNNER_TEMP/blocked_terms.py"'])
            self.assertNotIn("env", job)
        for file in self.texts:
            self.assertEqual(self.texts[file].count("secrets.PRIVATE_TERMS"), int(file == "ci.yml"), file)


if __name__ == "__main__":
    unittest.main()
