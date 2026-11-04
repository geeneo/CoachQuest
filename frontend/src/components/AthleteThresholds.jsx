import { useState } from "react";
import { api } from "../lib/api.js";
import { dateTime } from "../lib/format.js";
import ThresholdHistory from "./ThresholdHistory.jsx";

const FIELDS = [
  ["ftp_watts", "FTP (watts)", "Rides with power are scored by it"],
  ["run_ftp_watts", "Run threshold power (watts)", "Runs with power; heart rate until it's set"],
  ["lthr_bpm", "Lactate threshold HR (bpm)", "Sessions without power, strength and walks"],
  ["max_hr_bpm", "Max HR (bpm)", ""],
];

function source(a, k) {
  const s = a.profile_sources?.[k];
  if (s?.source === "coach") return `Set by ${s.by || "a coach"}, ${dateTime(s.at)}`;
  if (s?.source === "garmin") return `From Garmin, ${dateTime(s.at)}`;
  if (a[k] != null) return "Entered by the athlete";
  return null;
}

// A coach with the profile share sets an athlete's thresholds (training load and the plan's zones use them).
export default function AthleteThresholds({ id, athlete, readOnly }) {
  const [a, setA] = useState(athlete);
  const [form, setForm] = useState(() => Object.fromEntries(FIELDS.map(([k]) => [k, athlete[k] ?? ""])));
  const [msg, setMsg] = useState(null);
  const [correct, setCorrect] = useState(false);

  const save = async (e) => {
    e.preventDefault();
    setMsg(null);
    const body = {};
    for (const [k] of FIELDS) {
      const v = form[k] === "" ? null : Number(form[k]);
      // A correction sends the thresholds even when unchanged, so they count for every earlier workout.
      if (v !== (a[k] ?? null) || (correct && k !== "max_hr_bpm")) body[k] = v;
    }
    if (!Object.keys(body).length) return setMsg({ ok: "Nothing changed." });
    if (correct) body.correct_history = true;
    try {
      const out = await api(`/api/athletes/${id}/thresholds`, { method: "PATCH", body });
      setA({ ...a, ...out });
      setMsg({
        ok: correct
          ? "Saved for every workout, earlier ones too. Training load was recalculated."
          : "Saved. A change counts from today; earlier workouts keep theirs. Training load was recalculated.",
      });
      setCorrect(false);
    } catch (err) {
      setMsg({ error: err.message });
    }
  };

  return (
    <>
      <form className="card grid-form" onSubmit={save}>
        <h2 className="wide">Thresholds</h2>
        <p className="small muted wide">
          {a.display_name}'s thresholds for training load (TSS, fitness and fatigue) and the AI coach's zones. They see in
          their Profile that you set them.
        </p>
        {FIELDS.map(([k, label, hint]) => (
          <label key={k}>
            {label}
            <input
              type="number"
              value={form[k]}
              disabled={readOnly}
              onChange={(e) => setForm({ ...form, [k]: e.target.value })}
            />
            {hint && <span className="hint">{hint}</span>}
            {source(a, k) && <span className="hint source">{source(a, k)}</span>}
          </label>
        ))}
        {!readOnly && (
          <label className="check wide">
            <input type="checkbox" checked={correct} onChange={(e) => setCorrect(e.target.checked)} />
            Correct earlier workouts too: the old values were wrong (not a change in fitness), so these count for
            every workout
          </label>
        )}
        {msg?.ok && <div className="ok wide">{msg.ok}</div>}
        {msg?.error && <div className="error wide">{msg.error}</div>}
        {!readOnly && <button className="btn primary">Save</button>}
      </form>
      <ThresholdHistory
        key={JSON.stringify(a.threshold_history || [])}
        user={a}
        url={`/api/athletes/${id}/threshold-history`}
        readOnly={readOnly}
        onSaved={(out) => {
          const next = { ...a, ...out };
          setA(next);
          setForm(Object.fromEntries(FIELDS.map(([k]) => [k, next[k] ?? ""])));
        }}
      />
    </>
  );
}
