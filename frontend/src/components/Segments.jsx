import { ExternalLink, Mountain, Trash2 } from "lucide-react";
import { useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";

// Strava segments the athlete trains on (backend segments.py): the AI coach puts them on hill-repeat days.
export default function Segments({ id, readOnly }) {
  const url = `/api/athletes/${id}/segments`;
  const res = useApi(url);
  const [draft, setDraft] = useState({ link: "", name: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const call = async (path, method, body) => {
    setError(null);
    try {
      await api(url + path, { method, body });
      res.reload();
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    }
  };
  const add = async (e) => {
    e.preventDefault();
    setBusy(true);
    if (await call("", "POST", draft)) setDraft({ link: "", name: "", notes: "" });
    setBusy(false);
  };
  const list = res.data || [];
  return (
    <section className="card">
      <h2>
        <Mountain size={18} /> Strava segments
      </h2>
      <p className="muted small">
        Climbs and stretches you train on, e.g. the hill for hill repeats. The AI coach puts them on matching days: ride
        it outdoors, or the same efforts indoors. Each plan day shows the segment as a link to Strava.
      </p>
      {list.length > 0 && (
        <ul className="list segments">
          {list.map((s) => (
            <li key={s.id}>
              <span>
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.name} <ExternalLink size={12} />
                </a>
                <span className="muted small">
                  {[
                    s.distance_m && `${(s.distance_m / 1000).toFixed(1)} km`,
                    s.avg_grade != null && `${s.avg_grade}%`,
                    s.elevation_m && `${s.elevation_m} m up`,
                    s.city,
                  ]
                    .filter(Boolean)
                    .map((x) => ` · ${x}`)
                    .join("")}
                </span>
                {s.notes && <div className="small muted">{s.notes}</div>}
              </span>
              {!readOnly && (
                <button
                  className="icon-btn"
                  title="Remove"
                  aria-label={`Remove ${s.name}`}
                  onClick={() => confirm(`Remove ${s.name}?`) && call(`/${s.id}`, "DELETE")}
                >
                  <Trash2 size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {!list.length && <p className="muted small">No segments saved yet.</p>}
      {!readOnly && (
        <form className="row wrap" onSubmit={add}>
          <input
            className="grow"
            value={draft.link}
            onChange={(e) => setDraft({ ...draft, link: e.target.value })}
            placeholder="Strava segment link, e.g. https://www.strava.com/segments/1234567"
            required
          />
          <input
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            placeholder="Name (optional)"
            maxLength={120}
          />
          <input
            className="grow"
            value={draft.notes}
            onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
            placeholder="How you use it, e.g. hill repeats, 4-8 times"
            maxLength={300}
          />
          <button className="btn" disabled={busy}>
            {busy ? "Adding…" : "Add segment"}
          </button>
        </form>
      )}
      {error && <div className="error">{error}</div>}
    </section>
  );
}
