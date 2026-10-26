import { afterEach, describe, expect, it } from "vitest";
import { dateTime, duration, formatDate, formLabel, setFormatPrefs, shortDate, timeOfDay } from "./format.js";

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

describe("date format", () => {
  afterEach(() => setFormatPrefs(null));

  it("defaults to 26 Oct 2026, 24-hour", () => {
    setFormatPrefs({ timezone: "Africa/Johannesburg" });
    expect(dateTime("2026-10-26T06:28:05")).toBe("26 Oct 2026, 08:28"); // stored as UTC
    expect(formatDate("1968-07-01")).toBe("1 Jul 1968");
    expect(shortDate("2026-03-05")).toBe("5 Mar");
  });

  it("follows the user's choices", () => {
    setFormatPrefs({ date_format: "mdy", time_format: "12h", timezone: "Africa/Johannesburg" });
    expect(dateTime("2026-10-26T15:30:00Z")).toBe("10/26/2026, 5:30 pm");
    expect(formatDate("2026-03-05", { weekday: "short" })).toBe("Thu 03/05/2026");
    setFormatPrefs({ date_format: "iso", timezone: "UTC" });
    expect(formatDate("2026-03-05", { weekday: "long", year: false })).toBe("Thursday 03-05");
    expect(timeOfDay("2026-10-26T00:05:00")).toBe("00:05");
    setFormatPrefs({ date_format: "dmy", timezone: "Not/AZone" });
    expect(formatDate("2026-03-05")).toBe("05/03/2026");
  });

  it("calendar days don't shift with the timezone", () => {
    setFormatPrefs({ timezone: "Pacific/Honolulu" });
    expect(formatDate("2026-01-01")).toBe("1 Jan 2026");
    expect(dateTime(null)).toBe("never");
  });
});
