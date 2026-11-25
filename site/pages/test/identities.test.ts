import { readFileSync } from "node:fs";
import { expect, it } from "vitest";

// cloud-labs has one identity more on each cloud than the other projects, the one that reads costs. So no text counts them.
const COUNTED = /(?<!\p{L})(?:two|three|four|five|dos|tres|cuatro|cinco|deux|trois|quatre|cinq|\d+)(?:\s+\p{L}+)?\s+(?:identities|identidades|identités)/iu;
const read = (path: string) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");

it.each(["en", "es", "fr"])("says whose the identities are (%s)", (lang) => {
  expect(read(`pages/src/text/${lang}.ts`)).toMatch(/(?:identities|identidades|identités) (?:on each|en cada|sur chaque)/);
});

it.each(["pages/src/text/en.ts", "pages/src/text/es.ts", "pages/src/text/fr.ts", "pages/src/text/claims.ts", "pages/src/text/notes.ts", "README.md"])("does not count them in %s", (path) => {
  expect(read(path)).not.toMatch(COUNTED);
});

it.each(["three identities", "three separate identities", "cinco identidades", "trois petites identités", "3 identities"])("would notice: %s", (said) => {
  expect(said).toMatch(COUNTED);
});
