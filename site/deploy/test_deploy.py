"""Runs deploy.py against stand-ins for GitHub, Terraform, AWS, Azure and the public site. Nothing real is called."""

import contextlib
import datetime
import email.message
import hashlib
import http.server
import io
import json
import pathlib
import re
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import deploy

sys.path.insert(0, str(deploy.SCRIPTS))
from test_check_sign_in import jwt

ACCOUNT, BUCKET = "111122223333", "tfstate-0a1b2c3d"
CLIENT_ID, SUBSCRIPTION, TENANT, STORAGE, LOOKING_ID = (f"{digit * 8}-{digit * 4}-{digit * 4}-{digit * 4}-{digit * 12}" for digit in "12345")
SECRET, SESSION, BEARER, UPLOAD_KEY, ASKING = "aws-secret-of-the-session", "aws-session-token", "azure-bearer-token", "azure-upload-key", "github-asking-token"
STORE_BEARER = "azure-storage-token"
# Where Terraform keeps the state on Azure, from the stack itself.
BACKEND = dict(re.findall(r'^ +(container_name|key) += "(.*)"$', (deploy.SITE / "infra/azure/versions.tf").read_text(), re.M))
AZURE_STATE = f"{BACKEND['container_name']}/{BACKEND['key']}"
# Each environment gives its jobs an identity of their own.
ROLES = {tier: f"arn:aws:iam::{ACCOUNT}:role/github-actions/gha-cloud-labs-{tier}" for tier in ("plan", "apply")}
CLIENTS = {"plan": LOOKING_ID, "apply": CLIENT_ID}
TOKENS = {tier: jwt(deploy.SUBJECTS["cloud-labs"][tier]) for tier in ROLES}
GITHUB = "github-token-of-the-job"
HIDDEN = [ACCOUNT, BUCKET, *ROLES.values(), *CLIENTS.values(), SUBSCRIPTION, TENANT, STORAGE, SECRET, SESSION, BEARER, STORE_BEARER, *TOKENS.values(), ASKING, GITHUB]

FILES = {
    "404.html": b"<h1>not here</h1>",
    "_astro/Page.abc.css": b"body{}",
    "builds/react/main.js": b"1",
    "es/index.html": b"<h1>hola</h1>",
    "favicon.svg": b"<svg/>",
    "index.html": b"<h1>hello</h1>",
    "proof/index.html": b"<h1>proof</h1>",
    "robots.txt": b"User-agent: *",
}
FILES[deploy.LIST] = deploy.listing(FILES)
SAFE = {
    "referrer-policy": "strict-origin-when-cross-origin",
    "strict-transport-security": "max-age=31536000",
    "x-content-type-options": "nosniff",
    "x-frame-options": "SAMEORIGIN",
}
CLIENT = b"the upload client"
AWS_PLACE = {"bucket": "cloud-labs-site-20261124134512345600000001", "distribution": "EEXAMPLE0123", "host": "dexample0123.cloudfront.net"}
AZURE_PLACE = {"host": "lively-example-0a1b2c3d4.5.azurestaticapps.net"}


def with_list(files):
    return files | {deploy.LIST: deploy.listing(files)}


def state_of(cloud, place):
    """What Terraform says about the resources that exist."""
    if not place:
        return {"format_version": "1.0"}
    values = {
        "aws": {"aws_s3_bucket.site": {"bucket": place.get("bucket")}, "aws_cloudfront_distribution.site": {"id": place.get("distribution"), "domain_name": place.get("host")}},
        "azure": {"azapi_resource.site": {"output": {"host": place.get("host")}}},
    }[cloud]
    return {"format_version": "1.0", "values": {"root_module": {"resources": [{"address": address, "values": value} for address, value in values.items()]}}}


def change(address, *actions, before=None, after=None, unknown=None):
    return {"address": address, "change": {"actions": list(actions), "before": before, "after": after, "after_unknown": unknown or {}}}


NEW = {
    "aws": [change(address, "create", after={"name": address}, unknown={"id": True}) for address in sorted(deploy.STACK["aws"])],
    "azure": [change("azapi_resource.site", "create", after={"location": "westeurope"}, unknown={"output": True})],
}
SWITCHED_ON = change("aws_cloudfront_distribution.site", "update", before={"enabled": False, "etag": "A"}, after={"enabled": True}, unknown={"etag": True, "origin": [{}]})


def headers(values):
    message = email.message.Message()
    for name, value in values.items():
        message[name] = value
    return message


