import contextlib
import io
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

import blocked_terms

# Made-up terms: a stem, one with a slash, one with an underscore, one that looks like a pattern,
# and one of two words.
TERMS = "Zorblax,qux/Corp,snib_snab,a.c+,Wibble Wob"
PULL = {"title": "x", "body": None, "head": {"ref": "fix"}}


class Repo(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = pathlib.Path(self.dir.name)
        before = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, before)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "tester")
        self.git("config", "user.email", "tester@example.com")
        self.base = self.commit("README.md", "nothing to see\n", "first")

    def git(self, *args):
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, name, content, message):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def undo_then_check(self):
        """Removes everything again, so that only the history can give the term away."""
        (self.root / "gone").write_text("x")
        self.git("rm", "-rq", "--ignore-unmatch", ".")
        (self.root / "README.md").write_text("nothing to see\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "clean")
        return self.check()

    def check(self, terms=TERMS, pull=PULL, base=None, **env):
        pull_file = self.root / ".git" / "pull.json"
        pull_file.write_text(json.dumps(pull))
        env = {
            "BLOCKED_TERMS": terms,
            "BASE_SHA": base or self.base,
            "HEAD_SHA": self.git("rev-parse", "HEAD"),
            "PULL_REQUEST_FILE": str(pull_file),
            **env,
        }
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = blocked_terms.main(env)
        for term in ("zorblax", "qux/corp", "snib_snab", "a.c+", "wibble"):
            self.assertNotIn(term, out.getvalue().casefold(), "the output must never show a term")
        return code

    def test_clean(self):
        self.commit("a.txt", "abc and accc are fine\n", "second")
        self.assertEqual(self.check(), 0)

    def test_unusable_list_fails(self):
        for raw in ("", "   ", ",,", "zorblax\nother", "zorblax;other", "zorblax\tother", "zorblax|other", None):
            with self.subTest(raw):
                self.assertEqual(self.check(terms=raw), 1)

    def test_missing_inputs_fail(self):
        for name in ("BASE_SHA", "HEAD_SHA", "PULL_REQUEST_FILE"):
            with self.subTest(name):
                self.assertEqual(self.check(**{name: ""}), 1)

    def test_any_case_and_inside_a_word(self):
        self.commit("a.txt", "the MYZORBLAXES module\n", "second")
        self.assertEqual(self.check(), 1)

    def test_slash_underscore_and_pattern_characters_are_plain_text(self):
        for text in ("see QUX/corp", "x_SNIB_SNAB_y", "weird A.C+ thing"):
            with self.subTest(text):
                self.commit("a.txt", text, "second")
                self.assertEqual(self.check(), 1)

    def test_two_words_with_any_spacing(self):
        for text in ("wibble wob", "wibble   wob", "wibble\twob", "wibble\nwob", "a wibble\u00a0wob b", "# wibble\n# wob", "  // wibble\n  // wob", "> wibble\n> wob", " * wibble\n * wob"):
            with self.subTest(repr(text)):
                self.commit("a.txt", text, "second")
                self.assertEqual(self.check(), 1)

    def test_file_name(self):
        self.commit("zorblax/notes.txt", "fine\n", "second")
        self.assertEqual(self.check(), 1)

    def test_utf16_and_binary(self):
        for content in ("zorblax".encode("utf-16"), "zorblax".encode("utf-16-le"), b"\x00\x01zorblax\xff"):
            with self.subTest(content):
                self.commit("a.bin", content, "second")
                self.assertEqual(self.check(), 1)

    def test_commit_message(self):
        self.commit("a.txt", "fine\n", "as used at Zorblax")
        self.assertEqual(self.check(), 1)

    def test_author_email(self):
        self.git("config", "user.email", "someone@zorblax.example")
        self.commit("a.txt", "fine\n", "second")
        self.assertEqual(self.check(), 1)

    def test_added_then_removed_in_the_same_pull_request(self):
        for content in ("zorblax\n", "a\fzorblax\n", "a\rzorblax\n", "a\u2028zorblax\n", "wibble\nwob\n", "# wibble\n# wob\n", "zorblax".encode("utf-16"), "++ zorblax\n"):
            with self.subTest(repr(content)):
                self.base = self.git("rev-parse", "HEAD")
                self.commit("a.txt", content, "second")
                self.assertEqual(self.undo_then_check(), 1)

    def test_renamed_or_empty_file_in_the_history(self):
        self.commit("a.txt", "some text\nthat stays the same\n", "second")
        self.git("mv", "a.txt", "zorblax.txt")
        self.git("commit", "-q", "-m", "third")
        self.assertEqual(self.undo_then_check(), 1)
        self.base = self.git("rev-parse", "HEAD")
        self.commit("zorblax-empty", "", "fourth")
        self.assertEqual(self.undo_then_check(), 1)

    def test_removing_an_old_term_passes(self):
        base = self.commit("a.txt", "zorblax\n", "second")
        self.commit("a.txt", "fine\n", "third")
        self.assertEqual(self.check(base=base), 0)

    def test_renaming_away_an_old_term_passes(self):
        base = self.commit("zorblax.txt", "fine\n", "second")
        self.git("mv", "zorblax.txt", "b.txt")
        self.git("commit", "-q", "-m", "third")
        self.assertEqual(self.check(base=base), 0)

    def test_pull_request_text(self):
        for change in ({"title": "Zorblax"}, {"body": "at zorblax"}, {"head": {"ref": "zorblax-fix"}}):
            with self.subTest(change):
                self.assertEqual(self.check(pull={**PULL, **change}), 1)

    def test_symlink_is_not_followed(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as outside:
            outside.write("zorblax")
            outside.flush()
            (self.root / "link").symlink_to(outside.name)
            self.git("add", "-A")
            self.git("commit", "-q", "-m", "second")
            self.assertEqual(self.check(), 0)


if __name__ == "__main__":
    unittest.main()
