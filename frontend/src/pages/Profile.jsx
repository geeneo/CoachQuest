import { useState } from "react";
import TrainingPreferences from "../components/TrainingPreferences.jsx";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { dateTime } from "../lib/format.js";
import { getTheme, setTheme } from "../lib/theme.js";
import { MySignIns } from "../components/SignInLog.jsx";

const NUMBER_FIELDS = [
  ["ftp_watts", "FTP (watts)", "Used for power-based TSS"],
  ["lthr_bpm", "Lactate threshold HR (bpm)", "Used for heart-rate TSS when there is no power"],
  ["max_hr_bpm", "Max HR (bpm)", ""],
  ["weight_kg", "Weight (kg)", ""],
];
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

// Where a profile number came from, shown under the field.
function sourceLine(user, k) {
  if (k === "weight_kg" && user.weight_source === "garmin") return `From Garmin, weighed ${dateTime(user.weight_updated_at)}`;
  if (user.profile_sources?.[k]?.source === "garmin") return `From Garmin, ${dateTime(user.profile_sources[k].at)}`;
  if (user[k] != null) return "Entered by you";
  return null;
}

export default function Profile() {
  const { user, setUser } = useAuth();
  const [form, setForm] = useState(() => ({
    display_name: user.display_name,
    goal: user.goal || "",
    week_start: user.week_start ?? 0,
    notify_sharing: user.notify_sharing ?? true,
    notify_comments: user.notify_comments ?? true,
    timezone: user.timezone || "",
    ...Object.fromEntries(NUMBER_FIELDS.map(([k]) => [k, user[k] ?? ""])),
  }));
  const [msg, setMsg] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const save = async (e) => {
    e.preventDefault();
    setMsg(null);
    const body = {
      display_name: form.display_name,
      goal: form.goal || null,
      week_start: Number(form.week_start),
      notify_sharing: form.notify_sharing,
      notify_comments: form.notify_comments,
      ...(form.timezone ? { timezone: form.timezone } : {}),
    };
    for (const [k] of NUMBER_FIELDS) body[k] = form[k] === "" ? null : Number(form[k]);
    try {
      setUser(await api("/api/me", { method: "PATCH", body }));
      setMsg({ ok: "Saved. Training load was recalculated." });
    } catch (err) {
      setMsg({ error: err.message });
    }
  };

  const logoutAll = async () => {
    if (!confirm("Sign out on every device?")) return;
    await api("/api/auth/logout-all", { method: "POST" });
    setUser(null);
  };

  return (
    <>
      <h1>Profile</h1>
      <form className="card grid-form" onSubmit={save}>
        <label>
          Name
          <input value={form.display_name} onChange={set("display_name")} required maxLength={100} />
        </label>
        {NUMBER_FIELDS.map(([k, label, hint]) => (
          <label key={k}>
            {label}
            <input type="number" value={form[k]} onChange={set(k)} step="any" />
            {hint && <span className="hint">{hint}</span>}
            {sourceLine(user, k) && <span className="hint source">{sourceLine(user, k)}</span>}
          </label>
        ))}
        <label>
          My week starts on
          <select value={form.week_start} onChange={set("week_start")}>
            {WEEKDAYS.map((d, i) => (
              <option key={d} value={i}>
                {d}
              </option>
            ))}
          </select>
          <span className="hint">Weekly totals, charts, plans and weekly reviews use this.</span>
        </label>
        <TimezoneField value={form.timezone} onChange={(timezone) => setForm({ ...form, timezone })} />
        <label className="check wide">
          <input
            type="checkbox"
            checked={form.notify_sharing}
            onChange={(e) => setForm({ ...form, notify_sharing: e.target.checked })}
          />
          Email me when someone invites me as their coach, accepts my invitation, or changes or stops sharing
        </label>
        <label className="check wide">
          <input
            type="checkbox"
            checked={form.notify_comments}
            onChange={(e) => setForm({ ...form, notify_comments: e.target.checked })}
          />
          Email me when someone comments on my training plan, or on a plan of an athlete I coach
        </label>
        <label className="wide">
          Goal
          <textarea rows={3} value={form.goal} onChange={set("goal")} maxLength={2000} placeholder="What are you training for?" />
        </label>
        {msg?.ok && <div className="ok wide">{msg.ok}</div>}
        {msg?.error && <div className="error wide">{msg.error}</div>}
        <button className="btn primary">Save</button>
      </form>
      <PullFromGarmin
        onPulled={(u) => {
          setUser(u);
          setForm((f) => ({ ...f, ...Object.fromEntries(NUMBER_FIELDS.map(([k]) => [k, u[k] ?? ""])) }));
        }}
      />
      <TrainingPreferences />
      <Appearance />
      <ChangePassword />
      <section className="card">
        <h2>Security</h2>
        <p className="muted small">Signed in as {user.email}.</p>
        <button className="btn danger" onClick={logoutAll}>
          Sign out everywhere
        </button>
        <MySignIns />
      </section>
    </>
  );
}

