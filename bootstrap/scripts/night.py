#!/usr/bin/env python3
"""The night run of one cloud, as the identity that can only delete.

  night.py aws | azure | gcp

Every stack stands in stacks.json, with the clouds it is on and what the night does to it. A state that is
not listed there means that something was deployed which nobody declared, and the run fails. What no state
knows is not seen here. It also checks where the identity's rights end. A stack that a night should destroy
needs code here first, and until then the run fails too.

Runs in GitHub Actions on main, in the nightly-destroy environment. Job logs are public, so it prints its
own words, names that look like ours, and short error codes.
"""

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from check_sign_in import (
    ALLOWED,
    AZURE_TEMPLATE,
    CLOUDS,
    DENIED,
    NAME,
    OWNER,
    SUBJECTS,
    Unusable,
    answer,
    aws,
    azure,
    gcp,
    github_token,
    subject_of,
)

STACKS = pathlib.Path(__file__).resolve().parents[2] / "stacks.json"
STAYS, DESTROYED = "stays", "destroyed"


def declared(cloud, path=STACKS):
    """What every stack on this cloud is called, and what a night does to it."""
    stacks = json.loads(path.read_text(encoding="utf-8"))["stacks"]
    for stack in stacks:
        fine = set(stack) == {"name", "clouds", "night", "why"} and stack["night"] in (STAYS, DESTROYED)
        if not (fine and re.fullmatch("[a-z][a-z0-9-]{1,30}", stack["name"]) and stack["clouds"] and set(stack["clouds"]) <= set(CLOUDS)):
            raise Unusable("stacks.json is not in the expected form.")
    return {stack["name"]: stack["night"] for stack in stacks if cloud in stack["clouds"]}


def judge(files, nights):
    """Yields what is there, what should come of it, and what did. `files` are the names below this repo's own."""
    strange = 0
    for file in sorted(files):
        found = re.fullmatch(r"([a-z][a-z0-9-]{1,30})/(?:terraform|default)\.tfstate(\.tflock)?", file)
        name = found and found.group(1)
        if name not in nights:
            strange += 1
        elif found.group(2):
            # A deploy is under way, or one was cut off. Terraform refuses to go on from there by itself.
            yield f"see a lock on {name}", "seen", "seen"
        elif nights[name] == STAYS:
            yield f"keep {name}", STAYS, STAYS
        else:
            yield f"destroy {name}", DESTROYED, "no way to yet"
    yield "find states that nobody declared", "none", "none" if strange == 0 else str(strange)


def prepare(needed, audience, env, send):
    """Returns this repo and GitHub's token for its destroy identity."""
    owner, _, repo = env.get("GITHUB_REPOSITORY", "").partition("/")
    if owner != OWNER or repo not in SUBJECTS:
        raise Unusable("This is not one of the repos in subjects.json.")
    missing = [name for name in needed if not env.get(name)]
    if missing:
        raise Unusable(f"Not set: {', '.join(missing)}.")
    token = github_token(audience.format_map(env), env, send)
    if subject_of(token) != SUBJECTS[repo]["destroy"]:
        raise Unusable("GitHub's subject is not this repo's nightly-destroy.")
    return repo, token


