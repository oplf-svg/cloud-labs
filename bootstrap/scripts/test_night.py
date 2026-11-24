"""Runs night.py against stand-ins for GitHub, the AWS CLI, Azure and Google. Nothing real is called."""

import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import night
from test_check_sign_in import ACCOUNT, BEARER, BUCKET, ENV, GOOGLE_BUCKET, GRANTED, KEY, PRIVATE, PROJECT, REPO, ROLES, jwt, no, no_blob, refuse

TOKEN = jwt(night.SUBJECTS[REPO]["destroy"])
NIGHT_ENV = ENV | {"AWS_ROLE_ARN": f"{ROLES}/gha-{REPO}-destroy"}
HIDDEN = [value for value in PRIVATE if not value.startswith("header.")] + [TOKEN]


class World:
    """GitHub and the three clouds, as they should answer. `files` are the states of this repo."""

    def __init__(self, files=(), token=TOKEN, searches=True, **changes):
        self.files, self.token, self.searches, self.changes, self.sent = list(files), token, searches, changes, []

    def run(self, command, env, **options):
        line = " ".join(command)
        for part, reply in self.changes.items():
            if part.replace("_", "-") in line:
                return subprocess.CompletedProcess(command, *reply)
        if f"--role-arn {ROLES}/gha-{REPO}-destroy " in line:
            return subprocess.CompletedProcess(command, *GRANTED)
        if "list-objects-v2" in line:
            assert env["AWS_ACCESS_KEY_ID"] == KEY and f"--bucket {BUCKET} --prefix {REPO}/" in line
            found = [{"Key": f"{REPO}/{file}"} for file in self.files]
            return subprocess.CompletedProcess(command, 0, json.dumps({"Contents": found} if found else {}), "")
        return subprocess.CompletedProcess(command, *refuse("UnauthorizedOperation" if "create-vpc" in line else "AccessDenied"))

    def send(self, method, url, headers=None, body=None):
        self.sent.append((method, url))
        for part, reply in self.changes.items():
            if part in url:
                return reply
        if url.startswith("https://token.example/"):
            return 200, {}, json.dumps({"value": self.token}).encode()
        if "login.microsoftonline.com" in url or "sts.googleapis.com" in url:
            return 200, {}, json.dumps({"access_token": BEARER}).encode()
        assert headers["Authorization"] == f"Bearer {BEARER}"
        if "/validate?" in url:
            return no("AuthorizationFailed")
        if "comp=list" in url:
            return 200, {}, ("<R>" + "".join(f"<Blob><Name>{file}</Name></Blob>" for file in self.files) + "</R>").encode()
        if "testIamPermissions" in url:
            has = {"resourcemanager.projects.get", night.SEARCH} if self.searches else {"resourcemanager.projects.get"}
            return 200, {}, json.dumps({"permissions": sorted(has & set(json.loads(body)["permissions"]))}).encode()
        if "storage.googleapis.com" in url:
            assert GOOGLE_BUCKET in url
            return 200, {}, json.dumps({"items": [{"name": f"{REPO}/{file}"} for file in self.files]} if self.files else {}).encode()
        raise AssertionError(url)


