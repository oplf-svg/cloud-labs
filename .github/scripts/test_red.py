"""What decides whether a pull request is red.

Each shell script that a workflow starts runs here for real, with a stand-in for what it starts. Each of those fails once, and
then the script has to be red, at that place. The step of the required check runs for real too, with every way in which a job
can end. What ci.yml runs stands here word for word, so a line that is gone is noticed, and so is one that goes on after a
failure. This cannot notice that nobody starts it: test_workflows.py does.
"""

import fnmatch
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# What each script starts on GitHub, in this order. ~ is the folder of the test.
TERRAFORM = [
    "terraform providers lock -platform=linux_amd64 -platform=linux_arm64 -platform=darwin_arm64",
    "git diff --exit-code .terraform.lock.hcl",
    "terraform fmt -check -diff -recursive",
    "terraform init -backend=false -input=false -lockfile=readonly",
    "terraform validate",
    "terraform test",
]
SCRIPTS = {
    ".github/scripts/more_checks.sh": [f"bash {path.parent.name}/checks.sh" for path in sorted(ROOT.glob("*/checks.sh"))],
    "bootstrap/checks.sh": ["shellcheck checks.sh mac/setup.sh mac/clouds.command", "python3 -m unittest discover --start-directory mac"],
    "bootstrap/scripts/install-terraform.sh": None,  # Its lines depend on the machine.
    "site/checks.sh": [
        "install-terraform.sh ~/made",
        "shellcheck checks.sh deploy/build.sh",
        "bash deploy/build.sh",
        "npm run check",
        "npm test",
        "npm run e2e",
        "python3 -m unittest discover --start-directory deploy",
        *TERRAFORM * 2,
    ],
    "site/deploy/build.sh": ["npm ci --no-audit --no-fund", "npm run build", "cp -R pages/dist out", "node scripts/list-files.mjs out"],
}
# Started by a person, not by a workflow. Each has tests of its own.
BY_HAND = {"bootstrap/mac/setup.sh", "bootstrap/scripts/run.sh"}

# What each job of ci.yml runs. The step of the job ci runs for real, further down.
CI = {
    "terraform": [
        '../scripts/install-terraform.sh "$RUNNER_TEMP/bin"\necho "$RUNNER_TEMP/bin" >> "$GITHUB_PATH"',
        "terraform providers lock -platform=linux_amd64 -platform=linux_arm64 -platform=darwin_arm64\ngit diff --exit-code .terraform.lock.hcl",
        "terraform fmt -check -diff -recursive",
        "terraform init -backend=false -input=false -lockfile=readonly",
        "terraform validate",
        "terraform test",
    ],
    "scripts": [
        "shellcheck bootstrap/scripts/*.sh",
        "python3 -m unittest discover --start-directory bootstrap/scripts",
        "python3 -m unittest discover --start-directory .github/scripts",
    ],
    "more": ["bash .github/scripts/more_checks.sh"],
    "blocked-terms": [
        'cp .github/scripts/blocked_terms.py "$RUNNER_TEMP/blocked_terms.py"',
        'gh api "repos/$GITHUB_REPOSITORY/pulls/$NUMBER" > "$RUNNER_TEMP/pull.json"',
        'python3 -I "$RUNNER_TEMP/blocked_terms.py"',
    ],
}
# Says on the owner's phone that something is red, and decides nothing.
TELLS = {("nightly-destroy.yml", "tell")}

# What a script may really use. `rm` does nothing here, and the rest are stand-ins. A stand-in reads what it is given, as the
# real one would.
REAL = ("dirname", "mkdir", "uname")
NAMES = ("bash", "cp", "curl", "git", "node", "npm", "python3", "sha256sum", "shasum", "shellcheck", "terraform", "unzip")
STAND_IN = """#!/bin/sh
while read -r _; do :; done
n=1; while read -r _; do n=$((n + 1)); done < "$CALLS"
echo "${0##*/} $*" >> "$CALLS"
[ "$n" -ne "$FAIL_AT" ] || exit 1
"""
NOTHING = "#!/bin/sh\n"
MKTEMP = '#!/bin/sh\nmkdir -p "$HOME/made"\necho "$HOME/made"\n'


