// Runs the function that stands in front of the storage on AWS, as it would run there.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(new URL("../infra/aws/edge.js", import.meta.url), "utf8");
const ADDRESSES = ["/", "/proof/", "/es/", "/es/proof/", "/favicon.svg", "/_astro/Page.gPBELLEX.css"];
const code = SOURCE.replace("[/* addresses */]", `[${ADDRESSES.map((address) => JSON.stringify(address)).join(", ")}]`);

function ask(uri) {
  const world = vm.createContext({ event: { version: "1.0", request: { method: "GET", uri, querystring: {}, headers: {}, cookies: {} } } });
  return JSON.parse(vm.runInContext(`${code}\nJSON.stringify(handler(event))`, world));
}

describe("the function in front of the storage", () => {
  it("has one place for the addresses", () => {
    expect(SOURCE.split("[/* addresses */]").length).toBe(2);
  });

  it("finds the page of a folder, and leaves files alone", () => {
    expect(ask("/").uri).toBe("/index.html");
    expect(ask("/es/proof/").uri).toBe("/es/proof/index.html");
    expect(ask("/favicon.svg").uri).toBe("/favicon.svg");
    expect(ask("/_astro/Page.gPBELLEX.css").uri).toBe("/_astro/Page.gPBELLEX.css");
  });

  it("sends every page to its one address", () => {
    for (const [asked, to] of [["/proof", "/proof/"], ["/es", "/es/"], ["/index.html", "/"], ["/es/proof/index.html", "/es/proof/"]]) {
      expect(ask(asked)).toEqual({ statusCode: 301, statusDescription: "Moved Permanently", headers: { location: { value: to } } });
    }
  });

  it("turns whatever does not exist into the same address", () => {
    const made = ["/nowhere", "/nowhere/", "/proof/x", "/proof//", "//", "/favicon.svg/", "/FAVICON.svg", "/favicon.svg%00", "/%70roof/", "/es/../proof/", "/.git/config", "/404.html", "/-", "/index.html/index.html", "/nowhere/index.html", "//evil.example/", "/proof/?x", "/__proto__", "constructor"];
    for (const asked of made) expect(ask(asked), asked).toMatchObject({ uri: "/-" });
    for (let i = 0; i < 1000; i++) expect(ask(`/${Math.random().toString(36).slice(2)}`).uri).toBe("/-");
  });

  it("only ever sends a visitor to an address of the site", () => {
    for (const asked of ["//evil.example", "/\\evil.example", "https://evil.example", "/es/index.html/../..//evil.example/index.html"]) expect(ask(asked)).not.toHaveProperty("statusCode");
  });
});