def night_aws(repo, token, env, run, send, nights):
    bare = {name: env[name] for name in ("PATH", "HOME") if name in env}
    bare |= {"AWS_CLI_ERROR_FORMAT": "enhanced", "AWS_EC2_METADATA_DISABLED": "true", "AWS_PAGER": ""}
    with tempfile.TemporaryDirectory(dir=env.get("RUNNER_TEMP")) as folder:
        file = pathlib.Path(folder, "token")
        file.write_text(token, encoding="utf-8")

        def become(role):
            arguments = ["--role-arn", role, "--role-session-name", NAME, "--web-identity-token", f"file://{file}"]
            return aws(["sts", "assume-role-with-web-identity", *arguments], bare, run)

        output, got = become(env["AWS_ROLE_ARN"])
        yield f"sign in as gha-{repo}-destroy", ALLOWED, got
        if got != ALLOWED:
            return
        yield f"become gha-{repo}-apply", DENIED, become(env["AWS_ROLE_ARN"].removesuffix("-destroy") + "-apply")[1]

    keys = json.loads(output)["Credentials"]
    signed = bare | {
        "AWS_ACCESS_KEY_ID": keys["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": keys["SecretAccessKey"],
        "AWS_SESSION_TOKEN": keys["SessionToken"],
    }
    yield "create a network", DENIED, aws(["ec2", "create-vpc", "--cidr-block", "10.0.0.0/16", "--dry-run"], signed, run)[1]
    output, got = aws(["s3api", "list-objects-v2", "--bucket", env["AWS_STATE_BUCKET"], "--prefix", f"{repo}/"], signed, run)
    yield "list its own states", ALLOWED, got
    if got == ALLOWED:
        files = [item["Key"].removeprefix(f"{repo}/") for item in json.loads(output or "{}").get("Contents") or []]
        yield from judge(files, nights)


def night_azure(repo, token, env, run, send, nights):
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

    key, got = sign_in("https://management.azure.com")
    yield f"sign in as id-gha-{repo}-destroy", ALLOWED, got
    if got != ALLOWED:
        return
    group = f"https://management.azure.com/subscriptions/{env['AZURE_SUBSCRIPTION_ID']}/resourceGroups/rg-{repo}"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    empty = json.dumps({"properties": {"mode": "Incremental", "template": AZURE_TEMPLATE}}).encode()
    check = f"{group}/providers/Microsoft.Resources/deployments/{NAME}/validate?api-version=2021-04-01"
    yield "prepare a deployment", DENIED, azure(*send("POST", check, headers, empty))

    key, got = sign_in("https://storage.azure.com")
    yield "sign in to the state storage", ALLOWED, got
    if got != ALLOWED:
        return
    url = f"https://{env['AZURE_STATE_ACCOUNT']}.blob.core.windows.net/{repo}?restype=container&comp=list"
    status, headers, body = send("GET", url, {"Authorization": f"Bearer {key}", "x-ms-version": "2023-11-03"})
    got = azure(status, headers, body)
    yield "list its own states", ALLOWED, got
    if got == ALLOWED:
        yield from judge(re.findall("<Name>([^<]*)</Name>", body.decode("utf-8", "replace")), nights)


def night_gcp(repo, token, env, run, send, nights):
    form = {
        "audience": f"//iam.googleapis.com/{env['GCP_WORKLOAD_IDENTITY_PROVIDER']}",
        "grantType": "urn:ietf:params:oauth:grant-type:token-exchange",
        "requestedTokenType": "urn:ietf:params:oauth:token-type:access_token",
        "scope": "https://www.googleapis.com/auth/cloud-platform",
        "subjectToken": token,
        "subjectTokenType": "urn:ietf:params:oauth:token-type:jwt",
    }
    headers = {"Content-Type": "application/json"}
    status, _, body = send("POST", "https://sts.googleapis.com/v1/token", headers, json.dumps(form).encode())
    found = re.search(rb'"error": *"([a-z_]{3,40})"', body)
    got = ALLOWED if status == 200 else found.group(1).decode() if found else f"HTTP {status}"
    yield f"sign in as the destroy of {repo}", ALLOWED, got
    if got != ALLOWED:
        return
    key = json.loads(body)["access_token"]

    known, project = "resourcemanager.projects.get", env["GCP_PROJECT_ID"]
    wanted = ["compute.instances.create", "compute.networks.create", "storage.buckets.create"]
    question = json.dumps({"permissions": [known, *wanted]}).encode()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Goog-User-Project": project}
    url = f"https://cloudresourcemanager.googleapis.com/v3/projects/{project}:testIamPermissions"
    status, _, body = send("POST", url, headers, question)
    has = json.loads(body).get("permissions", []) if status == 200 else []
    yield "create something", DENIED, "no answer" if known not in has else ALLOWED if set(has) & set(wanted) else DENIED

    url = f"https://storage.googleapis.com/storage/v1/b/{env['GCP_STATE_BUCKET']}/o?prefix={repo}/"
    status, headers, body = send("GET", url, {"Authorization": f"Bearer {key}"})
    got = gcp(status, headers, body)
    yield "list its own states", ALLOWED, got
    if got == ALLOWED:
        yield from judge([item["name"].removeprefix(f"{repo}/") for item in json.loads(body).get("items") or []], nights)


NIGHTS = {"aws": night_aws, "azure": night_azure, "gcp": night_gcp}


def main(argv=None, env=os.environ, run=subprocess.run, send=answer, stacks=STACKS):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cloud", choices=NIGHTS)
    cloud = parser.parse_args(argv).cloud
    needed, audience, _ = CLOUDS[cloud]

    failed = False
    try:
        nights = declared(cloud, stacks)
        repo, token = prepare(needed, audience, env, send)
        for what, wanted, got in NIGHTS[cloud](repo, token, env, run, send, nights):
            failed = failed or got != wanted
            print(f"ok   {what}: {got}" if got == wanted else f"FAIL {what}: {got}, should be {wanted}", flush=True)
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
