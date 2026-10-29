import { HeartPulse } from "lucide-react";
import { useEffect, useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";

// Shown wherever health conditions or plans are (backend health.DISCLAIMER says the same).
export const DISCLAIMER =
  "CoachQuest is not medical advice. Always consult a doctor or other qualified health professional before " +
  "starting or changing training, especially with a medical condition or injury. Stop and get help if you feel " +
  "chest pain, dizziness, unusual shortness of breath or pain.";

export function MedicalDisclaimer({ className = "" }) {
  return <p className={`small muted medical-disclaimer ${className}`}>⚕️ {DISCLAIMER}</p>;
}

const SIDES = [
  ["", "side?"],
  ["left", "left"],
  ["right", "right"],
  ["both", "both"],
];

// Health conditions (backend health.py): the athlete ticks and saves them in Profile; a coach with
// the plans scope sees them read only on the athlete's Plans tab. Friends never do (404: nothing shown).
export default function HealthConditions({ id = "me" }) {
  const self = id === "me";
  const res = useApi(`/api/athletes/${id}/health`);
  const [list, setList] = useState([]);
  const [accept, setAccept] = useState(false);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (res.data) setList(res.data.conditions);
  }, [res.data]);
  if (!res.data) return null;
  const { catalog, disclaimer_accepted_at: accepted } = res.data;
  const label = Object.fromEntries(catalog.flatMap((g) => g.conditions.map((c) => [c.id, c])));
  const heart = new Set(catalog.find((g) => g.group.startsWith("Heart"))?.conditions.map((c) => c.id));

  if (!self) {
    return (
      <section className="card">
        <h2>
          <HeartPulse size={18} /> Health conditions
        </h2>
        {list.length ? (
          <ul className="small health-list">
            {list.map((c) => (
              <li key={c.id}>
                <strong>{label[c.id]?.label}</strong>
                {c.side && ` (${c.side})`} · {c.status === "past" ? "in the past" : "current"}
                {c.cleared === true && " · cleared by a doctor"}
                {c.cleared === false && " · not cleared by a doctor"}
                {c.note && <span className="muted"> · {c.note}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted small">None ticked.</p>
        )}
        <p className="small muted">Only the athlete changes these. The AI coach plans around them.</p>
        <MedicalDisclaimer />
      </section>
    );
  }

  const ticked = (cid) => list.find((c) => c.id === cid);
  const toggle = (cid) => {
    setMsg(null);
    if (ticked(cid)) return setList(list.filter((c) => c.id !== cid));
    if (heart.has(cid) && !confirm(`${label[cid].label}\n\n${DISCLAIMER}\n\nAdd it?`)) return;
    setList([...list, { id: cid, side: null, status: "current", cleared: null, note: "" }]);
  };
  const edit = (cid, changes) => {
    setMsg(null);
    setList(list.map((c) => (c.id === cid ? { ...c, ...changes } : c)));
  };
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/api/me/health", { method: "PUT", body: { conditions: list, accept_disclaimer: accept } });
      setMsg({ ok: "Saved. The AI coach uses them the next time it plans." });
      res.reload();
    } catch (err) {
      setMsg({ error: err.message });
    }
    setBusy(false);
  };
  const needsAccept = !accepted && list.length > 0;
  return (
    <section className="card">
      <h2>
        <HeartPulse size={18} /> Health conditions
      </h2>
      <div className="disclaimer-box">
        <strong>⚕️ Not medical advice.</strong> {DISCLAIMER}
      </div>
      <p className="muted small">
        Tick what applies, now or in the past, so the AI coach plans around it (for example no jumps with a knee
        problem, or power instead of heart rate on beta blockers). Optional, and private: only you and coaches you
        share plans with see them, never friends.
      </p>
      <form onSubmit={save}>
        {catalog.map((g) => (
          <fieldset key={g.group} className="health-group">
            <legend className="small strong-label">{g.group}</legend>
            {g.conditions.map((c) => {
              const t = ticked(c.id);
              return (
                <div key={c.id} className={`health-row ${t ? "on" : ""}`}>
                  <label className="check">
                    <input type="checkbox" checked={!!t} onChange={() => toggle(c.id)} /> {c.label}
                  </label>
                  {t && (
                    <div className="row wrap tight health-details">
                      {c.sided && (
                        <select
                          aria-label="Side"
                          value={t.side || ""}
                          onChange={(e) => edit(c.id, { side: e.target.value || null })}
                        >
                          {SIDES.map(([v, l]) => (
                            <option key={v} value={v}>
                              {l}
                            </option>
                          ))}
                        </select>
                      )}
                      <select aria-label="Current or past" value={t.status} onChange={(e) => edit(c.id, { status: e.target.value })}>
                        <option value="current">current</option>
                        <option value="past">in the past</option>
                      </select>
                      <select
                        aria-label="Cleared by a doctor"
                        value={t.cleared == null ? "" : String(t.cleared)}
                        onChange={(e) => edit(c.id, { cleared: e.target.value === "" ? null : e.target.value === "true" })}
                      >
                        <option value="">doctor: not asked</option>
                        <option value="true">doctor cleared me to train</option>
                        <option value="false">not cleared yet</option>
                      </select>
                      <input
                        className="grow"
                        value={t.note}
                        maxLength={200}
                        placeholder={c.id === "other" ? "What is it? (needed)" : "Note, e.g. meniscus, 2025"}
                        required={c.id === "other"}
                        onChange={(e) => edit(c.id, { note: e.target.value })}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </fieldset>
        ))}
        {needsAccept && (
          <label className="check small">
            <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} required /> I have
            read the note above: CoachQuest is not medical advice, and I'll check my training with a doctor.
          </label>
        )}
        <div className="row">
          <button className="btn primary" disabled={busy}>
            {busy ? "Saving…" : "Save health conditions"}
          </button>
          {msg?.ok && <span className="ok-text small">{msg.ok}</span>}
        </div>
        {msg?.error && <div className="error">{msg.error}</div>}
      </form>
    </section>
  );
}
