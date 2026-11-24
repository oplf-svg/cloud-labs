// Turns the public logs of the sign-in test into recordings.
//
//   node scripts/import-runs.mjs
//
// It needs gh, signed in to any account: the logs are public, but GitHub wants a sign-in to download them. Only the test's
// own words are taken. A line that looks like anything else stops the import, so nothing else can reach the site.
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const SOURCE = "oplf-svg/cloud-labs";
const WORKFLOW = "sign-in.yml";
export const LANES = [
  { id: "aws", name: "AWS" },
  { id: "azure", name: "Azure" },
  { id: "gcp", name: "Google Cloud" },
];

// Every sentence that the test can say. A log is written by a machine that others may try to steer, so nothing else is
// let through, however harmless it looks. A new check needs a new line here, and a person to add it.
const REPO = "(?:webhook-platform|k8s-platform-lab|ai-ops-agent|event-pipeline-lab|cloud-labs)";
const SENTENCES = [
  `sign in as (?:id-)?gha-${REPO}-plan`,
  `sign in as the plan of ${REPO}`,
  "sign in to the state storage",
  `become gha-${REPO}-(?:plan|apply|destroy)`,
  "become a service account",
  "be that role, in the expected account",
  "be in the expected project",
  "use London",
  "create (?:a network|something)",
  "prepare a deployment",
  "change who has access",
  "read the project(?: of the bootstrap)?",
  `read (?:its own resource group|the resource group of (?:${REPO}|the bootstrap))`,
  `(?:read|list) (?:its own state|the state of (?:${REPO}|the bootstrap))`,
  "write its own state",
];
export const WHAT = new RegExp(`^(?:${SENTENCES.join("|")})$`);
const GOT = new Set(["allowed", "denied", "yes", "nothing there"]);
const LINE = /^(\S+)\t[^\t]*\t(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z) (ok  |FAIL) (.+)$/;

/** Reads one log. Returns the checks in the order of their time, with milliseconds since the first. */
export function parseLog(log) {
  const checks = [];
  for (const line of log.split("\n")) {
    const hit = LINE.exec(line.trimEnd());
    if (!hit) continue;
    const [, lane, time, verdict, words] = hit;
    // The first line of each job repeats the token's subject, which holds GitHub's ids.
    if (words.startsWith("GitHub's subject is ")) continue;
    if (!LANES.some((known) => known.id === lane)) throw new Error(`unknown lane ${lane}`);
    const at = words.lastIndexOf(": ");
    const what = words.slice(0, at);
    const [got, wanted] = words.slice(at + 2).split(", should be ");
    const ok = verdict === "ok  ";
    if (!WHAT.test(what) || !GOT.has(got) || ok !== (wanted === undefined) || (!ok && !GOT.has(wanted))) {
      throw new Error("a line of the log is not in the expected form, so nothing was imported");
    }
    checks.push({ lane, time: Date.parse(time), what, got, ok, ...(ok ? {} : { wanted }) });
  }
  if (checks.length === 0) throw new Error("no checks found");
  checks.sort((a, b) => a.time - b.time);
  const start = checks[0].time;
  return checks.map(({ time, ...check }) => ({ at: time - start, ...check }));
}

export function toRun(info, log) {
  const checks = parseLog(log);
  return {
    number: info.number,
    url: info.url,
    commit: info.headSha.slice(0, 7),
    date: info.createdAt,
    checks,
    lanes: LANES.filter((lane) => checks.some((check) => check.lane === lane.id)).map((lane) => ({
      ...lane,
      url: info.jobs.find((job) => job.name === lane.id)?.url ?? info.url,
    })),
  };
}

const gh = (...args) => execFileSync("gh", args, { encoding: "utf8", maxBuffer: 1 << 26 });

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const fields = "databaseId,number,url,headSha,createdAt,status,conclusion";
  const list = JSON.parse(gh("run", "list", "--repo", SOURCE, "--workflow", WORKFLOW, "--limit", "20", "--json", fields));
  const runs = list
    .filter((run) => run.status === "completed" && ["success", "failure"].includes(run.conclusion))
    .sort((a, b) => a.number - b.number)
    .map((run) => {
      const { jobs } = JSON.parse(gh("run", "view", `${run.databaseId}`, "--repo", SOURCE, "--json", "jobs"));
      return toRun({ ...run, jobs }, gh("run", "view", `${run.databaseId}`, "--repo", SOURCE, "--log"));
    });
  const file = new URL("../packages/core/data/runs.json", import.meta.url);
  writeFileSync(file, JSON.stringify({ repo: SOURCE, workflow: WORKFLOW, runs }, null, 1) + "\n");
  for (const run of runs) {
    console.log(`run ${run.number} ${run.commit}: ${run.checks.filter((c) => c.ok).length} of ${run.checks.length} as intended`);
  }
}
