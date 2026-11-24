"""Runs check_sign_in.py against stand-ins for GitHub, the AWS CLI and Azure. Nothing real is called."""

import base64
import contextlib
import io
import json
import pathlib
import re
import subprocess
import tempfile
import unittest
import urllib.parse

import check_sign_in as checks

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
REPO, OTHER = "cloud-labs", "webhook-platform"
SUBJECT = "repo:oplf-svg@228823995/cloud-labs@1469385611:pull_request"

ACCOUNT, BUCKET = "111122223333", "tfstate-0a1b2c3d"
ROLES = f"arn:aws:iam::{ACCOUNT}:role/github-actions"
CLIENT, SUBSCRIPTION, TENANT = (f"00000000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
STORE = "tfstate0a1b2c3d"
OFFER = "request-token-of-the-job"
KEY, SECRET, SESSION, BEARER = "ASIAEXAMPLEKEY", "example-secret-key", "example-session-token", "example-access-token"

ENV = {
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": OFFER,
    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.example/ask?api-version=2.0",
    "AWS_ACCOUNT_ID": ACCOUNT,
    "AWS_ROLE_ARN": f"{ROLES}/gha-{REPO}-plan",
    "AWS_STATE_BUCKET": BUCKET,
    "AZURE_CLIENT_ID": CLIENT,
    "AZURE_STATE_ACCOUNT": STORE,
    "AZURE_SUBSCRIPTION_ID": SUBSCRIPTION,
    "AZURE_TENANT_ID": TENANT,
    "GITHUB_REPOSITORY": f"oplf-svg/{REPO}",
    "HOME": "/home/runner",
    "PATH": "/usr/bin",
}


def jwt(subject):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": subject}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


TOKEN = jwt(SUBJECT)

# What must never be in a public log.
PRIVATE = [ACCOUNT, BUCKET, ROLES, CLIENT, SUBSCRIPTION, TENANT, STORE, OFFER, KEY, SECRET, SESSION, BEARER, TOKEN]

# What AWS says when it lets someone in.
GRANTED = 0, json.dumps({"Credentials": {"AccessKeyId": KEY, "SecretAccessKey": SECRET, "SessionToken": SESSION}}), ""


def refuse(code):
    # As AWS does, with everything in it that a log must not show.
    return 254, "", f"aws: [ERROR]: An error occurred ({code}) when calling it: {ROLES} may not use {BUCKET} in {ACCOUNT}"


class FakeAws:
    """Answers as AWS should. `changes` maps part of a command to another answer."""

    def __init__(self, changes=None, repo=REPO):
        self.changes, self.repo, self.commands, self.token_files = changes or {}, repo, [], set()

    def answer(self, line):
        for part, reply in self.changes.items():
            if part in line:
                return reply
        if f"--role-arn {ROLES}/gha-{self.repo}-plan " in line:
            return GRANTED
        if "get-caller-identity" in line:
            arn = f"arn:aws:sts::{ACCOUNT}:assumed-role/gha-{self.repo}-plan/check-sign-in"
            return 0, json.dumps({"UserId": "AROAEXAMPLE:check-sign-in", "Account": ACCOUNT, "Arn": arn}), ""
        if "describe-availability-zones" in line:
            return 0, "{}", ""
        if "create-vpc" in line:
            return refuse("UnauthorizedOperation")
        if f"get-object --bucket {BUCKET} --key {self.repo}/" in line:
            return refuse("NoSuchKey")
        return refuse("AccessDenied")

    def __call__(self, command, env, **options):
        self.commands.append((command, env))
        for part in command:
            if part.startswith("file://"):
                path = pathlib.Path(part.removeprefix("file://"))
                self.token_files.add(path)
                assert path.read_text() == jwt(checks.SUBJECTS[self.repo]["plan"])
        assert options["stdout"] == options["stderr"] == subprocess.PIPE
        return subprocess.CompletedProcess(command, *self.answer(" ".join(command)))


def no(code):
    # As Azure does, with everything in it that a log must not show.
    message = f"The client {CLIENT} may not use {SUBSCRIPTION} in {TENANT}"
    return 403, {}, json.dumps({"error": {"code": code, "message": message}}).encode()


def no_blob(code, status=403):
    return status, {"x-ms-error-code": code}, f"<Error><Message>{STORE} {TENANT}</Message></Error>".encode()


class FakeWeb:
    """Answers as GitHub and Azure should. `changes` maps part of a request to another answer."""

    def __init__(self, changes=None, token=TOKEN, repo=REPO):
        self.changes, self.token, self.repo, self.requests = changes or {}, token, repo, []

    def __call__(self, method, url, headers=None, body=None):
        self.requests.append((method, url, headers or {}, body))
        line = f"{method} {url} {urllib.parse.unquote((body or b'').decode())}"
        for part, reply in self.changes.items():
            if part in line:
                return reply
        host = urllib.parse.urlsplit(url).hostname
        if host == "token.example":
            return 200, {}, json.dumps({"value": self.token}).encode()
        if host == "login.microsoftonline.com":
            return 200, {}, json.dumps({"access_token": BEARER}).encode()
        if host == "management.azure.com":
            return (200, {}, b"{}") if f"/rg-{self.repo}?" in url else no("AuthorizationFailed")
        if host == f"{STORE}.blob.core.windows.net":
            return (200, {}, b"<x/>") if f"/{self.repo}?restype" in url else no_blob("AuthorizationPermissionMismatch")
        raise AssertionError(line)


def run(cloud, aws=None, web=None, env=None):
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        status = checks.main([cloud], env=env or ENV, run=aws or FakeAws(), send=web or FakeWeb())
    return status, output.getvalue()


class Base(unittest.TestCase):
    def assert_private(self, output):
        for value in PRIVATE:
            self.assertNotIn(value, output)

    def assert_fails_only(self, result, line):
        status, output = result
        self.assertEqual(status, 1)
        self.assertEqual([text for text in output.splitlines() if not text.startswith("ok ")], [line])
        self.assert_private(output)


class Aws(Base):
    def test_accepts_the_intended_rights(self):
        status, output = run("aws")
        self.assertEqual(status, 0)
        self.assertEqual(
            output.splitlines(),
            [
                f"ok   GitHub's subject is {SUBJECT}",
                "ok   sign in as gha-cloud-labs-plan: allowed",
                "ok   become gha-cloud-labs-apply: denied",
                "ok   become gha-cloud-labs-destroy: denied",
                "ok   become gha-webhook-platform-plan: denied",
                "ok   be that role, in the expected account: yes",
                "ok   use London: allowed",
                "ok   create a network: denied",
                "ok   read its own state: allowed",
                "ok   read the state of webhook-platform: denied",
                "ok   read the state of the bootstrap: denied",
                "ok   write its own state: denied",
            ],
        )
        self.assert_private(output)

    def test_fails_on_a_right_too_many(self):
        cases = {
            f"{ROLES}/gha-{REPO}-apply": (GRANTED, "become gha-cloud-labs-apply"),
            f"{ROLES}/gha-{REPO}-destroy": (GRANTED, "become gha-cloud-labs-destroy"),
            f"{ROLES}/gha-{OTHER}-plan": (GRANTED, "become gha-webhook-platform-plan"),
            "create-vpc": (refuse("DryRunOperation"), "create a network"),
            f"get-object --bucket {BUCKET} --key {OTHER}/": (refuse("NoSuchKey"), "read the state of webhook-platform"),
            f"get-object --bucket {BUCKET} --key bootstrap/": ((0, "{}", ""), "read the state of the bootstrap"),
            "put-object": (refuse("NoSuchKey"), "write its own state"),
        }
        for part, (reply, what) in cases.items():
            with self.subTest(what):
                self.assert_fails_only(run("aws", FakeAws({part: reply})), f"FAIL {what}: allowed, should be denied")

    def test_a_replaced_file_also_counts_as_the_right_to_write(self):
        for code in ("PreconditionFailed", "NoSuchKey"):
            result = run("aws", FakeAws({"put-object": refuse(code)}))
            self.assert_fails_only(result, "FAIL write its own state: allowed, should be denied")

    def test_fails_on_a_right_too_few(self):
        cases = {
            "describe-availability-zones": ("UnauthorizedOperation", "use London"),
            f"get-object --bucket {BUCKET} --key {REPO}/": ("AccessDenied", "read its own state"),
        }
        for part, (code, what) in cases.items():
            with self.subTest(what):
                result = run("aws", FakeAws({part: refuse(code)}))
                self.assert_fails_only(result, f"FAIL {what}: denied, should be allowed")

    def test_stops_when_the_sign_in_is_refused(self):
        for code, shown in {"AccessDenied": "denied", "InvalidIdentityToken": "InvalidIdentityToken"}.items():
            with self.subTest(code):
                fake = FakeAws({"assume-role-with-web-identity": refuse(code)})
                line = f"FAIL sign in as gha-cloud-labs-plan: {shown}, should be allowed"
                self.assert_fails_only(run("aws", fake), line)
                self.assertEqual(len(fake.commands), 1)

    def test_another_error_is_not_taken_for_a_refusal(self):
        for reply, shown in ((refuse("ExpiredToken"), "ExpiredToken"), ((255, "", f"lost {BUCKET}"), "no error code")):
            result = run("aws", FakeAws({"put-object": reply}))
            self.assert_fails_only(result, f"FAIL write its own state: {shown}, should be denied")

    def test_notices_another_account_or_role(self):
        for arn, account in (
            (f"arn:aws:sts::{ACCOUNT}:assumed-role/gha-{REPO}-apply/check-sign-in", ACCOUNT),
            (f"arn:aws:sts::444455556666:assumed-role/gha-{REPO}-plan/check-sign-in", "444455556666"),
        ):
            reply = (0, json.dumps({"Account": account, "Arn": arn}), "")
            result = run("aws", FakeAws({"get-caller-identity": reply}))
            self.assert_fails_only(result, "FAIL be that role, in the expected account: no, should be yes")

    def test_signs_in_once_and_leaves_no_token_behind(self):
        fake = FakeAws()
        run("aws", fake)
        for command, env in fake.commands:
            signing_in = "assume-role-with-web-identity" in command
            self.assertEqual("AWS_SESSION_TOKEN" in env, not signing_in)
            self.assertFalse(set(env) & set(checks.CLOUDS["aws"][0]))
            self.assertFalse([name for name in env if name.startswith("ACTIONS_")])
            self.assertNotIn(TOKEN, " ".join(command))
            self.assertIn("eu-west-2", command)
        self.assertEqual(len(fake.token_files), 1)
        self.assertFalse(any(path.exists() for path in fake.token_files))

    def test_no_command_can_change_anything(self):
        fake = FakeAws()
        run("aws", fake)
        for command, _ in fake.commands:
            reads = command[2].startswith(("assume-role-with-web-identity", "describe-", "get-"))
            self.assertTrue(reads or "--dry-run" in command or "--if-match" in command, command)


class Azure(Base):
    def test_accepts_the_intended_rights(self):
        status, output = run("azure")
        self.assertEqual(status, 0)
        self.assertEqual(
            output.splitlines(),
            [
                f"ok   GitHub's subject is {SUBJECT}",
                "ok   sign in as id-gha-cloud-labs-plan: allowed",
                "ok   read its own resource group: allowed",
                "ok   read the resource group of webhook-platform: denied",
                "ok   read the resource group of the bootstrap: denied",
                "ok   prepare a deployment: denied",
                "ok   sign in to the state storage: allowed",
                "ok   list its own state: allowed",
                "ok   list the state of webhook-platform: denied",
                "ok   list the state of the bootstrap: denied",
                "ok   write its own state: denied",
            ],
        )
        self.assert_private(output)

    def test_fails_on_a_right_too_many(self):
        cases = {
            f"/rg-{OTHER}?": ((200, {}, b"{}"), "read the resource group of webhook-platform"),
            "/rg-github-bootstrap?": ((200, {}, b"{}"), "read the resource group of the bootstrap"),
            "/validate?": ((200, {}, b"{}"), "prepare a deployment"),
            f"/{OTHER}?restype": ((200, {}, b"<x/>"), "list the state of webhook-platform"),
            "/bootstrap?restype": ((200, {}, b"<x/>"), "list the state of the bootstrap"),
            "PUT": (no_blob("ConditionNotMet", 412), "write its own state"),
        }
        for part, (reply, what) in cases.items():
            with self.subTest(what):
                self.assert_fails_only(run("azure", web=FakeWeb({part: reply})), f"FAIL {what}: allowed, should be denied")

    def test_fails_on_a_right_too_few(self):
        cases = {
            f"/rg-{REPO}?": (no("AuthorizationFailed"), "read its own resource group"),
            f"/{REPO}?restype": (no_blob("AuthorizationPermissionMismatch"), "list its own state"),
        }
        for part, (reply, what) in cases.items():
            with self.subTest(what):
                self.assert_fails_only(run("azure", web=FakeWeb({part: reply})), f"FAIL {what}: denied, should be allowed")

    def test_stops_when_the_sign_in_is_refused(self):
        refusal = {"error": "unauthorized_client", "error_description": f"AADSTS700213: No match for {CLIENT} in {TENANT}."}
        for body, shown in ((json.dumps(refusal).encode(), "AADSTS700213"), (f"no code {TENANT}".encode(), "HTTP 401")):
            with self.subTest(shown):
                web = FakeWeb({"login.microsoftonline.com": (401, {}, body)})
                line = f"FAIL sign in as id-gha-cloud-labs-plan: {shown}, should be allowed"
                self.assert_fails_only(run("azure", web=web), line)
                self.assertEqual(len(web.requests), 2)

    def test_stops_when_the_storage_sign_in_is_refused(self):
        web = FakeWeb({"scope=https://storage.azure.com": (400, {}, b"AADSTS500011")})
        result = run("azure", web=web)
        self.assert_fails_only(result, "FAIL sign in to the state storage: AADSTS500011, should be allowed")
        self.assertFalse([url for _, url, _, _ in web.requests if STORE in url])

    def test_another_error_is_not_taken_for_a_refusal(self):
        for reply, shown in (
            ((401, {}, b'{"error": {"code": "InvalidAuthenticationToken"}}'), "InvalidAuthenticationToken"),
            ((503, {}, f"<html>{TENANT}</html>".encode()), "HTTP 503"),
            ((403, {}, json.dumps({"error": {"code": f"see {TENANT}"}}).encode()), "HTTP 403"),
            ((403, {}, b'{"error": {"code": ["list"]}}'), "HTTP 403"),
            ((403, {}, b'{"error": "text"}'), "HTTP 403"),
        ):
            with self.subTest(shown):
                result = run("azure", web=FakeWeb({f"/rg-{OTHER}?": reply}))
                line = f"FAIL read the resource group of webhook-platform: {shown}, should be denied"
                self.assert_fails_only(result, line)

    def test_sends_each_token_only_where_it_belongs(self):
        web = FakeWeb()
        run("azure", web=web)
        for _, url, headers, body in web.requests:
            parts = urllib.parse.urlsplit(url)
            self.assertEqual(parts.scheme, "https")
            has_token = TOKEN in urllib.parse.unquote((body or b"").decode())
            self.assertEqual(has_token, parts.hostname == "login.microsoftonline.com")
            bearer = headers.get("Authorization", "").removeprefix("Bearer ")
            expected = {"token.example": OFFER, "login.microsoftonline.com": ""}.get(parts.hostname, BEARER)
            self.assertEqual(bearer, expected)
            for secret in (TOKEN, BEARER, OFFER):
                self.assertNotIn(secret, url)

    def test_no_request_can_change_anything(self):
        web = FakeWeb()
        run("azure", web=web)
        for method, url, headers, body in web.requests:
            signs_in = urllib.parse.urlsplit(url).hostname == "login.microsoftonline.com"
            validates = "/validate?" in url and json.loads(body)["properties"]["template"]["resources"] == []
            self.assertTrue(method == "GET" or (method == "POST" and (signs_in or validates)) or "If-Match" in headers, url)


class Preparation(Base):
    def assert_not_checked(self, message, env=None, web=None, cloud="aws"):
        aws, web = FakeAws(), web or FakeWeb()
        status, output = run(cloud, aws, web, env)
        self.assertEqual(status, 1)
        self.assertEqual(output, f"Not checked. {message}\n")
        self.assertEqual(aws.commands, [])
        self.assertFalse([url for _, url, _, _ in web.requests if not url.startswith("https://token.example/")])

    def test_missing_secrets(self):
        for cloud, (needed, _, _) in checks.CLOUDS.items():
            self.assert_not_checked(
                f"Not set: {', '.join(needed)}. Fork and Dependabot pull requests get no secrets.",
                env=ENV | dict.fromkeys(needed, ""),
                cloud=cloud,
            )

    def test_job_without_the_right_to_ask_for_a_token(self):
        for name in ("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL"):
            env = {key: value for key, value in ENV.items() if key != name}
            self.assert_not_checked("GitHub offers no OIDC token here. The job needs id-token: write.", env=env)

    def test_github_gives_no_token(self):
        web = FakeWeb({"https://token.example/": (500, {}, b"")})
        self.assert_not_checked("GitHub gave no OIDC token: HTTP 500.", web=web)

    def test_another_subject(self):
        for sent, shown in (
            ("repo:oplf-svg/cloud-labs:pull_request", "repo:oplf-svg/cloud-labs:pull_request"),
            ("repo:x:ref:refs/heads/a b\n::add", "repo:x:ref:refs/heads/a?b?::add"),
        ):
            message = f"GitHub's subject is {shown}, not the one in subjects.json."
            self.assert_not_checked(message, web=FakeWeb(token=jwt(sent)))

    def test_another_repo(self):
        for name in ("oplf-svg/oplf-svg", "someone/cloud-labs", ""):
            self.assert_not_checked("This is not one of the repos in subjects.json.", env=ENV | {"GITHUB_REPOSITORY": name})

    def test_asks_github_for_the_audience_of_the_cloud(self):
        for cloud, audience in {"aws": "sts.amazonaws.com", "azure": "api%3A%2F%2FAzureADTokenExchange"}.items():
            web = FakeWeb()
            run(cloud, web=web)
            self.assertEqual(web.requests[0][1], f"https://token.example/ask?api-version=2.0&audience={audience}")

    def test_works_in_every_repo(self):
        for repo, subjects in checks.SUBJECTS.items():
            env = ENV | {"GITHUB_REPOSITORY": f"oplf-svg/{repo}", "AWS_ROLE_ARN": f"{ROLES}/gha-{repo}-plan"}
            for cloud in checks.CLOUDS:
                with self.subTest(f"{repo} on {cloud}"):
                    web = FakeWeb(token=jwt(subjects["plan"]), repo=repo)
                    status, output = run(cloud, FakeAws(repo=repo), web, env)
                    self.assertEqual((status, "FAIL" in output), (0, False))
                    self.assertNotIn(f"state of {repo}", output)

    def test_a_crash_shows_only_its_kind(self):
        def broken(*_, **__):
            raise FileNotFoundError(f"{ROLES} {BUCKET} {TOKEN}")

        with tempfile.TemporaryDirectory() as folder:
            status, output = run("aws", broken, env=ENV | {"RUNNER_TEMP": folder})
            self.assertEqual(list(pathlib.Path(folder).iterdir()), [])
        self.assertEqual(status, 1)
        self.assertEqual(output.splitlines()[-1], "Stopped by FileNotFoundError.")
        self.assert_private(output)


class Workflow(unittest.TestCase):
    text = (ROOT / ".github/workflows/sign-in.yml").read_text()

    def test_gives_each_job_the_secrets_of_its_own_cloud_and_no_others(self):
        text = self.text.partition("\njobs:\n")[2] + "\n"
        jobs = dict(re.findall(r"^  (\w+):\n((?:(?:    .*)?\n)+)", text, re.MULTILINE))
        self.assertEqual(set(jobs), set(checks.CLOUDS))
        for cloud, (needed, _, _) in checks.CLOUDS.items():
            used = re.findall(r"^      (\w+): \$\{\{ secrets\.(\w+) \}\}$", jobs[cloud], re.MULTILINE)
            self.assertEqual(sorted(used), sorted((name, name) for name in needed))
            self.assertEqual(jobs[cloud].count("{{ secrets."), len(needed))
            self.assertIn(f"run: python3 bootstrap/scripts/check_sign_in.py {cloud}\n", jobs[cloud])

    def test_uses_only_the_action_that_ci_uses(self):
        used = set(re.findall(r"uses: (\S+)", self.text))
        self.assertEqual(len(used), 1)
        self.assertLessEqual(used, set(re.findall(r"uses: (\S+)", (ROOT / ".github/workflows/ci.yml").read_text())))


if __name__ == "__main__":
    unittest.main()
