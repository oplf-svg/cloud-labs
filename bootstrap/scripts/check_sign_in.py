#!/usr/bin/env python3
"""Signs in to one cloud as this repo's plan identity, and checks where its rights end.

  check_sign_in.py aws
  check_sign_in.py azure
  check_sign_in.py gcp

Runs in GitHub Actions on main, in the plan environment. It changes nothing: what it tries to write
could not be written even with the right to. Job logs are public, so it prints its own words and short
error codes, and never what a cloud answered.
"""

import argparse
import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

OWNER = "oplf-svg"
SUBJECTS = json.loads((pathlib.Path(__file__).resolve().parent.parent / "subjects.json").read_text())

ALLOWED, DENIED, EMPTY = "allowed", "denied", "nothing there"

# The name of the session, and of the files that are never written.
NAME = "check-sign-in"

# The only part of an error that is ever printed.
CODE = "[A-Za-z][A-Za-z0-9._]{1,63}"

AWS_REGION = "eu-west-2"
AWS_DENIED = {"AccessDenied", "UnauthorizedOperation"}
# What AWS says to someone with the right: only a dry run, or nothing to replace.
AWS_ALLOWED = {"DryRunOperation", "NoSuchKey", "PreconditionFailed"}

AZURE_DENIED = {"AuthorizationFailed", "AuthorizationPermissionMismatch"}
# What Azure says to someone with the right to write, because there is nothing to replace.
AZURE_ALLOWED = {"ConditionNotMet"}
AZURE_TEMPLATE = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    "contentVersion": "1.0.0.0",
    "resources": [],
}

GCP_REGION = "europe-west2"
GCP_DENIED = {"IAM_PERMISSION_DENIED", "PERMISSION_DENIED", "forbidden"}
# What Google says to someone with the right to write, because there is nothing to replace.
GCP_ALLOWED = {"conditionNotMet"}
# The identity must have this one, so an answer without it is no answer.
GCP_KNOWN = "resourcemanager.projects.get"


class Unusable(Exception):
    """Nothing can be checked. The message never contains a value."""


