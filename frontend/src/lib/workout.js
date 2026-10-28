// Helpers for the workout builder. The backend holds the real rules (validation,
// TSS / IF); these only format and parse what the user types.

export const STEP_KINDS = [
  { kind: "warmup", label: "Warm-up" },
  { kind: "steady", label: "Steady" },
  { kind: "intervals", label: "Intervals" },
  { kind: "recovery", label: "Recovery" },
  { kind: "ramp", label: "Ramp" },
  { kind: "free", label: "Free ride" },
  { kind: "cooldown", label: "Cool-down" },
];
export const KIND_LABEL = Object.fromEntries(STEP_KINDS.map((k) => [k.kind, k.label]));

export function newStep(kind) {
  switch (kind) {
    case "warmup":
      return { kind, duration_s: 600, power_start: 0.5, power_end: 0.75 };
    case "cooldown":
      return { kind, duration_s: 600, power_start: 0.7, power_end: 0.45 };
    case "ramp":
      return { kind, duration_s: 300, power_start: 0.6, power_end: 1.0 };
    case "recovery":
      return { kind, duration_s: 300, power: 0.5 };
    case "intervals":
      return { kind, repeat: 5, on_s: 60, on_power: 1.2, off_s: 60, off_power: 0.5 };
    case "free":
      return { kind, duration_s: 600 };
    default:
      return { kind: "steady", duration_s: 1200, power: 0.88 };
  }
}

// 90 -> "1:30", 3600 -> "1:00:00"
export function fmtDur(s) {
  if (s == null || Number.isNaN(s)) return "";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? h + ":" : ""}${mm}:${String(sec).padStart(2, "0")}`;
}

// "1:30" -> 90, "1:00:00" -> 3600, "20" -> 1200 (plain numbers are minutes). null if unreadable.
export function parseDur(text) {
  const t = String(text).trim();
  if (!t) return null;
  if (/^\d+(\.\d+)?$/.test(t)) return Math.round(Number(t) * 60);
  const parts = t.split(":");
  if (parts.length > 3 || parts.some((p) => !/^\d+$/.test(p))) return null;
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
}

export const pct = (fraction) => Math.round(fraction * 100);
export const watts = (fraction, ftp) => (ftp ? Math.round(fraction * ftp) : null);

export function zone(fraction) {
  if (fraction < 0.6) return "Z1";
  if (fraction < 0.76) return "Z2";
  if (fraction < 0.9) return "Z3";
  if (fraction < 1.05) return "Z4";
  if (fraction < 1.19) return "Z5";
  return "Z6";
}

export const STARTERS = [
  {
    name: "Sweet spot 2×20",
    description: "Two 20-minute blocks just under threshold.",
    instructions: "Stay seated, smooth pedalling, 85-95 rpm.",
    steps: [
      { kind: "warmup", duration_s: 600, power_start: 0.5, power_end: 0.75 },
      { kind: "steady", duration_s: 1200, power: 0.9, cadence: 90 },
      { kind: "recovery", duration_s: 300, power: 0.5 },
      { kind: "steady", duration_s: 1200, power: 0.9, cadence: 90 },
      { kind: "cooldown", duration_s: 600, power_start: 0.65, power_end: 0.45 },
    ],
  },
  {
    name: "VO2 max 5×3",
    description: "Five 3-minute efforts with equal recovery.",
    instructions: "Hard but even: the last rep should match the first.",
    steps: [
      { kind: "warmup", duration_s: 900, power_start: 0.5, power_end: 0.8 },
      { kind: "intervals", repeat: 5, on_s: 180, on_power: 1.15, off_s: 180, off_power: 0.5 },
      { kind: "cooldown", duration_s: 600, power_start: 0.6, power_end: 0.4 },
    ],
  },
  {
    name: "Endurance 90",
    description: "Steady zone 2.",
    instructions: "Conversational effort.",
    steps: [
      { kind: "warmup", duration_s: 600, power_start: 0.5, power_end: 0.68 },
      { kind: "steady", duration_s: 4200, power: 0.68 },
      { kind: "cooldown", duration_s: 600, power_start: 0.6, power_end: 0.45 },
    ],
  },
];

// Today as YYYY-MM-DD in this browser's timezone (toISOString would give the UTC date).
export function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function addDays(iso, n) {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// Steps laid out on a timeline, intervals expanded, for WorkoutChart (mirrors workouts.blocks in the backend).
export function blocks(steps) {
  const out = [];
  let t = 0;
  const add = (step, kind, secs, p0, p1, cadence) => {
    out.push({ step, kind, start_s: t, duration_s: secs, power_start: p0, power_end: p1, cadence });
    t += secs;
  };
  (steps || []).forEach((s, i) => {
    if (s.kind === "intervals") {
      for (let r = 0; r < s.repeat; r++) {
        add(i, "on", s.on_s, s.on_power, s.on_power, s.cadence);
        add(i, "off", s.off_s, s.off_power, s.off_power, s.off_cadence);
      }
    } else if (s.kind === "steady" || s.kind === "recovery") add(i, s.kind, s.duration_s, s.power, s.power, s.cadence);
    else if (s.kind === "free") add(i, s.kind, s.duration_s, null, null, null);
    else add(i, s.kind, s.duration_s, s.power_start, s.power_end, s.cadence);
  });
  return out;
}
