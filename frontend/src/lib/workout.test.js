import { expect, it } from "vitest";
import { blocks, fmtDur, parseDur, zone } from "./workout.js";

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

it("lays steps out on a timeline with intervals expanded", () => {
  const b = blocks([
    { kind: "warmup", duration_s: 600, power_start: 0.5, power_end: 0.75 },
    { kind: "intervals", repeat: 2, on_s: 60, on_power: 1.2, off_s: 30, off_power: 0.5 },
    { kind: "free", duration_s: 300 },
  ]);
  expect(b.map((x) => [x.kind, x.start_s, x.power_end])).toEqual([
    ["warmup", 0, 0.75],
    ["on", 600, 1.2],
    ["off", 660, 0.5],
    ["on", 690, 1.2],
    ["off", 750, 0.5],
    ["free", 780, null],
  ]);
});
