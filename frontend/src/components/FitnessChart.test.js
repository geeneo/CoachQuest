import { describe, expect, it } from "vitest";
import { mergeRows } from "./FitnessChart.jsx";

describe("mergeRows", () => {
  it("joins history and the projection on today, and adds the days ahead", () => {
    const hist = [
      { day: "2026-11-09", tss: 90, ctl: 57, atl: 60, tsb: -1 },
      { day: "2026-11-10", tss: 0, ctl: 56, atl: 52, tsb: -3 },
    ];
    const ahead = [
      { day: "2026-11-10", planned_tss: 60, ctl: 57, atl: 58, tsb: -3 },
      { day: "2026-11-11", planned_tss: null, ctl: 56, atl: 50, tsb: -1, race: "DC" },
    ];
    const rows = mergeRows(hist, ahead);
    expect(rows.map((r) => r.day)).toEqual(["2026-11-09", "2026-11-10", "2026-11-11"]);
    expect(rows[1]).toMatchObject({ tss: null, ctl: 56, p_ctl: 57, p_tss: 60 });
    expect(rows[2]).toMatchObject({ p_tsb: -1, race: "DC" });
    expect(rows[2].ctl).toBeUndefined();
  });
  it("works without a projection", () => {
    expect(mergeRows([{ day: "2026-11-10", tss: 50, ctl: 1, atl: 2, tsb: 0 }])).toHaveLength(1);
  });
});
