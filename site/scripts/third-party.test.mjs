import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { SERVED, licences } from "./third-party.mjs";

const SITE = fileURLToPath(new URL("../", import.meta.url));
const read = (path) => readFileSync(join(SITE, path), "utf8");
/** Where a package has its licence. */
const licenceOf = (name) => `node_modules/${name}/${readdirSync(join(SITE, "node_modules", name)).find((file) => /^licen[cs]e(?:\.|$)/i.test(file))}`;
const LINE = `\n${"-".repeat(72)}\n\n`;

describe("the licences of what others wrote", () => {
  it("are those of every package in the two builds, and of the fonts", () => {
    expect(SERVED).toEqual(["react", "react-dom", "scheduler", "@angular/common", "tslib", "@angular/compiler", "@angular/core", "@angular/elements", "@angular/platform-browser", "rxjs", "@fontsource-variable/atkinson-hyperlegible-mono", "@fontsource-variable/atkinson-hyperlegible-next", "vite", "rolldown", "esbuild"]);
    // The core has none. Of each, but for the builders, there is one copy only, so the version is the one that is built with.
    const { packages } = JSON.parse(read("package-lock.json"));
    expect(packages["packages/core"].dependencies).toBeUndefined();
    for (const name of SERVED.slice(0, -3)) expect(Object.keys(packages).filter((path) => path.endsWith(`node_modules/${name}`)), name).toEqual([`node_modules/${name}`]);
  });

  it("are each the whole text that the package brings, under its name and version", () => {
    const [first, ...parts] = licences().split(LINE);
    expect(first).toBe("Packages of others that this site serves, each with its licence.\n");
    expect(parts).toHaveLength(SERVED.length);
    const words = { MIT: "The above copyright notice and this permission notice shall be included", "Apache-2.0": "Apache License", "0BSD": "Permission to use, copy, modify, and/or distribute this software", "OFL-1.1": "SIL OPEN FONT LICENSE Version 1.1" };
    for (const [i, name] of SERVED.entries()) {
      const { version, license } = JSON.parse(read(`node_modules/${name}/package.json`));
      const piece = name === "react-dom" ? "In it: Modernizr 3.0.0pre (Custom Build) | MIT\n\n" : "";
      expect(parts[i], name).toBe(`${name} ${version}\n\n${piece}${read(licenceOf(name)).split("\r").join("").split("# Licenses of bundled")[0].trimEnd()}\n`);
      expect(parts[i].includes(words[license]), `${name}: ${license}`).toBe(true);
    }
  });

  it("name the one piece that React's code says it has from elsewhere", () => {
    const said = ["react/cjs/react.production.js", "react/cjs/react-jsx-runtime.production.js", "react-dom/cjs/react-dom.production.js", "react-dom/cjs/react-dom-client.production.js", "scheduler/cjs/scheduler.production.js"].flatMap((file) => read(`node_modules/${file}`).match(/^.*\| *(?:MIT|BSD|Apache).*$/gm) ?? []);
    expect(said.map((line) => line.trim())).toEqual(["Modernizr 3.0.0pre (Custom Build) | MIT"]);
  });

  it("stop the build if one is missing", () => {
    expect(() => licences(["no-such-package"])).toThrow(/no licence of no-such-package was found/);
  });

  it("are served beside the builds, and each build says where", () => {
    const folder = mkdtempSync(join(tmpdir(), "builds-"));
    const put = (path, text) => {
      mkdirSync(dirname(join(folder, path)), { recursive: true });
      writeFileSync(join(folder, path), text);
    };
    try {
      for (const path of ["scripts/collect-builds.mjs", "scripts/third-party.mjs", "package-lock.json"]) put(path, read(path));
      for (const name of SERVED) for (const path of [`node_modules/${name}/package.json`, licenceOf(name)]) put(path, read(path));
      // Long enough that another level of compression has another size, and not only ASCII.
      const built = { "angular/main.js": `"‹";${Array.from({ length: 4000 }, (_, i) => `f(${(i * 7919) % 10007})`).join(";")}`, "react/main.js": "console.log('›');\n", "react/more.js": "more();\n", "react/style.css": "a{}", "react/odd.js": Buffer.from([47, 47, 255, 254, 128, 13, 10]), "react/font.woff2": Buffer.from([0, 255, 254, 128, 10, 13]) };
      for (const [name, body] of Object.entries(built)) put(`packages/recorder-${name.replace("/", "/dist/")}`, body);
      for (const other of ["main.js.map", "stats.json", "3rdpartylicenses.txt"]) put(`packages/recorder-angular/dist/${other}`, "{}");
      const collect = () => execFileSync(process.execPath, [join(folder, "scripts/collect-builds.mjs")], { cwd: folder, stdio: "pipe" });
      collect();
      const there = join(folder, "pages/public/builds");
      const list = () => readdirSync(there, { recursive: true, withFileTypes: true }).filter((one) => one.isFile()).map((one) => join(one.parentPath, one.name).slice(there.length + 1)).toSorted();
      const expected = [...Object.keys(built), "third-party.txt"].toSorted();
      expect(list()).toEqual(expected);
      expect(readFileSync(join(there, "third-party.txt"), "utf8")).toBe(licences());
      const where = (name) => (name.endsWith(".js") ? "/*! Licences of what others wrote: /builds/third-party.txt */\n" : "");
      for (const [name, body] of Object.entries(built)) expect(readFileSync(join(there, name)).equals(Buffer.concat([Buffer.from(where(name)), Buffer.from(body)])), name).toBe(true);
      const size = (...names) => names.reduce((sum, name) => sum + gzipSync(built[name], { level: 9 }).length, 0);
      expect(JSON.parse(readFileSync(join(folder, "pages/src/data/builds.json"), "utf8"))).toEqual({ react: size("react/main.js", "react/more.js", "react/odd.js"), angular: size("angular/main.js") });
      // Once more, and nothing is left from before.
      put("pages/public/builds/old.js", "old();");
      collect();
      expect(list()).toEqual(expected);
      // And not at all if one of them has not been built.
      rmSync(join(folder, "packages/recorder-angular/dist/main.js"));
      put("packages/recorder-angular/dist/other.js", "other();");
      expect(collect).toThrow(/recorder-angular has not been built/);
    } finally {
      rmSync(folder, { recursive: true });
    }
  });
});
