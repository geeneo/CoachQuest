import { describe, expect, it } from "vitest";
import { gap, groupSimilar, hms, rescore } from "./RaceReview.jsx";

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

describe("years shown", () => {
  const s = { times: { 2026: { elapsed_s: 600 }, 2025: { elapsed_s: 580 }, 2023: { elapsed_s: 640 }, "rider-1": { elapsed_s: 500 } } };
  const col = (key, kind) => ({ key, kind });
  it("best and vs best over the years shown, never a rider", () => {
    const all = [col("2026", "race"), col("2025", "year"), col("2023", "year"), col("rider-1", "rider")];
    expect(rescore(s, all)).toMatchObject({ best: "2025", vs_best_before: 20 });
    const no2025 = [col("2026", "race"), col("2023", "year")];
    expect(rescore(s, no2025)).toMatchObject({ best: "2026", vs_best_before: -40 });
    expect(rescore(s, [col("2026", "race")])).toMatchObject({ best: null, vs_best_before: null });
  });
});
