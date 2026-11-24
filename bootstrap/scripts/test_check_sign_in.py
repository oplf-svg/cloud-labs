"""Runs check_sign_in.py against stand-ins for GitHub, the AWS CLI, Azure and Google. Nothing real is called."""

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
SUBJECT = "repo:oplf-svg@228823995/cloud-labs@1469385611:environment:plan"

ACCOUNT, BUCKET = "111122223333", "tfstate-0a1b2c3d"
ROLES = f"arn:aws:iam::{ACCOUNT}:role/github-actions"
CLIENT, SUBSCRIPTION, TENANT = (f"00000000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
STORE = "tfstate0a1b2c3d"
PROJECT, NUMBER, HOME_NUMBER = "example-project-1", "210987654321", "123456789012"
PROVIDER = f"projects/{HOME_NUMBER}/locations/global/workloadIdentityPools/github-actions/providers/github"
GOOGLE_BUCKET = "tfstate-4e5f6a7b"
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
    "GCP_PROJECT_ID": PROJECT,
    "GCP_PROJECT_NUMBER": NUMBER,
    "GCP_STATE_BUCKET": GOOGLE_BUCKET,
    "GCP_WORKLOAD_IDENTITY_PROVIDER": PROVIDER,
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
PRIVATE += [PROJECT, NUMBER, HOME_NUMBER, GOOGLE_BUCKET]

# The state bucket once repos have deployed something. Before that, only the bootstrap's file is there.
STATES = tuple(f"{owner}/terraform.tfstate" for owner in ("bootstrap", *checks.SUBJECTS))

# What AWS says when it lets someone in.
GRANTED = 0, json.dumps({"Credentials": {"AccessKeyId": KEY, "SecretAccessKey": SECRET, "SessionToken": SESSION}}), ""


def refuse(code):
    # As AWS does, with everything in it that a log must not show.
    return 254, "", f"aws: [ERROR]: An error occurred ({code}) when calling it: {ROLES} may not use {BUCKET} in {ACCOUNT}"


class FakeAws:
    """Answers as AWS should. `changes` maps part of a command to another answer."""

    def __init__(self, changes=None, repo=REPO, files=("bootstrap/terraform.tfstate",)):
        self.changes, self.repo, self.files = changes or {}, repo, files
        self.commands, self.token_files = [], set()

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
        if "list-objects-v2" in line:
            prefix = re.search(r"--prefix (\S+)", line).group(1)
            found = [{"Key": name} for name in self.files if name.startswith(prefix)]
            return 0, json.dumps({"Contents": found} if found else {"RequestCharged": None, "Prefix": prefix}), ""
        if "get-object" in line:
            # As S3 does: whoever may list the bucket hears that a file is missing, whatever they may open.
            key = re.search(r"--key (\S+)", line).group(1)
            own = key.startswith(f"{self.repo}/")
            return refuse("NoSuchKey") if key not in self.files else (0, "{}", "") if own else refuse("AccessDenied")
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


def no_google(code, *reasons, **error):
    # As Google does, with everything in it that a log must not show. Storage names its reason in another place.
    error |= {"code": code, "message": f"principal://{PROVIDER} may not use {PROJECT}, {NUMBER} or {GOOGLE_BUCKET}"}
    for reason in reasons:
        details = reason.isupper()
        error["details" if details else "errors"] = [{"message": NUMBER}, {"reason": reason, "metadata": PROJECT}]
    return code, {}, json.dumps({"error": error}).encode()


class FakeWeb:
    """Answers as GitHub, Azure and Google should. `changes` maps part of a request to another answer."""

    def __init__(self, changes=None, token=TOKEN, repo=REPO, files=("bootstrap/default.tfstate",), granted=()):
        self.changes, self.token, self.repo, self.requests = changes or {}, token, repo, []
        self.files, self.granted = files, {"resourcemanager.projects.get", *granted}

    def google_storage(self, method, url):
        parts = urllib.parse.urlsplit(url)
        if parts.path == f"/storage/v1/b/{GOOGLE_BUCKET}/o" and method == "GET":
            prefix = urllib.parse.parse_qs(parts.query)["prefix"][0]
            items = [{"name": name} for name in self.files if name.startswith(prefix)]
            return 200, {}, json.dumps({"kind": "storage#objects"} | ({"items": items} if items else {})).encode()
        # As S3 does: whoever may list the bucket hears that a file is missing, whatever they may open.
        name = parts.path.removeprefix(f"/storage/v1/b/{GOOGLE_BUCKET}/o/")
        # Google takes a slash for the end of the name, so it has to be encoded.
        assert method != "GET" or "/" not in name
        name = urllib.parse.unquote(name)
        if method == "GET" and name not in self.files:
            return no_google(404, "notFound")
        own = method == "GET" and name.startswith(f"{self.repo}/")
        return (200, {}, b"{}") if own else no_google(403, "forbidden")

    def __call__(self, method, url, headers=None, body=None):
        self.requests.append((method, url, headers or {}, body))
        line = f"{method} {urllib.parse.unquote(url)} {urllib.parse.unquote((body or b'').decode())}"
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
        if host == "sts.googleapis.com":
            return 200, {}, json.dumps({"access_token": BEARER}).encode()
        if host == "cloudresourcemanager.googleapis.com" and url.endswith(f"/{PROJECT}:testIamPermissions"):
            granted = [name for name in json.loads(body)["permissions"] if name in self.granted]
            return 200, {}, json.dumps({"permissions": granted}).encode()
        if host == "cloudresourcemanager.googleapis.com":
            if not url.endswith(f"/projects/{PROJECT}"):
                return no_google(403, "IAM_PERMISSION_DENIED")
            return 200, {}, json.dumps({"name": f"projects/{NUMBER}", "projectId": PROJECT}).encode()
        if host == "compute.googleapis.com":
            return 200, {}, b"{}"
        if host == "storage.googleapis.com":
            return self.google_storage(method, url)
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
                "ok   read its own state: nothing there",
                "ok   read the state of webhook-platform: nothing there",
                "ok   read the state of the bootstrap: denied",
                "ok   write its own state: denied",
            ],
        )
        self.assert_private(output)

    def test_opens_a_file_as_soon_as_there_is_one(self):
        status, output = run("aws", FakeAws(files=STATES))
        self.assertEqual(status, 0)
        self.assertIn("ok   read its own state: allowed\n", output)
        self.assertIn("ok   read the state of webhook-platform: denied\n", output)
        self.assert_private(output)

    def test_there_is_always_a_state_of_the_bootstrap(self):
        result = run("aws", FakeAws(files=()))
        self.assert_fails_only(result, "FAIL read the state of the bootstrap: nothing there, should be denied")

    def test_fails_on_a_right_too_many(self):
        cases = {
            f"{ROLES}/gha-{REPO}-apply": (GRANTED, "become gha-cloud-labs-apply"),
            f"{ROLES}/gha-{REPO}-destroy": (GRANTED, "become gha-cloud-labs-destroy"),
            f"{ROLES}/gha-{OTHER}-plan": (GRANTED, "become gha-webhook-platform-plan"),
            "create-vpc": (refuse("DryRunOperation"), "create a network"),
            f"get-object --bucket {BUCKET} --key {OTHER}/": ((0, "{}", ""), "read the state of webhook-platform"),
            f"get-object --bucket {BUCKET} --key bootstrap/": ((0, "{}", ""), "read the state of the bootstrap"),
            "put-object": (refuse("NoSuchKey"), "write its own state"),
        }
        for part, (reply, what) in cases.items():
            with self.subTest(what):
                result = run("aws", FakeAws({part: reply}, files=STATES))
                self.assert_fails_only(result, f"FAIL {what}: allowed, should be denied")

    def test_a_replaced_file_also_counts_as_the_right_to_write(self):
        for code in ("PreconditionFailed", "NoSuchKey"):
            result = run("aws", FakeAws({"put-object": refuse(code)}))
            self.assert_fails_only(result, "FAIL write its own state: allowed, should be denied")

    def test_fails_on_a_right_too_few(self):
        cases = {
            "describe-availability-zones": ("UnauthorizedOperation", "use London"),
            f"get-object --bucket {BUCKET} --key {REPO}/": ("AccessDenied", "read its own state"),
            f"--prefix {REPO}/": ("AccessDenied", "read its own state"),
        }
        for part, (code, what) in cases.items():
            with self.subTest(part):
                result = run("aws", FakeAws({part: refuse(code)}, files=STATES))
                self.assert_fails_only(result, f"FAIL {what}: denied, should be allowed")

    def test_stops_when_the_sign_in_is_refused(self):
        for code, shown in {"AccessDenied": "denied", "InvalidIdentityToken": "InvalidIdentityToken"}.items():
            with self.subTest(code):
                fake = FakeAws({"assume-role-with-web-identity": refuse(code)})
                line = f"FAIL sign in as gha-cloud-labs-plan: {shown}, should be allowed"
                self.assert_fails_only(run("aws", fake), line)
                self.assertEqual(len(fake.commands), 1)

    def test_a_list_that_fails_is_not_taken_for_an_empty_one(self):
        result = run("aws", FakeAws({f"--prefix {OTHER}/": refuse("SlowDown")}))
        self.assert_fails_only(result, "FAIL read the state of webhook-platform: SlowDown, should be denied")

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
        fake = FakeAws(files=STATES)
        run("aws", fake)
        for command, _ in fake.commands:
            reads = command[2].startswith(("assume-role-with-web-identity", "describe-", "get-", "list-"))
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