class World:
    """GitHub, Terraform, both clouds and the public site, as they should answer. Whoever signs in as plan can only look."""

    def __init__(self, cloud, plan=None, place=None, token=None, **changes):
        self.cloud, self.token, self.changes, self.place = cloud, token, changes, place
        # Which identity the job's environment stands for, and whether Azure has a state of the site.
        self.tier, self.state = None, True
        self.plan = {"format_version": "1.2", "complete": True, "errored": False, "resource_changes": NEW[cloud] if plan is None else plan}
        self.ran, self.sent, self.asked, self.environments, self.slept = [], [], [], [], 0
        self.there, self.plans, self.registered, self.night = {}, [], "Registered", "success"
        self.site, self.extra, self.visits, self.newest = dict(FILES), {}, 0, "c0ffee"

    # What is started on the machine.
    def run(self, command, env, **options):
        line = " ".join(command)
        assert "web-identity" in line or not pathlib.Path(env["HOME"], "token").exists(), "the token is still there"
        self.ran.append(line)
        self.environments.append((line, env))
        done = lambda output="", code=0, error="": subprocess.CompletedProcess(command, code, output, error)
        for part, reply in self.changes.items():
            if part in line:
                return done(*reply)
        if command[0] == "bash":
            assert command[1].endswith("install-terraform.sh")
            return done()
        if command[0] == "terraform":
            if self.cloud == "azure" and command[2] == "init" and not self.init_on_azure(pathlib.Path(command[1].removeprefix("-chdir=")), command[3:]):
                return done("", 1, f"Error: failed to lock azure state: unexpected status 403 AuthorizationPermissionMismatch in {STORAGE}")
            return done(self.terraform(command[2:], env))
        if command[0] == "aws":
            return done(json.dumps(self.aws(command[1:], env)))
        assert command[0].endswith("/StaticSitesClient"), command
        self.uploaded = {path.relative_to(env["APP_LOCATION"]).as_posix(): path.read_bytes() for path in pathlib.Path(env["APP_LOCATION"]).rglob("*") if path.is_file()}
        assert pathlib.Path(command[0]).read_bytes() == CLIENT
        return done("Finished. " + env["DEPLOYMENT_TOKEN"])

    def init_on_azure(self, folder, arguments):
        """Terraform's backend writes an empty state if there is none, and says no if it may not."""
        remote, local = f"-backend-config=storage_account_name={STORAGE}" in arguments, (folder / "local_override.tf").exists()
        assert remote != local and not (deploy.SITE / "infra" / "azure" / "local_override.tf").exists(), "either Azure keeps the state or this copy does"
        assert local == (folder != deploy.SITE / "infra" / "azure") and (folder / "main.tf").read_text() == (deploy.SITE / "infra" / "azure" / "main.tf").read_text()
        if remote and not self.state and self.tier == "plan":
            return False
        self.state = self.state or remote
        return True

    def terraform(self, arguments, env):
        self.variables = {name: value for name, value in env.items() if name.startswith("TF_VAR_")}
        if arguments == ["show", "-json"]:
            return json.dumps(state_of(self.cloud, self.place))
        if arguments[0] == "show":
            return json.dumps(self.plan)
        if arguments[0] == "apply":
            self.place = {"aws": AWS_PLACE, "azure": AZURE_PLACE}[self.cloud]
        else:
            assert arguments[0] in ("init", "plan"), arguments
        return ""

    def aws(self, arguments, env):
        action = arguments[:2]
        given = dict(zip(arguments[2::2], arguments[3::2]))
        if action == ["sts", "assume-role-with-web-identity"]:
            assert pathlib.Path(given["--web-identity-token"].removeprefix("file://")).read_text() == TOKENS[self.tier] and given["--role-arn"] == ROLES[self.tier]
            return {"Credentials": {"AccessKeyId": "ASIAEXAMPLE", "SecretAccessKey": SECRET, "SessionToken": SESSION}}
        assert env["AWS_SESSION_TOKEN"] == SESSION
        assert self.tier == "apply" or action[1].startswith("list-"), "plan may only look"
        if action == ["pricing-plan-manager", "list-subscriptions"]:
            assert given["--region"] == "us-east-1"
            return {"subscriptionSummaries": self.plans}
        if action == ["s3api", "list-objects-v2"]:
            return {"Contents": [{"Key": name, "ETag": f'"{etag}"'} for name, etag in self.there.items()]} if self.there else {}
        if action == ["s3api", "put-object"]:
            body = pathlib.Path(given["--body"]).read_bytes()
            self.there[given["--key"]] = hashlib.md5(body).hexdigest()
            return {}
        if action == ["s3api", "delete-object"]:
            del self.there[given["--key"]]
            return {}
        if action == ["cloudfront", "create-invalidation"]:
            return {"Invalidation": {"Id": "I1"}}
        assert action == ["cloudfront", "wait"], arguments
        return {}

    # What is sent to GitHub, Azure and Microsoft.
    def send(self, method, url, headers=None, body=None):
        path = urllib.parse.urlsplit(url).path
        self.sent.append((method, path))
        for part, reply in self.changes.items():
            if part in url:
                return reply
        if url.startswith("https://token.example/"):
            return 200, {}, json.dumps({"value": self.token or TOKENS[self.tier]}).encode()
        if "login.microsoftonline.com" in url:
            form = urllib.parse.parse_qs(body.decode())
            assert form["client_id"] == [CLIENTS[self.tier]] and form["client_assertion"] == [TOKENS[self.tier]]
            return 200, {}, json.dumps({"access_token": {"https://management.azure.com/.default": BEARER, "https://storage.azure.com/.default": STORE_BEARER}[form["scope"][0]]}).encode()
        if url == deploy.CLIENT:
            return 200, {}, CLIENT
        if url == f"https://{STORAGE}.blob.core.windows.net/{AZURE_STATE}":
            assert method == "HEAD" and headers["Authorization"] == f"Bearer {STORE_BEARER}"
            return (200, {"Content-Length": "181"}, b"") if self.state else (404, {"x-ms-error-code": "BlobNotFound"}, b"")
        assert headers["Authorization"] == f"Bearer {BEARER}"
        if self.tier == "plan":
            # It may read its own resource group, and nothing here asks for that.
            return 403, {}, b'{"error": {"code": "AuthorizationFailed"}}'
        if method == "GET" and path.endswith("/providers/Microsoft.Web"):
            return 200, {}, json.dumps({"registrationState": self.registered}).encode()
        if path.endswith("/providers/Microsoft.Web/register"):
            self.registered = "Registered"
            return 200, {}, b"{}"
        if path.endswith("/listSecrets"):
            return 200, {}, json.dumps({"properties": {"apiKey": UPLOAD_KEY}}).encode()
        assert path.endswith("/resetapikey") and json.loads(body) == {"properties": {"shouldUpdateRepository": False}}, url
        return 200, {}, b""

    # What a visitor gets.
    def ask(self, url, method="GET"):
        parts = urllib.parse.urlsplit(url)
        self.visits += 1
        self.asked.append(url)
        if parts.scheme == "https" and (method, parts.path) in self.extra:
            return self.extra[method, parts.path]
        if parts.scheme == "http":
            return self.extra.get(("GET", "/unencrypted")) or (301, headers({"Location": f"https://{parts.netloc}/"}), b"")
        if method != "GET":
            return 405, headers(SAFE), b""
        name = parts.path[1:] + "index.html" if parts.path.endswith("/") else parts.path[1:]
        if name in self.site and name != "404.html":
            kind = deploy.TYPES[pathlib.Path(name).suffix]
            return 200, headers(SAFE | {"Content-Type": kind}), self.site[name]
        if name + "/index.html" in self.site:
            return 301, headers(SAFE | {"Location": parts.path + "/"}), b""
        return 404, headers(SAFE | {"Content-Type": "text/html"}), self.site["404.html"]

    # What GitHub says about the night run.
    def fetch(self, path):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if "/runs?" in path:
            return {"workflow_runs": [{"created_at": now, "status": "completed", "conclusion": self.night}]}
        if "/commits?path=site" in path:
            return [{"sha": self.newest if "sha=main" in path else "c0ffee"}]
        if "/commits?" in path:
            return [{"commit": {"committer": {"date": now}}}]
        return {"workflows": [{"id": 1, "path": ".github/workflows/nightly-destroy.yml", "state": "active"}]}

    def sleep(self, seconds):
        self.slept += 1


