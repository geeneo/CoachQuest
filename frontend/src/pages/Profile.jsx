import { useEffect, useState } from "react";
import TrainingPreferences from "../components/TrainingPreferences.jsx";
import HealthConditions from "../components/HealthConditions.jsx";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { DATE_FORMATS, dateTime, formatDate } from "../lib/format.js";
import { EVENT as THEME_EVENT, getTheme, setTheme } from "../lib/theme.js";
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
    date_format: user.date_format || "d_mon_y",
    time_format: user.time_format || "24h",
    birth_date: user.birth_date || "",
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
      date_format: form.date_format,
      time_format: form.time_format,
      notify_sharing: form.notify_sharing,
      notify_comments: form.notify_comments,
      ...(form.timezone ? { timezone: form.timezone } : {}),
      // Only when changed, so saving other fields doesn't mark a Garmin birth date as typed in.
      ...((form.birth_date || null) !== (user.birth_date || null) ? { birth_date: form.birth_date || null } : {}),
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
        <label>
          Birth date
          <input type="date" value={form.birth_date} onChange={set("birth_date")} max={new Date().toISOString().slice(0, 10)} />
          <span className="hint">
            {form.birth_date ? `${formatDate(form.birth_date)}. ` : ""}
            {user.age != null ? `Age ${user.age}. ` : ""}Coaches who see your profile, and the AI coach, get your age only.
          </span>
          {sourceLine(user, "birth_date") && <span className="hint source">{sourceLine(user, "birth_date")}</span>}
        </label>
        <TimezoneField value={form.timezone} onChange={(timezone) => setForm({ ...form, timezone })} />
        <label>
          Date format
          <select value={form.date_format} onChange={set("date_format")}>
            {Object.entries(DATE_FORMATS).map(([k, example]) => (
              <option key={k} value={k}>
                {example}
              </option>
            ))}
          </select>
          <span className="hint">Used on every page, in emails and in the AI coach's notes.</span>
        </label>
        <label>
          Time format
          <select value={form.time_format} onChange={set("time_format")}>
            <option value="24h">24-hour (17:30)</option>
            <option value="12h">12-hour (5:30 pm)</option>
          </select>
          <span className="hint">Times are in your timezone. Date pickers follow your browser's language.</span>
        </label>
        {user.emails_disabled && (
          <div className="wide small warn-text">
            The administrator has turned off emails to your account, so the email options below have no effect.
            Password reset links still reach you.
          </div>
        )}
        <label className="check wide">
          <input
            type="checkbox"
            checked={form.notify_sharing}
            disabled={user.emails_disabled}
            onChange={(e) => setForm({ ...form, notify_sharing: e.target.checked })}
          />
          Email me when someone invites me as their coach, accepts my invitation, or changes or stops sharing
        </label>
        <label className="check wide">
          <input
            type="checkbox"
            checked={form.notify_comments}
            disabled={user.emails_disabled}
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
      <HealthConditions />
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
      <PauseAccount email={user.email} onPaused={() => setUser(null)} />
    </>
  );
}

// Pause your own account: a step before deleting it. An admin turns it back on.
function PauseAccount({ email, onPaused }) {
  const [confirmEmail, setConfirmEmail] = useState("");
  const [error, setError] = useState(null);
  const pause = async (e) => {
    e.preventDefault();
    if (!confirm("Pause your account? You'll be signed out, and only an admin can turn it back on.")) return;
    try {
      await api("/api/auth/pause", { method: "POST", body: { confirm_email: confirmEmail } });
      onPaused();
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <section className="card">
      <h2>Pause my account</h2>
      <p className="muted small">
        Signs you out everywhere and stops syncing, AI notes, emails and sending workouts. Your data, plans and sharing
        stay; your coaches see the account as paused. Ask your CoachQuest administrator to turn it back on.
      </p>
      <form className="row wrap" onSubmit={pause}>
        <input
          placeholder={`Type ${email} to confirm`}
          value={confirmEmail}
          onChange={(e) => setConfirmEmail(e.target.value)}
          autoComplete="off"
        />
        <button className="btn danger" disabled={confirmEmail.trim().toLowerCase() !== email}>
          Pause my account
        </button>
      </form>
      {error && <div className="error small">{error}</div>}
    </section>
  );
}

function Appearance() {
  const [theme, setChoice] = useState(getTheme);
  useEffect(() => {
    // The header switch changes it too.
    const update = () => setChoice(getTheme());
    window.addEventListener(THEME_EVENT, update);
    return () => window.removeEventListener(THEME_EVENT, update);
  }, []);
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
  const labels = {
    ftp_watts: ["FTP", "W"],
    lthr_bpm: ["Lactate threshold HR", "bpm"],
    max_hr_bpm: ["Max HR", "bpm"],
    weight_kg: ["Weight", "kg"],
    birth_date: ["Birth date", ""],
  };
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
        your latest weigh-in, and your birth date. This also happens on every Garmin sync while "Thresholds → Profile",
        "Weight → Profile" and "Birth date → Profile" are ticked under Connections; a value you type here is kept until
        Garmin reports a new one. <strong>Strava</strong> can't fill these: CoachQuest only has read access to your
        activities, Strava keeps FTP and weight behind an extra permission, and its API has no birth date.
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
