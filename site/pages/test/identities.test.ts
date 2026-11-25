import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { WORDS } from "../src/text/recordings.ts";
import { LANGS, type Lang } from "../src/text/types.ts";

// cloud-labs has one identity more on each cloud than the other projects, the one that reads costs. So no text counts them.
const COUNTED = /(?<!\p{L})(?:two|three|four|five|dos|tres|cuatro|cinco|deux|trois|quatre|cinq|\d+)(?:\s+\p{L}+)?\s+(?:identities|identidades|identités)/iu;
// How long something lasts, and what may be said of it: of GitHub's token alone, which is not one of the identities.
const LASTS = /(?<!\p{L})(?:lasts|lasting|lasted|last(?=\s+(?:for\s+)?(?:\p{L}+\s+)?(?:minutes?|hours?|days?))|valid\s+for|expires?|duran?|durar|durará|caducan?|dure(?:nt|ra)?|expirent?|expire)(?!\p{L})/iu;
const TOKENS = ["GitHub signs in to each cloud with a token that lasts minutes", "GitHub inicia sesión en cada nube con un token que dura minutos", "GitHub se connecte à chaque cloud avec un jeton qui dure quelques minutes"];
const read = (path: string) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");

it.each(["en", "es", "fr"])("says whose the identities are (%s)", (lang) => {
  expect(read(`pages/src/text/${lang}.ts`)).toMatch(/(?:identities|identidades|identités) (?:on each|en cada|sur chaque)/);
});

it.each(["pages/src/text/en.ts", "pages/src/text/es.ts", "pages/src/text/fr.ts", "pages/src/text/claims.ts", "pages/src/text/notes.ts", "README.md"])("does not count them in %s", (path) => {
  expect(read(path)).not.toMatch(COUNTED);
});

it("says how long something lasts of GitHub's token only", () => {
  const texts = ["en", "es", "fr", "claims", "notes"].map((name) => read(`pages/src/text/${name}.ts`)).join("\n");
  expect(texts.split(/[.":;\n]/).map((sentence) => sentence.trim()).filter((sentence) => LASTS.test(sentence))).toEqual(TOKENS);
});

it.each(["One identity has one job and lasts minutes", "It lasts minutes", "Identities last minutes", "they last for some hours", "valid for minutes", "expires after an hour", "dura minutos una identidad", "caduca en minutos", "Une identité a un seul travail et dure quelques minutes", "elle dure une heure"])("would notice: %s", (said) => {
  expect(said).toMatch(LASTS);
});

it("says as much in every language of the rules and of the identities", () => {
  const states = (lang: Lang) => [WORDS[lang].how.agents.rules, WORDS[lang].how.keys.tiers].map((list) => list.map(({ state }) => state));
  for (const lang of LANGS) expect(states(lang), lang).toEqual([["proven", "proven", "planned", "planned", "planned", "planned", "planned"], ["tested", "used", "tested"]]);
});

it.each(["three identities", "three separate identities", "cinco identidades", "trois petites identités", "3 identities"])("would notice: %s", (said) => {
  expect(said).toMatch(COUNTED);
});
