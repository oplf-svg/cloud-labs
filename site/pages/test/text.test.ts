import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { CLAIMS } from "../src/text/claims.ts";
import { NOTES } from "../src/text/notes.ts";
import { FIRST, LATEST, RUNS, WORDS, recorderData, toMark, wrongIn } from "../src/text/recordings.ts";
import { DOORS, LANGS, STATUSES } from "../src/text/types.ts";

/** Every piece of text, with where it is. */
function* texts(value: unknown, path = ""): Generator<[string, string]> {
  if (typeof value === "string") yield [path, value];
  else if (Array.isArray(value)) for (const [i, item] of value.entries()) yield* texts(item, `${path}[${i}]`);
  else if (value && typeof value === "object") for (const [key, item] of Object.entries(value)) yield* texts(item, `${path}.${key}`);
}

describe("words", () => {
  it("has no empty text in any language", () => {
    for (const lang of LANGS) for (const [path, text] of texts(WORDS[lang])) expect(text.trim(), `${lang}${path}`).not.toBe("");
    for (const [path, text] of texts([CLAIMS, NOTES])) expect(text.trim(), path).not.toBe("");
  });

  it("keeps the same blanks to fill in, in every language", () => {
    const blanks = (text: string) => [...text.matchAll(/\{\w+\}/g)].map((hit) => hit[0]).toSorted();
    for (const lang of LANGS) {
      expect(blanks(WORDS[lang].recorder.measured)).toEqual(["{kb}", "{ms}"]);
      expect(blanks(WORDS[lang].recorder.player.reading)).toEqual(["{lane}", "{n}", "{result}", "{time}", "{total}", "{what}"]);
    }
  });

  it("is translated, not copied", () => {
    for (const { id, claim } of CLAIMS) expect(new Set(Object.values(claim)).size, id).toBe(LANGS.length);
    for (const { slug, title, silent, now } of NOTES) for (const text of [title, silent, now]) expect(new Set(Object.values(text)).size, slug).toBe(LANGS.length);
  });

  it("names no person, company, account or address", () => {
    const all = [...texts([CLAIMS, NOTES, WORDS]), ...LANGS.flatMap((lang) => [...texts(recorderData(lang))])];
    for (const [path, text] of all) {
      expect(text, path).not.toMatch(/[\w.]+@[\w-]+\.\w+/);
      expect(text, path).not.toMatch(/\b\d{12}\b(?!\/)|arn:aws|tfstate-?[0-9a-f]{8}|[0-9a-f]{8}-[0-9a-f]{4}-/);
    }
  });
});

describe("claims", () => {
  it("has evidence for what is proven, and none for what is not", () => {
    for (const { id, status, evidence } of CLAIMS) {
      if (status === "proven") expect(evidence.length, id).toBeGreaterThan(0);
      else expect(evidence, id).toEqual([]);
      for (const { href } of evidence) expect(href, id).toMatch(/^https:\/\/github\.com\/oplf-svg\//);
    }
  });

  it("points to files that exist", () => {
    const here = "https://github.com/oplf-svg/cloud-labs/blob/main/";
    const files = CLAIMS.flatMap((claim) => claim.evidence).map((link) => link.href).filter((href) => href.startsWith(here));
    expect(files.length).toBeGreaterThan(10);
    for (const href of files) expect(existsSync(new URL(`../../../${href.slice(here.length)}`, import.meta.url)), href).toBe(true);
  });

  it("has a claim behind every door, and no two with the same id", () => {
    for (const door of DOORS) expect(CLAIMS.filter((claim) => claim.doors.includes(door)).length, door).toBeGreaterThan(0);
    expect(new Set(CLAIMS.map((claim) => claim.id)).size).toBe(CLAIMS.length);
    expect(new Set(CLAIMS.map((claim) => claim.status))).toEqual(new Set(STATUSES));
  });

  it("does not call the read-only sign-in proven if the latest run was not as intended", () => {
    expect(wrongIn(LATEST.checks)).toBe(0);
  });
});

describe("recordings", () => {
  it("starts with a real run and marks the example as one", () => {
    for (const lang of LANGS) {
      const { recordings } = recorderData(lang);
      expect(recordings.map(({ id, real }) => [id, real])).toEqual([["latest", true], ["first", true], ["day", false], ["attack", false]]);
      for (const { real, url, unseen } of recordings) expect([url !== undefined, unseen === undefined]).toEqual([real, real]);
      for (const { marks, unseen, lanes, length } of recordings) {
        for (const mark of [...marks, ...(unseen ?? [])]) {
          expect(lanes.map((lane) => lane.id)).toContain(mark.lane);
          expect(mark.at).toBeLessThanOrEqual(length);
        }
      }
    }
  });

  it("shows the failed check of the first run as it was", () => {
    const wrong = FIRST.checks.filter((check) => !check.ok).map((check) => toMark(check, WORDS.en));
    expect(wrong).toEqual([expect.objectContaining({ kind: "wrong", what: "read the state of webhook-platform", result: "Let in, but it should be refused" })]);
  });

  it("never turns a check that was not as intended into a good mark", () => {
    for (const run of RUNS) for (const check of run.checks) expect(toMark(check, WORDS.en).kind === "wrong").toBe(!check.ok);
  });
});