function Appearance() {
  const [theme, setChoice] = useState(getTheme);
  const choose = (t) => {
    setTheme(t);
    setChoice(t);
  };
  return (
    <section className="card">
      <h2>Appearance</h2>
      <div className="chips" role="radiogroup" aria-label="Theme">
        {[
          ["system", "System"],
          ["light", "Light"],
          ["dark", "Dark"],
        ].map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={theme === value}
            className={`chip ${theme === value ? "on" : ""}`}
            onClick={() => choose(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="hint">Saved in this browser. System follows your device's light or dark setting.</p>
    </section>
  );
}

function ChangePassword() {
  const empty = { current_password: "", new_password: "", repeat: "" };
  const [form, setForm] = useState(empty);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setMsg(null);
    if (form.new_password !== form.repeat) {
      setMsg({ error: "The new passwords don't match." });
      return;
    }
    setBusy(true);
    try {
      await api("/api/auth/password", {
        method: "POST",
        body: { current_password: form.current_password, new_password: form.new_password },
      });
      setForm(empty);
      setMsg({ ok: "Password changed. Your other devices have been signed out." });
    } catch (err) {
      setMsg({ error: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2>Change password</h2>
      <form className="stack" onSubmit={submit}>
        <label>
          Current password
          <input type="password" autoComplete="current-password" value={form.current_password} onChange={set("current_password")} required />
        </label>
        <label>
          New password
          <input type="password" autoComplete="new-password" minLength={12} value={form.new_password} onChange={set("new_password")} required />
          <span className="hint">At least 12 characters.</span>
        </label>
        <label>
          New password again
          <input type="password" autoComplete="new-password" minLength={12} value={form.repeat} onChange={set("repeat")} required />
        </label>
        {msg?.ok && <div className="ok">{msg.ok}</div>}
        {msg?.error && <div className="error">{msg.error}</div>}
        <button className="btn primary" disabled={busy}>
          Change password
        </button>
      </form>
    </section>
  );
}

function PullFromGarmin({ onPulled }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const labels = { ftp_watts: ["FTP", "W"], lthr_bpm: ["Lactate threshold HR", "bpm"], max_hr_bpm: ["Max HR", "bpm"], weight_kg: ["Weight", "kg"] };
  const pull = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api("/api/me/profile/pull-garmin", { method: "POST" });
      setResult(r);
      onPulled(r.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card">
      <div className="row between">
        <h2>Fill from Garmin and Strava</h2>
        <button className="btn" onClick={pull} disabled={busy}>
          {busy ? "Asking Garmin…" : "Pull from Garmin now"}
        </button>
      </div>
      <p className="muted small">
        <strong>Garmin</strong> fills FTP, lactate threshold HR and max HR (from your Garmin power and heart-rate zones)
        and your latest weigh-in. This also happens on every Garmin sync while "Thresholds → Profile" and "Weight →
        Profile" are ticked under Connections; a number you type here is kept until Garmin reports a new one.{" "}
        <strong>Strava</strong> can't fill these: CoachQuest only has read access to your activities, and Strava keeps
        FTP and weight behind an extra permission.
      </p>
      {error && <div className="error">{error}</div>}
      {result && (
        <ul className="pull-result">
          {Object.entries(labels).map(([k, [label, unit]]) => (
            <li key={k}>
              {label}:{" "}
              {result.found[k] == null ? (
                <span className="muted">not set in Garmin</span>
              ) : (
                <strong>
                  {result.found[k]} {unit}
                  {result.changed.includes(k) ? " · updated" : " · unchanged"}
                </strong>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
const ZONES = (() => {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return [BROWSER_TZ];
  }
})();

function TimezoneField({ value, onChange }) {
  return (
    <label>
      My timezone
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {!value && <option value="">Not set (UTC)</option>}
        {ZONES.map((z) => (
          <option key={z} value={z}>
            {z.replaceAll("_", " ")}
          </option>
        ))}
      </select>
      <span className="hint">
        Decides which day a ride counts on and what "today" is in plans and the calendar.
        {value !== BROWSER_TZ && (
          <>
            {" "}
            <button type="button" className="link-btn inline-link" onClick={() => onChange(BROWSER_TZ)}>
              Use this device's ({BROWSER_TZ})
            </button>
          </>
        )}
      </span>
    </label>
  );
}
