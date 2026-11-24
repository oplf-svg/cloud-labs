import { timeOf } from "./drawing.ts";
import type { View } from "./player.ts";
import type { Data, Kind, Words } from "./types.ts";

/** Reads the data that the page holds for the recorder. */
export function readData(element: HTMLElement): Data {
  const source = document.getElementById(element.dataset["for"] ?? "");
  if (!source?.textContent) throw new Error("the recorder has no data");
  return JSON.parse(source.textContent) as Data;
}

export interface Reading {
  time: string;
  lane: string;
  kind: Kind;
  what: string;
  result: string;
}

/** The mark to read out: the one pointed at, or else the last one that was reached. */
export const current = (view: View): number => (view.pointed >= 0 ? view.pointed : view.index);

/** Where across an element an event happened, between 0 and 1. */
export function across(event: { clientX: number; currentTarget: EventTarget | null }): number {
  const box = (event.currentTarget as Element).getBoundingClientRect();
  return box.width > 0 ? (event.clientX - box.left) / box.width : 0;
}

export function reading(view: View): Reading | undefined {
  const mark = view.marks[current(view)];
  if (!mark) return undefined;
  const lane = view.recording.lanes.find((known) => known.id === mark.lane)?.name ?? mark.lane;
  return { time: timeOf(view.recording, mark), lane, kind: mark.kind, what: mark.what, result: mark.result };
}

/** The same in one sentence, for the slider. */
export function sentence(view: View, words: Words): string {
  const now = reading(view);
  if (!now) return words.start;
  const parts: Record<string, string | number> = { ...now, n: view.index + 1, total: view.marks.length };
  return words.reading.replace(/\{(\w+)\}/g, (whole, name: string) => String(parts[name] ?? whole));
}

export function playLabel(view: View, words: Words): string {
  if (view.playing) return words.pause;
  return view.position <= 0 || view.position >= 1 ? words.play : words.resume;
}

/** The kinds that this recording uses, in the order of the legend. */
export function kindsIn(view: View): Kind[] {
  const order: Kind[] = ["in", "refused", "empty", "wrong", "caught", "fault", "action"];
  const used = new Set([...view.recording.marks, ...(view.recording.unseen ?? [])].map((mark) => mark.kind));
  return order.filter((kind) => used.has(kind));
}
