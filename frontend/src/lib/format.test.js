import { describe, expect, it } from "vitest";
import { duration, formLabel } from "./format.js";

describe("format", () => {
  it("formats durations", () => {
    expect(duration(0)).toBe("–");
    expect(duration(45 * 60)).toBe("45m");
    expect(duration(3600 + 5 * 60)).toBe("1h 05m");
  });

  it("labels form the same way the backend flags it", () => {
    expect(formLabel(-35)).toBe("Overreaching");
    expect(formLabel(-20)).toBe("Building");
    expect(formLabel(0)).toBe("Neutral");
    expect(formLabel(10)).toBe("Fresh");
    expect(formLabel(20)).toBe("Very fresh");
  });
});
