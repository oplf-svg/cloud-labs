#!/usr/bin/env python3
"""Signs in to one cloud as the identity that reads costs, and checks where its rights end.

  check_cost.py aws
  check_cost.py azure
  check_cost.py gcp

Runs in GitHub Actions on main, in the cost environment of cloud-labs. It asks what a day or a month has
cost and throws the answer away: on AWS that one question costs 0.01 USD, on the other clouds nothing. It
changes nothing: what it tries to change could not be changed even with the right to. Job logs are public,
so it prints its own words and short error codes, and never a sum or what a cloud answered.
"""

import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from check_sign_in import ALLOWED, AZURE_TEMPLATE, CLOUDS, DENIED, NAME, OWNER, Unusable, answer, aws, azure, gcp, github_token, subject_of

# The one repo that has this identity, and the subject that its jobs have in that environment.
REPO, ENVIRONMENT = "cloud-labs", "cost"
COST = json.loads((pathlib.Path(__file__).resolve().parent.parent / "cost.json").read_text())

# AWS offers costs in one place only.
AWS_COST_REGION = "us-east-1"

# Where Google writes the billing export.
DATASET = "billing_export"

# Nothing on Google has this version, so nothing with it is ever changed.
NEVER = '"never"'


def check_aws(token, env, run, send, today):
    """Yields what the identity tried, what should come of it, and what did."""
    account, bucket = env["AWS_ACCOUNT_ID"], env["AWS_STATE_BUCKET"]
    path, _, role = env["AWS_ROLE_ARN"].rpartition("/")
    # Nothing else from the job, so that the AWS CLI cannot sign in by itself.
    bare = {name: env[name] for name in ("PATH", "HOME") if name in env}
    bare |= {"AWS_CLI_ERROR_FORMAT": "enhanced", "AWS_EC2_METADATA_DISABLED": "true", "AWS_PAGER": ""}

    with tempfile.TemporaryDirectory(dir=env.get("RUNNER_TEMP")) as folder:
        token_file = pathlib.Path(folder, "token")
        token_file.write_text(token, encoding="utf-8")

        def become(name):
            arguments = ["--role-arn", f"{path}/{name}", "--role-session-name", NAME, "--web-identity-token", f"file://{token_file}"]
            return aws(["sts", "assume-role-with-web-identity", *arguments], bare, run)

        output, got = become(role)
        yield f"sign in as gha-{REPO}-cost", ALLOWED, got
        if got != ALLOWED:
            return
        for tier in ("plan", "apply", "destroy"):
            yield f"become gha-{REPO}-{tier}", DENIED, become(f"gha-{REPO}-{tier}")[1]

    keys = json.loads(output)["Credentials"]
    signed = bare | {
        "AWS_ACCESS_KEY_ID": keys["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": keys["SecretAccessKey"],
        "AWS_SESSION_TOKEN": keys["SessionToken"],
    }

    def call(*arguments, **options):
        return aws(arguments, signed, run, **options)[1]

    def cost(command, start, end, *arguments):
        period = f"Start={start},End={end}"
        return call("ce", command, "--time-period", period, "--granularity", "DAILY", *arguments, region=AWS_COST_REGION)

    identity = json.loads(aws(["sts", "get-caller-identity"], signed, run)[0] or "{}")
    expected = f"arn:aws:sts::{account}:assumed-role/gha-{REPO}-cost/{NAME}"
    yield "be that role, in the expected account", "yes", "yes" if identity.get("Arn") == expected else "no"

    day = datetime.timedelta(days=1)
    yield "ask what a day has cost", ALLOWED, cost("get-cost-and-usage", today - day, today, "--metrics", "UnblendedCost")
    yield "ask what a day will cost", DENIED, cost("get-cost-forecast", today + day, today + 2 * day, "--metric", "UNBLENDED_COST")
    only = ["--filter", json.dumps({"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Simple Storage Service"]}})]
    which = cost("get-cost-and-usage-with-resources", today - day, today, *only, "--metrics", "UnblendedCost")
    yield "ask which resources have cost it", DENIED, which
    yield "read the budgets", DENIED, call("budgets", "describe-budgets", "--account-id", account, region=AWS_COST_REGION)
    yield "look around", DENIED, call("ec2", "describe-availability-zones")
    yield "create a network", DENIED, call("ec2", "create-vpc", "--cidr-block", "10.0.0.0/16", "--dry-run")
    yield "list the states", DENIED, call("s3api", "list-objects-v2", "--bucket", bucket, "--max-items", "1")


