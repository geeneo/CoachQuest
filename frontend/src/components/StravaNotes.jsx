import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";

const MODES = [
  ["off", "Off", "Nothing is written to Strava."],
  ["manual", "Per activity", "A button on each Strava activity under My training → Activities: you choose which."],
  ["auto", "Automatically", "After each Strava sync, every activity that matches a planned day gets the lines."],
];

// Profile → Strava: the plan in your Strava activity descriptions (backend strava_notes.py).
export default function StravaNotes() {
  const { setUser } = useAuth();
  const res = useApi("/api/me/strava-notes");
  const [error, setError] = useState(null);
  const s = res.data;
  if (!s) return null;
  const choose = async (mode) => {
    setError(null);
    try {
      setUser(await api("/api/me", { method: "PATCH", body: { strava_notes: mode } }));
      res.reload();
    } catch (err) {
      setError(err.message);
    }
  };
  const allow = async () => {
    try {
      const { url } = await api("/api/connections/strava/authorize?write=true", { method: "POST" });
      window.location.href = url;
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <section className="card">
      <h2>Your plan on Strava</h2>
      <p className="muted small">
        Add what was planned and how it went to your Strava activity's description, under your own text. Indoor
        workouts also get their shape (📊), if your admin left that on. Written
        from your CoachQuest plan; your own words stay, and the lines are replaced (never added twice) if the day
        changes.
      </p>
      <pre className="strava-note-example">
        {`🎯 Planned: Indoor · Sweet spot 3×10 (1h 05m)\n📊 ▂▂▃▃▄▆▆▆▃▂▅▆▆▅▂▃▆▆▆▄▂▃▂▂▁\n✅ Goal met\n📋 Training plan by CoachQuest · ${s.host}`}
      </pre>
      <div className="chips" role="radiogroup" aria-label="Plan on Strava">
        {MODES.map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={s.mode === value}
            className={`chip ${s.mode === value ? "on" : ""}`}
            onClick={() => choose(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="small">{MODES.find(([v]) => v === s.mode)?.[2]}</p>
      {s.mode !== "off" &&
        (!s.connected ? (
          <p className="small warn-text">
            Connect Strava first on <Link to="/connections">Connections</Link>.
          </p>
        ) : (
          !s.can_write && (
            <div className="row wrap">
              <span className="small warn-text">Strava hasn't allowed CoachQuest to change your activities yet.</span>
              <button type="button" className="btn small" onClick={allow}>
                Allow on Strava
              </button>
            </div>
          )
        ))}
      {s.mode !== "off" && s.can_write && <p className="small ok-text">✓ Strava lets CoachQuest add the lines.</p>}
      {error && <div className="error">{error}</div>}
    </section>
  );
}
