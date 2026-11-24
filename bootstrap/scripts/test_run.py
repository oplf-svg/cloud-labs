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
EXPECTED = {"aws": 106, "azure": 97, "gcp": 55}
SUBJECTS = [s for file in ("subjects.json", "cost.json") for some in json.loads((BOOTSTRAP / file).read_text()).values() for s in some.values()]

TERRAFORM = r"""#!/usr/bin/env python3
import json, os, pathlib, sys
box, args = pathlib.Path(os.environ["BOX"]), sys.argv[1:]
conf = json.loads((box / "conf.json").read_text())
log = open(box / "log", "a"); print("terraform", *args, file=log)
(box / "developer").write_text(os.environ.get("DEVELOPER_DIR", ""))
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
    update = 0 if (box / "applied").exists() else conf.get("update", 0)
    if "-out=tfplan" in args: pathlib.Path("tfplan").write_text(json.dumps({"create": conf.get("create", missing), "update": update, "delete": conf.get("delete", 0)}))
    sys.exit(2 if missing or update or conf.get("outputs_only") else 0)
elif args[0] == "show":
    p = json.loads(pathlib.Path("tfplan").read_text())
    changes = [{"mode": "managed", "change": {"actions": a}} for a, n in ((["create"], "create"), (["update"], "update"), (["delete", "create"], "delete")) for _ in range(p[n])]
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
    print(json.dumps({"cloud": conf["cloud"], "repos": conf.get("repos", {})}) if "-json" in args else "terraform {}")
"""

