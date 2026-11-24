"""Runs install-terraform.sh against stand-ins for the network. Nothing is loaded."""

import hashlib
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import zipfile

SCRIPT = pathlib.Path(__file__).resolve().parent / "install-terraform.sh"

# From HashiCorp's list for 1.17.2, whose signature was checked on 24 November 2026.
SIGNED = {
    "Linux x86_64": ("linux_amd64", "e6f16b2f0b137ee5729caa8c4e79a3bae4ee261acd198a1fcfa8584a6296605b"),
    "Linux aarch64": ("linux_arm64", "858e08c181a76b6b223e8c767a8e983922eebe2d062db949a2de66ce040c368c"),
    "Darwin arm64": ("darwin_arm64", "da0c7ef278a911347862758e7573a5907365e66485c2637cf5c217c5e227992e"),
}


class Install(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.box = pathlib.Path(self.dir.name)
        self.bin = self.box / "bin"
        self.bin.mkdir()
        with zipfile.ZipFile(self.box / "archive.zip", "w") as archive:
            info = zipfile.ZipInfo("terraform")
            info.external_attr = 0o755 << 16
            archive.writestr(info, "#!/bin/sh\necho it is here\n")
            archive.writestr("LICENSE.txt", "x")
        # The last argument of curl is the address, and what comes after --output is the file.
        self.tool("curl", 'echo "$*" >> "$BOX/asked"\nwhile [ $# -gt 1 ]; do [ "$1" != --output ] || to=$2; shift; done\ncp "$BOX/archive.zip" "$to"\n')
        for name in ("bash", "cat", "cp", "mkdir", "mktemp", "rm", "unzip"):
            found = next(pathlib.Path(folder, name) for folder in ("/bin", "/usr/bin") if pathlib.Path(folder, name).exists())
            (self.bin / name).symlink_to(found)

    def tool(self, name, text):
        (self.bin / name).write_text("#!/bin/sh\n" + text)
        (self.bin / name).chmod(0o755)

    def go(self, system, sums=("sha256sum",), code=0):
        self.tool("uname", f'[ "$1" = -s ] && echo "{system.split()[0]}" || echo "{system.split()[1]}"\n')
        for name in ("sha256sum", "shasum"):
            (self.bin / name).unlink(missing_ok=True)
        for name in sums:
            self.tool(name, f'echo "{name} $* $(cat)" >> "$BOX/sums"\nexit {code}\n')
        for name in ("asked", "sums"):
            (self.box / name).unlink(missing_ok=True)
        done = subprocess.run(["/bin/bash", str(SCRIPT), str(self.box / "to")], env={"PATH": str(self.bin), "BOX": str(self.box), "TMPDIR": str(self.box)}, capture_output=True, text=True)
        self.assertEqual(sorted(path.name for path in self.box.iterdir() if path.name.startswith("tmp")), [])
        return done

    def test_each_platform_gets_its_own_file_and_sum(self):
        for system, (platform, sha256) in SIGNED.items():
            for sums, options in ((("sha256sum",), "--check --quiet -"), (("sha256sum", "shasum"), "--check --quiet -"), (("shasum",), "--algorithm 256 --check --quiet -")):
                done = self.go(system, sums)
                self.assertEqual((done.returncode, done.stdout), (0, "it is here\n"), done.stderr)
                self.assertTrue((self.box / "asked").read_text().endswith(f" https://releases.hashicorp.com/terraform/1.17.2/terraform_1.17.2_{platform}.zip\n"))
                lines = (self.box / "sums").read_text().splitlines()
                self.assertEqual(len(lines), 1)
                self.assertTrue(lines[0].startswith(f"{sums[0]} {options} {sha256}  ") and lines[0].endswith(f"/terraform_1.17.2_{platform}.zip"), lines)
                (self.box / "to" / "terraform").unlink()

    def test_other_bytes_are_not_used(self):
        for system in SIGNED:
            for sums in (("sha256sum",), ("shasum",)):
                done = self.go(system, sums, code=1)
                self.assertNotEqual(done.returncode, 0)
                self.assertFalse((self.box / "to" / "terraform").exists())

    def test_the_real_tools_take_these_options(self):
        file = self.box / "archive.zip"
        right = hashlib.sha256(file.read_bytes()).hexdigest()
        found = 0
        for name, options in (("sha256sum", []), ("shasum", ["--algorithm", "256"])):
            if not shutil.which(name):
                continue
            found += 1
            for sum_, fine in ((right, True), ("0" * 64, False)):
                done = subprocess.run([name, *options, "--check", "--quiet", "-"], input=f"{sum_}  {file}\n", capture_output=True, text=True)
                self.assertEqual(done.returncode == 0, fine, (name, done.stderr))
        self.assertGreater(found, 0)

    def test_nothing_is_known_for_other_machines(self):
        for system in ("Darwin x86_64", "Linux riscv64", "FreeBSD amd64"):
            done = self.go(system)
            self.assertEqual((done.returncode, done.stderr), (1, f"No pinned Terraform for {system.replace(' ', '/')}.\n"))
            self.assertFalse((self.box / "asked").exists())

    def test_the_version_is_the_same_for_all(self):
        self.assertEqual(SCRIPT.read_text().count("version=1.17.2"), 1)
        self.assertEqual(SCRIPT.read_text().count("sha256="), len(SIGNED))


if __name__ == "__main__":
    unittest.main()
