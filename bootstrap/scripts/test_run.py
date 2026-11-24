"""Runs run.sh against stand-ins for terraform, aws, az and gcloud. Nothing real is called."""

import json
import os
import pathlib
import pty
import re
import select
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

BOOTSTRAP = pathlib.Path(__file__).resolve().parent.parent
EXPECTED = {"aws": 104, "azure": 91, "gcp": 45}
SUBJECTS = [s for tiers in json.loads((BOOTSTRAP / "subjects.json").read_text()).values() for s in tiers.values()]

TERRAFORM = r"""#!/usr/bin/env python3
import json, os, pathlib, sys
box, args = pathlib.Path(os.environ["BOX"]), sys.argv[1:]
conf = json.loads((box / "conf.json").read_text())
log = open(box / "log", "a"); print("terraform", *args, file=log)
here, remote = pathlib.Path("terraform.tfstate"), box / "remote"
backend = pathlib.Path("backend.tf").exists()
def state(): return int((remote if backend else here).read_text() or 0) if (remote if backend else here).exists() else 0
if args[0] == "init":
    if "-migrate-state" in args:
        left = int((box / "denied").read_text()) if (box / "denied").exists() else conf.get("denied", 0)
        if left:
            (box / "denied").write_text(str(left - 1)); sys.exit("403")
        # As the real one does: the content goes to the backend and to a backup, and the file is left empty.
        remote.write_text(here.read_text()); pathlib.Path("terraform.tfstate.backup").write_text(here.read_text()); here.write_text("")
elif args[0] == "plan":
    missing = conf["total"] - state()
    if "-out=tfplan" in args: pathlib.Path("tfplan").write_text(json.dumps({"create": conf.get("create", missing), "delete": conf.get("delete", 0)}))
    sys.exit(2 if missing or conf.get("outputs_only") else 0)
elif args[0] == "show":
    p = json.loads(pathlib.Path("tfplan").read_text())
    changes = [{"mode": "managed", "change": {"actions": ["create"]}}] * p["create"] + [{"mode": "managed", "change": {"actions": ["delete", "create"]}}] * p["delete"]
    print(json.dumps({"resource_changes": changes + [{"mode": "data", "change": {"actions": ["read"]}}]}))
elif args[0] == "apply":
    (box / "applied").write_text("yes")
    target = remote if backend else here
    if conf.get("breaks_at") and not (box / "broke").exists():
        (box / "broke").write_text("yes"); target.write_text(str(conf["breaks_at"])); sys.exit("apply failed")
    target.write_text(str(conf["total"]))
elif args[0] == "state":
    print("\n".join(f"r{i}" for i in range(conf.get("arrived", state()))))
elif args[0] == "output":
    print(json.dumps({"cloud": conf["cloud"], "repos": {}}) if "-json" in args else "terraform {}")
"""

