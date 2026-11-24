import { place, reached } from "./drawing.ts";
import type { Mark, Recording } from "./types.ts";

export interface View {
  recording: Recording;
  /** The marks on the paper now: those with the checks, or those without them. */
  marks: Mark[];
  unseen: boolean;
  /** How far the paper has been drawn, between 0 and 1. */
  position: number;
  /** The last mark that was reached, or -1. */
  index: number;
  /** The mark that the reader is pointing at, or -1. */
  pointed: number;
  playing: boolean;
}

export interface Clock {
  now(): number;
  /** Calls back once, soon. Returns a way to stop it. */
  soon(call: () => void): () => void;
  /** True when the reader asked for less motion: the pen then jumps from mark to mark. */
  calm: boolean;
}

export const browserClock = (): Clock => ({
  now: () => performance.now(),
  soon: (call) => {
    const id = requestAnimationFrame(call);
    return () => cancelAnimationFrame(id);
  },
  calm: matchMedia("(prefers-reduced-motion: reduce)").matches,
});

/** How near to a mark is near enough, as a share of the paper. */
const REACH = 0.035;
const PER_MARK = 450;
const SHORTEST = 6000;
const LONGEST = 16000;

/** Plays a recording. It knows nothing about the page, so both builds share it. */
export class Player {
  readonly recordings: Recording[];
  #clock: Clock;
  #listeners = new Set<() => void>();
  #stop: (() => void) | undefined;
  #view: View;

  constructor(recordings: Recording[], clock: Clock) {
    const [first] = recordings;
    if (!first) throw new Error("nothing to play");
    this.recordings = recordings;
    this.#clock = clock;
    // At rest the whole recording is on the paper, so there is something to see before anyone presses play.
    this.#view = { recording: first, marks: first.marks, unseen: false, position: 1, index: first.marks.length - 1, pointed: -1, playing: false };
  }

  get view(): View {
    return this.#view;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  };

  choose(id: string): void {
    const recording = this.recordings.find((known) => known.id === id);
    if (!recording || recording === this.#view.recording) return;
    this.pause();
    this.#set({ recording, marks: recording.marks, unseen: false, position: 1, pointed: -1 });
  }

  show(unseen: boolean): void {
    const { recording } = this.#view;
    if (!recording.unseen || unseen === this.#view.unseen) return;
    this.#set({ unseen, marks: unseen ? recording.unseen : recording.marks, pointed: -1 });
  }

  seek(position: number): void {
    this.pause();
    this.#set({ position: Math.min(Math.max(position, 0), 1) });
  }

  /** Reads the mark nearest to a place in a lane. The paper stays where it is. */
  point(lane: string, share: number): void {
    const pointed = this.#near(lane, share);
    if (pointed !== this.#view.pointed) this.#set({ pointed, index: this.#view.index });
  }

  leave(): void {
    if (this.#view.pointed !== -1) this.#set({ pointed: -1, index: this.#view.index });
  }

  /** Goes to the mark nearest to a place in a lane. */
  pick(lane: string, share: number): void {
    const index = this.#near(lane, share);
    if (index < 0) return;
    this.pause();
    this.#set({ position: place(this.#view.marks[index]!.at, this.#view.recording.length), index, pointed: -1 });
  }

  #near(lane: string, share: number): number {
    const { marks, recording, position } = this.#view;
    let best = -1;
    let distance = REACH;
    for (const [i, mark] of marks.entries()) {
      const at = place(mark.at, recording.length);
      if (mark.lane !== lane || at > position + 1e-9 || Math.abs(at - share) > distance) continue;
      distance = Math.abs(at - share);
      best = i;
    }
    return best;
  }

  step(by: 1 | -1): void {
    this.pause();
    const { marks, recording, index, position } = this.#view;
    const at = (i: number) => place(marks[i]!.at, recording.length);
    // Going back from between two marks first returns to the one just passed.
    const behind = by === -1 && index >= 0 && position > at(index) + 1e-9 && position < 1;
    const next = Math.max(-1, Math.min(behind ? index : index + by, marks.length - 1));
    // The index is given, because two marks can share one place and each of them must be reachable.
    this.#set({ position: next < 0 ? 0 : at(next), index: next });
  }

  toggle(): void {
    if (this.#view.playing) this.pause();
    else this.play();
  }

  play(): void {
    if (this.#view.playing) return;
    const { marks, recording } = this.#view;
    const total = Math.min(Math.max(marks.length * PER_MARK, SHORTEST), LONGEST);
    const from = this.#view.position >= 1 ? 0 : this.#view.position;
    const started = this.#clock.now();
    this.#set({ playing: true, position: from });
    const tick = () => {
      let position = Math.min(from + (this.#clock.now() - started) / total, 1);
      if (this.#clock.calm && position < 1) {
        const index = reached(marks, recording.length, position);
        position = index < 0 ? 0 : place(marks[index]!.at, recording.length);
      }
      this.#set({ position });
      if (position < 1) this.#stop = this.#clock.soon(tick);
      else this.#set({ playing: false });
    };
    this.#stop = this.#clock.soon(tick);
  }

  pause(): void {
    this.#stop?.();
    this.#stop = undefined;
    if (this.#view.playing) this.#set({ playing: false });
  }

  #set(change: Partial<View>): void {
    const view = { ...this.#view, ...change };
    if (change.index === undefined) view.index = reached(view.marks, view.recording.length, view.position);
    this.#view = view;
    for (const listener of this.#listeners) listener();
  }
}
