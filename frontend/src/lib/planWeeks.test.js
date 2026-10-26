import { describe, expect, it } from "vitest";
import { planStart, weekStartOf, weeksToEvent } from "./planWeeks.js";

describe("plan weeks", () => {
  it("finds the first day of a week", () => {
    expect(weekStartOf("2026-10-29")).toBe("2026-10-26"); // Thursday → Monday
    expect(weekStartOf("2026-10-29", 5)).toBe("2026-10-24"); // weeks start on Saturday
  });

  it("starts next week by default, today when a week starts today", () => {
    expect(planStart("", "2026-10-28")).toBe("2026-11-02");
    expect(planStart("", "2026-10-26")).toBe("2026-10-26");
  });

  it("counts weeks up to and including the race week", () => {
    // Plan from Mon 26 Oct, race on Sat 21 Nov: 26 Oct, 2, 9, 16 Nov = 4 weeks.
    expect(weeksToEvent("2026-11-21", "2026-10-26", "2026-10-26")).toEqual({
      weeks: 4,
      start: "2026-10-26",
      moved: false,
    });
    // Weeks start on Saturday and none is given: from Sat 31 Oct (the next week to begin) to Sat 21 Nov.
    expect(weeksToEvent("2026-11-21", "", "2026-10-26", 5)).toMatchObject({ weeks: 4, start: "2026-10-31" });
  });

  it("moves the start later when the event is more than 16 weeks away", () => {
    expect(weeksToEvent("2027-05-13", "", "2026-10-26")).toEqual({
      weeks: 16,
      start: "2027-01-25",
      moved: true,
      away: 29,
    });
  });

  it("says when the event comes before the start", () => {
    expect(weeksToEvent("2026-10-20", "2026-10-26", "2026-10-26").error).toMatch(/before the plan/);
  });
});
