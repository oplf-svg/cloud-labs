"""Runs check_cost.py against stand-ins for GitHub, the AWS CLI, Azure and Google. Nothing real is called."""

import contextlib
import datetime
import io
import json
import pathlib
import re
import subprocess
import tempfile
import unittest
import urllib.parse

import check_cost as checks
from test_check_sign_in import ACCOUNT, BEARER, BUCKET, ENV, GOOGLE_BUCKET, GRANTED, HOME_NUMBER, KEY, OFFER, PRIVATE, PROJECT, PROVIDER, REPO, ROLES, STORE, SUBSCRIPTION, TENANT
from test_check_sign_in import jwt, no, no_blob, no_google, refuse

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SUBJECT = "repo:oplf-svg@228823995/cloud-labs@1469385611:environment:cost:ref:refs/heads/main"
TOKEN = jwt(SUBJECT)
COSTS = "example-bootstrap-1"
COST_ENV = ENV | {"AWS_ROLE_ARN": f"{ROLES}/gha-{REPO}-cost", "GCP_COST_PROJECT_ID": COSTS}
# What was spent is nobody's business here either.
SUM = "12.34567890"
HIDDEN = [value for value in PRIVATE if not value.startswith("header.")] + [TOKEN, COSTS, SUM]
TODAY = datetime.date(2026, 12, 1)
CODES = {"ec2": "UnauthorizedOperation", "ce": "AccessDeniedException", "budgets": "AccessDeniedException"}


class World:
    """GitHub and the three clouds, as they should answer. `changes` maps part of a command or a request to another answer."""

    def __init__(self, changes=None, token=TOKEN):
        self.changes, self.token, self.commands, self.requests = changes or {}, token, [], []

    def run(self, command, env, **options):
        line = " ".join(command)
        self.commands.append((command, env))
        for part in command:
            if part.startswith("file://"):
                assert pathlib.Path(part.removeprefix("file://")).read_text() == self.token
        for part, reply in self.changes.items():
            if part in line:
                return subprocess.CompletedProcess(command, *reply)
        if f"--role-arn {ROLES}/gha-{REPO}-cost " in line:
            return subprocess.CompletedProcess(command, *GRANTED)
        if "get-caller-identity" in line:
            arn = f"arn:aws:sts::{ACCOUNT}:assumed-role/gha-{REPO}-cost/check-sign-in"
            return subprocess.CompletedProcess(command, 0, json.dumps({"Account": ACCOUNT, "Arn": arn}), "")
        if "get-cost-and-usage " in line:
            return subprocess.CompletedProcess(command, 0, json.dumps({"ResultsByTime": [{"Total": {"UnblendedCost": {"Amount": SUM}}}]}), "")
        return subprocess.CompletedProcess(command, *refuse(CODES.get(command[1], "AccessDenied")))

    def send(self, method, url, headers=None, body=None):
        self.requests.append((method, url, headers or {}, body))
        line = f"{method} {urllib.parse.unquote(url)} {urllib.parse.unquote((body or b'').decode())}"
        for part, reply in self.changes.items():
            if part in line:
                return reply
        host = urllib.parse.urlsplit(url).hostname
        if host == "token.example":
            return 200, {}, json.dumps({"value": self.token}).encode()
        if host in ("login.microsoftonline.com", "sts.googleapis.com"):
            return 200, {}, json.dumps({"access_token": BEARER}).encode()
        if host == "management.azure.com":
            if "/Microsoft.CostManagement/query?" in url:
                return 200, {}, json.dumps({"properties": {"rows": [[SUM, "USD"]]}}).encode()
            return no("AuthorizationFailed")
        if host == f"{STORE}.blob.core.windows.net":
            return no_blob("AuthorizationPermissionMismatch")
        if host == "bigquery.googleapis.com":
            if method == "GET" and f"/projects/{COSTS}/datasets/billing_export/tables?" in url:
                return 200, {}, json.dumps({"tables": [{"id": f"{COSTS}:billing_export.gcp_billing_export_v1_0A0B0C"}]}).encode()
            return no_google(403, "accessDenied", status="PERMISSION_DENIED")
        if host == "cloudresourcemanager.googleapis.com":
            return no_google(403, "IAM_PERMISSION_DENIED")
        if host == "storage.googleapis.com":
            assert GOOGLE_BUCKET in url
            return no_google(403, "forbidden")
        raise AssertionError(line)


