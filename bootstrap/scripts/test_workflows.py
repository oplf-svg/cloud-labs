"""What every workflow has to keep to, so that no code gets a cloud token before a person has approved it into main."""

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TRUSTED = [json.loads((ROOT / "bootstrap" / file).read_text()) for file in ("subjects.json", "cost.json")]

# The only places where the clouds trust a job. GitHub lets only main into them, which github_checks.py checks.
TIERS, COSTS = ({subject.partition(":environment:")[2].removesuffix(":ref:refs/heads/main") for some in file.values() for subject in some.values()} for file in TRUSTED)
ENVIRONMENTS = TIERS | COSTS

# No others: some run what is on main for whoever sends something in, and some run what was sent in.
TRIGGERS = {"pull_request", "push", "schedule", "workflow_dispatch"}

RIGHTS = {"actions: read", "contents: read", "id-token: write", "pull-requests: read"}


def block(text):
    """The keys of a block and what belongs to each, two columns further to the left."""
    found = re.findall(r"^([A-Za-z_-]+):(.*(?:\n(?: .*)?)*)", text, re.M)
    return {key: re.sub(r"(?m)^  ", "", value).strip() for key, value in found}


def environment(job):
    """The name of a job's environment. It can also be written in a way that keeps the job out of GitHub's list of deployments."""
    return re.sub(r"\Aname: ([a-z-]+)\ndeployment: false\Z", r"\1", job["environment"]) if "environment" in job else None


class Workflows(unittest.TestCase):
    def setUp(self):
        self.texts = {path.name: re.sub(r"(?m)^ *#.*\n", "", path.read_text()) for path in (ROOT / ".github/workflows").iterdir()}
        self.assertEqual(set(self.texts), {"ci.yml", "cost.yml", "nightly-destroy.yml", "sign-in.yml", "site.yml"})
        self.workflows = {file: block(text) for file, text in self.texts.items()}

    def each_job(self):
        for file, workflow in self.workflows.items():
            jobs = {name: block(text) for name, text in block(workflow["jobs"]).items()}
            # None is missed, however it is written.
            self.assertEqual(sum("runs-on" in job for job in jobs.values()), self.texts[file].count("runs-on:"), file)
            for name, job in jobs.items():
                with self.subTest(file=file, job=name):
                    yield file, name, job, jobs

    def test_the_environments_are_the_four(self):
        self.assertEqual((TIERS, COSTS), ({"plan", "production", "nightly-destroy"}, {"cost"}))

    def test_only_the_jobs_about_costs_are_in_the_environment_for_them(self):
        found = {(file, name) for file, name, job, _ in self.each_job() if environment(job) in COSTS}
        self.assertEqual(found, {("cost.yml", cloud) for cloud in ("aws", "azure", "gcp")})
        for file, name, job, _ in self.each_job():
            if file == "cost.yml":
                self.assertEqual(environment(job), "cost")
                self.assertRegex(job["steps"], r"\A- uses: actions/checkout@[0-9a-f]{40} # v[0-9.]+\n  with:\n    persist-credentials: false\n- run: python3 bootstrap/scripts/check_cost\.py (?:aws|azure|gcp)\Z")
            else:
                self.assertNotIn("GCP_COST_PROJECT_ID", "\n".join(job.values()))

    def test_what_deploys_is_in_the_list_of_deployments(self):
        for file, name, job, _ in self.each_job():
            if environment(job) == "production":
                self.assertEqual(job["environment"], "production")

    def test_what_the_clock_starts(self):
        """The night twice: GitHub may drop a start, and then nobody would look that night. The site's looks each morning."""
        starts = {file: block(workflow["on"]).get("schedule", "").split("\n") for file, workflow in self.workflows.items()}
        night, morning, never = ['- cron: "17 2 * * *"', '- cron: "17 4 * * *"'], ['- cron: "41 6 * * *"'], [""]
        self.assertEqual(starts, dict.fromkeys(self.workflows, never) | {"nightly-destroy.yml": night, "site.yml": morning})

    def test_the_rules_are_looked_at_without_an_identity(self):
        (job,) = [job for file, name, job, _ in self.each_job() if (file, name) == ("nightly-destroy.yml", "github")]
        self.assertEqual(job["permissions"], "actions: read\ncontents: read")
        self.assertNotIn("environment", job)
        self.assertNotIn("secrets", "\n".join(job.values()))
        self.assertTrue(job["steps"].endswith("- run: python3 bootstrap/scripts/night.py github"))

    def test_the_job_that_tells_runs_nothing_of_the_repo(self):
        ((jobs, job),) = [(jobs, job) for file, name, job, jobs in self.each_job() if (file, name) == ("nightly-destroy.yml", "tell")]
        self.assertEqual((job["if"], job["permissions"]), ("${{ always() }}", "issues: write"))
        self.assertEqual(job["needs"], "[" + ", ".join(name for name in jobs if name != "tell") + "]")
        self.assertEqual(set(job), {"if", "needs", "runs-on", "timeout-minutes", "permissions", "steps"})
        (step,) = re.split(r"(?m)^- ", job["steps"])[1:]
        self.assertNotRegex(step, r"uses:|bootstrap|python|secrets")
        self.assertEqual(re.findall(r"\$\{\{ (.*?) \}\}", step), ["github.token", "toJSON(needs)"])
        self.assertNotIn("${{", step.partition("run: |")[2])

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
            tells = (file, name) == ("nightly-destroy.yml", "tell")
            self.assertLessEqual(set(filter(None, job.get("permissions", "").split("\n"))), {"issues: write"} if tells else RIGHTS)
            # What another workflow would ask for cannot be seen here.
            self.assertNotIn("uses", job)

    def test_a_token_is_only_for_jobs_in_an_environment(self):
        found = {file: set() for file in self.workflows}
        for file, name, job, _ in self.each_job():
            if "id-token" in job.get("permissions", ""):
                found[file].add(name)
                self.assertIn(environment(job), ENVIRONMENTS)
        clouds = {"aws", "azure", "gcp"}
        site = {"look-aws", "look-azure", "deploy-aws", "deploy-azure"}
        self.assertEqual(found, {"ci.yml": set(), "cost.yml": clouds, "nightly-destroy.yml": clouds, "sign-in.yml": clouds, "site.yml": site})
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
                self.assertIn(environment(job), ENVIRONMENTS)
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
