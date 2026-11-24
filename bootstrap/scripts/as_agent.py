#!/usr/bin/env python3
"""Runs one command as the agents' own GitHub identity, in one repo.

  as_agent.py REPO -- COMMAND...

The identity is a GitHub App. It can push branches and open pull requests. It cannot change workflow
files, settings or secrets, and cannot approve its own work. Its key is in the macOS Keychain and is
used only here, to sign a request for a token that works in that one repo for at most an hour. Neither
the key nor the token is ever printed or written to a file.

Put the key there once, with the App's client id and the file that GitHub gave you, then delete the file:

  security add-generic-password -U -s oplf-svg-agent -a CLIENT_ID -w "$(base64 < KEY.pem)"
"""

import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

OWNER = "oplf-svg"
APP = "oplf-svg-agent"
REPOS = [*json.loads((pathlib.Path(__file__).resolve().parent.parent / "subjects.json").read_text()), OWNER]
API = "https://api.github.com"

# Asked for again on every call, so a token never holds more than this, even if the App is given more one day.
RIGHTS = {"actions": "read", "checks": "read", "contents": "write", "metadata": "read", "pull_requests": "write"}


class Unusable(Exception):
    """The identity cannot be used. The message never holds the key or a token."""


def keychain(run=subprocess.run):
    """Returns the App's client id and its key."""
    found = run(["security", "find-generic-password", "-s", APP], capture_output=True, text=True)
    account = re.search(r'"acct"<blob>="([A-Za-z0-9.]{8,40})"', found.stdout)
    if found.returncode or not account:
        raise Unusable(f"There is no key for {APP} in the Keychain. See the top of this file.")
    secret = run(["security", "find-generic-password", "-s", APP, "-w"], capture_output=True, text=True)
    try:
        key = base64.b64decode(secret.stdout, validate=False)
    except ValueError:
        key = b""
    if secret.returncode or b"PRIVATE KEY" not in key:
        raise Unusable("The Keychain did not give a usable key.")
    return account.group(1), key


def encoded(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def sign(data, key, run=subprocess.run):
    """Signs with openssl. The key goes through a pipe, so that it is never in a file or in a list of processes."""
    reader, writer = os.pipe()
    try:
        os.write(writer, key)
        os.close(writer)
        done = run(["openssl", "dgst", "-sha256", "-sign", f"/dev/fd/{reader}"], input=data, capture_output=True, pass_fds=(reader,))
    finally:
        os.close(reader)
    if done.returncode:
        raise Unusable("The key could not be used for signing.")
    return done.stdout


def proof(client, key, now=time.time, signer=sign):
    """What GitHub calls a JWT: it says which App is asking, for the next few minutes."""
    moment = int(now())
    header = encoded(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = encoded(json.dumps({"iat": moment - 60, "exp": moment + 300, "iss": client}).encode())
    return b".".join([header, claims, encoded(signer(header + b"." + claims, key))]).decode()


def ask(path, bearer, body=None):
    request = urllib.request.Request(
        API + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {bearer}", "User-Agent": APP},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise Unusable(f"GitHub refused ({error.code}).") from None
    except (urllib.error.URLError, TimeoutError):
        raise Unusable("GitHub could not be reached.") from None


def token_for(repo, credentials=keychain, prove=proof, send=ask):
    """Returns a token for one repo, and the name and address that its commits carry."""
    jwt = prove(*credentials())
    place = send(f"/repos/{OWNER}/{repo}/installation", jwt)
    answer = send(f"/app/installations/{place['id']}/access_tokens", jwt, {"repositories": [repo], "permissions": RIGHTS})
    if answer.get("permissions") != RIGHTS or [one["name"] for one in answer.get("repositories", [])] != [repo]:
        raise Unusable("GitHub gave other rights than the ones that were asked for, so they are not used.")
    bot = send(f"/users/{APP}%5Bbot%5D", answer["token"])
    return answer["token"], f"{APP}[bot]", f"{bot['id']}+{APP}[bot]@users.noreply.github.com"


def surroundings(token, name, address, env=os.environ):
    """The environment of the command: the agents' token, and nothing that belongs to the owner."""
    mine = {key: value for key, value in env.items() if key not in {"GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "SSH_AUTH_SOCK", "GIT_ASKPASS", "SSH_ASKPASS"}}
    settings = [
        ("credential.helper", ""),
        ("credential.https://github.com.helper", ""),
        ("credential.https://github.com.helper", '!f() { echo username=x-access-token; echo "password=$GH_TOKEN"; }; f'),
    ]
    for number, (key, value) in enumerate(settings):
        mine[f"GIT_CONFIG_KEY_{number}"], mine[f"GIT_CONFIG_VALUE_{number}"] = key, value
    return {
        **mine,
        "GH_TOKEN": token,
        "GIT_CONFIG_COUNT": str(len(settings)),
        "GIT_TERMINAL_PROMPT": "0",
        **{f"GIT_{role}_{part}": value for role in ("AUTHOR", "COMMITTER") for part, value in (("NAME", name), ("EMAIL", address))},
    }


def main(argv=None, get=token_for, run=subprocess.run):
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) < 3 or arguments[0] not in REPOS or arguments[1] != "--":
        print(f"usage: as_agent.py REPO -- COMMAND...   where REPO is one of {', '.join(REPOS)}", file=sys.stderr)
        return 2
    try:
        token, name, address = get(arguments[0])
    except Unusable as problem:
        print(f"Nothing was run. {problem}", file=sys.stderr)
        return 1
    return run(arguments[2:], env=surroundings(token, name, address)).returncode


if __name__ == "__main__":
    sys.exit(main())