class Cost(unittest.TestCase):
    def go(self, cloud, world=None, env=None):
        world, screen = world or World(), io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            with contextlib.redirect_stdout(screen), contextlib.redirect_stderr(screen):
                code = checks.main([cloud], env=COST_ENV | {"RUNNER_TEMP": folder} | (env or {}), run=world.run, send=world.send, today=TODAY)
            self.assertEqual(list(pathlib.Path(folder).iterdir()), [])
        for value in HIDDEN:
            self.assertNotIn(value, screen.getvalue())
        return code, screen.getvalue().splitlines()

    def fails(self, cloud, changes):
        code, lines = self.go(cloud, World(changes))
        self.assertEqual(code, 1)
        return [line for line in lines if not line.startswith("ok ")]

    def test_the_intended_rights(self):
        expected = {
            "aws": [
                "sign in as gha-cloud-labs-cost: allowed",
                "become gha-cloud-labs-plan: denied",
                "become gha-cloud-labs-apply: denied",
                "become gha-cloud-labs-destroy: denied",
                "be that role, in the expected account: yes",
                "ask what a day has cost: allowed",
                "ask what a day will cost: denied",
                "ask which resources have cost it: denied",
                "read the budgets: denied",
                "look around: denied",
                "create a network: denied",
                "list the states: denied",
            ],
            "azure": [
                "sign in as id-gha-cloud-labs-cost: allowed",
                "ask what the month has cost: allowed",
                "read the budgets: denied",
                "read the resource group of cloud-labs: denied",
                "read the resource group of the bootstrap: denied",
                "prepare a deployment: denied",
                "sign in to the state storage: allowed",
                "list the state of cloud-labs: denied",
                "list the state of the bootstrap: denied",
            ],
            "gcp": [
                "sign in as the cost of cloud-labs: allowed",
                "list the tables of the costs: allowed",
                "run a query where the costs are: denied",
                "run a query where the repos deploy: denied",
                "change who may read the costs: denied",
                "read the project: denied",
                "read the project of the bootstrap: denied",
                "list the states: denied",
                "read the state of the bootstrap: denied",
            ],
        }
        for cloud, lines in expected.items():
            with self.subTest(cloud):
                self.assertEqual(self.go(cloud), (0, [f"ok   {line}" for line in [f"GitHub's subject is {SUBJECT}", *lines]]))

    def test_a_right_too_many(self):
        fine = (0, "{}", "")
        cases = {
            "aws": {
                f"{ROLES}/gha-{REPO}-plan": (GRANTED, "become gha-cloud-labs-plan"),
                f"{ROLES}/gha-{REPO}-apply": (GRANTED, "become gha-cloud-labs-apply"),
                f"{ROLES}/gha-{REPO}-destroy": (GRANTED, "become gha-cloud-labs-destroy"),
                "get-cost-forecast": (fine, "ask what a day will cost"),
                "get-cost-and-usage-with-resources": (fine, "ask which resources have cost it"),
                "describe-budgets": (fine, "read the budgets"),
                "describe-availability-zones": (fine, "look around"),
                "create-vpc": (refuse("DryRunOperation"), "create a network"),
                "list-objects-v2": (fine, "list the states"),
            },
            "azure": {
                "/budgets?": ((200, {}, b"{}"), "read the budgets"),
                f"/rg-{REPO}?": ((200, {}, b"{}"), "read the resource group of cloud-labs"),
                "/rg-github-bootstrap?": ((200, {}, b"{}"), "read the resource group of the bootstrap"),
                "/validate?": ((200, {}, b"{}"), "prepare a deployment"),
                f"/{REPO}?restype": ((200, {}, b"<x/>"), "list the state of cloud-labs"),
                "/bootstrap?restype": ((200, {}, b"<x/>"), "list the state of the bootstrap"),
            },
            "gcp": {
                f"/projects/{COSTS}/queries": ((200, {}, b"{}"), "run a query where the costs are"),
                f"/projects/{PROJECT}/queries": ((200, {}, b"{}"), "run a query where the repos deploy"),
                "PATCH": (no_google(412, "conditionNotMet"), "change who may read the costs"),
                f"v3/projects/{PROJECT}": ((200, {}, b"{}"), "read the project"),
                f"v3/projects/{HOME_NUMBER}": ((200, {}, b"{}"), "read the project of the bootstrap"),
                "/o?maxResults": ((200, {}, b"{}"), "list the states"),
                "/o/bootstrap": ((200, {}, b"{}"), "read the state of the bootstrap"),
            },
        }
        for cloud, changes in cases.items():
            for part, (reply, what) in changes.items():
                with self.subTest(what):
                    self.assertEqual(self.fails(cloud, {part: reply}), [f"FAIL {what}: allowed, should be denied"])

    def test_a_right_too_few(self):
        cases = {
            "aws": ({"get-cost-and-usage ": refuse("AccessDeniedException")}, "ask what a day has cost"),
            "azure": ({"/Microsoft.CostManagement/query?": no("AuthorizationFailed")}, "ask what the month has cost"),
            "gcp": ({"/tables?": no_google(403, "accessDenied")}, "list the tables of the costs"),
        }
        for cloud, (changes, what) in cases.items():
            with self.subTest(cloud):
                self.assertEqual(self.fails(cloud, changes), [f"FAIL {what}: denied, should be allowed"])

    def test_costs_that_are_not_there_yet_are_no_success(self):
        # Cost Explorer was never opened, the service is busy, or the API is off.
        cases = (
            ("aws", {"get-cost-and-usage ": refuse("DataUnavailableException")}, "ask what a day has cost: DataUnavailableException"),
            ("azure", {"/Microsoft.CostManagement/query?": (429, {}, b"{}")}, "ask what the month has cost: HTTP 429"),
            ("gcp", {"/tables?": no_google(404, "notFound")}, "list the tables of the costs: notFound"),
            ("gcp", {"/tables?": no_google(403, "SERVICE_DISABLED", status="PERMISSION_DENIED")}, "list the tables of the costs: SERVICE_DISABLED"),
        )
        for cloud, changes, line in cases:
            with self.subTest(line):
                self.assertEqual(self.fails(cloud, changes), [f"FAIL {line}, should be allowed"])

    def test_another_error_is_not_taken_for_a_refusal(self):
        cases = (
            ("aws", {"describe-budgets": refuse("ThrottlingException")}, "read the budgets: ThrottlingException"),
            ("azure", {f"/rg-{REPO}?": (503, {}, TENANT.encode())}, "read the resource group of cloud-labs: HTTP 503"),
            ("gcp", {f"/projects/{PROJECT}/queries": no_google(403, "SERVICE_DISABLED", status="PERMISSION_DENIED")}, "run a query where the repos deploy: SERVICE_DISABLED"),
            ("gcp", {"/o?maxResults": no_google(403, "USER_PROJECT_DENIED", status="PERMISSION_DENIED")}, "list the states: USER_PROJECT_DENIED"),
        )
        for cloud, changes, line in cases:
            with self.subTest(line):
                self.assertEqual(self.fails(cloud, changes), [f"FAIL {line}, should be denied"])

    def test_stops_when_the_sign_in_is_refused(self):
        cases = (
            ("aws", {"assume-role": refuse("AccessDenied")}, "sign in as gha-cloud-labs-cost: denied"),
            ("azure", {"login.microsoftonline.com": (400, {}, b"AADSTS700213: no match for " + SUBSCRIPTION.encode())}, "sign in as id-gha-cloud-labs-cost: AADSTS700213"),
            ("azure", {"scope=https://storage.azure.com": (400, {}, b"AADSTS500011")}, "sign in to the state storage: AADSTS500011"),
            ("gcp", {"sts.googleapis.com": (400, {}, b'{"error": "unauthorized_client", "error_description": "' + PROVIDER.encode() + b'"}')}, "sign in as the cost of cloud-labs: unauthorized_client"),
        )
        for cloud, changes, line in cases:
            with self.subTest(line):
                world = World(changes)
                self.assertEqual(self.go(cloud, world)[1][-1], f"FAIL {line}, should be allowed")
                self.assertEqual(sum(BEARER in headers.get("Authorization", "") for _, _, headers, _ in world.requests), 0 if "storage" not in line else 5)
                self.assertLessEqual(len(world.commands), 1)

    def test_notices_another_account_or_role(self):
        for arn in (f"arn:aws:sts::{ACCOUNT}:assumed-role/gha-{REPO}-plan/check-sign-in", f"arn:aws:sts::444455556666:assumed-role/gha-{REPO}-cost/check-sign-in"):
            found = self.fails("aws", {"get-caller-identity": (0, json.dumps({"Arn": arn}), "")})
            self.assertEqual(found, ["FAIL be that role, in the expected account: no, should be yes"])

    def test_one_question_about_costs_that_is_paid_for(self):
        world = World()
        self.go("aws", world)
        asked = [" ".join(command) for command, _ in world.commands if "ce" in command]
        self.assertEqual(sum("get-cost-and-usage " in line for line in asked), 1)
        self.assertEqual(len(asked), 3)
        for line in asked:
            self.assertIn("--region us-east-1", line)
        self.assertIn("--time-period Start=2026-11-30,End=2026-12-01", next(line for line in asked if "get-cost-and-usage " in line))

    def test_nothing_can_be_changed(self):
        for cloud in checks.CHECKS:
            world = World()
            self.go(cloud, world)
            for command, env in world.commands:
                reads = command[2].startswith(("assume-role-with-web-identity", "describe-", "get-", "list-"))
                self.assertTrue(reads or "--dry-run" in command, command)
                self.assertEqual("AWS_SESSION_TOKEN" in env, "assume-role-with-web-identity" not in command)
                self.assertFalse([name for name in env if name.startswith("ACTIONS_") or name in COST_ENV and name.startswith(("AWS_", "AZURE_", "GCP_"))])
                self.assertNotIn(TOKEN, " ".join(command))
            for method, url, headers, body in world.requests:
                host, sent = urllib.parse.urlsplit(url).hostname, (body or b"").decode()
                signs_in = host in ("login.microsoftonline.com", "sts.googleapis.com")
                asks = "/Microsoft.CostManagement/query?" in url or "/validate?" in url and json.loads(sent)["properties"]["template"]["resources"] == []
                dry = url.endswith("/queries") and json.loads(sent)["dryRun"] is True
                never = method == "PATCH" and sent == "{}" and headers["If-Match"] == checks.NEVER
                self.assertTrue(method == "GET" or method == "POST" and (signs_in or asks or dry) or never, url)

    def test_each_token_goes_only_where_it_belongs(self):
        for cloud in checks.CHECKS:
            world = World()
            self.go(cloud, world)
            for _, url, headers, body in world.requests:
                parts = urllib.parse.urlsplit(url)
                self.assertEqual(parts.scheme, "https")
                signs_in = parts.hostname in ("login.microsoftonline.com", "sts.googleapis.com")
                self.assertEqual(TOKEN in urllib.parse.unquote((body or b"").decode()), signs_in)
                bearer = headers.get("Authorization", "").removeprefix("Bearer ")
                self.assertEqual(bearer, OFFER if parts.hostname == "token.example" else "" if signs_in else BEARER)
                self.assertNotIn("X-Goog-User-Project", headers)
                for secret in (TOKEN, BEARER, OFFER):
                    self.assertNotIn(secret, url)

    def test_only_the_cost_identity_may_run_it(self):
        prefix = SUBJECT.partition(":environment:")[0]
        for sent, shown in (
            (f"{prefix}:environment:plan:ref:refs/heads/main", None),
            (f"{prefix}:environment:cost", None),
            (f"{prefix}:environment:cost:ref:refs/heads/agent", None),
            (f"{prefix}:pull_request", None),
            ("repo:x:ref:refs/heads/a b\n::add", "repo:x:ref:refs/heads/a?b?::add"),
        ):
            world = World(token=jwt(sent))
            code, lines = self.go("aws", world)
            self.assertEqual((code, lines), (1, [f"Not checked. GitHub's subject is {shown or sent}, not the one in cost.json."]))
            self.assertEqual(world.commands, [])

    def test_says_what_is_missing(self):
        for cloud, name in (("aws", "AWS_ROLE_ARN"), ("azure", "AZURE_CLIENT_ID"), ("gcp", "GCP_COST_PROJECT_ID")):
            self.assertEqual(self.go(cloud, env={name: ""}), (1, [f"Not checked. Not set: {name}."]))
        for repo in ("oplf-svg/webhook-platform", "someone/cloud-labs", ""):
            self.assertEqual(self.go("aws", env={"GITHUB_REPOSITORY": repo}), (1, ["Not checked. This is not the repo that has an identity for costs."]))

    def test_a_crash_shows_only_its_kind(self):
        world = World()

        def broken(*_, **__):
            raise FileNotFoundError(f"{ROLES} {BUCKET} {TOKEN} {KEY}")

        world.run = broken
        self.assertEqual(self.go("aws", world)[1][-1], "Stopped by FileNotFoundError.")


