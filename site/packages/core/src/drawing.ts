import type { Kind, Mark, Recording } from "./types.ts";

// Every lane is drawn in this box and then stretched to the width of the page. Pen lines keep their thickness.
export const WIDTH = 1000;
export const HEIGHT = 64;
const MIDDLE = HEIGHT / 2;
const MARGIN = 14;

/** Where on the paper a moment is, between 0 and 1. */
export function place(at: number, length: number): number {
  const share = length > 0 ? Math.min(Math.max(at / length, 0), 1) : 0;
  return (MARGIN + share * (WIDTH - 2 * MARGIN)) / WIDTH;
}

const round = (value: number) => Math.round(value * 10) / 10;

/** The line a resting pen draws. It shakes a little, and always in the same way. */
export function rest(seed: string): string {
  let state = [...seed].reduce((sum, letter) => (sum * 31 + letter.charCodeAt(0)) >>> 0, 7);
  const next = () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 2 ** 32 - 0.5;
  };
  let path = `M0 ${MIDDLE}`;
  for (let x = 10; x <= WIDTH; x += 10) path += `L${x} ${round(MIDDLE + next() * 1.6)}`;
  return path;
}

const SHAPES: Record<Kind, [number, number][]> = {
  in: [[-4, 0], [0, -22], [4, 0]],
  refused: [[-4, 0], [0, 22], [4, 0]],
  empty: [[-3, 0], [0, -7], [3, 0]],
  wrong: [[-7, 0], [-3, -29], [3, 29], [7, 0]],
  fault: [[-7, 0], [-3, -29], [3, 29], [7, 0]],
  caught: [[-4, 0], [0, -22], [4, 0]],
  action: [[-5, 0], [-5, 18], [5, 18], [5, 0]],
};

/** The pen's movement at one mark. */
export function swing(kind: Kind, at: number, length: number): string {
  const x = place(at, length) * WIDTH;
  return SHAPES[kind].map(([dx, dy], i) => `${i ? "L" : "M"}${round(x + dx)} ${MIDDLE + dy}`).join("");
}

/** The same shape on its own, for the legend, in a box of 24 by HEIGHT. */
export function glyph(kind: Kind): string {
  return `M0 ${MIDDLE}${SHAPES[kind].map(([dx, dy]) => `L${12 + dx} ${MIDDLE + dy}`).join("")}L24 ${MIDDLE}`;
}

/** The last mark at or before a place on the paper, or -1. */
export function reached(marks: Mark[], length: number, position: number): number {
  let index = -1;
  for (const [i, mark] of marks.entries()) if (place(mark.at, length) <= position + 1e-9) index = i;
  return index;
}

export function timeOf(recording: Recording, mark: Mark): string {
  if (recording.clock === undefined) return `+${(mark.at / 1000).toFixed(1)} s`;
  const minutes = recording.clock + Math.floor(mark.at / 60000);
  return [Math.floor(minutes / 60), minutes % 60].map((part) => String(part).padStart(2, "0")).join(":");
}
