import { describe, expect, it, vi } from "vitest";
import { Player, kindsIn, place, playLabel, reading, sentence, type Clock, type Recording, type Words } from "../src/index.ts";

const recording = (id: string, extra: Partial<Recording> = {}): Recording => ({
  id, real: true, title: id, about: "", length: 1000, lanes: [{ id: "a", name: "Lane A" }, { id: "b", name: "Lane B" }],
  marks: [
    { at: 0, lane: "a", kind: "in", what: "sign in", result: "let in" },
    { at: 500, lane: "b", kind: "refused", what: "create", result: "refused" },
    { at: 1000, lane: "a", kind: "wrong", what: "read", result: "let in" },
  ],
  ...extra,
});

/** Time that only moves when a test says so. */
class StillClock implements Clock {
  time = 0;
  calm = false;
  waiting: (() => void) | undefined;
  now = () => this.time;
  soon = (call: () => void) => {
    this.waiting = call;
    return () => (this.waiting = undefined);
  };
  pass(ms: number) {
    this.time += ms;
    const call = this.waiting;
    this.waiting = undefined;
    call?.();
  }
}

const words = { play: "Play", pause: "Pause", resume: "Carry on", start: "Nothing yet", reading: "{n} of {total}, {lane}: {what}, {result}" } as Words;

describe("player", () => {
  it("shows the whole recording at rest", () => {
    const { view } = new Player([recording("one")], new StillClock());
    expect(view).toMatchObject({ position: 1, index: 2, playing: false });
  });

  it("plays from the start to the end and then stops", () => {
    const clock = new StillClock();
    const player = new Player([recording("one")], clock);
    player.play();
    expect(player.view).toMatchObject({ position: 0, index: -1, playing: true });
    clock.pass(3000);
    expect(player.view.position).toBeCloseTo(0.5);
    expect(player.view.index).toBe(1);
    clock.pass(99999);
    expect(player.view).toMatchObject({ position: 1, index: 2, playing: false });
    expect(clock.waiting).toBeUndefined();
  });

  it("carries on from where it was paused", () => {
    const clock = new StillClock();
    const player = new Player([recording("one")], clock);
    player.play();
    clock.pass(3000);
    player.toggle();
    expect(player.view.playing).toBe(false);
    clock.pass(5000);
    expect(player.view.position).toBeCloseTo(0.5);
    player.toggle();
    clock.pass(600);
    expect(player.view.position).toBeCloseTo(0.6);
  });

  it("jumps from mark to mark for readers who want less motion", () => {
    const clock = new StillClock();
    clock.calm = true;
    const player = new Player([recording("one")], clock);
    player.play();
    clock.pass(3600);
    expect(player.view.position).toBeCloseTo(place(500, 1000));
  });

  it("steps through every mark and no further", () => {
    const player = new Player([recording("one")], new StillClock());
    player.seek(0);
    const seen = [player.view.index];
    for (let i = 0; i < 5; i++) {
      player.step(1);
      seen.push(player.view.index);
    }
    expect(seen).toEqual([-1, 0, 1, 2, 2, 2]);
    for (let i = 0; i < 5; i++) player.step(-1);
    expect(player.view).toMatchObject({ index: -1, position: 0 });
  });

  it("stops at both of two marks in the same moment", () => {
    const marks = [0, 500, 500, 1000].map((at, i) => ({ at, lane: "a", kind: "in" as const, what: `mark ${i}`, result: "" }));
    const player = new Player([recording("one", { marks })], new StillClock());
    player.seek(0);
    const there = [0, 1, 2, 3].map(() => (player.step(1), player.view.index));
    const back = [0, 1, 2, 3].map(() => (player.step(-1), player.view.index));
    expect([there, back]).toEqual([[0, 1, 2, 3], [2, 1, 0, -1]]);
  });

  it("steps back to the mark it has just passed", () => {
    const player = new Player([recording("one")], new StillClock());
    player.seek(0.7);
    player.step(-1);
    expect(player.view.index).toBe(1);
    player.step(-1);
    expect(player.view.index).toBe(0);
  });

  it("reads the mark that is pointed at, in its own lane, and stays where it is", () => {
    const player = new Player([recording("one")], new StillClock());
    player.point("b", place(500, 1000) + 0.02);
    expect(player.view).toMatchObject({ pointed: 1, index: 2, position: 1 });
    expect(reading(player.view)?.what).toBe("create");
    player.point("a", place(500, 1000));
    expect(player.view.pointed).toBe(-1);
    player.point("b", place(500, 1000));
    player.leave();
    expect(reading(player.view)?.what).toBe("read");
  });

  it("goes to the mark that is picked, but not to one that is not drawn yet", () => {
    const player = new Player([recording("one")], new StillClock());
    player.pick("b", place(500, 1000));
    expect(player.view).toMatchObject({ index: 1, position: place(500, 1000) });
    player.pick("a", place(1000, 1000));
    expect(player.view.index).toBe(1);
    player.pick("a", 0.5);
    expect(player.view.index).toBe(1);
  });

  it("stops playing when the reader takes over", () => {
    for (const act of [(p: Player) => p.seek(0.2), (p: Player) => p.step(1), (p: Player) => p.choose("two"), (p: Player) => p.pause()]) {
      const clock = new StillClock();
      const player = new Player([recording("one"), recording("two")], clock);
      player.play();
      clock.pass(1000);
      act(player);
      expect(player.view.playing).toBe(false);
      expect(clock.waiting).toBeUndefined();
    }
  });

  it("shows another recording from its end, with its checks", () => {
    const unseen = [{ at: 900, lane: "a", kind: "fault" as const, what: "x", result: "y" }];
    const player = new Player([recording("one", { unseen }), recording("two")], new StillClock());
    player.show(true);
    expect(player.view.marks).toBe(unseen);
    player.choose("two");
    expect(player.view).toMatchObject({ unseen: false, position: 1, index: 2 });
    player.show(true);
    expect(player.view.unseen).toBe(false);
  });

  it("keeps one view until something changes, as React needs", () => {
    const player = new Player([recording("one")], new StillClock());
    const heard = vi.fn();
    const stop = player.subscribe(heard);
    expect(player.view).toBe(player.view);
    player.seek(0.5);
    expect(heard).toHaveBeenCalledTimes(1);
    stop();
    player.seek(0.6);
    expect(heard).toHaveBeenCalledTimes(1);
  });

  it("refuses to play nothing", () => {
    expect(() => new Player([], new StillClock())).toThrow("nothing to play");
  });
});

