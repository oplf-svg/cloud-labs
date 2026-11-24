"""Uses a key made for the test, and stand-ins for GitHub and the Keychain. Nothing real is called."""

import base64
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import as_agent as agent

CLIENT, TOKEN = "Iv23liExample0000000", "ghs_example_token_that_must_stay_private"


def made_key():
    return subprocess.run(["openssl", "genrsa", "2048"], capture_output=True, check=True).stdout


def decoded(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


class Github:
    """Answers as GitHub should, and remembers what it was asked."""

    def __init__(self, **changes):
        self.changes, self.asked = changes, []

    def __call__(self, path, bearer, body=None):
        self.asked.append((path, bearer, body))
        if path.endswith("/installation"):
            return {"id": 42}
        if path.endswith("/access_tokens"):
            return {"token": TOKEN, "permissions": body["permissions"], "repositories": [{"name": name} for name in body["repositories"]], **self.changes}
        return {"id": 987654}


class Proof(unittest.TestCase):
    def test_is_signed_by_the_key_and_short_lived(self):
        key = made_key()
        header, claims, signature = agent.proof(CLIENT, key, now=lambda: 1_000_000).split(".")
        self.assertEqual(json.loads(decoded(header)), {"alg": "RS256", "typ": "JWT"})
        self.assertEqual(json.loads(decoded(claims)), {"iat": 999_940, "exp": 1_000_300, "iss": CLIENT})
        with tempfile.TemporaryDirectory() as folder:
            public, signed = pathlib.Path(folder, "public.pem"), pathlib.Path(folder, "signature")
            public.write_bytes(subprocess.run(["openssl", "rsa", "-pubout"], input=key, capture_output=True, check=True).stdout)
            signed.write_bytes(decoded(signature))
            checked = subprocess.run(["openssl", "dgst", "-sha256", "-verify", public, "-signature", signed], input=f"{header}.{claims}".encode(), capture_output=True)
        self.assertEqual(checked.returncode, 0, checked.stdout)

    def test_the_key_is_never_in_a_command(self):
        commands = []

        def run(command, **options):
            commands.append(command)
            return subprocess.run(command, **options)

        key = made_key()
        agent.sign(b"data", key, run=run)
        self.assertNotIn("PRIVATE", " ".join(commands[0]))
        self.assertRegex(commands[0][-1], r"^/dev/fd/\d+$")

    def test_a_broken_key_says_so(self):
        with self.assertRaisesRegex(agent.Unusable, "could not be used for signing"):
            agent.sign(b"data", b"-----BEGIN " + b"PRIVATE KEY-----\nbroken\n")


class Keychain(unittest.TestCase):
    def answer(self, secret, account=f'    "acct"<blob>="{CLIENT}"\n', code=0):
        def run(command, **_):
            return types.SimpleNamespace(returncode=code, stdout=secret if command[-1] == "-w" else account)

        return agent.keychain(run)

    def test_gives_the_client_id_and_the_key(self):
        key = made_key()
        wrapped = "\n".join(base64.encodebytes(key).decode().split("\n"))
        self.assertEqual(self.answer(wrapped), (CLIENT, key))

    def test_says_what_is_missing(self):
        for case in ({"secret": "", "code": 44}, {"secret": "", "account": ""}, {"secret": base64.b64encode(b"something else").decode()}):
            with self.subTest(case), self.assertRaises(agent.Unusable):
                self.answer(**case)


class Token(unittest.TestCase):
    def get(self, github, repo="cloud-labs"):
        return agent.token_for(repo, credentials=lambda: (CLIENT, b"key"), prove=lambda *_: "jwt", send=github)

    def test_is_for_one_repo_and_the_listed_rights(self):
        github = Github()
        self.assertEqual(self.get(github), (TOKEN, "oplf-svg-agent[bot]", "987654+oplf-svg-agent[bot]@users.noreply.github.com"))
        self.assertEqual(github.asked[0], ("/repos/oplf-svg/cloud-labs/installation", "jwt", None))
        self.assertEqual(github.asked[1], ("/app/installations/42/access_tokens", "jwt", {"repositories": ["cloud-labs"], "permissions": agent.RIGHTS}))

    def test_the_rights_hold_nothing_that_decides(self):
        self.assertEqual(sorted(agent.RIGHTS), ["actions", "checks", "contents", "metadata", "pull_requests"])
        self.assertEqual(sorted(name for name, right in agent.RIGHTS.items() if right == "write"), ["contents", "pull_requests"])

    def test_more_than_was_asked_for_is_not_used(self):
        cases = (
            {"permissions": {**agent.RIGHTS, "administration": "write"}},
            {"permissions": {**agent.RIGHTS, "workflows": "write"}},
            {"permissions": {"contents": "write"}},
            {"repositories": [{"name": "cloud-labs"}, {"name": "webhook-platform"}]},
            {"repositories": []},
        )
        for changes in cases:
            with self.subTest(changes), self.assertRaisesRegex(agent.Unusable, "other rights"):
                self.get(Github(**changes))


class Command(unittest.TestCase):
    def go(self, *arguments, get=None):
        seen = []

        def run(command, env):
            seen.append((command, env))
            return types.SimpleNamespace(returncode=7)

        screen = io.StringIO()
        with contextlib.redirect_stdout(screen), contextlib.redirect_stderr(screen):
            code = agent.main(list(arguments), get=get or (lambda repo: (TOKEN, "bot", "bot@example.com")), run=run)
        return code, seen, screen.getvalue()

    def test_runs_the_command_with_the_token_and_shows_neither(self):
        code, seen, screen = self.go("cloud-labs", "--", "gh", "pr", "list")
        self.assertEqual((code, screen), (7, ""))
        command, env = seen[0]
        self.assertEqual(command, ["gh", "pr", "list"])
        self.assertEqual(env["GH_TOKEN"], TOKEN)

    def test_refuses_anything_else(self):
        for arguments in ([], ["cloud-labs"], ["cloud-labs", "gh"], ["someone-elses-repo", "--", "gh"], ["cloud-labs", "--"]):
            with self.subTest(arguments):
                code, seen, _ = self.go(*arguments)
                self.assertEqual((code, seen), (2, []))

    def test_runs_nothing_without_the_identity(self):
        def refuse(_):
            raise agent.Unusable("GitHub refused (401).")

        code, seen, screen = self.go("cloud-labs", "--", "gh", get=refuse)
        self.assertEqual((code, seen), (1, []))
        self.assertIn("Nothing was run. GitHub refused (401).", screen)

    def test_nothing_of_the_owner_is_left_around(self):
        before = {"PATH": "/bin", "GITHUB_TOKEN": "owner", "GH_TOKEN": "owner", "SSH_AUTH_SOCK": "/owner", "GIT_ASKPASS": "/owner", "GH_ENTERPRISE_TOKEN": "owner"}
        env = agent.surroundings(TOKEN, "bot", "bot@example.com", before)
        self.assertNotIn("owner", " ".join(env.values()))
        self.assertEqual((env["GIT_AUTHOR_EMAIL"], env["GIT_COMMITTER_NAME"]), ("bot@example.com", "bot"))

    def test_git_takes_the_token_and_no_other_credential(self):
        with tempfile.TemporaryDirectory() as folder:
            home = pathlib.Path(folder, ".gitconfig")
            home.write_text('[credential]\n\thelper = "!echo username=owner; echo password=owner"\n[credential "https://github.com"]\n\thelper = "!echo username=owner; echo password=owner #"\n')
            env = agent.surroundings(TOKEN, "bot", "bot@example.com", {"PATH": os.environ["PATH"], "HOME": folder})
            asked = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n", env=env, capture_output=True, text=True)
        self.assertIn(f"password={TOKEN}", asked.stdout, asked.stderr)
        self.assertNotIn("owner", asked.stdout)


if __name__ == "__main__":
    unittest.main()