class Deploy(unittest.TestCase):
    def setUp(self):
        patch = unittest.mock.patch.object(deploy, "CLIENT_SHA256", hashlib.sha256(CLIENT).hexdigest())
        patch.start()
        self.addCleanup(patch.stop)

    def go(self, step, world, fingerprint=None, files=FILES, **env):
        world.tier = {"look": "plan", "apply": "apply"}[step]
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            out = folder / "out"
            for name, body in files.items():
                (out / name).parent.mkdir(parents=True, exist_ok=True)
                (out / name).write_bytes(body)
            (folder / "runner").mkdir()
            github = {
                "PATH": "/usr/bin",
                "HOME": "/home/runner",
                "RUNNER_TEMP": str(folder / "runner"),
                "GITHUB_OUTPUT": str(folder / "output"),
                "GITHUB_REPOSITORY": "oplf-svg/cloud-labs",
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_RUN_ID": "45383236941",
                "GITHUB_SHA": "c0ffee",
                "GITHUB_TOKEN": GITHUB,
                "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.example/?x=1",
                "ACTIONS_ID_TOKEN_REQUEST_TOKEN": ASKING,
                "AWS_ACCOUNT_ID": ACCOUNT,
                "AWS_ROLE_ARN": ROLES[world.tier],
                "AWS_STATE_BUCKET": BUCKET,
                "AZURE_CLIENT_ID": CLIENTS[world.tier],
                "AZURE_STATE_ACCOUNT": STORAGE,
                "AZURE_SUBSCRIPTION_ID": SUBSCRIPTION,
                "AZURE_TENANT_ID": TENANT,
            }
            if fingerprint:
                github["FINGERPRINT"] = fingerprint
            screen = io.StringIO()
            with contextlib.redirect_stdout(screen):
                code = deploy.main([step, world.cloud], env=github | env, run=world.run, send=world.send, ask=world.ask, fetch=world.fetch, sleep=world.sleep, folder=out)
            self.assertEqual(list((folder / "runner").iterdir()), [], "something was left behind")
            written = (folder / "output").read_text() if (folder / "output").exists() else ""
        output = screen.getvalue()
        for value in HIDDEN:
            self.assertNotIn(value, output)
        self.assertLessEqual(output.count(UPLOAD_KEY), 1)
        if UPLOAD_KEY in output:
            self.assertIn(f"::add-mask::{UPLOAD_KEY}\n", output)
        self.mark = written.removeprefix("fingerprint=").strip()
        return code, output

    def looked(self, cloud, **options):
        world = World(cloud, **options)
        code, output = self.go("look", world)
        self.assertEqual(code, 0, output)
        return self.mark

    def changed(self, world):
        """Everything that was done to a cloud, not counting what was only asked."""
        started = [line for line in world.ran if " apply " in line or re.search("put-object|delete-object|create-invalidation|StaticSitesClient", line)]
        return started + [path for method, path in world.sent if method == "POST" and "oauth2" not in path]

    def test_looking_changes_nothing(self):
        for cloud in ("aws", "azure"):
            with self.subTest(cloud):
                world = World(cloud)
                code, output = self.go("look", world)
                self.assertEqual((code, self.changed(world)), (0, []), output)
                for line in NEW[cloud]:
                    self.assertIn(f"     create {line['address']}\n", output)
                self.assertTrue(output.startswith(f"9 files, {hashlib.sha256(FILES['files.txt']).hexdigest()}\n"))
                self.assertIn("The files: 9 new, 0 changed, 0 removed.\n" + "".join(f"     new {name}\n" for name in sorted(FILES)), output)
                self.assertRegex(self.mark, "^[0-9a-f]{64}$")
                self.assertTrue(all("-lock=false" in line for line in world.ran if " plan " in line))
                self.assertTrue(all("-lockfile=readonly" in line for line in world.ran if " init " in line))
                self.assertEqual(f"The settings: staticwebapp.config.json, {hashlib.sha256(deploy.SETTINGS.read_bytes()).hexdigest()}\n" in output, cloud == "azure")

    def test_looking_does_not_turn_anything_on(self):
        # Whoever looks may not ask whether they are on. They are where a site exists, and may not be where one is made:
        # the first time, or again after someone deleted it by hand.
        line = "     turn on static sites (Microsoft.Web) in the subscription"
        adjusted = [change("azapi_resource.site", "update", before={"x": "a"}, after={"x": "b"})]
        for registered in ("NotRegistered", "Registered"):
            for plan, place, expected in ((None, None, [line + ", if they are off"]), (None, AZURE_PLACE, [line + ", if they are off"]), ([], AZURE_PLACE, []), (adjusted, AZURE_PLACE, [])):
                world = World("azure", plan=plan, place=place)
                world.registered = registered
                code, output = self.go("look", world)
                self.assertEqual((code, self.changed(world), world.registered), (0, [], registered), output)
                self.assertEqual([text for text in output.splitlines() if "static sites" in text], expected)
                self.assertFalse([path for _, path in world.sent if "Microsoft.Web" in path])
        # Whoever deploys may ask, and says what is so.
        mark = self.looked("azure")
        for registered, expected in (("NotRegistered", [line]), ("Registered", [])):
            world = World("azure")
            world.registered = registered
            code, output = self.go("apply", world, mark)
            self.assertEqual((code, world.registered, [text for text in output.splitlines() if "static sites" in text]), (0, "Registered", expected), output)

    def test_looking_at_azure_writes_no_state(self):
        # With a state it is read where it is. Without one, or with an empty file, Terraform would write one.
        world = World("azure")
        code, output = self.go("look", world)
        mark = self.mark
        self.assertEqual((code, world.state), (0, True), output)
        self.assertTrue(any(f" init -no-color -lockfile=readonly -backend-config=storage_account_name={STORAGE}" in line for line in world.ran))
        for reply in (None, (200, {"Content-Length": "0"}, b"")):
            world = World("azure", **({"/site/terraform.tfstate": reply} if reply else {}))
            world.state = False
            code, output = self.go("look", world)
            self.assertEqual((code, world.state, self.changed(world)), (0, False, []), output)
            self.assertTrue(any(line.endswith(" init -no-color -lockfile=readonly") for line in world.ran))
            # It comes to the same, so the deploy that follows does what was looked at, and writes the state.
            self.assertEqual(self.mark, mark)
            world = World("azure")
            world.state = False
            code, output = self.go("apply", world, mark)
            self.assertEqual((code, world.state), (0, True), output)

    def test_stops_if_azure_does_not_say_whether_there_is_a_state(self):
        for reply in ((403, {"x-ms-error-code": "AuthorizationPermissionMismatch"}, b""), (404, {"x-ms-error-code": "ContainerNotFound"}, b""), (404, {}, b""), (500, {}, b""), (304, {}, b"")):
            with self.subTest(reply):
                world = World("azure", **{"/site/terraform.tfstate": reply})
                code, output = self.go("look", world)
                self.assertEqual((code, self.changed(world), any(line.startswith("terraform") for line in world.ran)), (1, [], False))
                self.assertEqual(output.splitlines()[-1], f"Stopped. Azure refused to say whether there is a state: HTTP {reply[0]}.")

    def test_looking_says_what_would_change_for_visitors(self):
        expected = "The files: 1 new, 2 changed, 2 removed.\n     new robots.txt\n     changed files.txt\n     changed index.html\n     removed (a name that the site does not use)\n     removed old/index.html\n"
        before = with_list({name: body for name, body in FILES.items() if name not in ("robots.txt", "files.txt")} | {"index.html": b"before", "old/index.html": b"old"})
        world = World("aws", plan=[], place=AWS_PLACE)
        world.there = {name: hashlib.md5(body).hexdigest() for name, body in before.items()} | {"::error::pwned": "0" * 32}
        code, output = self.go("look", world)
        self.assertIn(expected, output)
        self.assertIn("The stack:\n     nothing to change\n", output)
        self.assertNotIn("pwned", output)
        world = World("azure", plan=[], place=AZURE_PLACE)
        world.site = dict(before)
        code, output = self.go("look", world)
        self.assertIn(expected.replace("2 removed", "1 removed").replace("     removed (a name that the site does not use)\n", ""), output)
        # A list that says something else is not repeated.
        world.site[deploy.LIST] = b"0" * 64 + b"  ::error::pwned\n"
        code, output = self.go("look", world)
        self.assertEqual((code, "pwned" in output, [url for url in world.asked if "pwned" in url]), (0, False, []))

    def test_does_what_was_looked_at_on_aws(self):
        old = {"old/index.html": "0" * 32}
        first = World("aws")
        first.there = dict(old)
        self.go("look", first)
        world = World("aws")
        code, output = self.go("apply", world, self.mark)
        self.assertEqual(code, 0, output)
        self.assertEqual(world.there, {name: hashlib.md5(body).hexdigest() for name, body in FILES.items()})
        puts = {re.search("--key (.+?) --body", line).group(1): line for line in world.ran if "put-object" in line}
        self.assertEqual(set(puts), set(FILES))
        self.assertTrue(all(f"--bucket {AWS_PLACE['bucket']} " in line for line in puts.values()))
        self.assertIn("--content-type text/html; charset=utf-8 --cache-control public, max-age=0, s-maxage=31536000, must-revalidate", puts["proof/index.html"])
        self.assertIn("--content-type text/css; charset=utf-8 --cache-control public, max-age=31536000, immutable", puts["_astro/Page.abc.css"])
        self.assertIn("--cache-control public, max-age=0,", puts["files.txt"])
        verbs = [line.split()[2] for line in world.ran if line.startswith("terraform")]
        self.assertEqual(verbs, ["init", "show", "plan", "show", "apply", "show"])
        self.assertLess(max(i for i, line in enumerate(world.ran) if " apply " in line), min(i for i, line in enumerate(world.ran) if "put-object" in line))
        self.assertEqual(json.loads(world.variables["TF_VAR_addresses"]), ["/", "/_astro/Page.abc.css", "/builds/react/main.js", "/es/", "/favicon.svg", "/files.txt", "/proof/", "/robots.txt"])
        # It is off, so nobody is told that it works.
        self.assertEqual((world.variables["TF_VAR_on_free_plan"], world.visits), ("false", 0))
        self.assertIn("9 files are there, 0 were removed.\nThe distribution is off until it is on the free plan, so nothing is public yet.", output)

    def test_removes_what_was_shown_to_be_removed(self):
        def world():
            here = World("aws", plan=[], place=AWS_PLACE)
            here.there = {"old/index.html": "0" * 32}
            return here

        self.go("look", world())
        now = world()
        code, output = self.go("apply", now, self.mark)
        self.assertEqual((code, set(now.there)), (0, set(FILES)))
        self.assertIn("9 files are there, 1 were removed.\n", output)

    def test_is_on_only_while_it_is_on_the_free_plan(self):
        free = {"planTier": "FREE", "status": "ACTIVE", "resourceArns": [f"arn:aws:cloudfront::{ACCOUNT}:distribution/{AWS_PLACE['distribution']}", f"arn:aws:wafv2:us-east-1:{ACCOUNT}:global/webacl/x/y"]}

        def at(plans, fingerprint=None):
            world = World("aws", plan=[SWITCHED_ON], place=AWS_PLACE)
            world.plans = plans
            return world, *self.go("apply" if fingerprint else "look", world, fingerprint)

        world, code, output = at([free])
        self.assertIn("The distribution is on the free plan.\nThe stack:\n     update aws_cloudfront_distribution.site: enabled, then also etag\n", output)
        world, code, output = at([free], self.mark)
        self.assertEqual((code, world.variables["TF_VAR_on_free_plan"]), (0, "true"), output)
        order = [[index for index, line in enumerate(world.ran) if word in line] for word in ("put-object", "create-invalidation --distribution-id EEXAMPLE0123 --paths /* ", "wait invalidation-completed --distribution-id EEXAMPLE0123 --id I1 ")]
        self.assertEqual([len(found) for found in order], [len(FILES), 1, 1])
        self.assertEqual(sum(order, []), sorted(sum(order, [])))
        self.assertIn("https://dexample0123.cloudfront.net/\nok   8 addresses with the bytes that were built: all\n", output)
        self.assertNotIn("FAIL", output)

        for plans in ([], [free | {"resourceArns": [f"arn:aws:cloudfront::{ACCOUNT}:distribution/ANOTHER"]}]):
            world, code, output = at(plans)
            self.assertEqual((code, world.variables["TF_VAR_on_free_plan"]), (0, "false"))
            self.assertIn("The distribution is not on the free plan.", output)
        for wrong, said in (({"planTier": "PRO"}, "a plan that costs money"), ({"status": "SYNC_IN_PROGRESS"}, "not active yet"), ({"status": "FAILED"}, "not active yet")):
            world, code, output = at([free | wrong])
            self.assertEqual((code, self.changed(world), any(" plan " in line for line in world.ran)), (1, [], False))
            self.assertIn(said, output)

    def test_stops_if_aws_does_not_say_which_plan(self):
        # On the very first look too, because without an answer it could never be switched on.
        for place in (None, AWS_PLACE):
            for reply in (("", 254, "An error occurred (AccessDeniedException) when calling the ListSubscriptions operation: no"), ("", 252, "Invalid choice: pricing-plan-manager")):
                world = World("aws", place=place, **{"pricing-plan-manager": reply})
                code, output = self.go("look", world)
                self.assertEqual((code, self.changed(world), any(" plan " in line for line in world.ran)), (1, [], False))
                self.assertIn("Stopped. AWS refused pricing-plan-manager list-subscriptions: ", output)

    def test_does_what_was_looked_at_on_azure(self):
        world = World("azure")
        world.registered = "NotRegistered"
        code, output = self.go("apply", world, self.looked("azure"))
        self.assertEqual(code, 0, output)
        self.assertEqual(world.uploaded, FILES)
        own = next(env for line, env in world.environments if "StaticSitesClient" in line)
        self.assertEqual(set(own), {"PATH", "HOME", "DEPLOYMENT_ACTION", "DEPLOYMENT_PROVIDER", "DEPLOYMENT_TOKEN", "REPOSITORY_BASE", "APP_LOCATION", "CONFIG_FILE_LOCATION", "SKIP_APP_BUILD", "SKIP_API_BUILD", "VERBOSE"})
        self.assertIn(f"::add-mask::{UPLOAD_KEY}\n", output)
        posts = [path.rsplit("/", 1)[1] for method, path in world.sent if method == "POST" and "oauth2" not in path]
        self.assertEqual(posts, ["register", "listSecrets", "resetapikey"])
        self.assertIn(f"https://{AZURE_PLACE['host']}/\nok   8 addresses with the bytes that were built: all\n", output)
        self.assertNotIn("FAIL", output)

    def test_the_key_for_uploads_is_replaced_even_if_the_upload_fails(self):
        world = World("azure", **{"/StaticSitesClient": ("", 1, f"Reason: No matching app: {SUBSCRIPTION} {UPLOAD_KEY}")})
        world.send = lambda method, url, headers=None, body=None, real=world.send: (200, {}, CLIENT) if url == deploy.CLIENT else real(method, url, headers, body)
        code, output = self.go("apply", world, self.looked("azure"))
        self.assertEqual((code, world.sent[-1][1].rsplit("/", 1)[1], world.visits), (1, "resetapikey", 0))
        self.assertTrue(output.endswith("Stopped. The upload failed.\nNo matching app\n"), output)

    def test_says_so_if_the_key_for_uploads_could_not_be_replaced(self):
        code, output = self.go("apply", World("azure", resetapikey=(500, {}, b"")), self.looked("azure"))
        self.assertEqual((code, output.splitlines()[-1]), (1, "Stopped. Azure refused to replace the key for uploads: HTTP 500."))

    def test_another_upload_client_never_runs(self):
        world = World("azure", **{"swalocaldeploy": (200, {}, b"another client")})
        code, output = self.go("apply", world, self.looked("azure"))
        self.assertEqual((code, output.splitlines()[-1]), (1, "Stopped. Microsoft's upload client is not the one that was checked."))
        self.assertFalse([path for _, path in world.sent if "listSecrets" in path])

    def test_gives_up_if_azure_never_turns_it_on(self):
        world = World("azure", **{"providers/Microsoft.Web?": (200, {}, b'{"registrationState": "Registering"}')})
        code, output = self.go("apply", world, self.looked("azure"))
        self.assertEqual((code, any(" apply " in line for line in world.ran)), (1, False))
        self.assertIn("Azure has not turned on static sites yet.", output)

    def test_does_nothing_that_nobody_looked_at(self):
        for cloud in ("aws", "azure"):
            for mark in (None, "", "0" * 64, "nonsense"):
                with self.subTest(cloud=cloud, mark=mark):
                    world = World(cloud)
                    code, output = self.go("apply", world, mark)
                    self.assertEqual((code, self.changed(world)), (1, []), output)

    def test_does_nothing_if_anything_is_different_by_then(self):
        def refused(world, mark, **options):
            code, output = self.go("apply", world, mark, **options)
            self.assertEqual((code, self.changed(world)), (1, []), output)
            self.assertIn("This is not what was looked at.", output)

        update = lambda before, after="b": [change({"aws": "aws_s3_bucket.site", "azure": "azapi_resource.site"}[cloud], "update", before={"x": before}, after={"x": after})]
        for cloud, place in (("aws", AWS_PLACE), ("azure", AZURE_PLACE)):
            with self.subTest(cloud):
                # What should come of it, and what the files are.
                mark = self.looked(cloud)
                refused(World(cloud, plan=update("a")), mark)
                refused(World(cloud), mark, files=with_list(FILES | {"index.html": b"<h1>something else</h1>"}))
                # Another run, or the same one started again: an old approval is not for now.
                for name, value in (("GITHUB_RUN_ID", "2"), ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_SHA", "decade")):
                    world = World(cloud)
                    world.newest = "decade" if name == "GITHUB_SHA" else "c0ffee"
                    world.fetch = lambda path, real=world.fetch: [{"sha": "same"}] if "path=site" in path else real(path)
                    refused(world, mark, **{name: value})
                # What is there now.
                mark = self.looked(cloud, plan=update("a"), place=place)
                refused(World(cloud, plan=update("another"), place=place), mark)
                refused(World(cloud, plan=update("a", "c"), place=place), mark)
                world = World(cloud, plan=update("a"), place=place)
                world.there, world.site = {"new/index.html": "0" * 32}, with_list(FILES | {"new/index.html": b"newer"})
                refused(world, mark)
                # What Azure is told about headers and redirects.
                with tempfile.TemporaryDirectory() as folder:
                    other = pathlib.Path(folder, "staticwebapp.config.json")
                    other.write_text("{}")
                    with unittest.mock.patch.object(deploy, "SETTINGS", other):
                        refused(World(cloud, plan=update("a"), place=place), mark)
                self.assertEqual(self.go("apply", World(cloud, plan=update("a"), place=place), mark)[0], 0)

    def test_deploys_only_the_newest_version(self):
        for cloud in ("aws", "azure"):
            mark = self.looked(cloud)
            for answer in ([{"sha": "newer"}], [], None):
                world = World(cloud)
                world.fetch = lambda path, real=world.fetch, answer=answer: answer if "path=site&sha=main" in path or answer is None and "path=site" in path else real(path)
                code, output = self.go("apply", world, mark)
                self.assertEqual((code, world.ran, world.sent), (1, [], []))
                self.assertIn("There is a newer version of the site on main.", output)

    def test_never_deletes_replaces_or_adds_something_of_its_own(self):
        bad = {
            "aws_s3_bucket.site would be deleted or replaced.": [change("aws_s3_bucket.site", "delete", before={})],
            "aws_cloudfront_distribution.site would be deleted or replaced.": [change("aws_cloudfront_distribution.site", "delete", "create", before={}, after={})],
            "aws_s3_bucket.site would be deleted": [change("aws_s3_bucket.site", "forget", before={})],
            "not part of the site": [change("aws_iam_role.admin", "create", after={})],
            "has something in it": [change("aws_s3_bucket.site2", "update", before={}, after={})],
            "in it that is not part": [change("data.external.anything", "read", after={})],
        }
        for said, plan in bad.items():
            for step, mark in (("look", None), ("apply", "0" * 64)):
                with self.subTest(said=said, step=step):
                    world = World("aws", plan=plan)
                    code, output = self.go(step, world, mark)
                    self.assertEqual((code, self.changed(world)), (1, []))
                    self.assertIn(said, output)
        hidden = "The plan has a part that nobody would be shown."
        cases = {"complete": (False, "The plan is not complete."), "errored": (True, "The plan is not complete."), "action_invocations": ([{"address": "action.x.y"}], hidden), "deferred_changes": ([], hidden)}
        cases |= {"output_changes": ({"bucket": {"actions": ["update"], "before": "a", "after": "b"}}, hidden), "something_new": ({}, hidden)}
        for part, (value, said) in cases.items():
            world = World("aws")
            world.plan[part] = value
            code, output = self.go("look", world)
            self.assertEqual((code, self.mark), (1, ""))
            self.assertIn(said, output)
        world = World("aws")
        world.plan["output_changes"] = {"x": {"actions": ["no-op"], "before": "a", "after": "a"}}
        self.assertEqual(self.go("look", world)[0], 0)

    def test_stops_if_the_state_names_something_else(self):
        for cloud, place in (
            ("aws", AWS_PLACE | {"bucket": "tfstate-0a1b2c3d"}),
            ("aws", AWS_PLACE | {"bucket": "cloud-labs-site-x"}),
            ("aws", AWS_PLACE | {"distribution": "E1/../.."}),
            ("aws", AWS_PLACE | {"host": "evil.example"}),
            ("azure", {"host": "evil.example"}),
            ("azure", {"host": "evil.example/x.azurestaticapps.net"}),
        ):
            with self.subTest(place=place):
                world = World(cloud, plan=[], place=place)
                code, output = self.go("look", world)
                self.assertEqual((code, self.changed(world), world.asked), (1, [], []))
                self.assertIn("The state names something that is not part of the site.", output)

    def test_waits_until_the_night_run_works(self):
        for cloud in ("aws", "azure"):
            world = World(cloud)
            world.night = "failure"
            code, output = self.go("apply", world, self.looked(cloud))
            self.assertEqual((code, world.ran, world.sent), (1, [], []))
            self.assertIn("Not deployed, because of the night run: last nightly destroy ended with failure.", output)

    def test_each_step_has_an_identity_of_its_own(self):
        others = {"look": ("apply", "destroy"), "apply": ("plan", "destroy")}
        for step, own in (("look", "plan"), ("apply", "apply")):
            subjects = [deploy.SUBJECTS["cloud-labs"][tier] for tier in others[step]]
            # A pull request's, one without an environment, and another repo's.
            subjects += [subjects[0].partition(":environment:")[0] + end for end in (":pull_request", ":ref:refs/heads/main")] + [deploy.SUBJECTS["ai-ops-agent"][own]]
            for subject in subjects:
                for cloud in ("aws", "azure"):
                    with self.subTest(step=step, subject=subject, cloud=cloud):
                        world = World(cloud, token=jwt(subject))
                        code, output = self.go(step, world, "0" * 64 if step == "apply" else None)
                        self.assertEqual((code, output.splitlines()[-1]), (1, f"Stopped. GitHub's subject is not this repo's {own}."))
                        self.assertEqual((world.ran, self.changed(world)), ([], []))
        self.assertIn("This is not the repo", self.go("look", World("aws"), GITHUB_REPOSITORY="oplf-svg/ai-ops-agent")[1])
        self.assertIn("Not set: AWS_ROLE_ARN.", self.go("look", World("aws"), AWS_ROLE_ARN="")[1])

    def test_tools_get_only_what_they_need(self):
        for cloud in ("aws", "azure"):
            world = World(cloud)
            self.go("apply", world, self.looked(cloud))
            for line, env in world.environments:
                self.assertNotIn("GITHUB_TOKEN", env, line)
                self.assertNotIn(GITHUB, env.values(), line)
                self.assertEqual(ASKING in env.values(), line.startswith("terraform") and cloud == "azure", line)
                self.assertNotIn("/home/runner", env.values(), line)

    def test_stops_when_a_sign_in_is_refused(self):
        world = World("aws", **{"assume-role-with-web-identity": ("", 254, f"An error occurred (AccessDenied) when calling it for {ACCOUNT}")})
        self.assertEqual(self.go("look", world)[1].splitlines()[-1], "Stopped. AWS refused sts assume-role-with-web-identity: AccessDenied.")
        world = World("azure", **{"login.microsoftonline.com": (400, {}, b"AADSTS700213: no match for " + TENANT.encode())})
        self.assertEqual(self.go("look", world)[1].splitlines()[-1], "Stopped. Azure refused the sign-in: AADSTS700213.")

    def test_an_error_is_shown_without_ids(self):
        error = f"\x1b[31m╷\n│ Error: creating S3 Bucket (E2JWU1TLDA6YRS): https response error StatusCode: 403, api error AccessDenied: {ROLES['plan']} in {ACCOUNT}\n│ with {BUCKET} of My Company\n╵"
        code, output = self.go("look", World("aws", **{"terraform -chdir": ("", 1, error)}))
        self.assertEqual(output.splitlines()[-3:], ["Stopped. Terraform init failed.", "creating S3 Bucket", "AccessDenied, HTTP 403"])
        self.assertEqual(deploy.harmless('Error: Failed to get "0a1b" of tenant Contoso Ltd'), ["Failed to get"])
        self.assertEqual(deploy.harmless("Reason: No matching Static Web App was found or the api key was invalid."), ["No matching Static Web App was found or the api key was"])

    def test_notices_what_visitors_should_not_get(self):
        ok = {"Content-Type": "text/html"} | SAFE
        page = FILES["index.html"]
        cases = {
            "with the bytes that were built: not /, should be all": {("GET", "/"): (200, headers(ok), b"<h1>other</h1>")},
            "with the bytes that were built: not /proof/, should be all": {("GET", "/proof/"): (500, headers(ok), FILES["proof/index.html"])},
            "each with its own type: not /, should be all": {("GET", "/"): (200, headers(ok | {"Content-Type": "text/plain"}), page)},
            "headers that protect visitors: not x-frame-options, should be all": {("GET", "/"): (200, headers({k: v for k, v in ok.items() if k != "x-frame-options"}), page)},
            "headers that protect visitors: not strict-transport-security, should be all": {("GET", "/"): (200, headers(ok | {"strict-transport-security": "max-age=60"}), page)},
            "cookies: 1, should be none": {("GET", "/"): (200, headers(ok | {"Set-Cookie": "a=b"}), page)},
            "a page without its last slash: HTTP 200, should be moved there": {("GET", "/es"): (200, headers(ok), b"")},
            "a page without its last slash: HTTP 301, should be moved there": {("GET", "/es"): (301, headers(ok | {"Location": "/elsewhere/"}), b"")},
            "a page without its last slash: HTTP 302, should be moved there": {("GET", "/es"): (302, headers(ok | {"Location": "https://evil.example/es/"}), b"")},
            "a visit without TLS: HTTP 301, should be moved to TLS": {("GET", "/unencrypted"): (301, headers({"Location": "https://evil.example/"}), b"")},
            "something sent to it: HTTP 200, should be refused": {("POST", "/"): (200, headers(ok), b"")},
            "sign-in pages: /.auth/login/github, should be none": {("GET", "/.auth/login/github"): (302, headers({"Location": "https://github.com/"}), b"")},
        }
        for line, extra in cases.items():
            with self.subTest(line):
                world = World("azure")
                world.extra = extra
                code, output = self.go("apply", world, self.looked("azure"))
                self.assertEqual(code, 1)
                self.assertEqual([entry for entry in output.splitlines() if entry.startswith("FAIL") and entry.endswith(line)].__len__(), 1, output)
                self.assertTrue(output.endswith("Stopped. What visitors get is not what was built.\n"))
        there = lambda body: (lambda url: "/nowhere-" in url, body, "an address that does not exist: HTTP 200")
        for part, body, line in (there(b""), there(FILES["404.html"]), (lambda url: url.startswith("http:"), b"", "a visit without TLS: HTTP 200")):
            world = World("azure")
            world.ask = lambda url, method="GET", real=world.ask, part=part, body=body: (200, headers(ok), body) if part(url) else real(url, method)
            code, output = self.go("apply", world, self.looked("azure"))
            self.assertEqual(code, 1)
            self.assertIn(f"FAIL {line}", output)

    def test_waits_for_a_new_version_to_be_everywhere(self):
        world = World("azure")
        world.site["index.html"] = b"before"

        def sleep(seconds):
            world.slept += 1
            if world.slept == 3:
                world.site["index.html"] = FILES["index.html"]

        world.sleep = sleep
        code, output = self.go("apply", world, self.looked("azure"))
        self.assertEqual((code, world.slept, output.count("with the bytes")), (0, 3, 1))

    def test_refuses_files_that_the_site_does_not_use(self):
        for name in ("index.php", ".env", "a/.git/config", "run.sh", "a b.html", "es/..%2f.html", "x.HTML"):
            with self.subTest(name):
                world = World("aws")
                code, output = self.go("look", world, files=with_list(FILES | {name: b"x"}))
                self.assertEqual((code, world.ran, world.sent), (1, [], []), output)
                self.assertTrue("something strange among the files" in output or "a kind of file that the site does not use" in output, output)
        for files in ({k: v for k, v in FILES.items() if k != "404.html"}, {k: v for k, v in FILES.items() if k != "files.txt"}, FILES | {"big.txt": b"x" * 8_000_001}, FILES | {f"{n}.txt": b"" for n in range(200)}):
            self.assertIn("not the whole site, or it is far too big", self.go("look", World("aws"), files=files)[1])
        for files in (FILES | {"extra.txt": b"x"}, FILES | {"index.html": b"x"}, {k: v for k, v in FILES.items() if k != "robots.txt"}):
            self.assertIn("The list of the files is not the list of these files.", self.go("look", World("aws"), files=files)[1])
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            for name, body in with_list({"index.html": b"x", "404.html": b"x"}).items():
                (folder / name).write_bytes(body)
            self.assertEqual(set(deploy.read_site(folder)), {"index.html", "404.html", "files.txt"})
            (folder / "linked.txt").symlink_to("/etc/hosts")
            (folder / deploy.LIST).write_bytes(deploy.listing({"index.html": b"x", "404.html": b"x", "linked.txt": pathlib.Path("/etc/hosts").read_bytes()}))
            with self.assertRaisesRegex(deploy.Stop, "something strange"):
                deploy.read_site(folder)


class Consistent(unittest.TestCase):
    def test_the_list_of_resources_is_the_stack(self):
        for cloud, expected in deploy.STACK.items():
            text = "".join(path.read_text() for path in (deploy.SITE / "infra" / cloud).glob("*.tf"))
            self.assertEqual({".".join(found) for found in re.findall(r'^resource "(\w+)" "(\w+)"', text, re.M)}, expected)

    def test_azure_is_told_to_send_the_headers(self):
        config = json.loads((deploy.SITE / "deploy" / "staticwebapp.config.json").read_text())
        for header, fine in deploy.HEADERS.items():
            self.assertTrue(fine(config["globalHeaders"][header].lower()), header)
        self.assertEqual(config["responseOverrides"], {"404": {"rewrite": "/404.html"}})
        self.assertEqual(config["mimeTypes"], deploy.TYPES)
        self.assertEqual(config["routes"][-1], {"route": "/_astro/*", "headers": {"cache-control": deploy.KEEP}})
        closed = {rule["route"] for rule in config["routes"][:-1] if rule.get("statusCode") == 404}
        self.assertLessEqual({*deploy.SIGN_IN, "/.auth/*"}, closed)

    def test_only_the_deploys_wait_for_an_approval(self):
        text = (deploy.SITE.parent / ".github/workflows/site.yml").read_text()
        jobs = dict(re.findall(r"^  ([a-z-]+):\n((?:(?:    .*)?\n)+)", text.partition("\njobs:\n")[2] + "\n", re.M))
        self.assertEqual(set(jobs), {"build", "look-azure", "look-aws", "deploy-azure", "deploy-aws"})
        self.assertNotIn("environment:", jobs.pop("build"))
        for name, job in jobs.items():
            step, _, cloud = name.partition("-")
            self.assertEqual(re.findall("^    environment: (.*)$", job, re.M), ["plan" if step == "look" else "production"], name)
            self.assertEqual(re.findall("deploy.py (.*)$", job, re.M), [f"{'look' if step == 'look' else 'apply'} {cloud}"], name)
            # The secrets of its own cloud and no others.
            used = re.findall(r"^      (\w+): \$\{\{ secrets\.(\w+) \}\}$", job, re.M)
            self.assertEqual(sorted(used), sorted((secret, secret) for secret in deploy.CLOUDS[cloud][0]), name)
            self.assertEqual(job.count("secrets."), len(used), name)
        # A deploy does only what its own look has shown, and the two never wait for an approval together.
        for cloud, needs in (("azure", "[look-azure, look-aws]"), ("aws", "[look-aws, deploy-azure]")):
            self.assertIn(f"    if: ${{{{ !cancelled() && needs.look-{cloud}.result == 'success' }}}}\n    needs: {needs}\n", jobs[f"deploy-{cloud}"])
            self.assertIn(f"      FINGERPRINT: ${{{{ needs.look-{cloud}.outputs.fingerprint }}}}\n", jobs[f"deploy-{cloud}"])
            self.assertIn("    if: ${{ github.event_name != 'pull_request' }}\n    needs: build\n", jobs[f"look-{cloud}"])

    def test_the_night_run_knows_the_stack(self):
        sys.path.insert(0, str(deploy.SCRIPTS))
        import night

        self.assertEqual({cloud: night.declared(cloud).get("site") for cloud in night.NIGHTS}, {"aws": "stays", "azure": "stays", "gcp": None})


class Visit(unittest.TestCase):
    def test_follows_nothing_and_survives_a_dead_host(self):
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/elsewhere")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            status, headers, body = deploy.visit(f"http://127.0.0.1:{server.server_address[1]}/start")
            self.assertEqual((status, headers.get("location"), body, seen), (302, "/elsewhere", b"", ["/start"]))
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(deploy.visit(f"http://127.0.0.1:{server.server_address[1]}/"), (0, {}, b""))


if __name__ == "__main__":
    unittest.main()
