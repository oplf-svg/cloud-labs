import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent


class MoreChecks(unittest.TestCase):
    def go(self, files):
        with tempfile.TemporaryDirectory() as folder:
            script = pathlib.Path(folder, ".github/scripts/more_checks.sh")
            script.parent.mkdir(parents=True)
            shutil.copy(HERE / script.name, script)
            for name, text in files.items():
                path = pathlib.Path(folder, name)
                path.parent.mkdir(exist_ok=True)
                path.symlink_to(text[2:]) if text.startswith("->") else path.write_text(text)
            done = subprocess.run(["bash", str(script)], cwd="/", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            return done.returncode, done.stdout

    def test_runs_the_checks_of_every_folder(self):
        files = {"a/checks.sh": "echo one\n", "b/checks.sh": "echo two\n", "c/other.sh": "exit 1\n"}
        self.assertEqual(self.go(files), (0, "== a/checks.sh\none\n== b/checks.sh\ntwo\n2 folder(s) checked\n"))

    def test_one_that_fails_makes_it_red(self):
        code, output = self.go({"a/checks.sh": "echo one; exit 3\n", "b/checks.sh": "echo two\n"})
        self.assertNotEqual(code, 0)
        self.assertNotIn("two", output)

    def test_a_branch_that_has_to_wait_is_red_in_the_end(self):
        for text, said in (("Waits for run.sh, until 25 November.\nmore\n", "Waits for run.sh, until 25 November."), ("", "")):
            code, output = self.go({"HOLD": text, "a/checks.sh": "echo one\n"})
            self.assertEqual((code, output), (1, f"== a/checks.sh\none\n1 folder(s) checked\nNot to be merged yet: {said}\n"))

    def test_a_link_makes_it_wait_and_is_not_followed(self):
        for target in ("other", "nowhere", "a"):
            code, output = self.go({"HOLD": "->" + target, "other": "private\n", "a/x": "x"})
            self.assertEqual((code, output), (1, "0 folder(s) checked\nNot to be merged yet: HOLD is not a plain file.\n"))
        self.assertEqual(self.go({"HOLD/x": "x"})[0], 1)

    def test_no_check_can_take_it_away(self):
        for does in ("mv HOLD held", "rm HOLD", "echo other > HOLD", "rm HOLD; ln -s nowhere HOLD", "rm HOLD; mkdir HOLD"):
            code, output = self.go({"HOLD": "Waits.\n", "a/checks.sh": does + "\n", "b/checks.sh": "echo two\n"})
            self.assertEqual((code, output), (1, "== a/checks.sh\n== b/checks.sh\ntwo\n2 folder(s) checked\nNot to be merged yet: Waits.\n"))
        code, output = self.go({"HOLD": "->nowhere", "a/checks.sh": "rm HOLD\n"})
        self.assertEqual((code, output), (1, "== a/checks.sh\n1 folder(s) checked\nNot to be merged yet: HOLD is not a plain file.\n"))

    def test_no_check_can_change_what_comes_after_it(self):
        # bash reads a script as it goes, and this writes into the one that runs.
        write = "python3 -c \"import pathlib; s = pathlib.Path('.github/scripts/more_checks.sh'); s.write_text(chr(10) * s.stat().st_size + 'exit 0' + chr(10))\"\n"
        code, output = self.go({"HOLD": "Waits.\n", "a/checks.sh": write})
        self.assertEqual((code, output), (1, "== a/checks.sh\n1 folder(s) checked\nNot to be merged yet: Waits.\n"))
        code, output = self.go({"a/checks.sh": write, "b/checks.sh": "echo two; exit 3\n"})
        self.assertEqual((code, output), (3, "== a/checks.sh\n== b/checks.sh\ntwo\n"))

    def test_what_a_check_makes_does_not_count(self):
        self.assertEqual(self.go({"a/checks.sh": "echo x > HOLD\n"}), (0, "== a/checks.sh\n1 folder(s) checked\n"))

    def test_only_that_file_makes_it_wait(self):
        self.assertEqual(self.go({"HOLDER": "x", "a/HOLD": "x"}), (0, "0 folder(s) checked\n"))


if __name__ == "__main__":
    unittest.main()
