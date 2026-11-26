import { readFileSync, readdirSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { CLAIMS } from "../src/text/claims.ts";
import { NOTES } from "../src/text/notes.ts";
import { day } from "../src/text/paths.ts";
import { ALL_RUNS, LATEST, RUNS, WORDS, aboutLatest, newerRuns, recorderData, runName, runsName, scoreTitle, wrongIn } from "../src/text/recordings.ts";
import { LANGS, STATUSES } from "../src/text/types.ts";

// A run that is called the latest, or a list that is called every run, becomes wrong without a word as soon as a newer run
// comes. So the site names the runs that it shows by their numbers and days.
const NEWEST = /(?<!\p{L})(?:latest|newest|most[\s-]+recent|last|últim[oa]s?|más\s+recientes?|recientes?|derni(?:er|ère)s?|plus\s+récente?s?|récente?s?)(?!\p{L})/iu;
const EVERY = /(?<!\p{L})(?:all|every|each)\s+(?:[\p{L}-]+\s+){0,3}runs?(?!\p{L})|(?<!\p{L})(?:tod[ao]s\s+(?:l[ao]s\s+)?|cada\s+)(?:[\p{L}-]+\s+){0,3}ejecuci(?:ón|ones)(?!\p{L})|(?<!\p{L})(?:tou(?:te)?s\s+(?:les\s+)?|chaque\s+)(?:[\p{L}-]+\s+){0,3}exécutions?(?!\p{L})/iu;
// What may say "last": the last item in stock, which is no run.
const ITEM = /last item|último artículo|dernier article/giu;

// What a function is given, so that each of its branches says something: no, one and two of something, and counts of each stage.
const counts = (n: number) => Object.fromEntries(STATUSES.map((status) => [status, n]));
const GIVEN: unknown[][] = [[0, 0, "x", "x"], [1, 1, "x", "x"], [2, 2, "x", "x"], ["x", "x", "x", "x"], [counts(0)], [counts(1)], [counts(2)]];

/** Every piece of text in a value, also what each of its functions says with each of GIVEN. Ids are not shown. */
function said(value: unknown, called = { count: 0 }): string[] {
  if (typeof value === "string") return [value];
  if (typeof value === "function") {
    called.count += 1;
    return GIVEN.flatMap((given) => {
      try {
        return said(value(...given), called);
      } catch {
        return [];
      }
    });
  }
  if (Array.isArray(value)) return value.flatMap((item) => said(item, called));
  if (value && typeof value === "object") return Object.entries(value).flatMap(([key, item]) => (key === "id" ? [] : said(item, called)));
  return [];
}

const SAID = {
  en: ["Sign-in run 12, January 2, 2030, on 3 clouds: 2 checks, no wrong answer.", "Sign-in run 12, January 2, 2030, cloud by cloud", "Sign-in runs 3 to 12", "Runs after number 12 may not be here yet."],
  es: ["Ejecución 12 del inicio de sesión, 2 de enero de 2030, en 3 nubes: 2 comprobaciones, ninguna respuesta equivocada.", "Ejecución 12 del inicio de sesión, 2 de enero de 2030, nube por nube", "Ejecuciones 3 a 12 del inicio de sesión", "Puede que las ejecuciones posteriores a la 12 todavía no estén aquí."],
  fr: ["Exécution 12 de la connexion, 2 janvier 2030, sur 3 clouds : 2 contrôles, aucune mauvaise réponse.", "Exécution 12 de la connexion, 2 janvier 2030, cloud par cloud", "Exécutions 3 à 12 de la connexion", "Les exécutions après la 12 ne sont peut-être pas encore ici."],
};

const PAGES = new URL("../src/", import.meta.url);
const read = (name: string) => readFileSync(new URL(name, PAGES), "utf8");
/** The code of an Astro file: its script at the top, and what stands in braces. */
function code(text: string) {
  const top = text.match(/^---\n[\s\S]*?\n---\n/)?.[0] ?? "";
  const parts = [top];
  for (let i = top.length, depth = 0, start = 0; i < text.length; i += 1) {
    if (text[i] === "{" && depth++ === 0) start = i + 1;
    else if (text[i] === "}" && depth > 0 && --depth === 0) parts.push(text.slice(start, i));
  }
  return parts.join("\n");
}
/** The strings that an Astro file writes in its code. */
const literals = (text: string) => [...code(text).matchAll(/"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`/g)].map((hit) => hit[1] ?? hit[2] ?? hit[3] ?? "");
/** What an Astro file says itself: without its script at the top and without what stands in braces. */
function own(text: string) {
  let rest = text.replace(/^---\n[\s\S]*?\n---\n/, "");
  for (let before = ""; before !== rest; ) [before, rest] = [rest, rest.replace(/\{[^{}]*\}/g, " ")];
  return rest;
}

describe("the runs that the site shows", () => {
  it.each(LANGS)("are named by their numbers and days (%s)", (lang) => {
    // Other runs, of another day: what is said follows them, word for word.
    const other = { ...LATEST, number: 12, date: "2030-01-02T12:00:00Z", checks: LATEST.checks.slice(0, 2) };
    const first = { ...RUNS[0]!, number: 3 };
    expect([aboutLatest(lang, other), scoreTitle(lang, other), runsName(lang, [first, other]), newerRuns(lang, [first, other])]).toEqual(SAID[lang]);
    // And the ones on file.
    const about = recorderData(lang).recordings.find(({ id }) => id === "latest")!.about;
    expect(about).toBe(aboutLatest(lang));
    for (const part of [runName(lang), day(lang, LATEST.date), WORDS[lang].score.verdict(LATEST.checks.length, wrongIn(LATEST.checks))]) expect(about).toContain(part);
    expect(scoreTitle(lang)).toBe(WORDS[lang].score.title(runName(lang)));
    expect(runsName(lang)).toBe(WORDS[lang].recorder.runs(RUNS[0]!.number, LATEST.number));
    expect(newerRuns(lang)).toBe(WORDS[lang].proof.runs.newer(LATEST.number));
  });

  it("are those on file: the one shown is the last, and the list goes from the first to the last", () => {
    expect(LATEST).toBe(RUNS[RUNS.length - 1]);
    // "Runs 1 to 5" has to mean every one of them: none left out between the first and the last.
    const numbers = RUNS.map((run) => run.number);
    expect(numbers).toEqual(Array.from({ length: numbers.at(-1)! - numbers[0]! + 1 }, (_, i) => numbers[0]! + i));
    expect(ALL_RUNS).toBe("https://github.com/oplf-svg/cloud-labs/actions/workflows/sign-in.yml");
  });

  it("are called the latest nowhere, and no list is called every run", () => {
    const called = { count: 0 };
    const all = [...LANGS.flatMap((lang) => [...said(WORDS[lang], called), ...said(recorderData(lang), called)]), ...said([CLAIMS, NOTES], called)];
    expect(all.length).toBeGreaterThan(300);
    expect(called.count).toBeGreaterThan(20);
    expect(all.filter((text) => NEWEST.test(text.replace(ITEM, "")) || EVERY.test(text))).toEqual([]);
    const astro = readdirSync(PAGES, { recursive: true, encoding: "utf8" }).filter((name) => name.endsWith(".astro"));
    expect(astro).toEqual(expect.arrayContaining(["pages/[...lang]/index.astro", "pages/[...lang]/proof.astro", "layouts/Page.astro"]));
    for (const name of astro) {
      for (const text of [own(read(name)), ...literals(read(name))]) {
        expect(text, name).not.toMatch(NEWEST);
        expect(text, name).not.toMatch(EVERY);
      }
    }
  });

  it("are named so on the pages", () => {
    const home = read("pages/[...lang]/index.astro");
    const proof = read("pages/[...lang]/proof.astro");
    expect(home).toContain('<Part id="score-title" title={scoreTitle(lang)} lead={score.lead}>');
    expect(home).toContain("#runs`}>{runsName(lang)}</a></p>");
    expect(proof).toContain('<h2 id="runs-title">{runsName(lang)}</h2>');
    expect(proof).toContain('<p class="lead after">{proof.runs.lead} {newerRuns(lang)} <a href={ALL_RUNS}>{proof.runs.list}</a></p>');
  });
});

describe("a day", () => {
  it("is the day in UTC, wherever the site is built", () => {
    const before = process.env.TZ;
    try {
      for (const zone of ["Asia/Tokyo", "America/Los_Angeles", "UTC"]) {
        process.env.TZ = zone;
        expect([day("en", "2026-11-24T23:59:59Z"), day("en", "2026-11-25T00:00:01Z")], zone).toEqual(["November 24, 2026", "November 25, 2026"]);
      }
    } finally {
      if (before === undefined) delete process.env.TZ;
      else process.env.TZ = before;
    }
  });

  it("is written as each language writes it", () => {
    expect(LANGS.map((lang) => day(lang, "2026-12-01T10:00:00Z"))).toEqual(["December 1, 2026", "1 de diciembre de 2026", "1er décembre 2026"]);
    expect(["2026-12-11T10:00:00Z", "2026-11-24T10:00:00Z", "2026-12-21T10:00:00Z"].map((date) => day("fr", date))).toEqual(["11 décembre 2026", "24 novembre 2026", "21 décembre 2026"]);
  });
});

it.each(["The latest run on 3 clouds", "The newest run", "the most recent run", "the most-recent run", "The last run", "La ejecución más reciente", "La última ejecución", "La dernière exécution", "L'exécution la plus récente", "Le dernier run"])("would notice: %s", (text) => {
  expect(text).toMatch(NEWEST);
});

it.each(["All recorded runs", "Every recorded run", "every run", "Each recorded run", "all the recorded runs", "All sign-in runs", "Todas las ejecuciones grabadas", "todas las ejecuciones", "Cada ejecución grabada", "Toutes les exécutions enregistrées", "chaque exécution"])("would notice: %s", (text) => {
  expect(text).toMatch(EVERY);
});
