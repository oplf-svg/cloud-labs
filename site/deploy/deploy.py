#!/usr/bin/env python3
"""Deploys the site to one cloud, in two steps.

  deploy.py look aws | azure     says what would change, and changes nothing
  deploy.py apply aws | azure    does that if it is still the same, and checks what visitors get

Runs in GitHub Actions on main. A look runs in the plan environment, as an identity that can do nothing
else, so nobody has to approve it. An apply runs in the production environment, after a person has approved
it. Job logs are public, so it prints its own words, the names of public files, and errors without anything
that could be an id or an address.
"""

import argparse
import datetime
import hashlib
import hmac
import http.client
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse

SITE = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = SITE.parent / "bootstrap" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from check_sign_in import CLOUDS, OWNER, SUBJECTS, Unusable, answer, github_token, subject_of
from github_checks import check_schedules, get

REPO = "cloud-labs"

# Whose rights each step has.
TIERS = {"look": "plan", "apply": "apply"}

# Everything that each stack may consist of. Anything else in a plan stops the deploy.
STACK = {
    "aws": {
        "aws_cloudfront_distribution.site",
        "aws_cloudfront_function.edge",
        "aws_cloudfront_origin_access_control.site",
        "aws_s3_bucket.site",
        "aws_s3_bucket_lifecycle_configuration.site",
        "aws_s3_bucket_ownership_controls.site",
        "aws_s3_bucket_policy.site",
        "aws_s3_bucket_public_access_block.site",
        "aws_s3_bucket_versioning.site",
    },
    "azure": {"azapi_resource.site"},
}

TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".woff2": "font/woff2",
}
NAME = "[A-Za-z0-9_][A-Za-z0-9._-]*(?:/[A-Za-z0-9_][A-Za-z0-9._-]*)*"

# CloudFront keeps its copies until the next deploy, so that nobody can make it ask the storage again and again.
ALWAYS_ASK = "public, max-age=0, s-maxage=31536000, must-revalidate"
KEEP = "public, max-age=31536000, immutable"

# The list of the files, which is served with them.
LIST = "files.txt"

# Azure offers these to everyone unless it is told not to, and they set cookies.
SIGN_IN = ["/.auth/login/aad", "/.auth/login/github"]

# What Azure is told about headers, redirects and sign-in. It is part of what a deploy changes.
SETTINGS = SITE / "deploy" / "staticwebapp.config.json"

AZURE_SITE = "resourceGroups/rg-cloud-labs/providers/Microsoft.Web/staticSites/cloud-labs-site"
AZURE_STATE = "cloud-labs/site/terraform.tfstate"

# Microsoft's own client for uploads, one fixed build of it.
CLIENT = "https://swalocaldeployv2-bndtgugjgqc3dhdx.b01.azurefd.net/downloads/a58ffd5ddfced557500b295844f2490acc313951/linux/StaticSitesClient"
CLIENT_SHA256 = "0a3c8166b05fa427ed57386d9ba3d82d4f3f3e4f66fabc26c1f934fa705458fa"


class Stop(Exception):
    """Nothing more is done. The message contains no value."""


