// Writes files.txt into a folder: every other file in it with its SHA-256, in the form that sha256sum reads. It is served
// with the site, so anyone can compare what they get with what was built, and a deploy can tell what is there now.
//
//   node scripts/list-files.mjs out
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, sep } from "node:path";

const folder = process.argv[2];
if (!folder) throw new Error("Which folder?");
const names = readdirSync(folder, { recursive: true, withFileTypes: true })
  .filter((entry) => entry.isFile())
  .map((entry) => join(entry.parentPath, entry.name).slice(join(folder, sep).length).split(sep).join("/"))
  .filter((name) => name !== "files.txt")
  .sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
const lines = names.map((name) => `${createHash("sha256").update(readFileSync(join(folder, name))).digest("hex")}  ${name}\n`);
writeFileSync(join(folder, "files.txt"), lines.join(""));
console.log(`${names.length} files, and the list of them`);
