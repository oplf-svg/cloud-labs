import { describe, expect, it } from "vitest";
import { glyph, place, reached, rest, swing, type Kind, type Mark } from "../src/index.ts";

const KINDS: Kind[] = ["in", "refused", "empty", "wrong", "fault", "caught", "action"];

describe("drawing", () => {
  it("keeps every mark on the paper, in order", () => {
    expect(place(0, 100)).toBeGreaterThan(0);
    expect(place(100, 100)).toBeLessThan(1);
    expect(place(50, 100)).toBeCloseTo(0.5);
    expect(place(-5, 100)).toBe(place(0, 100));
    expect(place(500, 100)).toBe(place(100, 100));
    expect(place(0, 0)).toBe(place(0, 100));
  });

  it("draws let in above the line, refused below it, and a wrong answer across it", () => {
    const heights = (kind: Kind) => [...glyph(kind).matchAll(/[ML]-?[\d.]+ (-?[\d.]+)/g)].map((hit) => Number(hit[1]));
    expect(Math.min(...heights("in"))).toBeLessThan(32);
    expect(Math.max(...heights("in"))).toBe(32);
    expect(Math.max(...heights("refused"))).toBeGreaterThan(32);
    expect(Math.min(...heights("refused"))).toBe(32);
    expect(Math.min(...heights("wrong"))).toBeLessThan(10);
    expect(Math.max(...heights("wrong"))).toBeGreaterThan(54);
  });

  it("starts and ends every swing on the line and inside the box", () => {
    for (const kind of KINDS) {
      const points = [...swing(kind, 3, 10).matchAll(/[ML](-?[\d.]+) (-?[\d.]+)/g)].map((hit) => [Number(hit[1]), Number(hit[2])]);
      expect(points[0]![1]).toBe(32);
      expect(points.at(-1)![1]).toBe(32);
      for (const [x, y] of points) {
        expect(x).toBeGreaterThanOrEqual(0);
        expect(x).toBeLessThanOrEqual(1000);
        expect(y).toBeGreaterThanOrEqual(0);
        expect(y).toBeLessThanOrEqual(64);
      }
    }
  });

  it("draws the same resting line every time, and a different one per lane", () => {
    expect(rest("aws")).toBe(rest("aws"));
    expect(rest("aws")).not.toBe(rest("azure"));
    expect(rest("aws")).not.toContain("NaN");
  });

  it("finds the last mark that was reached", () => {
    const marks = [0, 400, 400, 1000].map((at) => ({ at }) as Mark);
    expect(reached(marks, 1000, 0)).toBe(-1);
    expect(reached(marks, 1000, place(0, 1000))).toBe(0);
    expect(reached(marks, 1000, 0.45)).toBe(2);
    expect(reached(marks, 1000, 1)).toBe(3);
    expect(reached([], 1000, 1)).toBe(-1);
  });
});
