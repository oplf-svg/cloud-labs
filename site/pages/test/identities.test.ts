import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { WORDS } from "../src/text/recordings.ts";
import { LANGS, type Lang } from "../src/text/types.ts";

// cloud-labs has one identity more on each cloud than the other projects, the one that reads costs. So no text counts them.
const COUNTED = /(?<!\p{L})(?:two|three|four|five|dos|tres|cuatro|cinco|deux|trois|quatre|cinq|\d+)(?:\s+\p{L}+)?\s+(?:identities|identidades|identités)/iu;
// How long something lasts. On AWS a session may last an hour, and GitHub's token minutes.
const LASTS = /(?<!\p{L})(?:lasts|lasting|lasted|last(?=\s+(?:for\s+)?(?:\p{L}+\s+)?(?:minutes?|hours?|days?))|valid\s+for|expires?|duran?|durar|durará|caducan?|dure(?:nt|ra)?|expirent?|expire)(?!\p{L})/iu;
// The README of the bootstrap says where a right is wider than the job.
const NEVER = /another['’]s job|el trabajo de otra|le travail d['’]une autre|refused the rest|se le niega el resto|le reste lui est refusé|hand out|repartir permisos|distribuer de droits|One identity has one job|tiene un solo trabajo|a un seul travail/iu;
const TEXTS = ["en", "es", "fr", "claims", "notes"];
const read = (path: string) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");

it.each(["en", "es", "fr"])("says whose the identities are (%s)", (lang) => {
  expect(read(`pages/src/text/${lang}.ts`)).toMatch(/(?:identities|identidades|identités) (?:on each|en cada|sur chaque)/);
});

it.each(["pages/src/text/en.ts", "pages/src/text/es.ts", "pages/src/text/fr.ts", "pages/src/text/claims.ts", "pages/src/text/notes.ts", "README.md"])("does not count them in %s", (path) => {
  expect(read(path)).not.toMatch(COUNTED);
});

it.each(TEXTS)("says of nothing how long it lasts (%s)", (name) => {
  expect(read(`pages/src/text/${name}.ts`)).not.toMatch(LASTS);
});

it.each(TEXTS)("does not say that a right is no wider than the job (%s)", (name) => {
  expect(read(`pages/src/text/${name}.ts`)).not.toMatch(NEVER);
});

it.each(["none of them can do another's job", "ninguna puede hacer el trabajo de otra", "aucune ne peut faire le travail d’une autre", "is refused the rest", "se le niega el resto", "le reste lui est refusé", "cannot hand out rights", "no puede repartir permisos", "ne peut pas distribuer de droits", "One identity has one job", "Una identidad tiene un solo trabajo", "Une identité a un seul travail"])("would notice: %s", (said) => {
  expect(said).toMatch(NEVER);
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