describe("text", () => {
  it("says where it is", () => {
    const player = new Player([recording("one")], new StillClock());
    expect(sentence(player.view, words)).toBe("3 of 3, Lane A: read, let in");
    expect(reading(player.view)).toMatchObject({ time: "+1.0 s", lane: "Lane A", kind: "wrong" });
    player.seek(0);
    expect(sentence(player.view, words)).toBe("Nothing yet");
    expect(reading(player.view)).toBeUndefined();
  });

  it("shows a clock when a recording has one", () => {
    const player = new Player([recording("one", { clock: 9 * 60 + 58, length: 600000, marks: [{ at: 300000, lane: "a", kind: "in", what: "", result: "" }] })], new StillClock());
    expect(reading(player.view)?.time).toBe("10:03");
  });

  it("names the button after what it will do", () => {
    const clock = new StillClock();
    const player = new Player([recording("one")], clock);
    expect(playLabel(player.view, words)).toBe("Play");
    player.play();
    expect(playLabel(player.view, words)).toBe("Pause");
    clock.pass(1000);
    player.pause();
    expect(playLabel(player.view, words)).toBe("Carry on");
    player.seek(0);
    expect(playLabel(player.view, words)).toBe("Play");
  });

  it("lists only the kinds that are used", () => {
    expect(kindsIn(new Player([recording("one")], new StillClock()).view)).toEqual(["in", "refused", "wrong"]);
  });
});
