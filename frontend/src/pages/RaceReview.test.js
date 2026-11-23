import { describe, expect, it } from "vitest";
import { gap, groupSimilar, hms } from "./RaceReview.jsx";

describe("race times", () => {
  it("shows hours, minutes and seconds", () => {
    expect(hms(7770)).toBe("2:09:30");
    expect(hms(305)).toBe("5:05");
    expect(hms(null)).toBe("–");
  });
  it("shows gaps with a sign", () => {
    expect(gap(-270)).toBe("−4:30");
    expect(gap(330)).toBe("+5:30");
    expect(gap(0)).toBe("0");
    expect(gap(null)).toBe("–");
  });
});

describe("similar segments", () => {
  const seg = (id, start_km, km, years) => ({
    id,
    start_km,
    distance_m: km * 1000,
    times: Object.fromEntries(years.map((y) => [y, { elapsed_s: 1 }])),
  });
  it("folds segments over the same stretch, led by the one ridden most", () => {
    const groups = groupSimilar([
      seg(1, 0, 104.0, ["2026"]),
      seg(2, 0.2, 104.9, ["2026", "2025"]),
      seg(3, 0, 30.1, ["2026", "2025"]),
      seg(4, 27.4, 7.0, ["2026"]),
      seg(5, 0.3, 104.2, ["2025"]),
    ]);
    expect(groups.map((g) => [g.lead.id, g.similar.map((s) => s.id)])).toEqual([
      [2, [1, 5]],
      [3, []],
      [4, []],
    ]);
  });
});
