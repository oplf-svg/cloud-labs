"""Tests clouds.command at a simulated terminal, against stand-ins: no cloud, no network, no sign-in.

    python3 test_clouds.py             the tests
    python3 test_clouds.py --mistakes  the same tests on copies with a mistake in them. Each one has to be noticed
"""

import os
import pathlib
import pty
import select
import shutil
import signal
import stat
import sys
import tempfile
import time
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "clouds.command"

# Every stand-in writes down that it was called. What it does can be changed with a file in the home folder.
TOOLS = {
    "id": """case "$1" in -Gn) cat "$HOME/groups" ;; -u) /usr/bin/id -u ;; esac""",
    "pgrep": """[ -e "$HOME/claude-is-open" ]""",
    "stat": """/usr/bin/python3 -c 'import os, sys; s = os.stat(sys.argv[1]); print("%o %d" % (s.st_mode & 0o777, s.st_uid))' "$3" """,
    "python3": """exec /usr/bin/python3 "$@" """,
    "git": """
        case "$1" in
          clone)
            [ ! -e "$HOME/no-network" ] || exit 1
            for last in "$@"; do :; done
            mkdir -p "$last/bootstrap/scripts"
            cp "$HOME/run.sh" "$last/bootstrap/scripts/run.sh"
            ;;
          *) echo "abc1234 of 24 November 20:00, A change" ;;
        esac""",
    "aws": """
        case "$1" in
          configure) mkdir -p "$HOME/.aws"; echo "$*" > "$HOME/.aws/config" ;;
          login) mkdir -p "$HOME/.aws/login/cache"; echo secret > "$HOME/.aws/login/cache/a.json"; [ ! -e "$HOME/no-login" ] ;;
          account) echo "The right one" ;;
          logout) [ -e "$HOME/no-logout" ] || rm -f "$HOME"/.aws/login/cache/* ;;
        esac""",
    "az": """
        mkdir -p "$HOME/.azure/logs"
        store=$HOME/.azure/msal_token_cache.json
        case "$*" in
          login*)
            echo secret > "$store"
            [ ! -e "$HOME/keychain" ] || echo secret > "$HOME/keychain"
            [ ! -e "$HOME/login-waits" ] || { trap 'exit 0' INT; echo "waiting for the browser"; sleep 20 & wait; }
            ;;
          logout) [ -e "$HOME/no-logout" ] || rm -f "$store"; [ -e "$HOME/no-logout" ] || [ ! -e "$HOME/keychain" ] || : > "$HOME/keychain" ;;
          'account show'*) echo "A subscription" ;;
          'account get-access-token'*) [ ! -e "$HOME/az-offline" ] && grep -qs secret "$store" "$HOME/keychain" ;;
        esac""",
    "gcloud": """
        account=$HOME/.config/gcloud/account
        mkdir -p "$HOME/.config/gcloud"
        case "$*" in
          'auth login'*) echo somebody > "$account" ;;
          'auth revoke'*) [ -e "$account" ] && [ ! -e "$HOME/no-logout" ] && rm -f "$account" ;;
          'auth print-access-token') [ ! -e "$HOME/no-token" ] && [ -e "$account" ] && echo token-of-an-hour ;;
          'auth list'*) [ ! -e "$account" ] || cat "$account" ;;
        esac""",
}

RUN = """#!/bin/bash
echo "run.sh $1 tmp=$RUN_TMP results=$RUN_RESULTS checked=$RUN_CHECKED token=${GOOGLE_OAUTH_ACCESS_TOKEN:-none}" >> "$HOME/calls"
echo "run.sh is here"
[ ! -e "$HOME/run-waits" ] || sleep "$(cat "$HOME/run-waits")"
[ ! -e "$HOME/run-fails" ]
"""

SIGN_IN = {"aws": "aws login", "azure": "az login", "gcp": "gcloud auth login"}
SIGN_OUT = {"aws": "aws logout", "azure": "az logout", "gcp": "gcloud auth revoke"}