class Workflow(unittest.TestCase):
    text = (ROOT / ".github/workflows/cost.yml").read_text()

    def test_gives_each_job_the_secrets_of_its_own_cloud_and_no_others(self):
        text = self.text.partition("\njobs:\n")[2] + "\n"
        jobs = dict(re.findall(r"^  (\w+):\n((?:(?:    .*)?\n)+)", text, re.MULTILINE))
        self.assertEqual(set(jobs), set(checks.CHECKS))
        for cloud, (_, more) in checks.CHECKS.items():
            needed = [*checks.CLOUDS[cloud][0], *more]
            used = re.findall(r"^      (\w+): \$\{\{ secrets\.(\w+) \}\}$", jobs[cloud], re.MULTILINE)
            self.assertEqual(sorted(used), sorted((name, name) for name in needed))
            self.assertEqual(jobs[cloud].count("{{ secrets."), len(needed))
            self.assertIn(f"run: python3 bootstrap/scripts/check_cost.py {cloud}\n", jobs[cloud])
            self.assertIn("\n    environment:\n      name: cost\n      deployment: false\n", jobs[cloud])

    def test_runs_on_main_only(self):
        starts = self.text.partition("\non:\n")[2].partition("\npermissions:")[0]
        self.assertEqual(
            starts.split("\n"),
            ["  push:", "    branches: [main]", "    paths:", "      - bootstrap/**", "      - .github/workflows/cost.yml", "  workflow_dispatch:", ""],
        )

    def test_uses_only_the_action_that_ci_uses(self):
        used = set(re.findall(r"uses: (\S+)", self.text))
        self.assertEqual(len(used), 1)
        self.assertLessEqual(used, set(re.findall(r"uses: (\S+)", (ROOT / ".github/workflows/ci.yml").read_text())))


if __name__ == "__main__":
    unittest.main()