CLOUD = r"""#!/usr/bin/env python3
import json, os, pathlib, sys
box, tool, args = pathlib.Path(os.environ["BOX"]), pathlib.Path(sys.argv[0]).name, sys.argv[1:]
conf = json.loads((box / "conf.json").read_text()); line = " ".join(args)
print(tool, *args, file=open(box / "log", "a"))
bucket, has_state = conf.get("bucket", ""), (box / "remote").exists()
trusted = (conf["subjects"] if (box / "applied").exists() else conf.get("subjects_before", conf["subjects"])) + conf.get("extra_subjects", [])
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


# Every test runs as in a Cloud Shell, unless it says that it is on a Mac.
UNAME = r"""#!/usr/bin/env python3
import json, os, pathlib
print(json.loads((pathlib.Path(os.environ["BOX"]) / "conf.json").read_text()).get("system", "Linux"))
"""

# What must not be in a file that others may read.
PRIVATE = ["111122223333", "admin", "00000000-0000-0000-0000-000000000000", "Example", "someone", "example-project-1", "example-bootstrap-1", "210987654321", "tfstate-0a1b2c3d", "owner@example.com", "repo:", "/"]


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
        self.tool(bin_ / "uname", UNAME)
        # Where the closed user of a Mac has its own tools. Outside of it, everything is somebody else's.
        (self.box / "tools").mkdir()
        (self.box / "tools/bin").symlink_to(bin_)
        self.tool(self.box / "terraform", TERRAFORM)
        # Instead of downloading: put the stand-in where the real one would go.
        self.tool(self.box / "bootstrap/scripts/install-terraform.sh", f'#!/bin/sh\nmkdir -p "$1"\ncp "{self.box}/terraform" "$1/terraform"\n')
        (self.box / "tmp").mkdir(mode=0o700)

    def tool(self, path, text):
        path.write_text(text)
        path.chmod(0o755)

    def prepare(self, cloud, github=0, **conf):
        total = conf.pop("total", EXPECTED[cloud])
        (self.box / "conf.json").write_text(json.dumps({"cloud": cloud, "total": total, "subjects": SUBJECTS} | conf))
        self.tool(self.box / "bootstrap/scripts/github_checks.py", f"#!/usr/bin/env python3\nraise SystemExit({github})\n")
        return ["bash", str(self.box / "bootstrap/scripts/run.sh"), cloud], {
            **os.environ,
            "BOX": str(self.box),
            "HOME": str(self.box),
            "PATH": f"{self.box}/bin:{os.environ['PATH']}",
            "RUN_TMP": str(self.box / "tmp"),
            "RUN_WAIT": "0",
            "TF_VAR_project_id": "example-project-1",
            "TF_VAR_bootstrap_project_id": "example-bootstrap-1",
        }

    def go(self, cloud, answer="yes", github=0, env=None, **conf):
        command, given = self.prepare(cloud, github, **conf)
        env = {name: value for name, value in (given | (env or {})).items() if value is not None}
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
            self.assertIn("16 subjects match", self.out)
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
            self.assertIn("16 subjects match", self.out)

    def test_run_again_for_a_new_output(self):
        for cloud in self.each_cloud():
            (self.box / "remote").write_text(str(EXPECTED[cloud]))
            self.assertEqual(self.go(cloud, bucket="tfstate-0a1b2c3d", outputs_only=True), 0, self.out)
            self.assertTrue(self.applied())

    def test_the_value_for_the_costs_stands_by_itself(self):
        names = {"aws": "AWS_ROLE_ARN", "azure": "AZURE_CLIENT_ID", "gcp": "GCP_COST_PROJECT_ID"}
        for cloud in self.each_cloud():
            (self.box / "remote").write_text(str(EXPECTED[cloud]))
            repos = {"webhook-platform": {"production": {names[cloud]: "another"}}, "cloud-labs": {"production": {names[cloud]: "another"}, "cost": {names[cloud]: "the-one"}}}
            self.assertEqual(self.go(cloud, bucket="tfstate-0a1b2c3d", outputs_only=True, repos=repos), 0, self.out)
            self.assertIn(f"environment cost:\n\n  {names[cloud]} = the-one\n", self.out)
            self.assertEqual(self.out.count("another"), 2)
            self.assertEqual(self.go(cloud, bucket="tfstate-0a1b2c3d", outputs_only=True, repos={"cloud-labs": {}}), 0, self.out)
            self.assertNotIn("environment cost", self.out)

    def test_carries_out_a_later_change(self):
        # As when plan came to trust another subject: everything is there already, and some of it changes in place.
        before = [subject.removesuffix(":ref:refs/heads/main") for subject in SUBJECTS if ":environment:cost" not in subject]
        self.assertEqual(len(set(before) - set(SUBJECTS)), 15)
        for cloud in self.each_cloud():
            (self.box / "remote").write_text(str(EXPECTED[cloud]))
            later = {"bucket": "tfstate-0a1b2c3d", "subjects_before": before, "update": 15}
            self.assertEqual(self.go(cloud, answer="no", **later), 1)
            self.assertFalse(self.applied())
            self.assertEqual(self.go(cloud, **later), 0, self.out)
            self.assertIn("This will create 0 and change 15 resources, and delete none, in:", self.out)
            self.assertTrue(self.applied())
            self.assertIn("16 subjects match", self.out)
            self.assertEqual((self.box / "remote").read_text(), str(EXPECTED[cloud]))

    def test_a_replacement_stops_a_later_change(self):
        for cloud in self.each_cloud():
            (self.box / "remote").write_text(str(EXPECTED[cloud]))
            self.assertEqual(self.go(cloud, bucket="tfstate-0a1b2c3d", delete=5), 1)
            self.assertIn("The plan would delete or replace 5 resource(s). Nothing was changed.", self.out)
            self.assertFalse(self.applied())

    def test_a_subject_that_is_no_longer_in_the_list_is_not_accepted(self):
        # What a pull request's job has, and what a job in an environment had before the branch was part of it. Nothing may
        # trust it, not even next to the right ones.
        for old in (SUBJECTS[0].partition(":environment:")[0] + ":pull_request", SUBJECTS[0].removesuffix(":ref:refs/heads/main")):
            for cloud in self.each_cloud():
                (self.box / "remote").write_text(str(EXPECTED[cloud]))
                for wrong in ({"extra_subjects": [old]}, {"subjects": [old, *SUBJECTS[1:]]}, {"subjects": SUBJECTS[1:]}):
                    self.assertEqual(self.go(cloud, bucket="tfstate-0a1b2c3d", **wrong), 1)
                    self.assertIn("differs from subjects.json and cost.json", self.out)
                    self.assertNotIn("pbpaste", self.out)

    def test_the_cost_identity_is_trusted_too(self):
        cost = next(subject for subject in SUBJECTS if ":environment:cost" in subject)
        for cloud in self.each_cloud():
            (self.box / "remote").write_text(str(EXPECTED[cloud]))
            self.assertEqual(self.go(cloud, bucket="tfstate-0a1b2c3d", subjects=[subject for subject in SUBJECTS if subject != cost]), 1)
            self.assertIn(f"< {cost}", self.out)

    def test_google_gets_the_apis_that_it_needs(self):
        self.assertEqual(self.go("gcp"), 0, self.out)
        enabled = [line for line in self.log().splitlines() if "services enable" in line]
        self.assertEqual(len(enabled), 2)
        for name, project in (("bigquery", "example-bootstrap-1"), ("cloudasset", "example-project-1")):
            self.assertEqual([line.endswith(f"--project {project}") for line in enabled if f"{name}.googleapis.com" in line], [True])

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

    # On a Mac

    def there(self, cloud, env=None, **conf):
        """A run on a Mac, where a Cloud Shell has made everything already."""
        (self.box / "remote").write_text(str(EXPECTED[cloud]))
        return self.go(cloud, env=env, **({"bucket": "tfstate-0a1b2c3d", "system": "Darwin"} | conf))

    def test_a_mac_carries_out_a_later_change(self):
        before = [subject.replace(":environment:plan", ":pull_request") for subject in SUBJECTS]
        for cloud in self.each_cloud():
            later = {"subjects_before": before, "update": 5}
            self.assertEqual(self.there(cloud, answer="no", **later), 1)
            self.assertFalse(self.applied())
            self.assertEqual(self.there(cloud, **later), 0, self.out)
            self.assertIn("This will create 0 and change 5 resources, and delete none, in:", self.out)
            self.assertTrue(self.applied())
            self.assertIn("16 subjects match", self.out)
            # GitHub has the ids already, so they are not on the screen.
            self.assertIn("Nothing new", self.out)
            self.assertNotIn('{"cloud": "', self.out)

    def test_a_mac_shows_what_github_needs_if_that_is_new(self):
        for cloud in self.each_cloud():
            for conf in ({"outputs_only": True}, {"total": EXPECTED[cloud] + 2}, {"total": EXPECTED[cloud] + 2, "update": 5}):
                (self.box / "applied").unlink(missing_ok=True)
                self.assertEqual(self.there(cloud, **conf), 0, self.out)
                self.assertIn('{"cloud": "' + cloud, self.out)

    def test_a_mac_makes_no_first_run(self):
        # As in a wrong account: nothing is there, and nothing may be begun.
        for cloud in self.each_cloud():
            self.assertEqual(self.go(cloud, system="Darwin"), 1)
            self.assertIn("Is it the right account?", self.out)
            self.assertFalse(self.applied())
            self.assertNotIn("terraform plan", self.log())

    def test_a_mac_runs_only_what_lies_in_a_closed_folder(self):
        closed = self.box / "tmp"
        (self.box / "link").symlink_to(closed)
        (self.box / "file").write_text("")
        (self.box / "file").chmod(0o600)
        for mode in (0o755, 0o750, 0o705, 0o711, 0o777, 0o701):
            closed.chmod(mode)
            self.assertEqual(self.there("aws"), 1)
            self.assertIn("only you can open", self.out)
        closed.chmod(0o700)
        for name in ("link", "file", "nowhere"):
            self.assertEqual(self.there("aws", env={"RUN_TMP": str(self.box / name)}), 1)
            self.assertIn("only you can open", self.out)
        # Closed, but by somebody else. Every system has one of these.
        for name in ("/root", "/lost+found", "/private/var/db/sudo", "/private/var/audit", "/private/var/db/dhcpclient"):
            path = pathlib.Path(name)
            if path.exists() and path.lstat().st_uid != os.getuid() and path.lstat().st_mode & 0o777 == 0o700:
                self.assertEqual(self.there("aws", env={"RUN_TMP": name}), 1)
                self.assertIn("only you can open", self.out)
                break
        else:
            self.assertNotIn("CI", os.environ, "no folder of somebody else's to try it on")
        self.assertEqual(self.log(), "")
        self.assertEqual(self.there("aws"), 0, self.out)

    def test_a_cloud_shell_has_its_folder_for_itself(self):
        (self.box / "tmp").chmod(0o777)
        self.assertEqual(self.there("aws", system="Linux"), 0, self.out)

    def test_a_mac_makes_a_folder_if_it_is_given_none(self):
        for name in (None, ""):
            own = self.box / f"own{name is None}"
            own.mkdir(mode=0o700)
            # mktemp takes the folder of the user, and not /tmp.
            self.tool(self.box / "bin/mktemp", f'#!/bin/sh\n[ "$*" = -d ] || exit 1\nmkdir -m 700 "{own}/new" && echo "{own}/new"\n')
            self.assertEqual(self.there("aws", env={"RUN_TMP": name}), 0, self.out)
            self.assertEqual(list(own.iterdir()), [])
            self.assertEqual(self.there("aws", env={"RUN_TMP": name}, delete=1), 1)
            self.assertEqual(list(own.iterdir()), [])
        # And none if it has one.
        self.tool(self.box / "bin/mktemp", "#!/bin/sh\nexit 1\n")
        self.assertEqual(self.there("aws"), 0, self.out)

    def test_a_mac_takes_no_tools_of_others(self):
        # As in /usr/local/bin, which administrators may change, and which comes first in a new user's path.
        others = self.box / "others"
        others.mkdir()
        for name in ("aws", "bash", "curl", "git", "jq", "python3", "terraform"):
            real = shutil.which(name, path=f"{self.box}/bin:/usr/bin:/bin:/usr/sbin:/sbin") or "/usr/bin/false"
            self.tool(others / name, f'#!/bin/sh\necho {name} >> "{self.box}/taken"\nexec "{real}" "$@"\n')
        for system, taken in (("Darwin", {"uname"}), ("Linux", {"aws", "git", "jq", "python3", "uname"})):
            (self.box / "taken").unlink(missing_ok=True)
            self.tool(others / "uname", f'#!/bin/sh\necho uname >> "{self.box}/taken"\necho {system}\n')
            env = {"PATH": f"{others}:{self.box}/bin:/usr/bin:/bin:/usr/sbin:/sbin"} | ({"DEVELOPER_DIR": str(others)} if system == "Darwin" else {})
            self.assertEqual(self.there("aws", env=env, system=system, update=1), 0, self.out)
            self.assertEqual((self.box / "developer").read_text(), "/Library/Developer/CommandLineTools" if system == "Darwin" else "")
            # Which system it is has to be asked before anything can be done about it.
            self.assertEqual({line for line in (self.box / "taken").read_text().split() if line != "bash"}, taken)
            (self.box / "applied").unlink()

    def test_github_is_asked_once_in_an_hour(self):
        remembered = self.box / "tmp" / "checked"
        asked = self.box / "asked"
        for cloud in EXPECTED:
            (self.box / "remote").write_text(str(EXPECTED[cloud]))
            command, env = self.prepare(cloud, bucket="tfstate-0a1b2c3d", system="Darwin")
            self.tool(self.box / "bootstrap/scripts/github_checks.py", f"#!/usr/bin/env python3\nprint('asked', file=open({str(asked)!r}, 'a'))\n")
            (self.box / "answer").write_text("yes\n")
            for system in ("Darwin", "Linux"):
                conf = json.loads((self.box / "conf.json").read_text()) | {"system": system}
                (self.box / "conf.json").write_text(json.dumps(conf))
                done = subprocess.run(command, env=env | {"RUN_CHECKED": str(remembered), "RUN_TERMINAL": str(self.box / "answer")}, capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(asked.read_text().count("asked"), 1)
        self.assertEqual(remembered.stat().st_mode & 0o777, 0o600)

    def test_what_is_remembered_is_not_always_believed(self):
        remembered = self.box / "tmp" / "checked"
        env = {"RUN_CHECKED": str(remembered)}

        # The check is part of the mark, so it is the same one that says yes first and no afterwards.
        answers = self.box / "answers"

        def check(code):
            answers.write_text(str(code))
            (self.box / "bootstrap/scripts/github_checks.py").write_text(f"raise SystemExit(int(open({str(answers)!r}).read()))\n")

        def run(**more):
            command, given = self.prepare("aws", bucket="tfstate-0a1b2c3d", system="Darwin")
            (self.box / "remote").write_text(str(EXPECTED["aws"]))
            (self.box / "answer").write_text("yes\n")
            check(more.pop("code", 1))
            done = subprocess.run(command, env=given | env | {"RUN_TERMINAL": str(self.box / "answer")} | more, capture_output=True, text=True)
            self.out = done.stdout + done.stderr
            return done.returncode

        self.assertEqual(run(code=1), 1)
        self.assertFalse(remembered.exists())
        self.assertEqual(run(code=0), 0, self.out)
        self.assertEqual(run(code=1), 0, self.out)
        self.assertIn("less than an hour ago", self.out)
        good = remembered.read_text()
        # Too old, from the future, of something else, open to others, a link, or of another code.
        for seconds in (3601, -60):
            os.utime(remembered, (time.time() - seconds, time.time() - seconds))
            self.assertEqual(run(), 1)
        remembered.write_text("x" + good[1:])
        self.assertEqual(run(), 1)
        remembered.write_text(good)
        for mode in (0o604, 0o640):
            remembered.chmod(mode)
            self.assertEqual(run(), 1)
        remembered.chmod(0o600)
        self.assertEqual(run(), 0, self.out)
        remembered.rename(self.box / "tmp" / "other")
        remembered.symlink_to(self.box / "tmp" / "other")
        self.assertEqual(run(), 1)
        remembered.unlink()
        (self.box / "tmp" / "other").rename(remembered)
        subjects = self.box / "bootstrap/subjects.json"
        before = subjects.read_text()
        subjects.write_text(before + "\n")
        self.assertEqual(run(), 1)
        subjects.write_text(before)
        self.assertEqual(run(), 0, self.out)
        (self.box / "bootstrap/more.json").write_text("{}\n")
        self.assertEqual(run(), 1)
        # In a folder that others can open, nothing is remembered at all.
        (self.box / "open").mkdir(mode=0o755)
        (self.box / "open").chmod(0o755)
        self.assertEqual(run(code=0, RUN_CHECKED=str(self.box / "open" / "checked")), 0, self.out)
        self.assertIn("nothing is remembered", self.out)
        self.assertEqual(list((self.box / "open").iterdir()), [])
        # A check that could not be made is not one that said yes.
        remembered.unlink()
        self.assertEqual(run(code=3), 0, self.out)
        self.assertFalse(remembered.exists())

    def test_github_limit_on_a_mac(self):
        for cloud in self.each_cloud():
            self.assertEqual(self.there(cloud, github=3, answer="no"), 1)
            self.assertIn("Start again in an hour", self.out)
            self.assertNotIn("your own computer", self.out)
            self.assertEqual(self.log(), "")
            self.assertEqual(self.there(cloud, github=3), 0, self.out)

    # The result

    def result(self, folder="results"):
        files = sorted((self.box / folder).iterdir())
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0].name, r"^2\d\d\d-\d\d-\d\dT\d{6}Z-(aws|azure|gcp)\.txt$")
        text = files[0].read_text()
        for value in PRIVATE:
            self.assertNotIn(value, text)
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o644)
        files[0].unlink()
        return text.splitlines()

    def test_the_result(self):
        steps = ["GitHub: the environments behind the trust", "Terraform", "Sign-in", "Plan"]
        last = ["Check: nothing left to change", "Check: every subject this cloud trusts", "For GitHub"]
        for cloud in self.each_cloud():
            where = {"RUN_RESULTS": str(self.box / "results")}
            self.assertEqual(self.there(cloud, env=where, update=5, subjects_before=SUBJECTS), 0, self.out)
            lines = self.result()
            self.assertEqual(lines[0], f"cloud: {cloud}")
            self.assertRegex(lines[1], "^code: ([0-9a-f]{40}|not known)$")
            self.assertRegex(lines[2], r"^began: 2\d\d\d-\d\d-\d\dT\d\d:\d\dZ$")
            self.assertRegex(lines[-1], r"^ended: 2\d\d\d-\d\d-\d\dT\d\d:\d\dZ, ok$")
            expected = [f"step: {step}" for step in steps] + ["plan: 0 to create, 5 to change, 0 to delete", "you said yes", "step: Apply"]
            expected += [f"step: {last[0]}", "nothing is left to change", f"step: {last[1]}", "every subject matches", f"step: {last[2]}"]
            self.assertEqual(lines[3:-1], expected)

    def test_the_result_of_a_run_that_stops(self):
        for conf, seen, stopped_at in (
            ({"answer": "no", "update": 5}, "plan: 0 to create, 5 to change, 0 to delete", "step: Plan"),
            # A replacement counts as both.
            ({"delete": 2}, "plan: 2 to create, 0 to change, 2 to delete", "step: Plan"),
            ({"extra_subjects": ["repo:anyone/x:pull_request"]}, "nothing is left to change", "step: Check: every subject this cloud trusts"),
            ({"github": 1}, "step: GitHub: the environments behind the trust", "step: GitHub: the environments behind the trust"),
            ({"bucket": ""}, "step: Sign-in", "step: Sign-in"),
        ):
            for cloud in self.each_cloud():
                self.assertEqual(self.there(cloud, env={"RUN_RESULTS": str(self.box / "results")}, **conf), 1)
                lines = self.result()
                self.assertTrue(lines[-1].endswith(", stopped"), lines)
                if cloud == "gcp" and conf.get("answer"):
                    # There is a question of its own before the plan.
                    seen = stopped_at = "step: Sign-in"
                self.assertIn(seen, lines)
                self.assertEqual([line for line in lines if line.startswith("step:")][-1], stopped_at)
                self.assertNotIn("you said yes", lines if conf.get("answer") else [])

    def test_what_is_on_the_screen_is_not_in_the_result(self):
        for cloud in self.each_cloud():
            where = {"RUN_RESULTS": str(self.box / "results")}
            # A state store without a state. Its name is on the screen.
            self.assertEqual(self.go(cloud, env=where, bucket="tfstate-0a1b2c3d", system="Darwin"), 1)
            self.assertIn("STOPPED: There is a state store (tfstate-0a1b2c3d)", self.out)
            self.assertTrue(self.result()[-1].endswith(", stopped"))
        self.assertEqual(self.there("gcp", env=where, editor=True), 1)
        self.assertIn("STOPPED: These accounts have Editor again", self.out)
        self.assertIn("210987654321", self.out)
        self.assertTrue(self.result()[-1].endswith(", stopped"))

    def test_a_result_also_in_a_cloud_shell(self):
        self.assertEqual(self.go("aws", env={"RUN_RESULTS": str(self.box / "results")}), 0, self.out)
        self.assertIn("step: Moving the state into the new bucket", self.result())

    def test_the_folder_of_the_result_is_ones_own(self):
        shared = self.box / "shared"
        shared.mkdir()
        (self.box / "link").symlink_to(shared)
        (self.box / "file").write_text("")
        for name, mode in (("shared", 0o777), ("shared", 0o775), ("shared", 0o757), ("link", 0o755), ("file", None), ("nowhere/deeper", None)):
            if mode:
                shared.chmod(mode)
            self.assertEqual(self.there("aws", env={"RUN_RESULTS": str(self.box / name)}), 0, self.out)
            self.assertIn("No result is written", self.out)
            self.assertEqual(list(shared.iterdir()), [])
        # One that is there already, and a new one, whatever files and folders would be made like otherwise.
        for name, mode in (("shared", 0o755), ("shared", 0o700), ("new", None)):
            folder = self.box / name
            if mode:
                folder.chmod(mode)
            command, env = self.prepare("aws", bucket="tfstate-0a1b2c3d", system="Darwin")
            (self.box / "answer").write_text("yes\n")
            (self.box / "remote").write_text(str(EXPECTED["aws"]))
            subprocess.run(["bash", "-c", 'umask 077; exec "$@"', "x", *command], env=env | {"RUN_RESULTS": str(folder), "RUN_TERMINAL": str(self.box / "answer")}, capture_output=True, check=True)
            self.result(name)
            self.assertEqual(folder.stat().st_mode & 0o777, mode or 0o755)

    def test_no_result_without_a_folder(self):
        for folder in (None, ""):
            self.assertEqual(self.there("aws", env={"RUN_RESULTS": folder}), 0, self.out)
            self.assertNotIn("result", self.out)

    def test_usage(self):
        for arguments in ([], ["oracle"]):
            done = subprocess.run(["bash", str(BOOTSTRAP / "scripts/run.sh"), *arguments], capture_output=True, text=True)
            self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