class Terminal:
    """A window with the script in it."""

    def __init__(self, home, through_shell=False):
        self.text = ""
        self.code = None
        pid, self.window = pty.fork()
        if pid == 0:
            # Whoever started these tests may ignore some signals, and a shell cannot change that for itself any more.
            for number in (signal.SIGHUP, signal.SIGINT, signal.SIGQUIT, signal.SIGTERM, signal.SIGPIPE):
                signal.signal(number, signal.SIG_DFL)
            env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "TERM": "dumb", "AWS_PROFILE": "somebody-else", "GIT_DIR": "/nowhere",
                   "HTTPS_PROXY": "http://127.0.0.1:1"}
            script = str(home / "clouds.command")
            if through_shell:
                os.execve("/bin/zsh", ["zsh", "-f", "-i"], env)
            os.execve("/bin/bash", ["bash", script], env)
        self.pid = pid
        if through_shell:
            time.sleep(0.3)
            self.type(f"{home / 'clouds.command'}; exit $?")

    def wait_for(self, words, seconds=15):
        end = time.time() + seconds
        while words not in self.text:
            if time.time() > end:
                raise AssertionError(f"{words!r} did not appear in:\n{self.text}")
            if not self.read(0.1) and self.done(0):
                if words in self.text:
                    return
                raise AssertionError(f"it ended without {words!r}:\n{self.text}")

    def read(self, seconds):
        try:
            if not select.select([self.window], [], [], seconds)[0]:
                return False
            data = os.read(self.window, 65536)
        except OSError:
            return False
        self.text += data.decode(errors="replace")
        return bool(data)

    def type(self, line):
        os.write(self.window, (line + "\n").encode())

    def key(self, character):
        os.write(self.window, character)

    def close(self):
        os.close(self.window)
        self.window = None

    def done(self, seconds=15):
        end = time.time() + seconds
        while self.code is None:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.code = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else (
                    os.WEXITSTATUS(status) if os.WIFEXITED(status) else -os.WTERMSIG(status))
                break
            if self.window is not None:
                self.read(0.05)
            else:
                time.sleep(0.05)
            if time.time() > end:
                return False
        while self.window is not None and self.read(0.05):
            pass
        return True


