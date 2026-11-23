import { describe, expect, it } from "vitest";
import { gap, hms } from "./RaceReview.jsx";

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