CLOUD = r"""#!/usr/bin/env python3
import json, os, pathlib, sys
box, tool, args = pathlib.Path(os.environ["BOX"]), pathlib.Path(sys.argv[0]).name, sys.argv[1:]
conf = json.loads((box / "conf.json").read_text()); line = " ".join(args)
print(tool, *args, file=open(box / "log", "a"))
bucket, has_state = conf.get("bucket", ""), (box / "remote").exists()
trusted = conf["subjects"] + conf.get("extra_subjects", [])
def say(text=""): print(text)
if tool == "aws":
    if "get-caller-identity" in line: say("111122223333" if "Account" in line else "arn:aws:iam::111122223333:user/admin")
    elif "list-buckets" in line: say(bucket or "None")
    elif "list-open-id" in line and conf.get("no_providers"): sys.exit("AccessDenied")
    elif "describe-availability-zones --region eu-west-2" in line: sys.exit("UnauthorizedOperation" if conf.get("no_london") else 0)
    elif "list-open-id" in line: say("OPENIDCONNECTPROVIDERLIST\tarn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com" if conf.get("in_the_way") else "")
    elif "head-object" in line: sys.exit(0 if has_state else 1)
    elif "list-roles" in line: say(json.dumps({"Roles": [{"AssumeRolePolicyDocument": {"Statement": [{"Principal": {"Federated": "x/token.actions.githubusercontent.com"}, "Condition": {"StringEquals": {"token.actions.githubusercontent.com:sub": s}}}]}} for s in trusted]}))
    else: sys.exit("aws? " + line)
elif tool == "az":
    if "account show" in line and "storage" not in line: say({"id": "00000000-0000-0000-0000-000000000000", "name": "Example"}.get(args[args.index("--query") + 1], "someone"))
    elif "storage account list" in line: say(bucket)
    elif "group exists" in line: say("true" if conf.get("in_the_way") else "false")
    elif "blob exists" in line: say("true" if has_state else "false")
    elif "identity list" in line: say("only-one")
    elif "federated-credential list" in line: say("\n".join(trusted))
    else: sys.exit("az? " + line)
elif tool == "gcloud":
    if "billing projects describe" in line: say(conf.get("billing", "True"))
    elif "services enable" in line or "service-accounts describe" in line: pass
    elif "projects describe" in line: say("210987654321")
    elif "remove-iam-policy-binding" in line: (box / "stripped").write_text("yes")
    elif "get-iam-policy" in line:
        say("user:owner@example.com\nserviceAccount:210987654321@cloudservices.gserviceaccount.com")
        if conf.get("editor") or not (box / "stripped").exists(): say("serviceAccount:210987654321-compute@developer.gserviceaccount.com")
    elif "buckets list" in line: say(bucket)
    elif "storage ls" in line: sys.exit(0 if has_state else 1)
    elif "providers describe" in line: say("assertion.sub in " + json.dumps(trusted))
    else: sys.exit("gcloud? " + line)
"""


