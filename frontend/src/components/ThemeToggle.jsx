import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { EVENT, getTheme, setTheme, shownTheme } from "../lib/theme.js";

// One click between light and dark, from any page. Profile → Appearance also offers System.
export default function ThemeToggle({ className = "" }) {
  const [shown, setShown] = useState(() => shownTheme());
  useEffect(() => {
    const update = () => setShown(shownTheme());
    const media = window.matchMedia?.("(prefers-color-scheme: light)");
    window.addEventListener(EVENT, update);
    media?.addEventListener?.("change", update); // following the device while on System
    return () => {
      window.removeEventListener(EVENT, update);
      media?.removeEventListener?.("change", update);
    };
  }, []);
  const next = shown === "dark" ? "light" : "dark";
  const label = `Switch to ${next} mode`;
  return (
    <button
      type="button"
      className={`icon-btn theme-toggle ${className}`}
      title={getTheme() === "system" ? `${label} (now following your device)` : label}
      aria-label={label}
      onClick={() => setTheme(next)}
    >
      {shown === "dark" ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}