@unittest.skipUnless(sys.platform == "darwin", "a Mac's Terminal and its bash")
class Clouds(unittest.TestCase):
    script = SCRIPT

    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.home.chmod(0o700)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        bin_folder = self.home / "tools" / "bin"
        bin_folder.mkdir(parents=True)
        for name, body in TOOLS.items():
            log = "" if name in ("stat", "python3", "id", "pgrep") else f'echo "{name} $*" >> "$HOME/calls"\n'
            (bin_folder / name).write_text(f"#!/bin/bash\n{log}{body}\n")
            (bin_folder / name).chmod(0o700)
        (self.home / "groups").write_text("staff everyone localaccounts\n")
        (self.home / "calls").write_text("")
        (self.home / "run.sh").write_text(RUN)
        (self.home / "run.sh").chmod(0o700)
        shutil.copy(self.script, self.home / "clouds.command")
        (self.home / "clouds.command").chmod(0o700)

    def put(self, *names, text=""):
        for name in names:
            (self.home / name).write_text(text)

    def calls(self):
        return (self.home / "calls").read_text()

    def signed_in(self):
        """What a thief would find, looked up without asking the script."""
        found = []
        for folder in (".aws", ".azure", ".config/gcloud"):
            found += [str(p) for p in (self.home / folder).rglob("*") if p.is_file()]
        if (self.home / "keychain").exists() and (self.home / "keychain").read_text():
            found.append("keychain")
        return found

    def open(self, number, what="r", right="yes", **options):
        window = Terminal(self.home, **options)
        self.addCleanup(self.away, window)
        window.wait_for("Which one?")
        window.type(number)
        if what:
            window.wait_for("to stop?")
            window.type(what)
        if what in ("r", "s") and right:
            window.wait_for("the right account?")
            window.type(right)
        return window

    def away(self, window):
        """Ends what is left of a window. Its own side is closed first: a program that still has to write would wait for ever."""
        if window.window is not None:
            window.close()
        for pid in (window.pid, self.number_in_lock()):
            if pid:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        end = time.time() + 5
        while window.code is None and time.time() < end:
            try:
                if os.waitpid(window.pid, os.WNOHANG)[0]:
                    window.code = -9
            except ChildProcessError:
                window.code = -9
            time.sleep(0.02)

    def number_in_lock(self):
        try:
            return int((self.home / "runs" / ".open" / "window").read_text())
        except (OSError, ValueError):
            return 0

    def check_signed_out(self, cloud):
        self.assertIn(SIGN_IN[cloud], self.calls())
        self.assertIn(SIGN_OUT[cloud], self.calls().split(SIGN_IN[cloud], 1)[1])
        self.assertEqual(self.signed_in(), [])

    def test_each_cloud_from_start_to_end(self):
        for number, cloud in (("1", "aws"), ("2", "azure"), ("3", "gcp")):
            with self.subTest(cloud):
                (self.home / "calls").write_text("")
                window = self.open(number)
                self.assertTrue(window.done())
                self.assertEqual(window.code, 0, window.text)
                self.assertIn("No sign-in is left on this disk", window.text)
                self.check_signed_out(cloud)
                calls = self.calls()
                self.assertLess(calls.index(SIGN_IN[cloud]), calls.index("run.sh " + cloud))
                self.assertIn(f"token={'token-of-an-hour' if cloud == 'gcp' else 'none'}", calls)
                self.assertIn(" results=/Users/Shared/clouds ", calls)
                # So that three clouds in one sitting ask GitHub once. run.sh wants that file in a closed folder.
                self.assertIn(f" checked={self.home}/runs/.checked ", calls)
                self.assertEqual(stat.S_IMODE((self.home / "runs").stat().st_mode), 0o700)
                # Its own closed folder, never the one that all users share.
                folder = pathlib.Path(calls.split("tmp=", 1)[1].split(" ", 1)[0])
                self.assertEqual(folder.parent, self.home / "runs")
                self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE((folder / "cloud-labs").stat().st_mode), 0o700)
                for place in (".aws", ".azure", ".config/gcloud"):
                    self.assertFalse((self.home / place).exists(), place)

    def test_run_fails(self):
        self.put("run-fails")
        window = self.open("1")
        self.assertTrue(window.done())
        self.assertNotEqual(window.code, 0)
        self.check_signed_out("aws")

    def test_control_c(self):
        self.put("run-waits", text="60")
        window = self.open("1")
        window.wait_for("run.sh is here")
        self.assertNotEqual(self.signed_in(), [])
        window.key(b"\x03")
        self.assertTrue(window.done())
        self.assertNotEqual(window.code, 0)
        self.check_signed_out("aws")

    def gone(self, window):
        """Closes the window and waits for what happens after it."""
        self.assertNotEqual(self.signed_in(), [])
        window.close()
        window.done(10)
        end = time.time() + 10
        while self.signed_in() and time.time() < end:
            time.sleep(0.05)
        time.sleep(0.2)

    def test_window_closed(self):
        # As the Mac's Terminal does it: a login shell in between, which passes the news on to all that it started.
        for number, cloud in (("1", "aws"), ("2", "azure"), ("3", "gcp")):
            with self.subTest(cloud):
                (self.home / "calls").write_text("")
                self.put("run-waits", text="60")
                window = self.open(number, through_shell=True)
                window.wait_for("run.sh is here")
                self.gone(window)
                self.check_signed_out(cloud)

    def test_hung_up_again_and_again(self):
        # A closed window is told twice: by the shell in between, and when that shell ends. The second time must not cut
        # off the sign-out that the first time has started.
        for how in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            for through_shell in (False, True):
                with self.subTest(f"{how} {through_shell}"):
                    (self.home / "calls").write_text("")
                    self.put("run-waits", text="60")
                    window = self.open("2", through_shell=through_shell)
                    window.wait_for("run.sh is here")
                    group = os.getpgid(self.number_in_lock())
                    until = time.time() + 0.4
                    while time.time() < until:
                        try:
                            os.killpg(group, how)
                        except (ProcessLookupError, PermissionError):
                            break
                    end = time.time() + 10
                    while (self.home / "runs" / ".open").exists() and time.time() < end:
                        window.read(0.05)
                    self.check_signed_out("azure")
                    self.assertFalse((self.home / "runs" / ".open").exists())
                    self.away(window)

    def test_window_closed_without_a_shell(self):
        # Then only this script hears of it. It signs out as soon as the running step ends.
        self.put("run-waits", text="3")
        window = self.open("1")
        window.wait_for("run.sh is here")
        self.gone(window)
        self.check_signed_out("aws")

    def test_terminated(self):
        self.put("run-waits", text="60")
        window = self.open("2")
        window.wait_for("run.sh is here")
        os.killpg(os.getpgid(window.pid), signal.SIGTERM)
        self.assertTrue(window.done())
        self.check_signed_out("azure")

    def test_sign_in_stops_halfway(self):
        self.put("no-login")
        window = self.open("1", right=None)
        self.assertTrue(window.done())
        self.assertEqual(window.code, 1)
        self.assertNotIn("run.sh", self.calls())
        self.check_signed_out("aws")

    def test_control_c_at_the_sign_in(self):
        # Even if the tool then says that all is well.
        self.put("login-waits")
        window = self.open("2", right=None)
        window.wait_for("waiting for the browser")
        window.key(b"\x03")
        self.assertTrue(window.done())
        self.assertIn("Interrupted.", window.text)
        self.assertNotIn("the right account?", window.text)
        self.assertNotIn("run.sh", self.calls())
        self.check_signed_out("azure")

    def test_control_c_at_the_last_question(self):
        window = self.open("2", right=None)
        window.wait_for("the right account?")
        window.key(b"\x03")
        time.sleep(0.3)
        window.type("yes")
        self.assertTrue(window.done())
        self.assertEqual(window.code, 1)
        self.assertNotIn("run.sh", self.calls())
        self.check_signed_out("azure")

    def test_google_gives_no_token(self):
        self.put("no-token")
        window = self.open("3")
        self.assertTrue(window.done())
        self.assertEqual(window.code, 1)
        self.assertNotIn("run.sh", self.calls())
        self.check_signed_out("gcp")

    def test_sign_out_does_not_work(self):
        for number, cloud in (("1", "aws"), ("2", "azure"), ("3", "gcp")):
            with self.subTest(cloud):
                # For AWS and Azure it is enough that the files go. At Google it has to be ended, so the files stay for that.
                self.put("no-logout", "keychain")
                window = self.open(number)
                self.assertTrue(window.done())
                if cloud == "aws":
                    self.assertEqual(window.code, 0)
                    self.assertEqual(self.signed_in(), [])
                    (self.home / "no-logout").unlink()
                    continue
                self.assertEqual(window.code, 1)
                self.assertIn("STILL SIGNED IN", window.text)
                self.assertNotIn("No sign-in is left", window.text)
                self.assertNotEqual(self.signed_in(), [])
                (self.home / "no-logout").unlink()
                # The next time it signs out first, and only then asks.
                window = Terminal(self.home)
                self.addCleanup(self.away, window)
                window.wait_for("Which one?")
                self.assertIn("An earlier sign-in", window.text)
                self.assertEqual(self.signed_in(), [])
                (self.home / "keychain").unlink()
                window.type("x")
                self.assertTrue(window.done())

    def test_earlier_sign_in_that_stays(self):
        folder = self.home / ".config" / "gcloud"
        folder.mkdir(parents=True)
        (folder / "account").write_text("somebody")
        self.put("no-logout")
        window = Terminal(self.home)
        self.addCleanup(self.away, window)
        self.assertTrue(window.done())
        self.assertEqual(window.code, 1)
        self.assertNotIn("Which one?", window.text)

    def test_earlier_sign_ins_go_first(self):
        for place in (".aws/login/cache/old.json", ".azure/msal_token_cache.json", ".config/gcloud/application_default_credentials.json"):
            (self.home / place).parent.mkdir(parents=True)
            (self.home / place).write_text("secret")
        # Without a connection az gets no token. What it has stored is a sign-in all the same.
        self.put("az-offline")
        window = Terminal(self.home)
        self.addCleanup(self.away, window)
        window.wait_for("Which one?")
        self.assertEqual(window.text.count("An earlier sign-in"), 3)
        self.assertEqual(self.signed_in(), [])

    def test_google_cannot_be_reached_at_the_end(self):
        # Then nothing is ended there, and no token comes either. That must not look like a sign-out.
        self.put("run-waits", text="1")
        window = self.open("3")
        window.wait_for("run.sh is here")
        self.put("no-logout", "no-token")
        self.assertTrue(window.done())
        self.assertEqual(window.code, 1)
        self.assertIn("STILL SIGNED IN", window.text)
        self.assertIn("Not ended at Google", window.text)
        self.assertTrue((self.home / ".config" / "gcloud" / "account").exists())

    def test_the_wrong_account(self):
        for number, cloud, shown in (("1", "aws", "The right one"), ("2", "azure", "A subscription"), ("3", "gcp", "somebody")):
            with self.subTest(cloud):
                (self.home / "calls").write_text("")
                window = self.open(number, right="no")
                self.assertTrue(window.done())
                self.assertIn("as: " + shown, window.text)
                self.assertEqual(window.code, 1)
                self.assertNotIn("run.sh", self.calls())
                self.check_signed_out(cloud)

    def test_shell(self):
        window = self.open("1", "s")
        window.wait_for("[AWS]")
        window.type("echo profile=${AWS_PROFILE:-empty} git=${GIT_DIR:-empty} proxy=${HTTPS_PROXY:-empty} path=$PATH")
        window.wait_for("profile=empty git=empty proxy=empty")
        self.assertIn(f"path={self.home}/tools/bin:/usr/bin:/bin:/usr/sbin:/sbin", window.text)
        self.assertNotIn("run.sh", self.calls())
        self.assertNotEqual(self.signed_in(), [])
        window.type("exit")
        self.assertTrue(window.done())
        self.check_signed_out("aws")

    def test_window_of_the_shell_closed(self):
        for through_shell in (False, True):
            with self.subTest(through_shell):
                (self.home / "calls").write_text("")
                window = self.open("1", "s", through_shell=through_shell)
                window.wait_for("[AWS]")
                self.gone(window)
                self.check_signed_out("aws")

    def test_no_to_the_code(self):
        window = self.open("1", "n")
        self.assertTrue(window.done())
        self.assertNotIn("aws login", self.calls())

    def test_typed_too_early_is_no_answer(self):
        window = Terminal(self.home)
        self.addCleanup(self.away, window)
        window.type("1")
        window.type("r")
        time.sleep(0.8)
        window.wait_for("Which one?")
        time.sleep(0.5)
        self.assertNotIn("aws login", self.calls())

    def test_refuses_an_administrator(self):
        (self.home / "groups").write_text("staff everyone admin localaccounts\n")
        self.refused("administrator")

    def test_refuses_an_open_home(self):
        self.home.chmod(0o750)
        self.refused("not closed")

    def test_refuses_while_claude_is_open(self):
        self.put("claude-is-open")
        self.refused("Claude is open")

    def refused(self, words):
        window = Terminal(self.home)
        self.addCleanup(self.away, window)
        self.assertTrue(window.done())
        self.assertEqual(window.code, 1)
        self.assertIn(words, window.text)
        self.assertEqual(self.calls(), "")

    def test_two_windows(self):
        self.put("run-waits", text="60")
        first = self.open("1", through_shell=True)
        first.wait_for("run.sh is here")
        second = Terminal(self.home)
        self.addCleanup(self.away, second)
        self.assertTrue(second.done())
        self.assertEqual(second.code, 1)
        self.assertIn("One at a time", second.text)
        self.assertNotEqual(self.signed_in(), [])
        self.assertNotIn(SIGN_OUT["aws"], self.calls())
        # The second one may not take the lock of the first away either.
        third = Terminal(self.home)
        self.addCleanup(self.away, third)
        self.assertTrue(third.done())
        self.assertIn("One at a time", third.text)
        self.gone(first)
        self.check_signed_out("aws")
        # And afterwards a new window is welcome.
        window = Terminal(self.home)
        self.addCleanup(self.away, window)
        window.wait_for("Which one?")

    def test_a_lock_that_was_left_does_not_block(self):
        lock = self.home / "runs" / ".open"
        for text in ("", "1\n", "999999\n", f"{os.getpid()}\n"):
            with self.subTest(text):
                lock.mkdir(parents=True, exist_ok=True)
                (lock / "window").write_text(text)
                window = Terminal(self.home)
                self.addCleanup(self.away, window)
                window.wait_for("Which one?")
                window.type("x")
                self.assertTrue(window.done())
                self.assertFalse(lock.exists())

    def test_without_the_tools(self):
        (self.home / "tools" / "bin" / "gcloud").unlink()
        self.refused("Run setup.sh first")

    def test_no_network(self):
        self.put("no-network")
        window = self.open("1", None)
        self.assertTrue(window.done())
        self.assertEqual(window.code, 1)
        self.assertNotIn("aws login", self.calls())


