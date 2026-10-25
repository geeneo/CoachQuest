import { useState } from "react";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";

const NUMBER_FIELDS = [
  ["ftp_watts", "FTP (watts)", "Used for power-based TSS"],
  ["lthr_bpm", "Lactate threshold HR (bpm)", "Used for heart-rate TSS when there is no power"],
  ["max_hr_bpm", "Max HR (bpm)", ""],
  ["weight_kg", "Weight (kg)", ""],
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