def answer(method, url, headers=None, body=None):
    """Sends one request. An error from the other side is an answer too."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.headers, error.read()


def verdict(code, allowed, denied):
    return ALLOWED if code in allowed else DENIED if code in denied else code


def github_token(audience, env, send):
    if not (env.get("ACTIONS_ID_TOKEN_REQUEST_URL") and env.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")):
        raise Unusable("GitHub offers no OIDC token here. The job needs id-token: write.")
    url = env["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=" + urllib.parse.quote(audience, safe="")
    status, _, body = send("GET", url, {"Authorization": "Bearer " + env["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})
    if status != 200:
        raise Unusable(f"GitHub gave no OIDC token: HTTP {status}.")
    return json.loads(body)["value"]


def subject_of(token):
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["sub"]


def aws(arguments, env, run):
    """Runs one AWS command. Returns what it printed, and allowed, denied or an error code."""
    command = ["aws", *arguments, "--region", AWS_REGION, "--output", "json"]
    done = run(
        command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60
    )
    if done.returncode == 0:
        return done.stdout, ALLOWED
    found = re.search(rf"An error occurred \(({CODE})\)", done.stderr)
    return "", verdict(found.group(1) if found else "no error code", AWS_ALLOWED, AWS_DENIED)


def check_aws(repo, other, token, env, run, send):
    """Yields what the identity tried, what should come of it, and what did."""
    account, bucket = env["AWS_ACCOUNT_ID"], env["AWS_STATE_BUCKET"]
    path, _, plan = env["AWS_ROLE_ARN"].rpartition("/")
    # Nothing else from the job, so that the AWS CLI cannot sign in by itself.
    bare = {name: env[name] for name in ("PATH", "HOME") if name in env}
    bare |= {"AWS_CLI_ERROR_FORMAT": "enhanced", "AWS_EC2_METADATA_DISABLED": "true", "AWS_PAGER": ""}

    with tempfile.TemporaryDirectory(dir=env.get("RUNNER_TEMP")) as folder:
        token_file = pathlib.Path(folder, "token")
        token_file.write_text(token, encoding="utf-8")

        def become(role):
            return aws(
                ["sts", "assume-role-with-web-identity", "--role-arn", f"{path}/{role}", "--role-session-name", NAME]
                + ["--web-identity-token", f"file://{token_file}"],
                bare,
                run,
            )

        output, got = become(plan)
        yield f"sign in as gha-{repo}-plan", ALLOWED, got
        if got != ALLOWED:
            return
        for role in (f"gha-{repo}-apply", f"gha-{repo}-destroy", f"gha-{other}-plan"):
            yield f"become {role}", DENIED, become(role)[1]

    keys = json.loads(output)["Credentials"]
    signed = bare | {
        "AWS_ACCESS_KEY_ID": keys["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": keys["SecretAccessKey"],
        "AWS_SESSION_TOKEN": keys["SessionToken"],
    }

    def call(*arguments):
        return aws(arguments, signed, run)[1]

    def read(owner):
        # Opens a file that is in the list, because a missing one tells nothing: S3 says that it is missing
        # to everyone who may list the bucket, whatever they may open.
        listing = ["s3api", "list-objects-v2", "--bucket", bucket, "--prefix", f"{owner}/", "--max-items", "1"]
        output, got = aws(listing, signed, run)
        files = json.loads(output or "{}").get("Contents") or []
        if got == ALLOWED and files:
            return call("s3api", "get-object", "--bucket", bucket, "--key", files[0]["Key"], os.devnull)
        return EMPTY if got == ALLOWED else got

    identity = json.loads(aws(["sts", "get-caller-identity"], signed, run)[0] or "{}")
    expected = f"arn:aws:sts::{account}:assumed-role/gha-{repo}-plan/{NAME}"
    yield "be that role, in the expected account", "yes", "yes" if identity.get("Arn") == expected else "no"

    yield "use London", ALLOWED, call("ec2", "describe-availability-zones")
    yield "create a network", DENIED, call("ec2", "create-vpc", "--cidr-block", "10.0.0.0/16", "--dry-run")
    yield "read its own state", (ALLOWED, EMPTY), read(repo)
    yield f"read the state of {other}", (DENIED, EMPTY), read(other)
    yield "read the state of the bootstrap", DENIED, read("bootstrap")
    # It may only replace a version of the file that does not exist.
    never = ["--if-match", f'"{"0" * 32}"']
    yield "write its own state", DENIED, call("s3api", "put-object", "--bucket", bucket, "--key", f"{repo}/{NAME}", *never)


def azure(status, headers, body):
    """Turns an answer from Azure into allowed, denied or an error code."""
    if 200 <= status < 300:
        return ALLOWED
    code = headers.get("x-ms-error-code")
    if not code:
        try:
            code = json.loads(body)["error"]["code"]
        except (KeyError, TypeError, ValueError):
            code = ""
    return verdict(code if re.fullmatch(CODE, str(code)) else f"HTTP {status}", AZURE_ALLOWED, AZURE_DENIED)


def check_azure(repo, other, token, env, run, send):
    """Yields what the identity tried, what should come of it, and what did."""

    def sign_in(resource):
        form = {
            "client_id": env["AZURE_CLIENT_ID"],
            "client_assertion": token,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "grant_type": "client_credentials",
            "scope": f"{resource}/.default",
        }
        url = f"https://login.microsoftonline.com/{env['AZURE_TENANT_ID']}/oauth2/v2.0/token"
        status, _, body = send("POST", url, None, urllib.parse.urlencode(form).encode())
        if status == 200:
            return json.loads(body)["access_token"], ALLOWED
        found = re.search(rb"AADSTS[0-9]{4,9}", body)
        return "", found.group().decode() if found else f"HTTP {status}"

    def manage(method, path, body=None):
        url = f"https://management.azure.com/subscriptions/{env['AZURE_SUBSCRIPTION_ID']}/resourceGroups/{path}"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        return azure(*send(method, f"{url}?api-version=2021-04-01", headers, body))

    def store(method, path, headers=None, body=None):
        url = f"https://{env['AZURE_STATE_ACCOUNT']}.blob.core.windows.net/{path}"
        headers = {"Authorization": f"Bearer {key}", "x-ms-version": "2023-11-03", **(headers or {})}
        return azure(*send(method, url, headers, body))

    def listing(container):
        return store("GET", f"{container}?restype=container&comp=list&maxresults=1")

    key, got = sign_in("https://management.azure.com")
    yield f"sign in as id-gha-{repo}-plan", ALLOWED, got
    if got != ALLOWED:
        return
    yield "read its own resource group", ALLOWED, manage("GET", f"rg-{repo}")
    yield f"read the resource group of {other}", DENIED, manage("GET", f"rg-{other}")
    yield "read the resource group of the bootstrap", DENIED, manage("GET", "rg-github-bootstrap")
    # Azure only validates this, and there is nothing in it to create.
    empty = json.dumps({"properties": {"mode": "Incremental", "template": AZURE_TEMPLATE}}).encode()
    deployment = f"rg-{repo}/providers/Microsoft.Resources/deployments/{NAME}/validate"
    yield "prepare a deployment", DENIED, manage("POST", deployment, empty)

    key, got = sign_in("https://storage.azure.com")
    yield "sign in to the state storage", ALLOWED, got
    if got != ALLOWED:
        return
    yield "list its own state", ALLOWED, listing(repo)
    yield f"list the state of {other}", DENIED, listing(other)
    yield "list the state of the bootstrap", DENIED, listing("bootstrap")
    # It may only replace a version of the file that does not exist.
    never = {"If-Match": '"0x8D0000000000000"', "x-ms-blob-type": "BlockBlob"}
    yield "write its own state", DENIED, store("PUT", f"{repo}/{NAME}", never, b"")


def gcp(status, headers, body):
    """Turns an answer from Google into allowed, denied or an error code."""
    if 200 <= status < 300:
        return ALLOWED
    try:
        error = json.loads(body)["error"]
        reasons = [item["reason"] for item in error.get("details", []) + error.get("errors", []) if "reason" in item]
        code = reasons[0] if reasons else error["status"]
    except (AttributeError, KeyError, TypeError, ValueError):
        code = ""
    return verdict(code if re.fullmatch(CODE, str(code)) else f"HTTP {status}", GCP_ALLOWED, GCP_DENIED)


def check_gcp(repo, other, token, env, run, send):
    """Yields what the identity tried, what should come of it, and what did."""
    project, bucket, provider = env["GCP_PROJECT_ID"], env["GCP_STATE_BUCKET"], env["GCP_WORKLOAD_IDENTITY_PROVIDER"]
    projects = "https://cloudresourcemanager.googleapis.com/v3/projects"
    region = f"https://compute.googleapis.com/compute/v1/projects/{project}/regions/{GCP_REGION}"

    def sign_in():
        form = {
            "audience": f"//iam.googleapis.com/{provider}",
            "grantType": "urn:ietf:params:oauth:grant-type:token-exchange",
            "requestedTokenType": "urn:ietf:params:oauth:token-type:access_token",
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "subjectToken": token,
            "subjectTokenType": "urn:ietf:params:oauth:token-type:jwt",
        }
        headers = {"Content-Type": "application/json"}
        status, _, body = send("POST", "https://sts.googleapis.com/v1/token", headers, json.dumps(form).encode())
        if status == 200:
            return json.loads(body)["access_token"], ALLOWED
        found = re.search(rb'"error": *"([a-z_]{3,40})"', body)
        return "", found.group(1).decode() if found else f"HTTP {status}"

    def manage(method, url, body=None):
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Goog-User-Project": project}
        return send(method, url, headers, body)

    def may(*permissions):
        # Google names those of the permissions that the identity has. Nothing is tried.
        question = json.dumps({"permissions": [GCP_KNOWN, *permissions]}).encode()
        status, _, body = manage("POST", f"{projects}/{project}:testIamPermissions", question)
        has = json.loads(body).get("permissions", []) if status == 200 else []
        return "no answer" if GCP_KNOWN not in has else ALLOWED if set(has) & set(permissions) else DENIED

    def store(method, path, body=None):
        return send(method, f"https://storage.googleapis.com/{path}", {"Authorization": f"Bearer {key}"}, body)

    def read(owner):
        # Opens a file that is in the list, because a missing one tells nothing here either.
        status, headers, body = store("GET", f"storage/v1/b/{bucket}/o?prefix={owner}/&maxResults=1")
        if status != 200:
            return gcp(status, headers, body)
        files = json.loads(body).get("items")
        if not files:
            return EMPTY
        return gcp(*store("GET", f"storage/v1/b/{bucket}/o/{urllib.parse.quote(files[0]['name'], safe='')}"))

    key, got = sign_in()
    yield f"sign in as the plan of {repo}", ALLOWED, got
    if got != ALLOWED:
        return
    status, headers, body = manage("GET", f"{projects}/{project}")
    yield "read the project", ALLOWED, gcp(status, headers, body)
    name = json.loads(body).get("name") if status == 200 else ""
    yield "be in the expected project", "yes", "yes" if name == f"projects/{env['GCP_PROJECT_NUMBER']}" else "no"
    yield "use London", ALLOWED, gcp(*manage("GET", region))
    yield "create something", DENIED, may("compute.instances.create", "compute.networks.create", "storage.buckets.create")
    keys = "iam.serviceAccounts.actAs", "iam.serviceAccounts.getAccessToken", "iam.serviceAccountKeys.create"
    yield "become a service account", DENIED, may(*keys)
    yield "change who has access", DENIED, may("resourcemanager.projects.setIamPolicy")
    yield "read the project of the bootstrap", DENIED, gcp(*manage("GET", f"{projects}/{provider.split('/')[1]}"))
    yield "read its own state", (ALLOWED, EMPTY), read(repo)
    yield f"read the state of {other}", (DENIED, EMPTY), read(other)
    yield "read the state of the bootstrap", DENIED, read("bootstrap")
    # It may only replace a version of the file that does not exist.
    never = f"upload/storage/v1/b/{bucket}/o?uploadType=media&name={repo}%2F{NAME}&ifGenerationMatch=1"
    yield "write its own state", DENIED, gcp(*store("POST", never, b""))


# Per cloud: the secrets it needs, whom GitHub's token is for, and the checks.
CLOUDS = {
    "aws": (
        ["AWS_ACCOUNT_ID", "AWS_ROLE_ARN", "AWS_STATE_BUCKET"],
        "sts.amazonaws.com",
        check_aws,
    ),
    "azure": (
        ["AZURE_CLIENT_ID", "AZURE_STATE_ACCOUNT", "AZURE_SUBSCRIPTION_ID", "AZURE_TENANT_ID"],
        "api://AzureADTokenExchange",
        check_azure,
    ),
    "gcp": (
        ["GCP_PROJECT_ID", "GCP_PROJECT_NUMBER", "GCP_STATE_BUCKET", "GCP_WORKLOAD_IDENTITY_PROVIDER"],
        "https://iam.googleapis.com/{GCP_WORKLOAD_IDENTITY_PROVIDER}",
        check_gcp,
    ),
}


def prepare(needed, audience, env, send):
    """Returns this repo, another one, and GitHub's token for this repo's plan identity."""
    owner, _, repo = env.get("GITHUB_REPOSITORY", "").partition("/")
    if owner != OWNER or repo not in SUBJECTS:
        raise Unusable("This is not one of the repos in subjects.json.")
    missing = [name for name in needed if not env.get(name)]
    if missing:
        raise Unusable(f"Not set: {', '.join(missing)}.")

    token = github_token(audience.format_map(env), env, send)
    subject = subject_of(token)
    if subject != SUBJECTS[repo]["plan"]:
        # Names and ids of a public repo. Only a job in the plan environment has the right one.
        raise Unusable(f"GitHub's subject is {re.sub('[^A-Za-z0-9@:/._-]', '?', subject)}, not the one in subjects.json.")
    return repo, next(name for name in SUBJECTS if name != repo), token


def main(argv=None, env=os.environ, run=subprocess.run, send=answer):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cloud", choices=CLOUDS)
    needed, audience, check = CLOUDS[parser.parse_args(argv).cloud]

    failed = False
    try:
        repo, other, token = prepare(needed, audience, env, send)
        print(f"ok   GitHub's subject is {SUBJECTS[repo]['plan']}", flush=True)
        for what, wanted, got in check(repo, other, token, env, run, send):
            accepted = (wanted,) if isinstance(wanted, str) else wanted
            failed = failed or got not in accepted
            print(f"ok   {what}: {got}" if got in accepted else f"FAIL {what}: {got}, should be {accepted[0]}", flush=True)
    except Unusable as problem:
        print(f"Not checked. {problem}")
        return 1
    except Exception as problem:
        # Not the problem itself: it could quote a command, an address or an answer.
        print(f"Stopped by {type(problem).__name__}.")
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
