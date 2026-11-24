"""Tests that setup.sh refuses what it should refuse, against stand-ins: no download, no installation.

That it works with the real files is for a Mac runner on GitHub: there it can load them, here it must not.
"""

import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent / "setup.sh"
SIZES = {"cpython": 26753457, "AWSCLIV2": 61141180, "azure-cli": 46713373, "google-cloud-cli": 54790650}
TOOLS = {
    "id": 'cat "$HOME/groups"',
    "uname": 'case "$1" in -s) echo Darwin ;; -m) cat "$HOME/machine" ;; esac',
    "curl": """
        echo "curl $*" >> "$HOME/calls"
        while [ $# -gt 1 ]; do if [ "$1" = --output ]; then to=$2; fi; shift; done
        for name in cpython AWSCLIV2 azure-cli google-cloud-cli; do
          case "$1" in *"$name"*) /usr/bin/python3 -c 'import sys; open(sys.argv[1], "wb").truncate(int(open(sys.argv[2]).read()))' "$to" "$HOME/size-$name" ;; esac
        done""",
    "pkgutil": """
        echo "pkgutil $*" >> "$HOME/calls"
        [ ! -e "$HOME/not-signed" ] || { echo "Status: no signature"; exit 1; }
        echo "   Status: signed by a developer certificate issued by Apple for distribution"
        echo "    1. $(cat "$HOME/signer")" """,
    "installer": """
        echo "installer $*" >> "$HOME/calls"
        for last in "$@"; do :; done
        to=$(grep -A1 attributeSetting "$last" | grep string | sed 's/ *<[^>]*>//g')
        mkdir -p "$to/aws-cli"; printf '#!/bin/bash\\n' > "$to/aws-cli/aws"; chmod 700 "$to/aws-cli/aws" """,
    "sudo": 'echo "sudo $*" >> "$HOME/calls"; exit 1',
}


@unittest.skipUnless(sys.platform == "darwin", "a Mac's own tools")
class Setup(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.home.chmod(0o750)
        fake = self.home / "fake"
        fake.mkdir()
        for name, body in TOOLS.items():
            (fake / name).write_text(f"#!/bin/bash\n{body}\n")
            (fake / name).chmod(0o700)
        (self.home / "groups").write_text("staff everyone\n")
        (self.home / "machine").write_text("arm64\n")
        (self.home / "calls").write_text("")
        (self.home / "signer").write_text("Developer ID Installer: AMZN Mobile LLC (94KV3E626L)\n")
        for name, size in SIZES.items():
            (self.home / f"size-{name}").write_text(str(size))
        text = SCRIPT.read_text()
        line = "PATH=/usr/bin:/bin:/usr/sbin:/sbin\n"
        assert text.count(line) == 1
        (self.home / "setup.sh").write_text(text.replace(line, f"PATH={fake}:/usr/bin:/bin:/usr/sbin:/sbin\n"))

    def run_it(self):
        done = subprocess.run(["/bin/bash", str(self.home / "setup.sh")], env={"HOME": str(self.home), "PATH": "/usr/bin:/bin"},
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        self.calls = (self.home / "calls").read_text()
        self.assertNotIn("sudo", self.calls)
        return done

    def there(self, *names):
        for name in names:
            (self.home / "tools" / name).mkdir(parents=True)

    def tools(self):
        folder = self.home / "tools"
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []

    def refused(self, words, left):
        done = self.run_it()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn(words, done.stdout)
        self.assertEqual(self.tools(), left)
        self.assertFalse((self.home / ".zprofile").exists())

    def test_an_administrator_changes_nothing(self):
        (self.home / "groups").write_text("staff admin everyone\n")
        self.refused("administrator", [])
        self.assertEqual(stat.S_IMODE(self.home.stat().st_mode), 0o750)
        self.assertEqual(self.calls, "")

    def test_another_kind_of_mac(self):
        (self.home / "machine").write_text("x86_64\n")
        self.refused("Apple silicon", [])
        self.assertEqual(self.calls, "")

    def test_another_size(self):
        (self.home / "size-cpython").write_text("26753456")
        self.refused("another size", ["bin"])

    def test_another_fingerprint(self):
        self.refused("another fingerprint", ["bin"])
        self.assertEqual(stat.S_IMODE(self.home.stat().st_mode), 0o700)

    def test_aws_not_signed(self):
        self.there("python-3.14.10")
        (self.home / "not-signed").write_text("")
        self.refused("is not signed", ["bin", "python-3.14.10"])
        self.assertNotIn("installer", self.calls)

    def test_aws_signed_by_somebody_else(self):
        self.there("python-3.14.10")
        (self.home / "signer").write_text("Developer ID Installer: Somebody Else (ABCDE12345)\n")
        self.refused("signed by somebody else", ["bin", "python-3.14.10"])
        self.assertNotIn("installer", self.calls)

    def test_aws_goes_into_the_home_folder_and_the_next_one_is_refused(self):
        self.there("python-3.14.10")
        self.refused("another fingerprint", ["aws-2.40.0", "bin", "python-3.14.10"])
        self.assertIn("-target CurrentUserHomeDirectory", self.calls)
        self.assertIn("azure-cli-2.92.0-macos-arm64", self.calls)
        self.assertNotIn("google-cloud-cli", self.calls)

    def test_google_is_refused_too(self):
        self.there("python-3.14.10", "aws-2.40.0", "az-2.92.0")
        self.refused("another fingerprint", ["aws-2.40.0", "az-2.92.0", "bin", "python-3.14.10"])

    def test_only_https(self):
        self.run_it()
        for call in self.calls.splitlines():
            if call.startswith("curl"):
                self.assertIn("--proto =https --proto-redir =https", call)
                self.assertIn(" https://", call)


if __name__ == "__main__":
    unittest.main()