class Night(unittest.TestCase):
    def go(self, cloud, world, stacks=(), env=None):
        with tempfile.TemporaryDirectory() as folder:
            file = pathlib.Path(folder, "stacks.json")
            file.write_text(json.dumps({"stacks": list(stacks)}) if not isinstance(stacks, str) else stacks)
            screen = io.StringIO()
            with contextlib.redirect_stdout(screen):
                code = night.main([cloud], env=NIGHT_ENV | {"RUNNER_TEMP": folder} | (env or {}), run=world.run, send=world.send, stacks=file)
            left = sorted(path.name for path in pathlib.Path(folder).iterdir())
        self.assertEqual(left, ["stacks.json"])
        for value in HIDDEN:
            self.assertNotIn(value, screen.getvalue())
        return code, screen.getvalue().splitlines()

    def test_an_empty_night(self):
        expected = {
            "aws": [f"sign in as gha-{REPO}-destroy: allowed", f"become gha-{REPO}-apply: denied", "create a network: denied"],
            "azure": [f"sign in as id-gha-{REPO}-destroy: allowed", "prepare a deployment: denied", "sign in to the state storage: allowed"],
            "gcp": [f"sign in as the destroy of {REPO}: allowed", "create something: denied", "search the whole project: allowed"],
        }
        for cloud, lines in expected.items():
            with self.subTest(cloud):
                code, output = self.go(cloud, World())
                self.assertEqual(output, [f"ok   {line}" for line in [*lines, "list its own states: allowed", "find states that nobody declared: none"]])
                self.assertEqual(code, 0)

    def test_a_stack_that_stays(self):
        for cloud, file in (("aws", "site/terraform.tfstate"), ("azure", "site/terraform.tfstate"), ("gcp", "site/default.tfstate")):
            with self.subTest(cloud):
                code, output = self.go(cloud, World([file]), [{"name": "site", "clouds": [cloud], "night": "stays", "why": "x"}])
                self.assertEqual((code, "ok   keep site: stays" in output), (0, True), output)
                # On the clouds where it is declared, and on no other.
                others = [other for other in night.NIGHTS if other != cloud]
                code, output = self.go(cloud, World([file]), [{"name": "site", "clouds": others, "night": "stays", "why": "x"}])
                self.assertEqual((code, output[-1]), (1, "FAIL find states that nobody declared: 1, should be none"))

    def test_a_lock_is_seen_and_does_not_fail_the_night(self):
        for night_of in ("stays", "destroyed"):
            stack = [{"name": "site", "clouds": ["aws"], "night": night_of, "why": "x"}]
            code, output = self.go("aws", World(["site/terraform.tfstate.tflock"]), stack)
            self.assertEqual((code, "ok   see a lock on site: seen" in output), (0, True), output)
            code, output = self.go("aws", World(["site/terraform.tfstate", "site/terraform.tfstate.tflock"]), stack)
            self.assertEqual((code, "ok   see a lock on site: seen" in output), (0 if night_of == "stays" else 1, True), output)

    def test_anything_undeclared_fails(self):
        strange = ["site/terraform.tfstate", "site/terraform.tfstate.tflock", "other/terraform.tfstate", "terraform.tfstate", "a/b/terraform.tfstate", "x; echo hacked"]
        for cloud in night.NIGHTS:
            for file in strange:
                with self.subTest(cloud=cloud, file=file):
                    code, output = self.go(cloud, World([file]))
                    self.assertEqual((code, output[-1]), (1, "FAIL find states that nobody declared: 1, should be none"))
                    self.assertNotIn("hacked", "".join(output))

    def test_a_stack_to_destroy_fails_until_there_is_a_way(self):
        for cloud in night.NIGHTS:
            code, output = self.go(cloud, World(["queue/terraform.tfstate"]), [{"name": "queue", "clouds": [cloud], "night": "destroyed", "why": "x"}])
            self.assertEqual((code, "FAIL destroy queue: no way to yet, should be destroyed" in output), (1, True), output)

    def test_a_right_too_many_fails(self):
        cases = (
            ("aws", {"create_vpc": refuse("DryRunOperation")}, "FAIL create a network: allowed, should be denied"),
            ("aws", {f"gha_{REPO}_apply".replace("-", "_"): GRANTED}, f"FAIL become gha-{REPO}-apply: allowed, should be denied"),
            ("azure", {"/validate?": (200, {}, b"{}")}, "FAIL prepare a deployment: allowed, should be denied"),
            ("gcp", {"testIamPermissions": (200, {}, json.dumps({"permissions": ["resourcemanager.projects.get", "compute.networks.create", night.SEARCH]}).encode())}, "FAIL create something: allowed, should be denied"),
        )
        for cloud, changes, line in cases:
            with self.subTest(line):
                code, output = self.go(cloud, World(**changes))
                self.assertEqual((code, [entry for entry in output if entry.startswith("FAIL")]), (1, [line]))

    def test_only_this_repo_may_search_the_whole_project(self):
        code, output = self.go("gcp", World(searches=False))
        self.assertEqual((code, [line for line in output if line.startswith("FAIL")]), (1, ["FAIL search the whole project: denied, should be allowed"]))
        # In another repo, the same right is one too many.
        other = "webhook-platform"
        for searches, line in ((False, "ok   search the whole project: denied"), (True, "FAIL search the whole project: allowed, should be denied")):
            world = World(token=jwt(night.SUBJECTS[other]["destroy"]), searches=searches)
            code, output = self.go("gcp", world, env={"GITHUB_REPOSITORY": f"oplf-svg/{other}"})
            self.assertIn(line, output)
            self.assertEqual(code, int(searches))

    def test_no_answer_is_not_a_refusal(self):
        code, output = self.go("gcp", World(testIamPermissions=(500, {}, b"")))
        self.assertIn("FAIL create something: no answer, should be denied", output)
        self.assertIn("FAIL search the whole project: no answer, should be allowed", output)
        code, output = self.go("azure", World(**{"comp=list": no_blob("ServerBusy", 503)}))
        self.assertEqual((code, output[-1]), (1, "FAIL list its own states: ServerBusy, should be allowed"))

    def test_stops_when_the_sign_in_is_refused(self):
        cases = (
            ("aws", {"assume_role": refuse("AccessDenied")}, "denied"),
            ("azure", {"login.microsoftonline.com": (400, {}, b"AADSTS700213: no match for " + ACCOUNT.encode())}, "AADSTS700213"),
            ("gcp", {"sts.googleapis.com": (400, {}, b'{"error": "unauthorized_client", "error_description": "' + PROJECT.encode() + b'"}')}, "unauthorized_client"),
        )
        for cloud, changes, code in cases:
            with self.subTest(cloud):
                status, output = self.go(cloud, World(**changes))
                self.assertEqual((status, len(output)), (1, 1))
                self.assertIn(f": {code}, should be allowed", output[0])

    def test_only_the_nightly_identity_may_run_it(self):
        for tier in ("plan", "apply"):
            code, output = self.go("aws", World(token=jwt(night.SUBJECTS[REPO][tier])))
            self.assertEqual((code, output), (1, ["Not checked. GitHub's subject is not this repo's nightly-destroy."]))

    def test_says_what_is_missing(self):
        self.assertEqual(self.go("aws", World(), env={"AWS_ROLE_ARN": ""})[1], ["Not checked. Not set: AWS_ROLE_ARN."])
        self.assertEqual(self.go("aws", World(), env={"GITHUB_REPOSITORY": "someone/else"})[1], ["Not checked. This is not one of the repos in subjects.json."])

    def test_the_list_of_stacks_is_checked(self):
        good = {"name": "site", "clouds": ["aws"], "night": "stays", "why": "x"}
        self.assertEqual(self.go("aws", World(), [good])[0], 0)
        for wrong in ({"night": "maybe"}, {"name": "../site"}, {"more": 1}, {"clouds": []}, {"clouds": ["aws", "another"]}):
            self.assertEqual(self.go("aws", World(), [good | wrong])[1], ["Not checked. stacks.json is not in the expected form."], wrong)
        for part in good:
            self.assertEqual(self.go("aws", World(), [{key: value for key, value in good.items() if key != part}])[1], ["Not checked. stacks.json is not in the expected form."], part)
        self.assertEqual(self.go("aws", World(), "not json")[1], ["Stopped by JSONDecodeError."])

    def test_the_real_list_is_in_that_form(self):
        for cloud in night.NIGHTS:
            self.assertIsInstance(night.declared(cloud), dict)


if __name__ == "__main__":
    unittest.main()
