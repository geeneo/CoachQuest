import { expect, it } from "vitest";
import { browser } from "./SignInLog.jsx";

it("names browsers", () => {
  expect(browser("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/131.0")).toBe("Firefox on Windows");
  expect(
    browser("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile Safari/604.1"),
  ).toBe("Safari on iOS");
  expect(browser("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36")).toBe(
    "Chrome on Android",
  );
  expect(browser("")).toBe("–");
});
