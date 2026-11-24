/** How a mark is drawn. The first four come from real checks, the last three from examples. */
export type Kind = "in" | "refused" | "empty" | "wrong" | "fault" | "caught" | "action";

export interface Mark {
  /** Milliseconds since the recording started. */
  at: number;
  lane: string;
  kind: Kind;
  /** For a real run: the test's own words. */
  what: string;
  result: string;
}

export interface Lane {
  id: string;
  name: string;
}

export interface Recording {
  id: string;
  real: boolean;
  title: string;
  about: string;
  lanes: Lane[];
  length: number;
  marks: Mark[];
  /** What anyone would see without the checks. Only examples have this. */
  unseen?: Mark[];
  /** Minutes after midnight at the start. With it, times are shown as a clock. */
  clock?: number;
  url?: string;
}

export interface Words {
  recordings: string;
  real: string;
  example: string;
  openRun: string;
  views: string;
  seen: string;
  unseen: string;
  play: string;
  pause: string;
  resume: string;
  back: string;
  on: string;
  position: string;
  /** With {n}, {total}, {lane}, {what} and {result}. */
  reading: string;
  start: string;
  legend: string;
  kinds: Record<Kind, string>;
}

export interface Data {
  words: Words;
  recordings: Recording[];
}
