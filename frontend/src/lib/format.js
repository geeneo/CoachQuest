export const SCOPE_LABELS = {
  activities: "Activities",
  fitness: "Fitness & load (CTL/ATL/TSB)",
  wellness: "Wellness (sleep, HRV, resting HR)",
  plans: "Training plans (view and create with the AI coach)",
};

export function duration(seconds) {
  if (!seconds) return "–";
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

export function dateTime(value) {
  if (!value) return "never";
  return new Date(value.endsWith("Z") ? value : value + "Z").toLocaleString();
}

export function shortDate(value) {
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// Plain-language reading of TSB, matching the thresholds the backend flags.
export function formLabel(tsb) {
  if (tsb == null) return "–";
  if (tsb < -30) return "Overreaching";
  if (tsb < -10) return "Building";
  if (tsb <= 5) return "Neutral";
  if (tsb <= 15) return "Fresh";
  return "Very fresh";
}
