// Light / Dark / System, remembered in this browser only.
const KEY = "cq-theme";

export function getTheme() {
  try {
    return localStorage.getItem(KEY) || "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme = getTheme()) {
  const root = document.documentElement;
  if (theme === "light" || theme === "dark") root.dataset.theme = theme;
  else delete root.dataset.theme;
}

export function setTheme(theme) {
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    // Storage blocked: the choice still applies until the page is reloaded.
  }
  applyTheme(theme);
  window.dispatchEvent(new CustomEvent(EVENT, { detail: theme }));
}

// Fired on every change, so the header switch and Profile → Appearance stay in step.
export const EVENT = "cq-theme-change";

// What's on screen now: "system" resolved through the device setting.
export function shownTheme(theme = getTheme()) {
  if (theme === "light" || theme === "dark") return theme;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}
