import { useState } from "react";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { dateTime } from "../lib/format.js";
import { getTheme, setTheme } from "../lib/theme.js";

const NUMBER_FIELDS = [
  ["ftp_watts", "FTP (watts)", "Used for power-based TSS"],
  ["lthr_bpm", "Lactate threshold HR (bpm)", "Used for heart-rate TSS when there is no power"],
  ["max_hr_bpm", "Max HR (bpm)", ""],
  ["weight_kg", "Weight (kg)", "Updated from Garmin when the Weight option is on under Connections"],
];

export default function Profile() {
  const { user, setUser } = useAuth();
  const [form, setForm] = useState(() => ({
    display_name: user.display_name,
    goal: user.goal || "",
    ...Object.fromEntries(NUMBER_FIELDS.map(([k]) => [k, user[k] ?? ""])),
  }));
  const [msg, setMsg] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const save = async (e) => {
    e.preventDefault();
    setMsg(null);
    const body = { display_name: form.display_name, goal: form.goal || null };
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
            {k === "weight_kg" && user.weight_source === "garmin" && (
              <span className="hint">From Garmin, weighed {dateTime(user.weight_updated_at)}</span>
            )}
            {user.profile_sources?.[k]?.source === "garmin" && (
              <span className="hint">From Garmin, {dateTime(user.profile_sources[k].at)}</span>
            )}
          </label>
        ))}
        <label className="wide">
          Goal
          <textarea rows={3} value={form.goal} onChange={set("goal")} maxLength={2000} placeholder="What are you training for?" />
        </label>
        {msg?.ok && <div className="ok wide">{msg.ok}</div>}
        {msg?.error && <div className="error wide">{msg.error}</div>}
        <button className="btn primary">Save</button>
      </form>
      <Appearance />
      <ChangePassword />
      <section className="card">
        <h2>Security</h2>
        <p className="muted small">Signed in as {user.email}.</p>
        <button className="btn danger" onClick={logoutAll}>
          Sign out everywhere
        </button>
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
