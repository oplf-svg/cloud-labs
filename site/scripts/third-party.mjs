// The licences of what others wrote and this site serves: of the packages in the two builds, with all that they need, of the
// fonts, and of the builders, which leave code of their own in what they build.
import { existsSync, readFileSync } from "node:fs";

const root = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");
const { packages } = JSON.parse(read("package-lock.json"));

function found() {
  const names = new Set();
  const add = (name) => {
    if (names.has(name)) return;
    names.add(name);
    Object.keys(packages[`node_modules/${name}`].dependencies ?? {}).forEach(add);
  };
  for (const part of ["recorder-react", "recorder-angular"]) Object.keys(packages[`packages/${part}`].dependencies).forEach(add);
  Object.keys(packages.pages.dependencies).filter((name) => name.startsWith("@fontsource")).forEach(add);
  return [...names, "vite", "rolldown", "esbuild"];
}
export const SERVED = found();

/** What a package says in its code of a piece that it has from elsewhere. */
const PIECES = { "react-dom": "In it: Modernizr 3.0.0pre (Custom Build) | MIT\n\n" };

/** All of them in one text. Stops if one is missing. */
export function licences(names = SERVED) {
  const parts = names.map((name) => {
    const path = ["LICENSE", "LICENSE.txt", "LICENSE.md"].map((file) => `node_modules/${name}/${file}`).find((one) => existsSync(new URL(one, root)));
    if (!path) throw new Error(`no licence of ${name} was found`);
    const { version } = JSON.parse(read(`node_modules/${name}/package.json`));
    // Vite goes on with what it is made of itself.
    const [text] = read(path).replaceAll("\r\n", "\n").split("\n# Licenses of bundled dependencies");
    return `${name} ${version}\n\n${PIECES[name] ?? ""}${text.trimEnd()}\n`;
  });
  return ["Packages of others that this site serves, each with its licence.\n", ...parts].join(`\n${"-".repeat(72)}\n\n`);
}
