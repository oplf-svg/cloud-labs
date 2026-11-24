import contextlib
import copy
import io
import json
import os
import pathlib
import pty
import subprocess
import tempfile
import textwrap
import unittest

import load_secrets as loader

ACCOUNT = "111122223333"
TIERS = {"repository": "plan", "production": "apply", "nightly-destroy": "destroy"}


def guid(number):
    return f"00000000-0000-0000-0000-{number:012x}"


def aws():
    def role(repo, tier):
        return f"arn:aws:iam::{ACCOUNT}:role/github-actions/gha-{repo}-{tier}"

    return {
        "cloud": "aws",
        "repos": {
            repo: {
                "repository": {
                    "AWS_ACCOUNT_ID": ACCOUNT,
                    "AWS_ROLE_ARN": role(repo, "plan"),
                    "AWS_STATE_BUCKET": "tfstate-0a1b2c3d",
                    "AWS_WORKLOAD_BOUNDARY_ARN": f"arn:aws:iam::{ACCOUNT}:policy/github-actions/workload-boundary",
                },
                "production": {"AWS_ROLE_ARN": role(repo, "apply")},
                "nightly-destroy": {"AWS_ROLE_ARN": role(repo, "destroy")},
                **({"cost": {"AWS_ROLE_ARN": role(repo, "cost")}} if repo == "cloud-labs" else {}),
            }
            for repo in loader.REPOS
        },
    }


def azure():
    numbers = iter(range(100, 200))
    return {
        "cloud": "azure",
        "repos": {
            repo: {
                "repository": {
                    "AZURE_CLIENT_ID": guid(next(numbers)),
                    "AZURE_STATE_ACCOUNT": "tfstate0a1b2c3d",
                    "AZURE_SUBSCRIPTION_ID": guid(1),
                    "AZURE_TENANT_ID": guid(2),
                },
                "production": {"AZURE_CLIENT_ID": guid(next(numbers))},
                "nightly-destroy": {"AZURE_CLIENT_ID": guid(next(numbers))},
                **({"cost": {"AZURE_CLIENT_ID": guid(next(numbers))}} if repo == "cloud-labs" else {}),
            }
            for repo in loader.REPOS
        },
    }


def gcp():
    return {
        "cloud": "gcp",
        "repos": {
            repo: {
                "repository": {
                    "GCP_PROJECT_ID": "example-project-1",
                    "GCP_PROJECT_NUMBER": "210987654321",
                    "GCP_STATE_BUCKET": "tfstate-0a1b2c3d",
                    "GCP_WORKLOAD_IDENTITY_PROVIDER": "projects/123456789012/locations/global/workloadIdentityPools/github-actions/providers/github",
                },
                "production": {},
                "nightly-destroy": {},
                **({"cost": {"GCP_COST_PROJECT_ID": "example-bootstrap-1"}} if repo == "cloud-labs" else {}),
            }
            for repo in loader.REPOS
        },
    }


class FakeGh:
    def __init__(self, login="oplf-svg", lose=(), fail_on=None):
        self.login, self.lose, self.fail_on = login, lose, fail_on
        self.commands, self.stored = [], {}

    def __call__(self, *args, value=None):
        self.commands.append(args)
        if args[:2] == ("api", "user"):
            return self.login + "\n"
        repo = args[args.index("--repo") + 1]
        scope = args[args.index("--env") + 1] if "--env" in args else "repository"
        if args[:2] == ("secret", "set"):
            if args[2] == self.fail_on:
                raise subprocess.CalledProcessError(1, ["gh", *args])
            self.stored[repo, scope, args[2]] = value
            return ""
        if args[:2] == ("secret", "list"):
            return "\n".join(n for r, s, n in self.stored if (r, s) == (repo, scope) and n not in self.lose) + "\n"
        raise AssertionError(args)