class Google(Base):
    states = tuple(f"{owner}/default.tfstate" for owner in ("bootstrap", *checks.SUBJECTS))

    def test_accepts_the_intended_rights(self):
        status, output = run("gcp")
        self.assertEqual(status, 0)
        self.assertEqual(
            output.splitlines(),
            [
                f"ok   GitHub's subject is {SUBJECT}",
                "ok   sign in as the plan of cloud-labs: allowed",
                "ok   read the project: allowed",
                "ok   be in the expected project: yes",
                "ok   use London: allowed",
                "ok   create something: denied",
                "ok   become a service account: denied",
                "ok   change who has access: denied",
                "ok   read the project of the bootstrap: denied",
                "ok   read its own state: nothing there",
                "ok   read the state of webhook-platform: nothing there",
                "ok   read the state of the bootstrap: denied",
                "ok   write its own state: denied",
            ],
        )
        self.assert_private(output)

    def test_opens_a_file_as_soon_as_there_is_one(self):
        status, output = run("gcp", web=FakeWeb(files=self.states))
        self.assertEqual(status, 0)
        self.assertIn("ok   read its own state: allowed\n", output)
        self.assertIn("ok   read the state of webhook-platform: denied\n", output)
        self.assert_private(output)

    def test_there_is_always_a_state_of_the_bootstrap(self):
        result = run("gcp", web=FakeWeb(files=()))
        self.assert_fails_only(result, "FAIL read the state of the bootstrap: nothing there, should be denied")

    def test_a_list_that_fails_is_not_taken_for_an_empty_one(self):
        result = run("gcp", web=FakeWeb({f"prefix={OTHER}/": no_google(429, "rateLimitExceeded")}))
        self.assert_fails_only(result, "FAIL read the state of webhook-platform: rateLimitExceeded, should be denied")

    def test_fails_on_a_right_too_many(self):
        cases = {
            f"/projects/{HOME_NUMBER} ": ((200, {}, b"{}"), "read the project of the bootstrap"),
            f"/o/{OTHER}": ((200, {}, b"{}"), "read the state of webhook-platform"),
            "/o/bootstrap": ((200, {}, b"{}"), "read the state of the bootstrap"),
            "/upload/": (no_google(412, "conditionNotMet"), "write its own state"),
        }
        for part, (reply, what) in cases.items():
            with self.subTest(what):
                result = run("gcp", web=FakeWeb({part: reply}, files=self.states))
                self.assert_fails_only(result, f"FAIL {what}: allowed, should be denied")

    def test_fails_on_a_permission_too_many(self):
        cases = {
            "compute.instances.create": "create something",
            "compute.networks.create": "create something",
            "storage.buckets.create": "create something",
            "iam.serviceAccounts.actAs": "become a service account",
            "iam.serviceAccounts.getAccessToken": "become a service account",
            "iam.serviceAccountKeys.create": "become a service account",
            "resourcemanager.projects.setIamPolicy": "change who has access",
        }
        for permission, what in cases.items():
            with self.subTest(permission):
                result = run("gcp", web=FakeWeb(granted=[permission]))
                self.assert_fails_only(result, f"FAIL {what}: allowed, should be denied")

    def test_fails_on_a_right_too_few(self):
        cases = {
            "/regions/europe-west2": (no_google(403, "IAM_PERMISSION_DENIED", "forbidden"), "use London"),
            f"/o/{REPO}": (no_google(403, "forbidden"), "read its own state"),
            f"prefix={REPO}/": (no_google(403, "forbidden"), "read its own state"),
        }
        for part, (reply, what) in cases.items():
            with self.subTest(part):
                result = run("gcp", web=FakeWeb({part: reply}, files=self.states))
                self.assert_fails_only(result, f"FAIL {what}: denied, should be allowed")

    def test_no_answer_about_permissions_is_not_taken_for_a_refusal(self):
        for reply in ((200, {}, b"{}"), (200, {}, b'{"permissions": []}'), no_google(403, "IAM_PERMISSION_DENIED")):
            status, output = run("gcp", web=FakeWeb({":testIamPermissions": reply}))
            self.assertEqual(status, 1)
            self.assertEqual(
                [line for line in output.splitlines() if line.startswith("FAIL")],
                [
                    f"FAIL {what}: no answer, should be denied"
                    for what in ("create something", "become a service account", "change who has access")
                ],
            )
            self.assert_private(output)

    def test_stops_when_the_sign_in_is_refused(self):
        refusal = {"error": "unauthorized_client", "error_description": f"Rejected by the condition of {PROVIDER}."}
        for body, shown in (
            (json.dumps(refusal).encode(), "unauthorized_client"),
            (json.dumps({"error": f"see {NUMBER}"}).encode(), "HTTP 403"),
            (f"<html>{PROVIDER}</html>".encode(), "HTTP 403"),
        ):
            with self.subTest(shown):
                web = FakeWeb({"sts.googleapis.com": (403, {}, body)})
                line = f"FAIL sign in as the plan of cloud-labs: {shown}, should be allowed"
                self.assert_fails_only(run("gcp", web=web), line)
                self.assertEqual(len(web.requests), 2)

    def test_another_error_is_not_taken_for_a_refusal(self):
        for reply, shown in (
            (no_google(403, "SERVICE_DISABLED", status="PERMISSION_DENIED"), "SERVICE_DISABLED"),
            (no_google(403, "accessNotConfigured"), "accessNotConfigured"),
            (no_google(401, status="UNAUTHENTICATED"), "UNAUTHENTICATED"),
            (no_google(429), "HTTP 429"),
            (no_google(403, f"see-{PROJECT}"), "HTTP 403"),
            ((503, {}, f"<html>{PROJECT}</html>".encode()), "HTTP 503"),
            ((403, {}, b'{"error": "text"}'), "HTTP 403"),
            ((403, {}, b'{"error": {"details": ["text"]}}'), "HTTP 403"),
            ((403, {}, b'{"error": {"status": ["list"]}}'), "HTTP 403"),
        ):
            with self.subTest(shown):
                result = run("gcp", web=FakeWeb({f"/projects/{HOME_NUMBER} ": reply}))
                self.assert_fails_only(result, f"FAIL read the project of the bootstrap: {shown}, should be denied")

    def test_a_refusal_without_a_reason_counts_by_its_status(self):
        status, _ = run("gcp", web=FakeWeb({f"/projects/{HOME_NUMBER} ": no_google(403, status="PERMISSION_DENIED")}))
        self.assertEqual(status, 0)

    def test_notices_another_project(self):
        reply = (200, {}, json.dumps({"name": "projects/999999999999"}).encode())
        result = run("gcp", web=FakeWeb({f"/projects/{PROJECT} ": reply}))
        self.assert_fails_only(result, "FAIL be in the expected project: no, should be yes")

    def test_sends_each_token_only_where_it_belongs(self):
        web = FakeWeb(files=self.states)
        run("gcp", web=web)
        for _, url, headers, body in web.requests:
            parts = urllib.parse.urlsplit(url)
            self.assertEqual(parts.scheme, "https")
            self.assertEqual(TOKEN in (body or b"").decode(), parts.hostname == "sts.googleapis.com")
            bearer = headers.get("Authorization", "").removeprefix("Bearer ")
            self.assertEqual(bearer, {"token.example": OFFER, "sts.googleapis.com": ""}.get(parts.hostname, BEARER))
            for secret in (TOKEN, BEARER, OFFER):
                self.assertNotIn(secret, url)

    def test_asks_for_the_provider_that_the_secret_names(self):
        web = FakeWeb()
        run("gcp", web=web)
        form = json.loads(next(body for _, url, _, body in web.requests if "sts.googleapis.com" in url))
        self.assertEqual(form["audience"], f"//iam.googleapis.com/{PROVIDER}")
        self.assertEqual(form["subjectToken"], TOKEN)

    def test_no_request_can_change_anything(self):
        web = FakeWeb(files=self.states)
        run("gcp", web=web)
        for method, url, _, _ in web.requests:
            asks = url == "https://sts.googleapis.com/v1/token" or url.endswith(":testIamPermissions")
            never = url.startswith("https://storage.googleapis.com/upload/") and url.endswith("&ifGenerationMatch=1")
            self.assertTrue(method == "GET" or (method == "POST" and (asks or never)), url)


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
                f"Not set: {', '.join(needed)}.",
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
            # What a pull request's job has, and a job on main without an environment.
            (SUBJECT.replace("environment:plan", "pull_request"), SUBJECT.replace("environment:plan", "pull_request")),
            (SUBJECT.replace("environment:plan", "ref:refs/heads/main"), SUBJECT.replace("environment:plan", "ref:refs/heads/main")),
            (checks.SUBJECTS[REPO]["apply"], checks.SUBJECTS[REPO]["apply"]),
            ("repo:oplf-svg/cloud-labs:environment:plan", "repo:oplf-svg/cloud-labs:environment:plan"),
            ("repo:x:ref:refs/heads/a b\n::add", "repo:x:ref:refs/heads/a?b?::add"),
        ):
            message = f"GitHub's subject is {shown}, not the one in subjects.json."
            self.assert_not_checked(message, web=FakeWeb(token=jwt(sent)))

    def test_another_repo(self):
        for name in ("oplf-svg/oplf-svg", "someone/cloud-labs", ""):
            self.assert_not_checked("This is not one of the repos in subjects.json.", env=ENV | {"GITHUB_REPOSITORY": name})

    def test_asks_github_for_the_audience_of_the_cloud(self):
        audiences = {
            "aws": "sts.amazonaws.com",
            "azure": "api%3A%2F%2FAzureADTokenExchange",
            "gcp": "https%3A%2F%2Fiam.googleapis.com%2F" + PROVIDER.replace("/", "%2F"),
        }
        self.assertEqual(set(audiences), set(checks.CLOUDS))
        for cloud, audience in audiences.items():
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
            self.assertIn("\n    environment: plan\n", jobs[cloud])

    def test_runs_on_main_only(self):
        starts = self.text.partition("\non:\n")[2].partition("\npermissions:")[0]
        self.assertEqual(
            starts.split("\n"),
            [
                "  push:",
                "    branches: [main]",
                "    paths:",
                "      - bootstrap/**",
                "      - .github/workflows/sign-in.yml",
                "  workflow_dispatch:",
                "",
            ],
        )

    def test_uses_only_the_action_that_ci_uses(self):
        used = set(re.findall(r"uses: (\S+)", self.text))
        self.assertEqual(len(used), 1)
        self.assertLessEqual(used, set(re.findall(r"uses: (\S+)", (ROOT / ".github/workflows/ci.yml").read_text())))


if __name__ == "__main__":
    unittest.main()
