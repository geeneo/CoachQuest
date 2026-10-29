import { Check, ExternalLink, Plus, Search, Trash2, Users } from "lucide-react";
import { useState } from "react";
import Segments, { KIND, stats } from "../components/Segments.jsx";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";

// Routes: your favourite Strava routes and segments (the AI coach plans rides on them), and the ones
// athletes shared with everyone in CoachQuest, to add to your own favourites in one click.
export default function Routes() {
  const [version, setVersion] = useState(0); // a shared one added: reload your favourites
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Routes</h1>
          <p className="muted small">
            Your favourite routes and segments, and the ones other athletes share. Share yours with the switch on each
            favourite.
          </p>
        </div>
      </div>
      <Segments key={version} id="me" canShare />
      <SharedRoutes onAdded={() => setVersion((v) => v + 1)} />
    </>
  );
}

function SharedRoutes({ onAdded }) {
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const params = new URLSearchParams({ q, ...(kind && { kind }) });
  const res = useApi(`/api/shared-routes?${params}`);
  const [error, setError] = useState(null);
  const act = async (fn) => {
    setError(null);
    try {
      await fn();
      res.reload();
    } catch (e) {
      setError(e.message);
    }
  };
  const add = (f) =>
    act(async () => {
      await api("/api/athletes/me/segments/copy", { method: "POST", body: { segment_id: f.id } });
      onAdded();
    });
  const unshare = (f) =>
    confirm(`Take "${f.name}" off the shared list for everyone? Favourites stay.`) &&
    act(() => api(`/api/shared-routes/${f.id}`, { method: "DELETE" }));
  const list = res.data || [];
  return (
    <section className="card">
      <h2>
        <Users size={18} /> Shared by athletes
      </h2>
      <p className="muted small">
        Routes and segments other CoachQuest athletes share. Add one and it's yours: the AI coach plans on it like your
        own. Shared with their uses and notes; change them after adding.
      </p>
      <div className="row wrap">
        <label className="inline grow search">
          <Search size={16} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, town or use, e.g. hill repeats" />
        </label>
        <div className="chips tight" role="group" aria-label="Show">
          {[
            ["", "Both"],
            ["route", "Routes"],
            ["segment", "Segments"],
          ].map(([v, label]) => (
            <button key={v} type="button" className={`chip small ${kind === v ? "on" : ""}`} onClick={() => setKind(v)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {res.data && !list.length && (
        <p className="muted small">
          {q || kind ? "Nothing shared matches." : "Nothing shared yet. Be the first: switch on Share on a favourite."}
        </p>
      )}
      <ul className="list segments">
        {list.map((f) => (
          <li key={f.id}>
            <span className="grow">
              {KIND[f.kind === "segment" ? "segment" : "route"][1]}{" "}
              <a href={f.url} target="_blank" rel="noreferrer">
                {f.name} <ExternalLink size={12} />
              </a>
              <span className="muted small">{stats(f).map((x) => ` · ${x}`).join("")}</span>
              {f.uses.length > 0 && (
                <div className="chips tight">
                  {f.uses.map((u) => (
                    <span key={u} className="chip small static">
                      {u}
                    </span>
                  ))}
                </div>
              )}
              {f.notes && <div className="small muted">{f.notes}</div>}
              <div className="small muted">
                Shared by {f.shared_by.slice(0, 3).join(", ")}
                {f.shared_count > f.shared_by.slice(0, 3).length &&
                  ` and ${f.shared_count - f.shared_by.slice(0, 3).length} more`}
              </div>
            </span>
            {f.have ? (
              <span className="ok-text small">
                <Check size={14} /> In your favourites
              </span>
            ) : (
              <button type="button" className="btn small" onClick={() => add(f)}>
                <Plus size={14} /> Add to my favourites
              </button>
            )}
            {user.is_admin && (
              <button
                type="button"
                className="icon-btn"
                title="Take off the shared list (admin)"
                aria-label={`Take ${f.name} off the shared list`}
                onClick={() => unshare(f)}
              >
                <Trash2 size={14} />
              </button>
            )}
          </li>
        ))}
      </ul>
      {error && <div className="error">{error}</div>}
    </section>
  );
}