class Load(unittest.TestCase):
    def load(self, data, *argv, gh=None, answer=True):
        self.gh = gh or FakeGh()
        text = data if isinstance(data, str) else json.dumps(data)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = loader.main(list(argv), stdin=io.StringIO(text), run=self.gh, ask=lambda question: answer)
        self.out = out.getvalue()
        # The one rule that must always hold.
        for source in (aws(), azure(), gcp()):
            for scopes in source["repos"].values():
                for values in scopes.values():
                    for value in values.values():
                        self.assertNotIn(value, self.out)
                        self.assertFalse(any(value in arg for command in self.gh.commands for arg in command))
        return code

    def test_stores_every_value_in_its_place(self):
        for make in (aws, azure, gcp):
            with self.subTest(make.__name__):
                data = make()
                self.assertEqual(self.load(data), 0)
                wanted = {
                    (f"oplf-svg/{repo}", scope, name): value
                    for repo, scopes in data["repos"].items()
                    for scope, values in scopes.items()
                    for name, value in values.items()
                }
                self.assertEqual(self.gh.stored, wanted)

    def test_counts(self):
        self.load(aws())
        self.assertEqual(len(self.gh.stored), 31)
        self.load(azure())
        self.assertEqual(len(self.gh.stored), 31)
        self.load(gcp())
        self.assertEqual(len(self.gh.stored), 21)

    def test_the_cost_identity_is_only_for_one_repo(self):
        for make, name in ((aws, "AWS_ROLE_ARN"), (azure, "AZURE_CLIENT_ID"), (gcp, "GCP_COST_PROJECT_ID")):
            self.load(make())
            self.assertEqual([key for key in self.gh.stored if key[1] not in TIERS], [("oplf-svg/cloud-labs", "cost", name)])
            self.assertIn(f"  cost             cost     {name} (only in cloud-labs)\n", self.out)
            self.assertIn("cost 1", next(line for line in self.out.splitlines() if line.startswith("  cloud-labs ")))

    def test_survives_a_terminal_copy(self):
        for text in (
            "\n".join(textwrap.wrap(json.dumps(aws()), 60)),
            "~ $ terraform output -json github_secrets | fold -w 100; echo\n-----\n" + json.dumps(aws()) + "\n-----\n~ $ ",
            json.dumps(aws(), indent=2).replace("\n", "\r\n"),
        ):
            with self.subTest(text[:20]):
                self.assertEqual(self.load(text), 0)
                self.assertEqual(len(self.gh.stored), 31)

    def test_reads_a_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder, "x.json")
            path.write_text(json.dumps(gcp()))
            self.assertEqual(self.load("", str(path)), 0)
            self.assertEqual(self.load("", str(path) + ".missing"), 1)

    def test_check_never_calls_gh(self):
        self.assertEqual(self.load(aws(), "--check"), 0)
        self.assertEqual(self.gh.commands, [])

    def test_no_answer_writes_nothing(self):
        self.assertEqual(self.load(aws(), answer=False), 1)
        self.assertEqual(self.gh.stored, {})

    def test_another_sign_in_writes_nothing(self):
        self.assertEqual(self.load(aws(), gh=FakeGh(login="someone-else")), 1)
        self.assertEqual(self.gh.stored, {})

    def test_reports_what_github_does_not_list(self):
        self.assertEqual(self.load(aws(), gh=FakeGh(lose=("AWS_ROLE_ARN",))), 1)

    def test_gh_failure(self):
        self.assertEqual(self.load(aws(), gh=FakeGh(fail_on="AWS_STATE_BUCKET")), 1)

    def test_rejects_wrong_input(self):
        repo = loader.REPOS[0]

        def edit(make, change):
            data = copy.deepcopy(make())
            change(data["repos"])
            return data

        wrong = {
            "nothing": "",
            "not an output": "{}",
            "cut off": json.dumps(aws())[:-40],
            "another cloud name": {**aws(), "cloud": "other"},
            "a repo missing": edit(aws, lambda r: r.pop(repo)),
            "a repo too many": edit(aws, lambda r: r.update({"oplf-svg": r[repo]})),
            "a scope missing": edit(aws, lambda r: r[repo].pop("production")),
            "a name missing": edit(aws, lambda r: r[repo]["repository"].pop("AWS_ACCOUNT_ID")),
            "another secret": edit(aws, lambda r: r[repo]["repository"].update(BLOCKED_TERMS="x")),
            "an empty value": edit(aws, lambda r: r[repo]["repository"].update(AWS_STATE_BUCKET="")),
            "not text": edit(aws, lambda r: r[repo]["repository"].update(AWS_ACCOUNT_ID=111122223333)),
            "apply role given to plan": edit(aws, lambda r: r[repo]["repository"].update(AWS_ROLE_ARN=r[repo]["production"]["AWS_ROLE_ARN"])),
            "another repo's role": edit(aws, lambda r: r[repo]["production"].update(AWS_ROLE_ARN=r[loader.REPOS[1]]["production"]["AWS_ROLE_ARN"])),
            "no cost identity": edit(aws, lambda r: r["cloud-labs"].pop("cost")),
            "a cost identity for another repo": edit(aws, lambda r: r["webhook-platform"].update(cost=r["cloud-labs"]["cost"])),
            "apply role given to cost": edit(aws, lambda r: r["cloud-labs"]["cost"].update(AWS_ROLE_ARN=r["cloud-labs"]["production"]["AWS_ROLE_ARN"])),
            "cost role given to plan": edit(aws, lambda r: r["cloud-labs"]["repository"].update(AWS_ROLE_ARN=r["cloud-labs"]["cost"]["AWS_ROLE_ARN"])),
            "apply identity given to cost": edit(azure, lambda r: r["cloud-labs"]["cost"].update(AZURE_CLIENT_ID=r["cloud-labs"]["production"]["AZURE_CLIENT_ID"])),
            "the costs where the repos deploy": edit(gcp, lambda r: r["cloud-labs"]["cost"].update(GCP_COST_PROJECT_ID="example-project-1")),
            "the place of the costs in every job": edit(gcp, lambda r: r["cloud-labs"]["repository"].update(GCP_COST_PROJECT_ID="example-bootstrap-1")),
            "two roles swapped": edit(aws, lambda r: r[repo].update({"production": r[repo]["nightly-destroy"], "nightly-destroy": r[repo]["production"]})),
            "the roles of costs and apply swapped": edit(aws, lambda r: r["cloud-labs"].update({"production": r["cloud-labs"]["cost"], "cost": r["cloud-labs"]["production"]})),
            "two accounts": edit(aws, lambda r: r[repo]["repository"].update(AWS_ACCOUNT_ID="444455556666")),
            "roles of another account": edit(aws, lambda r: [s["repository"].update(AWS_ACCOUNT_ID="444455556666") for s in r.values()]),
            "one identity twice": edit(azure, lambda r: r[repo]["production"].update(AZURE_CLIENT_ID=r[repo]["repository"]["AZURE_CLIENT_ID"])),
            "two subscriptions": edit(azure, lambda r: r[repo]["repository"].update(AZURE_SUBSCRIPTION_ID=guid(9))),
            "a secret for a tier": edit(gcp, lambda r: r[repo]["production"].update(GCP_PROJECT_ID="example-project-1")),
            "another provider": edit(gcp, lambda r: r[repo]["repository"].update(GCP_WORKLOAD_IDENTITY_PROVIDER="projects/123456789012/locations/global/workloadIdentityPools/github-actions/providers/other")),
        }
        for name, data in wrong.items():
            with self.subTest(name):
                self.assertEqual(self.load(data), 1)
                self.assertEqual(self.gh.commands, [], "nothing may be asked of gh")


class ConfirmTest(unittest.TestCase):
    """The prompt at a real terminal, with something else on standard input, as with pbpaste."""

    def answered(self, typed):
        child, terminal = pty.fork()
        if child == 0:
            code = 2
            try:
                os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
                code = 0 if loader.confirm("Store them now? ") else 1
            finally:
                os._exit(code)
        os.write(terminal, typed.encode())
        with contextlib.suppress(OSError):
            while os.read(terminal, 1024):
                pass
        os.close(terminal)
        return os.waitstatus_to_exitcode(os.waitpid(child, 0)[1])

    def test_yes_goes_on(self):
        self.assertEqual(self.answered("yes\n"), 0)

    def test_anything_else_stops(self):
        for typed in ("no\n", "\n", "y\n", "yes please\n"):
            with self.subTest(typed):
                self.assertEqual(self.answered(typed), 1)


if __name__ == "__main__":
    unittest.main()