MISTAKES = [
    ("no sign-out at the end", "trap end EXIT\n", "\n"),
    ("a closed window is ignored", "trap 'interrupted=129' HUP\n", "trap '' HUP\n"),
    ("a closed window ends the file at once", "trap 'interrupted=129' HUP\n", "trap 'exit 129' HUP\n"),
    ("being ended ends the file at once", "trap 'interrupted=143' TERM\n", "trap 'exit 143' TERM\n"),
    ("the sign-out can be interrupted", "  trap '' HUP INT TERM\n", ""),
    ("goes on after an interrupted sign-in", '[ -z "$interrupted" ] || stop "Interrupted."', ":"),
    ("an interrupted yes is a yes", '[ "$answer$interrupted" = yes ]', '[ "$answer" = yes ]'),
    ("no result is written", " RUN_RESULTS=/Users/Shared/clouds", ""),
    ("every cloud asks GitHub again", " RUN_CHECKED=$HOME/runs/.checked", ""),
    ("the sign-out needs the window", 'if sign_out "$cloud"; then', 'printf "Signing out.\\n" || exit 1; if sign_out "$cloud"; then'),
    ("signed in is noted too late", 'touched=yes\nprintf', 'printf'),
    ("nothing is ever left", '  [ -z "$left" ]\n', "  true\n"),
    ("AWS: the folder stays", '  rm -rf "$HOME/.aws"\n', ""),
    ("AWS: the sign-out is forgotten", "  aws logout --all\n", ""),
    ("AWS: nobody looks for the folder", 'if [ -e "$HOME/.aws" ]; then echo "$HOME/.aws"; fi', ":"),
    ("Azure: the folder stays", '  rm -rf "$HOME/.azure"\n', ""),
    ("Azure: the sign-out is forgotten", "  az logout\n", ""),
    ("Azure: only the files are looked at", 'if az account get-access-token --output none > /dev/null 2>&1; then', "if false; then"),
    ("Azure: nobody looks for the folder", '  if [ -e "$HOME/.azure" ]; then\n', "  if false; then\n"),
    ("Google: not ended at Google", 'if [ -n "$accounts" ]; then gcloud auth revoke --all --quiet || return 1; fi', ":"),
    ("Google: nobody listens to what it says", "gcloud auth revoke --all --quiet || return 1", "gcloud auth revoke --all --quiet"),
    ("Google: ended although nobody is signed in", 'if [ -n "$accounts" ]; then gcloud', "if true; then gcloud"),
    ("Google: nobody looks for the folder", '  if [ -e "$HOME/.config/gcloud" ]; then\n', "  if false; then\n"),
    ("Google: no token for Terraform", 'if [ "$cloud" = gcp ]; then gcp_token || stop "Google gave no token."; fi', ""),
    ("Google: goes on without a token", 'gcp_token || stop "Google gave no token."', "gcp_token"),
    ("goes on after a failed sign-in", '|| stop "The sign-in did not work."', "|| true"),
    ("goes on in the wrong account", '[ "$answer$interrupted" = yes ] || stop "Nothing was done there."', ":"),
    ("does not say whose account it is", '"$("${cloud}_who" 2> /dev/null || echo \'the tool does not say\')"', '""'),
    ("an administrator may", '*" admin "*)', '*" nobody "*)'),
    ("an open home is fine", '[ "$(stat -f \'%Lp %u\' "$HOME")" = "700 $(id -u)" ] ||', "true ||"),
    ("Claude may be open", 'if pgrep -U "$(id -u)" -i claude > /dev/null; then', "if false; then"),
    ("an earlier sign-in is not looked for", "for cloud in aws azure gcp; do", "for cloud in; do"),
    ("goes on although an earlier sign-in stays", '|| stop "That did not work. End it in the browser, then start again."', "|| true"),
    ("the folder of all users", "RUN_TMP=$run ", "RUN_TMP=/tmp "),
    ("open folders", "umask 077\n", "umask 022\n"),
    ("what is set outside counts", "/usr/bin/env -i CLOUDS_CLEAN=yes", "/usr/bin/env CLOUDS_CLEAN=yes"),
    ("the path from outside counts", 'PATH="$HOME/tools/bin:/usr/bin:/bin:/usr/sbin:/sbin"', 'PATH="$HOME/tools/bin:$PATH:/opt/x"'),
    ("any answer is a yes", "  *) stop \"Nothing was done.\" ;;\nesac\n\n# ---- From here", "  *) what=r ;;\nesac\n\n# ---- From here"),
    ("typed too early counts", "  python3 -c 'import termios; termios.tcflush(0, termios.TCIFLUSH)' 2> /dev/null || true\n", "  :\n"),
    ("goes on without the code", '|| stop "The code could not be loaded."', "|| true"),
    ("says yes although it is still signed in", "      code=1\n", "      code=0\n"),
    ("two windows at a time", "grep -qi 'clouds\\.command'", "grep -qi 'nothing like it'"),
    ("a lock that was left blocks for ever", "if [ -n \"$other\" ] && ps -p \"$other\" -o command= 2> /dev/null | grep -qi 'clouds\\.command'; then", "if true; then"),
    ("the lock stays", 'if [ "$locked" = yes ]; then rm -rf "$lock"; fi', ":"),
    ("a refused window takes the lock away", "locked=no\n", "locked=yes\n"),
    ("starts without the tools", '[ -x "$HOME/tools/bin/$tool" ] ||', "true ||"),
    ("another cloud is signed out", '"$1_out" > /dev/null 2>&1', "aws_out > /dev/null 2>&1"),
]


