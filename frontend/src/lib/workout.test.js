import { expect, it } from "vitest";
import { fmtDur, parseDur, zone } from "./workout.js";

it("workout durations", () => {
  expect(parseDur("1:30")).toBe(90);
  expect(parseDur("1:00:00")).toBe(3600);
  expect(parseDur("20")).toBe(1200);
  expect(parseDur("1.5")).toBe(90);
  expect(parseDur("abc")).toBe(null);
  expect(fmtDur(90)).toBe("1:30");
  expect(fmtDur(3725)).toBe("1:02:05");
  expect(zone(0.88)).toBe("Z3");
});