def tree():
    """The folders of the repo, and its shell scripts."""
    for folder, names, files in os.walk(ROOT):
        names[:] = sorted(set(names) - {".git", ".terraform", "node_modules", "dist", "out", "__pycache__"})
        here = pathlib.Path(folder).relative_to(ROOT)
        yield here, sorted(here / file for file in files if file.endswith(".sh"))


TREE = list(tree())


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


class Place:
    """One script in a copy of the folders. It may be run again and again."""

    def __init__(self, script, folder):
        self.script, self.folder = script, pathlib.Path(folder).resolve()
        for here, scripts in TREE:
            (self.folder / "repo" / here).mkdir(parents=True, exist_ok=True)
            for other in scripts:
                put(self.folder / "repo" / other, STAND_IN)
        put(self.folder / "repo" / script, (ROOT / script).read_text())
        for name in NAMES:
            put(self.folder / "bin" / name, STAND_IN)
        put(self.folder / "bin/mktemp", MKTEMP)
        put(self.folder / "bin/rm", NOTHING)
        for name in REAL:
            (self.folder / "bin" / name).symlink_to(shutil.which(name))
        # Where Terraform is unpacked to.
        put(self.folder / "tools/terraform", STAND_IN)

    def go(self, fail_at=0, ci=True, without=()):
        """Its exit code, what it started in order, and what it said."""
        calls = self.folder / "calls"
        calls.write_text("")
        arguments = [str(self.folder / "tools")] if self.script.endswith("install-terraform.sh") else []
        env = {"PATH": str(self.folder / "bin"), "CALLS": str(calls), "FAIL_AT": str(fail_at), "HOME": str(self.folder)} | ({"CI": "true", "GITHUB_ACTIONS": "true"} if ci else {})
        for name in without:
            (self.folder / "bin" / name).rename(self.folder / name)
        done = subprocess.run(["/bin/bash", str(self.folder / "repo" / self.script), *arguments], cwd=self.folder, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        for name in without:
            (self.folder / name).rename(self.folder / "bin" / name)
        return done.returncode, calls.read_text().replace(str(self.folder), "~").splitlines(), done.stdout


class Scripts(unittest.TestCase):
    # On GitHub, by hand, and on a Mac that has only the older of two tools.
    WAYS = ({"ci": True}, {"ci": False}, {"ci": False, "without": ["sha256sum"]})

    def test_every_script_is_known(self):
        found = {str(script) for _, scripts in TREE for script in scripts}
        self.assertEqual(found - set(SCRIPTS) - BY_HAND, set(), "New: say in SCRIPTS what it starts on GitHub, or in BY_HAND that a person starts it.")
        self.assertEqual((set(SCRIPTS) | BY_HAND) - found, set(), "Gone: take it out of SCRIPTS or BY_HAND.")
        # None that only a person starts is started by a workflow or by a script of one. Shellcheck only reads it.
        texts = [path.read_text() for path in [*(ROOT / ".github/workflows").glob("*.yml"), *(ROOT / script for script in SCRIPTS)]]
        started = {pathlib.PurePath(name).name for text in texts for name in re.findall(r"[\w./-]+\.sh\b", re.sub(r"(?m)^ *(?:#|shellcheck|- run: shellcheck).*$", "", text))}
        self.assertEqual(started - {pathlib.PurePath(script).name for script in SCRIPTS}, set())

    def test_a_script_is_red_where_something_that_it_starts_fails(self):
        for script, commands in SCRIPTS.items():
            with tempfile.TemporaryDirectory() as folder:
                place = Place(script, folder)
                for way in self.WAYS:
                    code, calls, output = place.go(**way)
                    with self.subTest(script=script, way=way):
                        self.assertEqual(code, 0, f"{output}\nA command that is not found here has to be added to NAMES.")
                        if commands and way["ci"]:
                            self.assertEqual(calls, commands, "It starts something else: say so in SCRIPTS.")
                        if not commands:
                            # Fetched, checked, unpacked and started, with the older tool where the newer one is missing.
                            self.assertEqual([call.split()[0] for call in calls], ["curl", "shasum" if "without" in way else "sha256sum", "unzip", "terraform"])
                    for n, call in enumerate(calls, 1):
                        with self.subTest(script=script, way=way, fails=call):
                            code, so_far, _ = place.go(fail_at=n, **way)
                            self.assertNotEqual(code, 0, "it is green")
                            self.assertEqual(so_far, calls[:n], "it went on")


def jobs(text):
    """Each job of a workflow, however its name is written, without the comments."""
    body = re.sub(r"(?m)^ *#.*\n", "", text).partition("\njobs:\n")[2] + "\n"
    return {name.partition(":")[0].strip("\"' "): job for name, job in re.findall(r"(?m)^  (\S.*)\n((?:(?:    .*)?\n)*)", body)}


def commands(job):
    """What its steps run."""
    found = []
    lines = job.split("\n")
    for at, line in enumerate(lines):
        key = re.fullmatch(r"( +)(- )?run: ?(.*)", line)
        if not key:
            continue
        column, value = len(key[1] + (key[2] or "")), key[3].strip()
        if value == "|":
            block = []
            for after in lines[at + 1 :]:
                if after.strip() and len(after) - len(after.lstrip()) <= column:
                    break
                block.append(after)
            value = "\n".join(one.strip() for one in block).strip()
        found.append(value)
    return found


class Workflows(unittest.TestCase):
    def setUp(self):
        self.texts = {path.name: re.sub(r"(?m)^ *#.*\n|^    defaults:\n      run:\n", "", path.read_text()) for path in (ROOT / ".github/workflows").glob("*.yml")}

    def test_none_is_missed(self):
        for file, text in self.texts.items():
            with self.subTest(file=file):
                self.assertEqual(sum(len(commands(job)) for job in jobs(text).values()), len(re.findall(r"""(?<![\w-])["']?run["']?\s*:""", text)), "A step is written in another way: write `run:` as the others do.")
                self.assertNotRegex(text, r"""["']?(?:continue-on-error|shell)["']?\s*:""")

    def test_ci_runs_these_commands(self):
        text = self.texts["ci.yml"]
        self.assertEqual({name: commands(job) for name, job in jobs(text).items() if name != "ci"}, CI, "ci.yml runs something else: say so in CI.")
        # For every cloud, each in its folder, at the commit that is to be merged, and whatever the reason for the run.
        self.assertIn("        stack: [aws, azure, gcp]\n", text)
        self.assertIn("        working-directory: bootstrap/${{ matrix.stack }}\n", text)
        self.assertNotRegex(text, r"(?:exclude|include)\s*:|uses\s*:\s*[\"']?\./")
        self.assertEqual([name for name, job in jobs(text).items() if re.search(r"(?m)^ +ref\s*:", job)], ["blocked-terms"])
        self.assertNotRegex(text, r"""(?m)^ {6,}(?:- +)?["']?if["']?\s*:""", "A step with a condition may be left out.")

    def test_the_others_start_one_script_in_each_step(self):
        for file, text in self.texts.items():
            for name, job in jobs(text).items():
                if file == "ci.yml" or (file, name) in TELLS:
                    continue
                for one in commands(job):
                    with self.subTest(file=file, job=name):
                        self.assertRegex(one, r"\A(?:exec )?(?:bash|python3) [\w./-]+\.(?:sh|py)(?: [a-z0-9-]+)*\Z", "What a step does belongs into a script.")


class Required(unittest.TestCase):
    """The check that every pull request needs: GitHub counts a skipped one as passed, so it always runs and looks at all others."""

    def setUp(self):
        self.jobs = jobs((ROOT / ".github/workflows/ci.yml").read_text())
        self.job = self.jobs["ci"]
        self.needs = re.search(r"(?m)^    needs: \[(.*)\]$", self.job)[1].split(", ")

    def go(self, results, attempt="1"):
        (step,) = re.findall(r"(?m)^        run: \|\n((?:          .*\n|\n)+)", self.job)
        with tempfile.TemporaryDirectory() as folder:
            file = pathlib.Path(folder, "step.sh")
            file.write_text(re.sub(r"(?m)^          ", "", step))
            # As GitHub runs it.
            env = {"PATH": os.environ["PATH"], "RESULTS": results if isinstance(results, str) else json.dumps(results), "ATTEMPT": attempt}
            return subprocess.run(["bash", "-e", str(file)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60).returncode

    def ended(self, **other):
        return {name: {"result": "success", "outputs": {"attempt": "1"} if name == "blocked-terms" else {}} for name in self.needs} | {name.replace("_", "-"): value for name, value in other.items()}

    def test_it_always_runs_and_waits_for_every_other_job(self):
        self.assertRegex(self.job, r"(?m)^    if: \$\{\{ always\(\) \}\}$")
        self.assertEqual(sorted(self.needs), sorted(set(self.jobs) - {"ci"}))
        self.assertRegex(self.job, r"(?m)^          RESULTS: \$\{\{ toJSON\(needs\) \}\}\n          ATTEMPT: \$\{\{ github\.run_attempt \}\}$")
        self.assertEqual(self.job.count("run:"), 1)

    def test_it_is_green_only_if_all_of_them_are(self):
        self.assertEqual(self.go(self.ended()), 0)
        for name in self.needs:
            for result in ("failure", "cancelled", "skipped", ""):
                with self.subTest(job=name, result=result):
                    self.assertNotEqual(self.go(self.ended() | {name: {"result": result, "outputs": {"attempt": "1"}}}), 0)
            with self.subTest(missing=name):
                self.assertNotEqual(self.go({key: value for key, value in self.ended().items() if key != name}), 0)
        self.assertNotEqual(self.go(self.ended(more_of_them={"result": "success", "outputs": {}})), 0)
        # A result from before the title was edited.
        self.assertNotEqual(self.go(self.ended(), attempt="2"), 0)
        for nothing in ("", "{}", "[]", "null", "not json"):
            with self.subTest(nothing=nothing):
                self.assertNotEqual(self.go(nothing), 0)


# What the two test runners of the site run, as it stands in their settings.
VITEST = 'import { defineConfig } from "vitest/config";\n\nexport default defineConfig({ test: { include: ["packages/core/test/**/*.test.ts", "scripts/**/*.test.mjs", "pages/test/**/*.test.ts", "deploy/**/*.test.mjs"] } });\n'
PLAYWRIGHT = 'import { defineConfig } from "@playwright/test";\n\n// The tests use the Chrome that is already on this computer, and the site as it would be published.\nexport default defineConfig({\n  testDir: "e2e",\n  fullyParallel: true,\n  forbidOnly: true,\n  reporter: [["list"]],\n  use: { baseURL: "http://localhost:4330", channel: "chrome" },\n  webServer: { command: "npm run preview -w pages -- --port 4330 --ignore-lock", url: "http://localhost:4330", reuseExistingServer: false },\n});\n'
# What is built or installed, and no file of ours.
SKIP = {"node_modules", ".git", "__pycache__", ".terraform"}
BUILT = {"site/out", "site/pages/dist"}


def files():
    """Every file of the repo, as a path from its top, but for what is built or installed. Links are not followed."""
    for folder, folders, names in os.walk(ROOT):
        here = pathlib.Path(folder).relative_to(ROOT)
        folders[:] = sorted(name for name in folders if name not in SKIP and str(here / name) not in BUILT and not (name == "dist" and here.parent == pathlib.Path("site/packages")))
        yield from (here / name for name in sorted(names))


def pattern_of(glob):
    """A pattern of the test runner's settings, as a regular expression: ** is any number of folders, * a part of a name."""
    return re.compile("".join("(?:.*/)?" if part == "**/" else "[^/]*" if part == "*" else re.escape(part) for part in re.findall(r"\*\*/|\*|[^*]", glob)))



class Site(unittest.TestCase):
    """site/checks.sh starts npm, and npm starts what stands in these files."""

    def test_npm_stops_at_the_first_failure(self):
        for path in sorted((ROOT / "site").glob("*/**/package.json")) + [ROOT / "site/package.json"]:
            if "node_modules" in path.parts:
                continue
            for name, text in json.loads(path.read_text()).get("scripts", {}).items():
                with self.subTest(file=str(path.relative_to(ROOT)), script=name):
                    self.assertNotRegex(text, r"[|;]|(?<!&)&(?!&)|\b(?:true|exit)\b|--if-present|--pass")
        scripts = json.loads((ROOT / "site/package.json").read_text())["scripts"]
        self.assertEqual([scripts[name] for name in ("build", "check", "test", "e2e")], ["npm run build:recorders && npm run build -w pages", "npm run check -w pages", "vitest run", "playwright test"])

    def test_no_tests_and_one_test_are_not_all_tests(self):
        self.assertNotIn("passWithNoTests", (ROOT / "site/vitest.config.ts").read_text())
        self.assertIn("  forbidOnly: true,\n", (ROOT / "site/playwright.config.ts").read_text())

    def test_what_the_test_runners_run_stands_here_word_for_word(self):
        # One pattern less, or a filter, and a test stops running without a word. A change of these files has to say so here.
        self.assertEqual((ROOT / "site/vitest.config.ts").read_text(), VITEST)
        self.assertEqual((ROOT / "site/playwright.config.ts").read_text(), PLAYWRIGHT)
        settings = re.compile(r"(?:vitest|vite|playwright)\.(?:config|workspace)\.|vitest\.(?:workspace|projects)\b")
        found = sorted(str(path) for path in files() if settings.match(path.name))
        self.assertEqual(found, ["site/packages/recorder-react/vite.config.ts", "site/playwright.config.ts", "site/vitest.config.ts"])

    def test_every_test_file_is_found_by_its_runner(self):
        # A test file that no runner finds never runs, and nothing turns red. So each kind lies where its runner looks.
        vitest = [pattern_of(glob) for glob in re.findall(r'"([^"]+)"', VITEST[VITEST.index("include: ["):].split("]")[0])]
        stacks = {f"{stack}/tests" for stack in ("bootstrap/aws", "bootstrap/azure", "bootstrap/gcp", "site/infra/aws", "site/infra/azure")}
        found = []
        for path in files():
            if str(path) == "site/vitest.config.ts" or not any(re.search(r"test|spec|e2e", part, re.I) for part in path.parts):
                continue
            folder = str(path.parent)
            if path.suffix == ".py":
                runs = folder in ("bootstrap/scripts", ".github/scripts", "bootstrap/mac", "site/deploy") and fnmatch.fnmatchcase(path.name, "test*.py")
            elif path.suffix == ".hcl":
                runs = folder in stacks and path.name.endswith(".tftest.hcl")
            elif folder.startswith("site/e2e"):
                runs = folder == "site/e2e" and path.name.endswith(".spec.ts")
            else:
                runs = path.parts[0] == "site" and any(pattern.fullmatch(str(path.relative_to("site"))) for pattern in vitest)
            with self.subTest(file=str(path)):
                self.assertTrue(runs, "no runner finds it")
            found.append(path)
        self.assertGreater(len(found), 30)


if __name__ == "__main__":
    unittest.main()
