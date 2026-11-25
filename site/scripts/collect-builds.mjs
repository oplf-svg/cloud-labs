// Puts both builds where the site serves them, and measures what a reader has to download.
import { cpSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { licences } from "./third-party.mjs";

const root = new URL("../", import.meta.url);
const target = new URL("pages/public/builds/", root);
rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });

const where = Buffer.from("/*! Licences of what others wrote: /builds/third-party.txt */\n");
const sizes = {};
for (const name of ["react", "angular"]) {
  const from = new URL(`packages/recorder-${name}/dist/`, root);
  const files = readdirSync(from).filter((file) => file.endsWith(".js"));
  if (!files.includes("main.js")) throw new Error(`recorder-${name} has not been built`);
  cpSync(from, new URL(`${name}/`, target), { recursive: true, filter: (file) => !/\.(json|txt|map)$/.test(file) });
  for (const file of files) writeFileSync(new URL(`${name}/${file}`, target), Buffer.concat([where, readFileSync(new URL(file, from))]));
  sizes[name] = files.reduce((sum, file) => sum + gzipSync(readFileSync(new URL(file, from)), { level: 9 }).length, 0);
}
writeFileSync(new URL("third-party.txt", target), licences());
// Nothing in that folder is kept in the repo, so in a fresh copy it is not there.
mkdirSync(new URL("pages/src/data/", root), { recursive: true });
writeFileSync(new URL("pages/src/data/builds.json", root), JSON.stringify(sizes, null, 2) + "\n");
console.log(Object.entries(sizes).map(([name, size]) => `${name} ${(size / 1024).toFixed(1)} KB compressed`).join(", "));