def harmless(text):
    """What a tool said about an error: the words before any detail, codes and statuses. Nothing that could be an id or a name."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    words = dict.fromkeys(found.strip(" ,") for found in re.findall(r"(?:Error|Reason): ((?:(?:S3|[A-Za-z][A-Za-z'-]*),? ?){1,12})", text))
    codes = dict.fromkeys(code for code in re.findall(r"\b(?:[A-Z][a-z]+){2,7}\b", text) if code not in ("CloudFront", "StatusCode"))
    codes |= dict.fromkeys(f"HTTP {status}" for status in re.findall(r"(?:StatusCode: |RESPONSE |HTTP )([1-5][0-9]{2})\b", text))
    return [line[:200] for line in (*list(words)[:4], ", ".join(list(codes)[:8])) if line]


def call(run, command, env, **options):
    return run(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **options)


def visit(url, method="GET"):
    """One request, as a visitor would send it. Follows nothing."""
    parts = urllib.parse.urlsplit(url)
    kind = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    connection = kind(parts.netloc, timeout=30)
    try:
        connection.request(method, parts.path, headers={"Accept-Encoding": "identity", "User-Agent": "cloud-labs-site"})
        response = connection.getresponse()
        return response.status, response.headers, response.read()
    except (OSError, http.client.HTTPException):
        return 0, {}, b""
    finally:
        connection.close()


# The site


def read_site(folder):
    """The files of the site. Stops if there is anything among them that the site does not consist of."""
    files = {}
    for path in sorted(folder.rglob("*")):
        name = path.relative_to(folder).as_posix()
        if path.is_symlink() or not re.fullmatch(NAME, name):
            raise Stop("There is something strange among the files.")
        if path.is_file():
            if path.suffix not in TYPES:
                raise Stop("There is a kind of file that the site does not use.")
            files[name] = path.read_bytes()
    if not {"index.html", "404.html", LIST} <= set(files) or len(files) > 200 or sum(map(len, files.values())) > 8_000_000:
        raise Stop("This is not the whole site, or it is far too big.")
    if files[LIST] != listing(files):
        raise Stop("The list of the files is not the list of these files.")
    return files


def listing(files):
    """What list-files.mjs writes: every file but the list itself, in the form that sha256sum reads."""
    return "".join(f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n" for name in sorted(files) if name != LIST).encode()


def addresses(files):
    """What visitors ask for, and the file that answers."""
    return {"/" + re.sub(r"(^|/)index\.html$", r"\1", name): name for name in sorted(files) if name != "404.html"}


def digest(files):
    """Stands for all of them. It is also the checksum of the list that is served with them."""
    return hashlib.sha256(files[LIST]).hexdigest()


def difference(files, there):
    """What a deploy does to the files, line by line. `there` has the MD5 of what is deployed now, by name."""
    md5 = {name: hashlib.md5(body, usedforsecurity=False).hexdigest() for name, body in files.items()}
    kinds = {
        "new": sorted(set(files) - set(there)),
        "changed": sorted(name for name in set(files) & set(there) if md5[name] != there[name]),
        "removed": sorted(set(there) - set(files)),
    }
    yield "The files: " + ", ".join(f"{len(names)} {kind}" for kind, names in kinds.items()) + "."
    for kind, names in kinds.items():
        # What is there now could have any name, and a log can be steered by what is printed into it.
        yield from (f"     {kind} {name if re.fullmatch(NAME, name) else '(a name that the site does not use)'}" for name in names)


def look_like_visitors(host, files, ask):
    """Yields what visitors should get, and what they do get."""
    base, wrong, kinds, cookies, weak = f"https://{host}", [], [], set(), set()
    pages = addresses(files)
    for address, name in pages.items():
        status, headers, body = ask(base + address)
        if status != 200 or body != files[name]:
            wrong.append(address)
        if (headers.get("content-type") or "").replace(" ", "").lower().split(";")[0] != TYPES[pathlib.Path(name).suffix].split(";")[0]:
            kinds.append(address)
        if headers.get("set-cookie"):
            cookies.add(address)
        for header, fine in HEADERS.items():
            if not fine((headers.get(header) or "").lower()):
                weak.add(header)
    yield f"{len(pages)} addresses with the bytes that were built", "all", "all" if not wrong else f"not {', '.join(wrong[:5])}"
    yield "each with its own type", "all", "all" if not kinds else f"not {', '.join(kinds[:5])}"
    yield "headers that protect visitors", "all", "all" if not weak else f"not {', '.join(sorted(weak))}"
    yield "cookies", "none", "none" if not cookies else str(len(cookies))

    open_pages = [page for page in SIGN_IN if ask(base + page)[0] != 404]
    yield "sign-in pages", "none", "none" if not open_pages else ", ".join(open_pages)

    status, _, body = ask(f"{base}/nowhere-{os.urandom(6).hex()}/")
    yield "an address that does not exist", "404 and its page", "404 and its page" if (status, body) == (404, files["404.html"]) else f"HTTP {status}"
    folder = next((address for address in pages if address.endswith("/") and address != "/"), None)
    if folder:
        status, headers, _ = ask(base + folder[:-1])
        moved = status in (301, 302, 308) and urllib.parse.urljoin(base + folder[:-1], headers.get("location") or "") == base + folder
        yield "a page without its last slash", "moved there", "moved there" if moved else f"HTTP {status}"
    status, headers, _ = ask(f"http://{host}/")
    safe = status in (301, 302, 307, 308) and (headers.get("location") or "").startswith(base + "/")
    yield "a visit without TLS", "moved to TLS", "moved to TLS" if safe else f"HTTP {status}"
    status, _, _ = ask(base + "/", "POST")
    yield "something sent to it", "refused", "refused" if 400 <= status < 500 else f"HTTP {status}"


def long_enough(value):
    found = re.search("max-age=([0-9]+)", value)
    return bool(found) and int(found.group(1)) >= 15_552_000


# What has to be in every answer, whichever cloud gives it.
HEADERS = {
    "referrer-policy": lambda value: value in ("no-referrer", "same-origin", "strict-origin", "strict-origin-when-cross-origin"),
    "strict-transport-security": long_enough,
    "x-content-type-options": lambda value: value == "nosniff",
    "x-frame-options": lambda value: value in ("deny", "sameorigin"),
}


def check_public(host, files, ask, sleep, tries=40):
    """Asks until everything is as it should be, because a new version takes a while to be everywhere."""
    for left in reversed(range(tries)):
        found = list(look_like_visitors(host, files, ask))
        if left == 0 or all(wanted == got for _, wanted, got in found):
            break
        sleep(15)
    for what, wanted, got in found:
        print(f"ok   {what}: {got}" if got == wanted else f"FAIL {what}: {got}, should be {wanted}", flush=True)
    if any(wanted != got for _, wanted, got in found):
        raise Stop("What visitors get is not what was built.")


# Terraform


class Terraform:
    """Runs in an environment that holds only what Terraform needs."""

    def __init__(self, cloud, env, run, work, secret):
        self.folder, self.work, self.run, self.secret, self.cloud = SITE / "infra" / cloud, work, run, secret, cloud
        tools = work / "tools"
        if call(run, ["bash", str(SCRIPTS / "install-terraform.sh"), str(tools)], {"PATH": env["PATH"], "HOME": str(work)}, timeout=300).returncode:
            raise Stop("Terraform could not be installed.")
        self.env = env | {"PATH": f"{tools}:{env['PATH']}", "TF_DATA_DIR": str(work / "data"), "TF_IN_AUTOMATION": "1", "TF_INPUT": "0", "CHECKPOINT_DISABLE": "1"}

    def __call__(self, *arguments):
        done = call(self.run, ["terraform", f"-chdir={self.folder}", *arguments], self.env, timeout=2400)
        if done.returncode:
            raise Stop("\n".join([f"Terraform {arguments[0]} failed.", *harmless(done.stderr + done.stdout)]))
        return done.stdout

    def init(self, **backend):
        self("init", "-no-color", "-lockfile=readonly", *(f"-backend-config={name}={value}" for name, value in backend.items()))

    def init_without_state(self):
        """For a look before there is a state. Azure's backend would write an empty one, so this copy of the stack uses none."""
        self.folder = shutil.copytree(self.folder, self.work / "stack", ignore=shutil.ignore_patterns(".terraform"))
        (self.folder / "local_override.tf").write_text('terraform {\n  backend "local" {}\n}\n', encoding="utf-8")
        self.init()

    def known(self):
        """What the state holds about each resource, by its address."""
        state = json.loads(self("show", "-json") or "{}")
        return {resource["address"]: resource["values"] for resource in state.get("values", {}).get("root_module", {}).get("resources", [])}

    def plan(self, lock, **variables):
        self.env |= {f"TF_VAR_{name}": value if isinstance(value, str) else json.dumps(value) for name, value in variables.items()}
        file = str(self.work / "tfplan")
        self("plan", "-no-color", f"-out={file}", "-lock-timeout=60s" if lock else "-lock=false")
        plan = json.loads(self("show", "-json", file))
        print("The stack:")
        for line in changes(plan, STACK[self.cloud]):
            print(f"     {line}", flush=True)
        return plan

    def mark(self, plan, files, there, env):
        """Stands for exactly this step: from what is there now to this plan and these files, in this attempt of this run."""
        run = [env[name] for name in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")]
        wanted = [[address, change["actions"], change.get("before"), change.get("after"), change.get("after_unknown")] for address, change in moves(plan)]
        text = json.dumps([run, self.cloud, wanted, there, digest(files), hashlib.sha256(SETTINGS.read_bytes()).hexdigest()], sort_keys=True)
        # It is public, so it depends on values that are not.
        return hmac.new(self.secret.encode(), text.encode(), "sha256").hexdigest()

    def apply(self):
        self("apply", "-no-color", str(self.work / "tfplan"))


# The parts of a plan that are read here, or that cannot change anything. A plan with any other part is not carried out.
PARTS = {
    "applyable", "checks", "complete", "configuration", "errored", "format_version", "output_changes", "planned_values", "prior_state",
    "relevant_attributes", "resource_changes", "resource_drift", "terraform_version", "timestamp", "variables",
}


def moves(plan):
    for change in sorted(plan.get("resource_changes", []), key=lambda change: change["address"]):
        if change["change"]["actions"] != ["no-op"]:
            yield change["address"], change["change"]


def unknown_in(value):
    """Whether a part of it is not known before the change is made."""
    parts = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return value is True or any(map(unknown_in, parts))


def touched(change):
    """The names of what changes, with the new values, and the names of which a part is not known yet."""
    before, after, unknown = change.get("before") or {}, change.get("after") or {}, change.get("after_unknown") or {}
    later = sorted(name for name, value in unknown.items() if unknown_in(value))
    return {name: after.get(name) for name in {*before, *after} if before.get(name) != after.get(name) or name in later}, later


def changes(plan, stack):
    """What the plan would do, in words. Stops if that is more than adding to this stack or adjusting it."""
    if plan.get("errored") or plan.get("complete") is False:
        raise Stop("The plan is not complete.")
    if set(plan) - PARTS or any(change["actions"] != ["no-op"] for change in plan.get("output_changes", {}).values()):
        raise Stop("The plan has a part that nobody would be shown.")
    lines = []
    for address, change in moves(plan):
        if address not in stack:
            raise Stop("The plan has something in it that is not part of the site.")
        if change["actions"] not in (["create"], ["update"]):
            raise Stop(f"{address} would be deleted or replaced. A deploy never does that.")
        known, later = touched(change)
        names = [", ".join(sorted(set(known) - set(later))), "then also " + ", ".join(later) if later else ""]
        detail = ": " + ", ".join(filter(None, names)) if change["actions"] == ["update"] else ""
        lines.append(f"{change['actions'][0]} {address}{detail}")
    return lines or ["nothing to change"]


# AWS


class Refused(Stop):
    pass


def sign_in_to_aws(token, env, run, work):
    bare = {"PATH": env["PATH"], "HOME": str(work), "AWS_CLI_ERROR_FORMAT": "enhanced", "AWS_EC2_METADATA_DISABLED": "true", "AWS_PAGER": ""}
    file = work / "token"
    file.write_text(token, encoding="utf-8")

    def aws(*arguments, region="eu-west-2", keys=bare):
        done = call(run, ["aws", *arguments, "--region", region, "--output", "json"], keys, timeout=1200)
        if done.returncode:
            found = re.search(r"An error occurred \(([A-Za-z][A-Za-z0-9._]{1,63})\)", done.stderr)
            raise Refused(f"AWS refused {' '.join(arguments[:2])}: {found.group(1) if found else 'no error code'}.")
        return json.loads(done.stdout or "{}")

    role = ["--role-arn", env["AWS_ROLE_ARN"], "--role-session-name", "deploy-site"]
    try:
        answered = aws("sts", "assume-role-with-web-identity", *role, "--web-identity-token", f"file://{file}")["Credentials"]
    finally:
        file.unlink()
    keys = bare | {"AWS_ACCESS_KEY_ID": answered["AccessKeyId"], "AWS_SECRET_ACCESS_KEY": answered["SecretAccessKey"], "AWS_SESSION_TOKEN": answered["SessionToken"]}
    return keys, lambda *arguments, **options: aws(*arguments, keys=keys, **options)


def on_free_plan(aws, distribution):
    """Whether AWS bills this distribution by the plan that has no overage charges."""
    try:
        plans = aws("pricing-plan-manager", "list-subscriptions", region="us-east-1").get("subscriptionSummaries", [])
    except Refused as problem:
        # A wrong no would switch the site off, and a wrong yes could cost money.
        raise Stop(f"{problem} Without that answer nothing is done. See the first deploy to AWS in site/README.md.") from None
    for plan in plans:
        if distribution and any(name.endswith(f":distribution/{distribution}") for name in plan["resourceArns"]):
            if plan["planTier"] != "FREE":
                raise Stop("The distribution is on a plan that costs money. Nothing is done until a person has looked at that.")
            if plan["status"] != "ACTIVE":
                raise Stop("The free plan is not active yet. Run this again in a few minutes.")
            return True
    return False


def place_on_aws(known):
    """The bucket, the distribution and its host, if they exist. Stops if the state holds names that this stack cannot have given."""
    bucket, distribution = known.get("aws_s3_bucket.site", {}), known.get("aws_cloudfront_distribution.site", {})
    place = bucket.get("bucket"), distribution.get("id"), distribution.get("domain_name")
    forms = r"cloud-labs-site-[0-9a-f]{26}", "[A-Z0-9]{8,20}", r"[a-z0-9]{8,20}\.cloudfront\.net"
    if any(value and not re.fullmatch(form, value) for value, form in zip(place, forms)):
        raise Stop("The state names something that is not part of the site.")
    return place


def prepare_aws(token, env, run, work, files, lock):
    keys, aws = sign_in_to_aws(token, env, run, work)
    # A look and its apply have to come to the same mark, so nothing is part of it that differs between their identities.
    terraform = Terraform("aws", keys, run, work, env["AWS_ACCOUNT_ID"] + env["AWS_STATE_BUCKET"])
    terraform.init(bucket=env["AWS_STATE_BUCKET"])
    bucket, distribution, _ = place_on_aws(terraform.known())
    on_plan = on_free_plan(aws, distribution)
    print(f"The distribution {'is' if on_plan else 'is not'} on the free plan.")
    plan = terraform.plan(lock, account_id=env["AWS_ACCOUNT_ID"], addresses=sorted(addresses(files)), on_free_plan=on_plan)
    there = stored(aws, bucket) if bucket else {}
    print(*difference(files, there), sep="\n", flush=True)
    return aws, terraform, on_plan, terraform.mark(plan, files, there, env)


def stored(aws, bucket):
    return {item["Key"]: item["ETag"].strip('"') for item in aws("s3api", "list-objects-v2", "--bucket", bucket).get("Contents") or []}


def look_aws(token, env, run, send, ask, work, files):
    return prepare_aws(token, env, run, work, files, lock=False)[-1]


def apply_aws(token, env, run, send, ask, sleep, work, files, folder, agreed):
    aws, terraform, on_plan, mark = prepare_aws(token, env, run, work, files, lock=True)
    agreed(mark)
    terraform.apply()
    bucket, distribution, host = place_on_aws(terraform.known())
    for name in sorted(files):
        kept = KEEP if name.startswith("_astro/") else ALWAYS_ASK
        aws("s3api", "put-object", "--bucket", bucket, "--key", name, "--body", str(folder / name), "--content-type", TYPES[pathlib.Path(name).suffix], "--cache-control", kept)
    gone = sorted(set(stored(aws, bucket)) - set(files))
    for name in gone:
        aws("s3api", "delete-object", "--bucket", bucket, "--key", name)
    print(f"{len(files)} files are there, {len(gone)} were removed.", flush=True)
    if not on_plan:
        print("The distribution is off until it is on the free plan, so nothing is public yet. See site/README.md.")
        return
    made = aws("cloudfront", "create-invalidation", "--distribution-id", distribution, "--paths", "/*")["Invalidation"]["Id"]
    aws("cloudfront", "wait", "invalidation-completed", "--distribution-id", distribution, "--id", made)
    print(f"https://{host}/")
    check_public(host, files, ask, sleep)


# Azure


def sign_in_to_azure(token, env, send, resource="https://management.azure.com"):
    form = {
        "client_id": env["AZURE_CLIENT_ID"],
        "client_assertion": token,
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "grant_type": "client_credentials",
        "scope": f"{resource}/.default",
    }
    status, _, body = send("POST", f"https://login.microsoftonline.com/{env['AZURE_TENANT_ID']}/oauth2/v2.0/token", None, urllib.parse.urlencode(form).encode())
    if status != 200:
        found = re.search(rb"AADSTS[0-9]{4,9}", body)
        raise Refused(f"Azure refused the sign-in: {found.group().decode() if found else f'HTTP {status}'}.")
    return json.loads(body)["access_token"]


def has_state(token, env, send):
    """Whether there is a state with something in it. Terraform takes an empty file for none."""
    key = sign_in_to_azure(token, env, send, "https://storage.azure.com")
    url = f"https://{env['AZURE_STATE_ACCOUNT']}.blob.core.windows.net/{AZURE_STATE}"
    status, headers, _ = send("HEAD", url, {"Authorization": f"Bearer {key}", "x-ms-version": "2023-11-03"})
    if status == 404 and headers.get("x-ms-error-code") == "BlobNotFound":
        return False
    if status != 200:
        raise Refused(f"Azure refused to say whether there is a state: HTTP {status}.")
    return headers.get("Content-Length") != "0"


class Azure:
    """Signs in with GitHub's token. Its answers are never printed."""

    def __init__(self, token, env, send):
        self.key, self.env, self.send = sign_in_to_azure(token, env, send), env, send

    def __call__(self, method, path, version, body=None, what=""):
        url = f"https://management.azure.com/subscriptions/{self.env['AZURE_SUBSCRIPTION_ID']}/{path}?api-version={version}"
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        status, _, answered = self.send(method, url, headers, None if body is None else json.dumps(body).encode())
        if not 200 <= status < 300:
            raise Refused(f"Azure refused to {what}: HTTP {status}.")
        return json.loads(answered or b"{}")

    def registered(self):
        return self("GET", "providers/Microsoft.Web", "2021-04-01", what="say whether static sites are turned on")["registrationState"] == "Registered"


def host_on_azure(known):
    host = (known.get("azapi_resource.site", {}).get("output") or {}).get("host")
    if host and not re.fullmatch(r"[a-z0-9-]{1,60}\.(?:[0-9]+\.)?azurestaticapps\.net", host):
        raise Stop("The state names something that is not part of the site.")
    return host


def served(host, files, ask):
    """The MD5 of what visitors get now, by name. Azure has no list of its own, so the one that is served with the site is used."""
    there, (status, _, body) = {}, ask(f"https://{host}/{LIST}")
    listed = re.findall(rf"(?m)^[0-9a-f]{{64}}  ({NAME})$", body.decode("utf-8", "replace")) if status == 200 else []
    wanted = {name: address for address, name in addresses(dict.fromkeys([*listed, *files])).items()}
    for name, address in wanted.items():
        status, _, body = ask(f"https://{host}{address}")
        if status == 200:
            there[name] = hashlib.md5(body, usedforsecurity=False).hexdigest()
    status, _, body = ask(f"https://{host}/nowhere/")
    return there | {"404.html": hashlib.md5(body, usedforsecurity=False).hexdigest()} if there else {}


def prepare_azure(token, env, run, send, ask, work, files, lock):
    azure = Azure(token, env, send)
    own = {
        "PATH": env["PATH"],
        "HOME": str(work),
        "ARM_CLIENT_ID": env["AZURE_CLIENT_ID"],
        "ARM_SUBSCRIPTION_ID": env["AZURE_SUBSCRIPTION_ID"],
        "ARM_TENANT_ID": env["AZURE_TENANT_ID"],
        "ARM_USE_OIDC": "true",
        # Terraform asks GitHub for tokens itself, because one lasts only minutes.
        "ACTIONS_ID_TOKEN_REQUEST_URL": env["ACTIONS_ID_TOKEN_REQUEST_URL"],
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": env["ACTIONS_ID_TOKEN_REQUEST_TOKEN"],
    }
    terraform = Terraform("azure", own, run, work, env["AZURE_SUBSCRIPTION_ID"] + env["AZURE_STATE_ACCOUNT"])
    if lock or has_state(token, env, send):
        terraform.init(storage_account_name=env["AZURE_STATE_ACCOUNT"])
    else:
        terraform.init_without_state()
    host = host_on_azure(terraform.known())
    plan = terraform.plan(lock, subscription_id=env["AZURE_SUBSCRIPTION_ID"])
    # Whoever looks may not ask for this, because it is a setting of the subscription. Where the site exists, it is on.
    off = not azure.registered() if lock else any(change["actions"] == ["create"] for _, change in moves(plan))
    if off:
        print("     turn on static sites (Microsoft.Web) in the subscription" + ("" if lock else ", if they are off"))
    there = served(host, files, ask) if host else {}
    print(*difference(files, there), sep="\n")
    print(f"The settings: {SETTINGS.name}, {hashlib.sha256(SETTINGS.read_bytes()).hexdigest()}", flush=True)
    return azure, terraform, terraform.mark(plan, files, there, env)


def look_azure(token, env, run, send, ask, work, files):
    return prepare_azure(token, env, run, send, ask, work, files, lock=False)[-1]


def apply_azure(token, env, run, send, ask, sleep, work, files, folder, agreed):
    azure, terraform, mark = prepare_azure(token, env, run, send, ask, work, files, lock=True)
    agreed(mark)
    if not azure.registered():
        azure("POST", "providers/Microsoft.Web/register", "2021-04-01", what="turn on static sites")
        for _ in range(40):
            if azure.registered():
                break
            sleep(15)
        else:
            raise Stop("Azure has not turned on static sites yet. Run this again later.")
    terraform.apply()
    host = host_on_azure(terraform.known())

    client = work / "StaticSitesClient"
    status, _, body = send("GET", CLIENT)
    if status != 200 or hashlib.sha256(body).hexdigest() != CLIENT_SHA256:
        raise Stop("Microsoft's upload client is not the one that was checked.")
    client.write_bytes(body)
    client.chmod(0o700)

    key = azure("POST", f"{AZURE_SITE}/listSecrets", "2024-11-01", what="give the key for uploads")["properties"]["apiKey"]
    print(f"::add-mask::{key}", flush=True)
    try:
        own = {
            "PATH": env["PATH"],
            "HOME": str(work),
            "DEPLOYMENT_ACTION": "upload",
            "DEPLOYMENT_PROVIDER": "SwaCli",
            "DEPLOYMENT_TOKEN": key,
            "REPOSITORY_BASE": str(folder.parent),
            "APP_LOCATION": str(folder),
            "CONFIG_FILE_LOCATION": str(SETTINGS.parent),
            "SKIP_APP_BUILD": "true",
            "SKIP_API_BUILD": "true",
            "VERBOSE": "false",
        }
        done = call(run, [str(client)], own, cwd=work, timeout=900)
        if done.returncode:
            raise Stop("\n".join(["The upload failed.", *harmless(done.stderr + done.stdout)]))
        print(f"{len(files)} files were uploaded.", flush=True)
    finally:
        # The key was used once, and it is of no use to anyone from here on.
        azure("POST", f"{AZURE_SITE}/resetapikey", "2024-11-01", {"properties": {"shouldUpdateRepository": False}}, what="replace the key for uploads")
    print(f"https://{host}/")
    check_public(host, files, ask, sleep)


LOOK = {"aws": look_aws, "azure": look_azure}
APPLY = {"aws": apply_aws, "azure": apply_azure}


def sign_in_with_github(step, cloud, env, send):
    needed, audience, _ = CLOUDS[cloud]
    if env.get("GITHUB_REPOSITORY") != f"{OWNER}/{REPO}":
        raise Stop("This is not the repo that the site is deployed from.")
    missing = [name for name in needed if not env.get(name)]
    if missing:
        raise Stop(f"Not set: {', '.join(missing)}.")
    token = github_token(audience, env, send)
    if subject_of(token) != SUBJECTS[REPO][TIERS[step]]:
        raise Stop(f"GitHub's subject is not this repo's {TIERS[step]}.")
    return token


def main(argv=None, env=os.environ, run=subprocess.run, send=answer, ask=visit, fetch=get, sleep=time.sleep, folder=SITE / "out"):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=TIERS)
    parser.add_argument("cloud", choices=LOOK)
    args = parser.parse_args(argv)
    try:
        files = read_site(folder)
        print(f"{len(files)} files, {digest(files)}", flush=True)
        if args.step == "apply":
            if not re.fullmatch("[0-9a-f]{64}", env.get("FINGERPRINT", "")):
                raise Stop("Nobody has looked at this yet.")
            problems = check_schedules(REPO, fetch, datetime.datetime.now(datetime.timezone.utc))
            if problems:
                raise Stop(f"Not deployed, because of the night run: {'; '.join(problems)}.")
            newest, this = (fetch(f"/repos/{OWNER}/{REPO}/commits?path=site&sha={at}&per_page=1") or [{}] for at in ("main", env["GITHUB_SHA"]))
            if not newest[0].get("sha") or newest[0]["sha"] != this[0].get("sha"):
                raise Stop("There is a newer version of the site on main. Start this workflow again from there.")
        token = sign_in_with_github(args.step, args.cloud, env, send)

        def agreed(mark):
            if not hmac.compare_digest(mark, env["FINGERPRINT"]):
                raise Stop("This is not what was looked at. Run all jobs again, so that someone can look at it.")

        with tempfile.TemporaryDirectory(dir=env.get("RUNNER_TEMP")) as work:
            work = pathlib.Path(work)
            if args.step == "apply":
                APPLY[args.cloud](token, env, run, send, ask, sleep, work, files, folder, agreed)
            else:
                mark = LOOK[args.cloud](token, env, run, send, ask, work, files)
                with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                    output.write(f"fingerprint={mark}\n")
    except (Stop, Unusable) as problem:
        print(f"Stopped. {problem}")
        return 1
    except Exception as problem:
        # Not the problem itself: it could quote a command, an address or an answer.
        print(f"Stopped by {type(problem).__name__}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