class Run(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.box = pathlib.Path(self.dir.name)
        shutil.copytree(BOOTSTRAP, self.box / "bootstrap", ignore=shutil.ignore_patterns(".terraform", "__pycache__"))
        bin_ = self.box / "bin"
        bin_.mkdir()
        for name in ("aws", "az", "gcloud"):
            self.tool(bin_ / name, CLOUD)
        self.tool(self.box / "terraform", TERRAFORM)
        # Instead of downloading: put the stand-in where the real one would go.
        self.tool(self.box / "bootstrap/scripts/install-terraform.sh", f'#!/bin/sh\nmkdir -p "$1"\ncp "{self.box}/terraform" "$1/terraform"\n')
        (self.box / "tmp").mkdir()

    def tool(self, path, text):
        path.write_text(text)
        path.chmod(0o755)

    def prepare(self, cloud, github=0, **conf):
        total = conf.pop("total", EXPECTED[cloud])
        (self.box / "conf.json").write_text(json.dumps({"cloud": cloud, "total": total, "subjects": SUBJECTS, **conf}))
        self.tool(self.box / "bootstrap/scripts/github_checks.py", f"#!/usr/bin/env python3\nraise SystemExit({github})\n")
        return ["bash", str(self.box / "bootstrap/scripts/run.sh"), cloud], {
            **os.environ,
            "BOX": str(self.box),
            "PATH": f"{self.box}/bin:{os.environ['PATH']}",
            "RUN_TMP": str(self.box / "tmp"),
            "RUN_WAIT": "0",
            "TF_VAR_project_id": "example-project-1",
            "TF_VAR_bootstrap_project_id": "example-bootstrap-1",
        }

    def go(self, cloud, answer="yes", github=0, **conf):
        command, env = self.prepare(cloud, github, **conf)
        (self.box / "answer").write_text(answer + "\n")
        env["RUN_TERMINAL"] = str(self.box / "answer")
        done = subprocess.run(command, env=env, capture_output=True, text=True)
        self.out = done.stdout + done.stderr
        return done.returncode

    def type(self, cloud, early, *answers, without=()):
        """Runs it at a real terminal. Types `early` at once, and the next answer whenever it asks something."""
        command, env = self.prepare(cloud)
        for name in without:
            del env[name]
        child, terminal = pty.fork()
        if child == 0:
            try:
                os.execvpe(command[0], command, env)
            finally:
                os._exit(2)
        os.write(terminal, early.encode())
        self.out, given, deadline = "", 0, time.monotonic() + 60
        while time.monotonic() < deadline:
            if not select.select([terminal], [], [], 1)[0]:
                continue
            try:
                data = os.read(terminal, 4096)
            except OSError:  # How Linux says that the other side is gone.
                break
            if not data:
                break
            self.out += data.decode(errors="replace")
            if len(re.findall("Type yes to go on: |Id of the [^:]*: ", self.out)) > given and given < len(answers):
                os.write(terminal, answers[given].encode())
                given += 1
        else:
            os.kill(child, signal.SIGKILL)
        os.close(terminal)
        return os.waitstatus_to_exitcode(os.waitpid(child, 0)[1])

    @property
    def stack(self):
        return self.box / "bootstrap" / self.cloud

    def applied(self):
        return (self.box / "applied").exists()

    def log(self):
        path = self.box / "log"
        return path.read_text() if path.exists() else ""

    def each_cloud(self):
        for cloud in EXPECTED:
            with self.subTest(cloud):
                self.setUp()
                self.cloud = cloud
                yield cloud

    def test_first_run(self):
        for cloud in self.each_cloud():
            self.assertEqual(self.go(cloud), 0, self.out)
            self.assertTrue(self.applied())
            self.assertEqual((self.box / "remote").read_text(), str(EXPECTED[cloud]))
            for leftover in ("terraform.tfstate", "terraform.tfstate.backup", "tfplan"):
                self.assertFalse((self.stack / leftover).exists(), leftover)
            self.assertIn("15 subjects match", self.out)
            self.assertIn('{"cloud": "' + cloud, self.out)
            self.assertNotRegex(self.log(), r"terraform (destroy|apply -auto)")
            for line in self.log().splitlines():
                if line.startswith("terraform init"):
                    self.assertIn("-lockfile=readonly", line)

    def test_no_means_nothing_is_created(self):
        for cloud in self.each_cloud():
            for answer in ("no", "y", "", "YES"):
                self.assertEqual(self.go(cloud, answer=answer), 1)
                self.assertFalse(self.applied())
                self.assertFalse((self.stack / "tfplan").exists())

    def test_what_is_typed_early_is_no_answer(self):
        # A second yes to the first question, or an Enter too many, comes long before the plan is on the screen.
        for cloud, early, answers in (("aws", "yes\n", ["no\n"]), ("gcp", "", ["yes\nyes\n", "no\n"])):
            with self.subTest(cloud):
                self.setUp()
                self.assertEqual(self.type(cloud, early, *answers), 1, self.out)
                self.assertIn("Nothing was changed", self.out)
                self.assertFalse(self.applied())

    def test_what_is_typed_early_does_not_spoil_the_answer(self):
        for early in ("\n", "ye", "no\nno"):
            with self.subTest(early):
                self.setUp()
                self.assertEqual(self.type("aws", early, "yes\n"), 0, self.out)
                self.assertTrue(self.applied())

    def test_what_is_typed_early_is_no_project(self):
        names = ("TF_VAR_project_id", "TF_VAR_bootstrap_project_id")
        answers = ("example-project-1\n", "example-bootstrap-1\n", "yes\n", "no\n")
        self.assertEqual(self.type("gcp", "another-project-1\n", *answers, without=names), 1, self.out)
        self.assertIn("Google Cloud projects example-project-1 and example-bootstrap-1", self.out)

    def test_github_side_comes_first(self):
        for cloud in self.each_cloud():
            self.assertEqual(self.go(cloud, github=1), 1)
            self.assertEqual(self.log(), "")

    def test_github_limit_asks(self):
        for cloud in self.each_cloud():
            self.assertEqual(self.go(cloud, github=3, answer="no"), 1)
            self.assertEqual(self.log(), "")
            self.assertEqual(self.go(cloud, github=3), 0, self.out)

    def test_unexpected_plan(self):
        for cloud in self.each_cloud():
            self.assertEqual(self.go(cloud, create=3), 1)
            self.assertIn("should create", self.out)
            self.assertEqual(self.go(cloud, delete=1), 1)
            self.assertIn("would delete", self.out)
            self.assertFalse(self.applied())

    def test_apply_stops_halfway_and_continues(self):
        for cloud in self.each_cloud():
            self.assertEqual(self.go(cloud, breaks_at=20), 1)
            self.assertIn("it continues", self.out)
            self.assertEqual((self.stack / "terraform.tfstate").read_text(), "20")
            # By now the bucket may exist already, without any state in it.
            self.assertEqual(self.go(cloud, breaks_at=20, bucket="tfstate-0a1b2c3d"), 0, self.out)
            self.assertIn("Continuing", self.out)
            self.assertEqual((self.box / "remote").read_text(), str(EXPECTED[cloud]))

    def test_waits_for_access_to_the_bucket(self):
        for cloud in self.each_cloud():
            self.assertEqual(self.go(cloud, denied=3), 0, self.out)
            self.assertIn("(3 of 20)", self.out)

    def test_keeps_the_state_when_it_cannot_be_moved(self):
        for cloud in self.each_cloud():
            self.assertEqual(self.go(cloud, denied=99), 1)
            self.assertEqual((self.stack / "terraform.tfstate").read_text(), str(EXPECTED[cloud]))
            (self.box / "denied").write_text("0")
            self.assertEqual(self.go(cloud, bucket="tfstate-0a1b2c3d"), 0, self.out)
            self.assertIn("Continuing", self.out)

    def test_keeps_the_state_when_too_little_arrives(self):
        for cloud in self.each_cloud():
            self.assertEqual(self.go(cloud, arrived=EXPECTED[cloud] - 1), 1)
            self.assertIn("terraform.tfstate.backup", self.out)
            self.assertEqual((self.stack / "terraform.tfstate.backup").read_text(), str(EXPECTED[cloud]))

    def test_run_again_when_all_is_done(self):
        for cloud in self.each_cloud():
            (self.box / "remote").write_text(str(EXPECTED[cloud]))
            self.assertEqual(self.go(cloud, bucket="tfstate-0a1b2c3d", answer="yes" if cloud == "gcp" else "no"), 0, self.out)
            self.assertFalse(self.applied())
            self.assertIn("tfstate-0a1b2c3d", (self.stack / "backend.tf").read_text())
            self.assertIn("15 subjects match", self.out)

    def test_run_again_for_a_new_output(self):
        for cloud in self.each_cloud():
            (self.box / "remote").write_text(str(EXPECTED[cloud]))
            self.assertEqual(self.go(cloud, bucket="tfstate-0a1b2c3d", outputs_only=True), 0, self.out)
            self.assertTrue(self.applied())

    def test_bucket_without_state(self):
        for cloud in self.each_cloud():
            self.assertEqual(self.go(cloud, bucket="tfstate-0a1b2c3d"), 1)
            self.assertIn("Do not go on", self.out)
            self.assertFalse(self.applied())

    def test_something_in_the_way(self):
        for cloud in ("aws", "azure"):
            with self.subTest(cloud):
                self.setUp()
                self.assertEqual(self.go(cloud, in_the_way=True), 1)
                self.assertFalse(self.applied())

    def test_aws_account_that_cannot_be_used(self):
        for block, reason in (("no_providers", "identity providers"), ("no_london", "London")):
            with self.subTest(block):
                self.setUp()
                self.assertEqual(self.go("aws", **{block: True}), 1)
                self.assertIn(reason, self.out)
                self.assertNotIn("terraform", self.log())

    def test_an_extra_subject_is_not_accepted(self):
        for cloud in self.each_cloud():
            self.assertEqual(self.go(cloud, extra_subjects=["repo:anyone/x:pull_request"]), 1)
            self.assertIn("differs from subjects.json", self.out)
            self.assertNotIn("pbpaste", self.out)

    def test_google_needs_billing_and_no_editor(self):
        self.assertEqual(self.go("gcp", billing="False"), 1)
        self.assertIn("not linked to billing", self.out)
        self.assertEqual(self.go("gcp", editor=True), 1)
        self.assertIn("Editor", self.out)
        self.assertFalse(self.applied())

    def test_usage(self):
        for arguments in ([], ["oracle"]):
            done = subprocess.run(["bash", str(BOOTSTRAP / "scripts/run.sh"), *arguments], capture_output=True, text=True)
            self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
