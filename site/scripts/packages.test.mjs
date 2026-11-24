import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const read = (name) => readFileSync(new URL(`../${name}`, import.meta.url), "utf8");
const { packages } = JSON.parse(read("package-lock.json"));
const installed = Object.entries(packages).filter(([path, info]) => path.includes("node_modules/") && !info.link);

describe("packages", () => {
  it("come from npm, with a fingerprint", () => {
    expect(installed.length).toBeGreaterThan(100);
    for (const [path, { resolved, integrity }] of installed) {
      expect(resolved, path).toMatch(/^https:\/\/registry\.npmjs\.org\//);
      expect(integrity, path).toMatch(/^sha512-/);
    }
  });

  it("are pinned to one version", () => {
    for (const name of ["package.json", "pages/package.json", "packages/core/package.json", "packages/recorder-react/package.json", "packages/recorder-angular/package.json"]) {
      const { dependencies = {}, devDependencies = {} } = JSON.parse(read(name));
      for (const [dependency, version] of Object.entries({ ...dependencies, ...devDependencies })) expect(version, `${name} ${dependency}`).toMatch(/^\d+\.\d+\.\d+$/);
    }
  });

  it("cannot run anything while they are installed, and are not brand new", () => {
    const settings = read(".npmrc").split("\n");
    expect(settings).toContain("ignore-scripts=true");
    expect(settings).toContain("min-release-age=7");
  });

  it("stay off the page: the site has only its own code and the two builds", () => {
    const { dependencies } = JSON.parse(read("pages/package.json"));
    expect(Object.keys(dependencies).toSorted()).toEqual(["@fontsource-variable/atkinson-hyperlegible-mono", "@fontsource-variable/atkinson-hyperlegible-next", "astro", "cookie"]);
  });
});
