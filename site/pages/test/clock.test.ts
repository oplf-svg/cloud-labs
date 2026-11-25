import { readFileSync, readdirSync } from "node:fs";
import { expect, it } from "vitest";

// GitHub's clock may start a run late or not at all, and a start that it dropped leaves no trace. So nothing here says that
// something happens at a fixed time until its starts were counted.
const PROMISE = /(?:every|each)\s+(?:night|morning|evening|day|week)|\b(?:nightly(?!-destroy)|daily|weekly)\b|second\s+clock|cada\s+(?:noche|mañana|tarde|día|semana)|tod[ao]s\s+l[ao]s\s+(?:noches|mañanas|tardes|días|semanas)|\bdiari[oa]|\bsemanal|segundo\s+reloj|chaque\s+(?:nuit|matin|soir|jour|semaine)|tou(?:te)?s\s+les\s+(?:nuits|matins|soirs|jours|semaines)|\bquotidien|\bhebdomadaire|(?:deuxième|seconde)\s+horloge/i;

const PAGES = new URL("../src/", import.meta.url);
const names = readdirSync(PAGES, { recursive: true, encoding: "utf8" }).filter((name) => /\.(?:ts|astro)$/.test(name));

it("promises no start by GitHub's clock", () => {
  expect(names).toEqual(expect.arrayContaining(["text/en.ts", "text/es.ts", "text/fr.ts", "text/claims.ts", "text/notes.ts", "pages/[...lang]/how.astro"]));
  for (const name of names) expect(readFileSync(new URL(name, PAGES), "utf8"), name).not.toMatch(PROMISE);
  expect(readFileSync(new URL("../../README.md", import.meta.url), "utf8"), "README").not.toMatch(PROMISE);
});

it.each(["Every night, on its own", "every\nmorning", "Each morning the looks run", "Nightly, on its own", "Cada noche, sola", "todas las noches", "una ejecución diaria", "Chaque nuit, seule", "tous les soirs", "une exécution quotidienne", "a second clock", "Weekly.", "every week", "cada semana", "una revisión semanal", "chaque semaine", "un contrôle hebdomadaire"])("would notice: %s", (said) => {
  expect(said).toMatch(PROMISE);
});