def check_azure(token, env, run, send, today):
    """Yields what the identity tried, what should come of it, and what did."""
    subscription = f"https://management.azure.com/subscriptions/{env['AZURE_SUBSCRIPTION_ID']}"

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

    def manage(method, path, version, body=None):
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        data = None if body is None else json.dumps(body).encode()
        return azure(*send(method, f"{subscription}/{path}?api-version={version}", headers, data))

    def listing(container):
        url = f"https://{env['AZURE_STATE_ACCOUNT']}.blob.core.windows.net/{container}?restype=container&comp=list&maxresults=1"
        return azure(*send("GET", url, {"Authorization": f"Bearer {key}", "x-ms-version": "2023-11-03"}))

    key, got = sign_in("https://management.azure.com")
    yield f"sign in as id-gha-{REPO}-cost", ALLOWED, got
    if got != ALLOWED:
        return
    total = {"granularity": "None", "aggregation": {"total": {"name": "Cost", "function": "Sum"}}}
    question = {"type": "ActualCost", "timeframe": "MonthToDate", "dataset": total}
    yield "ask what the month has cost", ALLOWED, manage("POST", "providers/Microsoft.CostManagement/query", "2024-08-01", question)
    yield "read the budgets", DENIED, manage("GET", "providers/Microsoft.Consumption/budgets", "2023-05-01")
    # One group by its name. A list would answer even someone without any right, with nothing in it.
    yield f"read the resource group of {REPO}", DENIED, manage("GET", f"resourceGroups/rg-{REPO}", "2021-04-01")
    yield "read the resource group of the bootstrap", DENIED, manage("GET", "resourceGroups/rg-github-bootstrap", "2021-04-01")
    # Azure only validates this, and there is nothing in it to create.
    empty = {"properties": {"mode": "Incremental", "template": AZURE_TEMPLATE}}
    deployment = f"resourceGroups/rg-{REPO}/providers/Microsoft.Resources/deployments/{NAME}/validate"
    yield "prepare a deployment", DENIED, manage("POST", deployment, "2021-04-01", empty)

    key, got = sign_in("https://storage.azure.com")
    yield "sign in to the state storage", ALLOWED, got
    if got != ALLOWED:
        return
    yield f"list the state of {REPO}", DENIED, listing(REPO)
    yield "list the state of the bootstrap", DENIED, listing("bootstrap")


def check_gcp(token, env, run, send, today):
    """Yields what the identity tried, what should come of it, and what did."""
    project, costs, bucket = env["GCP_PROJECT_ID"], env["GCP_COST_PROJECT_ID"], env["GCP_STATE_BUCKET"]
    provider = env["GCP_WORKLOAD_IDENTITY_PROVIDER"]
    projects = "https://cloudresourcemanager.googleapis.com/v3/projects"
    bigquery = "https://bigquery.googleapis.com/bigquery/v2/projects"
    storage = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o"

    form = {
        "audience": f"//iam.googleapis.com/{provider}",
        "grantType": "urn:ietf:params:oauth:grant-type:token-exchange",
        "requestedTokenType": "urn:ietf:params:oauth:token-type:access_token",
        "scope": "https://www.googleapis.com/auth/cloud-platform",
        "subjectToken": token,
        "subjectTokenType": "urn:ietf:params:oauth:token-type:jwt",
    }
    status, _, body = send("POST", "https://sts.googleapis.com/v1/token", {"Content-Type": "application/json"}, json.dumps(form).encode())
    found = re.search(rb'"error": *"([a-z_]{3,40})"', body)
    got = ALLOWED if status == 200 else found.group(1).decode() if found else f"HTTP {status}"
    yield f"sign in as the cost of {REPO}", ALLOWED, got
    if got != ALLOWED:
        return
    key = json.loads(body)["access_token"]

    def call(method, url, body=None, **headers):
        # No project to count this against: that would need a right that this identity does not have.
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"} | {name.replace("_", "-"): value for name, value in headers.items()}
        return gcp(*send(method, url, headers, None if body is None else json.dumps(body).encode()))

    # First what has to work. Otherwise a refusal below would prove nothing.
    yield "list the tables of the costs", ALLOWED, call("GET", f"{bigquery}/{costs}/datasets/{DATASET}/tables?maxResults=1")
    question = {"query": "SELECT 1", "useLegacySql": False, "dryRun": True}
    yield "run a query where the costs are", DENIED, call("POST", f"{bigquery}/{costs}/queries", question)
    yield "run a query where the repos deploy", DENIED, call("POST", f"{bigquery}/{project}/queries", question)
    # It changes nothing, and only in a version of the dataset that does not exist.
    yield "change who may read the costs", DENIED, call("PATCH", f"{bigquery}/{costs}/datasets/{DATASET}", {}, If_Match=NEVER)
    yield "read the project", DENIED, call("GET", f"{projects}/{project}")
    yield "read the project of the bootstrap", DENIED, call("GET", f"{projects}/{provider.split('/')[1]}")
    yield "list the states", DENIED, call("GET", f"{storage}?maxResults=1")
    yield "read the state of the bootstrap", DENIED, call("GET", f"{storage}/bootstrap%2Fdefault.tfstate")


# The checks of each cloud, and what its secrets have that the other identities do not need.
CHECKS = {"aws": (check_aws, []), "azure": (check_azure, []), "gcp": (check_gcp, ["GCP_COST_PROJECT_ID"])}


def prepare(cloud, env, send):
    """Returns GitHub's token for the identity that reads costs."""
    if env.get("GITHUB_REPOSITORY") != f"{OWNER}/{REPO}":
        raise Unusable("This is not the repo that has an identity for costs.")
    needed, audience, _ = CLOUDS[cloud]
    missing = [name for name in [*needed, *CHECKS[cloud][1]] if not env.get(name)]
    if missing:
        raise Unusable(f"Not set: {', '.join(missing)}.")
    token = github_token(audience.format_map(env), env, send)
    subject = subject_of(token)
    if subject != COST[REPO][ENVIRONMENT]:
        # Names and ids of a public repo. Only a job in the cost environment has the right one.
        raise Unusable(f"GitHub's subject is {re.sub('[^A-Za-z0-9@:/._-]', '?', subject)}, not the one in cost.json.")
    return token


def main(argv=None, env=os.environ, run=subprocess.run, send=answer, today=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cloud", choices=CHECKS)
    cloud = parser.parse_args(argv).cloud
    today = today or datetime.datetime.now(datetime.timezone.utc).date()

    failed = False
    try:
        token = prepare(cloud, env, send)
        print(f"ok   GitHub's subject is {COST[REPO][ENVIRONMENT]}", flush=True)
        for what, wanted, got in CHECKS[cloud][0](token, env, run, send, today):
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
