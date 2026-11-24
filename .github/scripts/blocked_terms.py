#!/usr/bin/env python3
"""Fails when a private term appears in this pull request.

BLOCKED_TERMS is one line of comma-separated terms. Terms are plain text, matched anywhere and
without regard to case or spacing. Job logs are public, so nothing here prints a term or the text
around it.

Not covered: a message typed into the merge box, which exists only after this has run.
"""

import json
import os
import pathlib
import re
import subprocess
import sys


# What can stand at the start of a wrapped line in a comment, a quote, a list or a string.
PREFIX = re.compile(r"^[\s#/>*+;|\"'`-]+", re.MULTILINE)


class BadList(ValueError):
    pass


def normalise(text):
    """Folds case, turns any run of whitespace into one space, and drops the NULs of UTF-16 text."""
    return " ".join(text.replace("\0", "").casefold().split())


def parse_terms(raw):
    raw = (raw or "").strip()
    # Any other separator would make one long term that never matches anything.
    if any(character in raw for character in "\r\n\t;|"):
        raise BadList("BLOCKED_TERMS must be one line with commas between the terms. Failing.")
    terms = [term for term in map(normalise, raw.split(",")) if term]
    if not terms:
        # Fork and Dependabot pull requests get no secrets. They fail too: nothing merges unchecked.
        raise BadList("BLOCKED_TERMS is empty, so nothing can be checked. Failing.")
    return terms


def decode(data):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8", errors="replace")


def has_term(text, terms):
    """Looks in the text as it is, and again with its lines joined as if they had been wrapped."""
    return any(term in form for form in (normalise(text), normalise(PREFIX.sub("", text))) for term in terms)


def git(*args):
    return subprocess.run(["git", *args], check=True, stdout=subprocess.PIPE).stdout


def names(output):
    return [decode(name) for name in output.split(b"\0") if name]


def scan_file(path, terms):
    """Yields what matched in one tracked file: its name, a line, or text that runs over lines."""
    if has_term(path, terms):
        yield "name"
    file = pathlib.Path(path)
    # A symlink's content is its target. Never follow it out of the checkout.
    content = os.readlink(file).encode() if file.is_symlink() else file.read_bytes() if file.is_file() else b""
    text = decode(content)
    lines = [number for number, line in enumerate(text.split("\n"), 1) if has_term(line, terms)]
    for number in lines:
        yield f"line {number}"
    if not lines and has_term(text, terms):
        yield "text that runs over more than one line"


def scan_commit(commit, terms):
    """Yields what matched in one commit: its message, its names, or what it adds."""
    if has_term(decode(git("show", "--no-patch", "--format=%an%n%ae%n%cn%n%ce%n%B", commit)), terms):
        yield "author or message"
    if any(has_term(name, terms) for name in names(git("show", "--format=", "--name-only", "--diff-filter=d", "--no-renames", "-z", "-m", commit))):
        yield "a file name"
    patch = git("show", "--format=", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames", "--text", "-m", commit)
    # Added lines only, so that a commit can remove a term.
    added = b"\n".join(line[1:] for line in patch.split(b"\n") if line.startswith(b"+"))
    if has_term(decode(added), terms):
        yield "an added line"


def scan_pull(pull, terms):
    """Yields which public text of the pull request matched."""
    fields = {"title": pull["title"], "description": pull.get("body"), "branch name": pull["head"]["ref"]}
    for name, text in fields.items():
        if has_term(text or "", terms):
            yield f"pull request {name}"


def main(env=os.environ):
    try:
        terms = parse_terms(env.get("BLOCKED_TERMS"))
    except BadList as problem:
        print(problem)
        return 1

    base, head, pull_file = env.get("BASE_SHA"), env.get("HEAD_SHA"), env.get("PULL_REQUEST_FILE")
    if not (base and head and pull_file):
        print("BASE_SHA, HEAD_SHA and PULL_REQUEST_FILE are all needed. Failing.")
        return 1

    found = []
    paths = names(git("ls-files", "-z"))
    for number, path in enumerate(paths, 1):
        # A path that holds a term is described by its position, not by its name.
        label = f"tracked file number {number}" if has_term(path, terms) else json.dumps(path)
        found += [f"{label}: {what}" for what in scan_file(path, terms)]

    commits = decode(git("rev-list", f"{base}..{head}")).split()
    for commit in commits:
        found += [f"commit {commit[:12]}: {what}" for what in scan_commit(commit, terms)]

    found += scan_pull(json.loads(pathlib.Path(pull_file).read_text(encoding="utf-8")), terms)

    for item in found:
        print(f"blocked term in {item}")
    print(f"Checked {len(paths)} files, {len(commits)} commits and the pull request: {len(found) or 'no'} matches.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
