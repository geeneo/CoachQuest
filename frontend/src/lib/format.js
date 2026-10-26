export const SCOPE_LABELS = {
  activities: "Activities",
  fitness: "Fitness & load (CTL/ATL/TSB)",
  wellness: "Wellness (sleep, HRV, resting HR)",
  profile: "Profile (FTP, threshold and max HR, goal)",
  weight: "Weight",
  plans: "Training plans (view and create with the AI coach)",
};

export function duration(seconds) {
  if (!seconds) return "–";
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

// Date and time format from Profile (kept in step with backend/app/datefmt.py).
export const DATE_FORMATS = {
  d_mon_y: "26 Oct 2026",
  iso: "2026-10-26",
  dmy: "26/10/2026",
  mdy: "10/26/2026",
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const LONG_WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
let prefs = { date: "d_mon_y", time: "24h", tz: undefined };

// Called whenever the signed-in user changes (lib/auth.jsx).
export function setFormatPrefs(user) {
  let tz;
  try {
    tz = user?.timezone ? Intl.DateTimeFormat(undefined, { timeZone: user.timezone }) && user.timezone : undefined;
  } catch {
    tz = undefined; // unknown to this browser: use the browser's own zone
  }
  prefs = {
    date: DATE_FORMATS[user?.date_format] ? user.date_format : "d_mon_y",
    time: user?.time_format === "12h" ? "12h" : "24h",
    tz,
  };
}

const pad = (n) => String(n).padStart(2, "0");

// {y, m (1-12), d, wd (0 = Sunday), H, M} for a timestamp (in the user's zone) or a "YYYY-MM-DD" day.
function parts(value) {
  if (value instanceof Date) value = value.toISOString();
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split("-").map(Number);
    return { y, m, d, wd: new Date(Date.UTC(y, m - 1, d)).getUTCDay(), H: 0, M: 0 };
  }
  const t = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : value + "Z");
  const p = {};
  for (const { type, value: v } of new Intl.DateTimeFormat("en-US", {
    timeZone: prefs.tz,
    year: "numeric",
    month: "numeric",
    day: "numeric",
    weekday: "short",
    hour: "numeric",
    minute: "numeric",
    hourCycle: "h23",
  }).formatToParts(t))
    p[type] = v;
  return {
    y: +p.year,
    m: +p.month,
    d: +p.day,
    wd: WEEKDAYS.indexOf(p.weekday),
    H: +p.hour % 24,
    M: +p.minute,
  };
}

function datePart({ y, m, d }, withYear = true) {
  switch (prefs.date) {
    case "iso":
      return withYear ? `${y}-${pad(m)}-${pad(d)}` : `${pad(m)}-${pad(d)}`;
    case "dmy":
      return withYear ? `${pad(d)}/${pad(m)}/${y}` : `${pad(d)}/${pad(m)}`;
    case "mdy":
      return withYear ? `${pad(m)}/${pad(d)}/${y}` : `${pad(m)}/${pad(d)}`;
    default:
      return withYear ? `${d} ${MONTHS[m - 1]} ${y}` : `${d} ${MONTHS[m - 1]}`;
  }
}

function timePart({ H, M }) {
  if (prefs.time === "12h") return `${H % 12 || 12}:${pad(M)} ${H < 12 ? "am" : "pm"}`;
  return `${pad(H)}:${pad(M)}`;
}

// A moment: "26 Oct 2026, 17:30".
export function dateTime(value) {
  if (!value) return "never";
  const p = parts(value);
  return `${datePart(p)}, ${timePart(p)}`;
}

// A day: "26 Oct 2026". Options: weekday ("short" | "long"), year (false = leave it out).
export function formatDate(value, { weekday, year = true } = {}) {
  if (!value) return "–";
  const p = parts(value);
  const day = datePart(p, year);
  if (!weekday) return day;
  return `${(weekday === "long" ? LONG_WEEKDAYS : WEEKDAYS)[p.wd]} ${day}`;
}

// Day and month only, for chart axes and compact lists: "26 Oct" / "10-26" / "26/10" / "10/26".
export function shortDate(value) {
  return formatDate(value, { year: false });
}

// The time of day of a moment: "17:30" / "5:30 pm".
export function timeOfDay(value) {
  return value ? timePart(parts(value)) : "";
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
