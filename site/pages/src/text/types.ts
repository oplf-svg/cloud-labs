import type { Words } from "@recorder/core";

export const LANGS = ["en", "es", "fr"] as const;
export type Lang = (typeof LANGS)[number];
/** The same text in every language. Leaving one out does not compile. */
export type Text = Record<Lang, string>;

export const DOORS = ["backend", "frontend", "cloud", "data", "ai", "security", "agents", "leadership"] as const;
export type Door = (typeof DOORS)[number];

/** proven: a public run or test. planned: not built. */
export const STATUSES = ["proven", "planned"] as const;
export type Status = (typeof STATUSES)[number];

export interface Link {
  href: string;
  text: Text;
}

export interface Claim {
  id: string;
  doors: Door[];
  project: string;
  status: Status;
  claim: Text;
  /** What the proof does not cover. */
  limit?: Text;
  evidence: Link[];
}

export interface Note {
  slug: string;
  date: string;
  title: Text;
  summary: Text;
  happened: Text[];
  silent: Text;
  now: Text;
  evidence: Link[];
}

export interface SiteWords {
  language: string;
  title: string;
  description: string;
  skip: string;
  menu: string;
  languages: string;
  home: string;
  nav: { proof: string; notes: string; how: string };
  hero: { flag: string; quiet: string; loud: string; lead: string; proof: string; how: string };
  recorder: {
    title: string; lead: string; builtWith: string;
    /** With {kb} and {ms}. */
    measured: string;
    needsScript: string; failed: string; list: string; runs: string;
    first: string; firstAbout: string; latest: string; latestAbout: (verdict: string, clouds: number) => string;
    example: string; exampleAbout: string; attack: string; attackAbout: string;
    player: Words;
    results: { in: string; refused: string; confirmed: string; empty: string; wrong: (got: string, wanted: string) => string };
    got: { allowed: string; denied: string; yes: string; "nothing there": string };
  };
  score: {
    title: string; lead: string; cloud: string; checks: string; in: string; refused: string; empty: string; wrong: string; answer: string; open: string; note: string;
    verdict: (checks: number, wrong: number) => string;
  };
  doors: { title: string; lead: string; names: Record<Door, string>; lines: Record<Door, string>; count: (counts: Record<Status, number>) => string };
  notes: { title: string; lead: string; happened: string; silent: string; now: string; evidence: string; all: string };
  proof: {
    title: string; lead: string; filter: string; everyone: string; statuses: Record<Status, string>; limit: string; evidence: string; project: string; none: string;
    runs: { title: string; lead: string; run: (n: number) => string; open: string };
  };
  how: {
    title: string; lead: string;
    keys: { title: string; text: string[]; tiers: { name: string; who: string; can: string; state: "tested" | "used" }[]; tested: string; used: string };
    agents: { title: string; text: string[]; rules: { rule: string; state: Status }[] };
    ai: { title: string; text: string[] };
    builds: { title: string; text: string[]; build: string; size: string; tests: string; same: string };
    rules: { title: string; list: string[] };
  };
  footer: { text: string; source: string };
  missing: { title: string; text: string; back: string };
}