def mistakes(only):
    original = SCRIPT.read_text()
    unnoticed = []
    # Without this, a test that fails for a reason of its own would look as if it noticed every mistake.
    result = unittest.TestResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(Clouds).run(result)
    if not result.wasSuccessful() or result.skipped:
        print("The file without a mistake does not pass, so nothing can be said:", [test.id() for test, _ in result.failures + result.errors])
        return False
    print(f"without a mistake: {result.testsRun} tests pass", flush=True)
    chosen = [entry for entry in enumerate(MISTAKES, 1) if not only or entry[0] in only]
    absent = [name for _, (name, old, _) in chosen if old not in original]
    if absent:
        print("Not in the file any more, so nothing can be said:", absent)
        return False
    for number, (name, old, new) in chosen:
        folder = pathlib.Path(tempfile.mkdtemp())
        copy = folder / "clouds.command"
        copy.write_text(original.replace(old, new))
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(type("Copy", (Clouds,), {"script": copy}))
        result = unittest.TestResult()
        result.failfast = True
        suite.run(result)
        noticed = not result.wasSuccessful()
        first = (result.failures + result.errors + [(None, "")])[0][0]
        print(f"{number:2} {'noticed ' if noticed else 'UNNOTICED'}  {name}" + (f"   ({first.id().rsplit('.', 1)[-1]})" if noticed and first is not None else ""), flush=True)
        if not noticed:
            unnoticed.append(name)
        shutil.rmtree(folder)
    print(f"{len(chosen) - len(unnoticed)} of {len(chosen)} mistakes noticed")
    return not unnoticed


if __name__ == "__main__":
    if "--mistakes" in sys.argv:
        sys.exit(0 if mistakes([int(word) for word in sys.argv[1:] if word.isdigit()]) else 1)
    unittest.main()
