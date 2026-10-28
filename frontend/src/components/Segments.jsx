import { ExternalLink, Mountain, Route, Trash2 } from "lucide-react";
import { useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { duration } from "../lib/format.js";

const KIND = {
  route: [
    "Routes",
    "🗺",
    "Whole rides: the long-ride loop, the easy spin, also saved from a ride you did. The AI coach plans outdoor rides on them.",
  ],
  segment: ["Segments", "⛰", "Climbs and stretches for efforts: hill repeats, intervals, sprints."],
};

function stats(f) {
  return [
    f.distance_m && `${(f.distance_m / 1000).toFixed(f.kind === "route" ? 0 : 1)} km`,
    f.kind === "ride" && "from a ride",
    f.kind === "segment" && f.avg_grade != null && `${f.avg_grade}%`,
    f.elevation_m && `${f.elevation_m} m up`,
    f.est_minutes && `~${duration(f.est_minutes * 60)}`,
    f.sport === "run" && "run",
    f.city,
  ].filter(Boolean);
}

// Favourite Strava routes and segments (backend segments.py): the AI coach plans rides on them.
export default function Segments({ id, readOnly }) {
  const url = `/api/athletes/${id}/segments`;
  const res = useApi(url);
  const [draft, setDraft] = useState({ link: "", name: "", notes: "", uses: [] });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [fromStrava, setFromStrava] = useState(null); // null = closed, "loading", or a list
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
    if (await call("", "POST", draft)) setDraft({ link: "", name: "", notes: "", uses: [] });
    setBusy(false);
  };
  const openStrava = async () => {
    setFromStrava("loading");
    setError(null);
    try {
      setFromStrava(await api(`${url}/strava`));
    } catch (e) {
      setError(e.message);
      setFromStrava(null);
    }
  };
  const addFromStrava = async (f) => {
    const link = `https://www.strava.com/${f.kind === "route" ? "routes" : "segments"}/${f.strava_id}`;
    if (await call("", "POST", { link, name: f.name, uses: f.kind === "route" ? ["endurance"] : ["hill repeats"] }))
      setFromStrava(fromStrava.filter((x) => x !== f));
  };
  const d = res.data;
  const list = d?.favourites || [];
  const uses = d?.uses || [];
  return (
    <section className="card">
      <h2>
        <Mountain size={18} /> Favourite routes &amp; segments
      </h2>
      <p className="muted small">
        Where you ride. The AI coach plans your rides on them: a route for outdoor endurance and long rides, a segment
        for hill repeats and efforts (or the same efforts indoors). Tick what each is for. Plan days link to them in
        Strava.
      </p>
      {["route", "segment"].map((kind) => {
        // Rides saved from an activity are routes too.
        const group = list.filter((f) => f.kind === kind || (kind === "route" && f.kind === "ride"));
        if (!group.length) return null;
        return (
          <div key={kind} className="favourite-group">
            <h3>
              {KIND[kind][1]} {KIND[kind][0]} <span className="muted small">{KIND[kind][2]}</span>
            </h3>
            <ul className="list segments">
              {group.map((f) => (
                <li key={f.id}>
                  <span className="grow">
                    <a href={f.url} target="_blank" rel="noreferrer">
                      {f.name} <ExternalLink size={12} />
                    </a>
                    <span className="muted small">{stats(f).map((x) => ` · ${x}`).join("")}</span>
                    <div className="chips tight">
                      {(readOnly ? f.uses : uses).map((u) => (
                        <button
                          key={u}
                          type="button"
                          className={`chip small ${f.uses.includes(u) ? "on" : ""}`}
                          disabled={readOnly}
                          onClick={() =>
                            call(`/${f.id}`, "PATCH", {
                              uses: f.uses.includes(u) ? f.uses.filter((x) => x !== u) : [...f.uses, u],
                            })
                          }
                        >
                          {u}
                        </button>
                      ))}
                    </div>
                    {f.notes && <div className="small muted">{f.notes}</div>}
                  </span>
                  {!readOnly && (
                    <button
                      className="icon-btn"
                      title="Remove"
                      aria-label={`Remove ${f.name}`}
                      onClick={() => confirm(`Remove ${f.name} from favourites?`) && call(`/${f.id}`, "DELETE")}
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      {d && !list.length && <p className="muted small">No favourites yet.</p>}
      {!readOnly && (
        <>
          {d?.strava_linked && (
            <div className="row wrap">
              <button type="button" className="btn" onClick={openStrava} disabled={fromStrava === "loading"}>
                <Route size={16} /> {fromStrava === "loading" ? "Asking Strava…" : "From my Strava"}
              </button>
              <span className="muted small">Your starred segments and your routes on Strava.</span>
            </div>
          )}
          {Array.isArray(fromStrava) && (
            <div className="card inset">
              {fromStrava.length ? (
                <ul className="list segments">
                  {fromStrava.map((f) => (
                    <li key={`${f.kind}${f.strava_id}`}>
                      <span>
                        {KIND[f.kind][1]} <strong>{f.name}</strong>
                        <span className="muted small">{stats(f).map((x) => ` · ${x}`).join("")}</span>
                      </span>
                      <button type="button" className="btn small" onClick={() => addFromStrava(f)}>
                        Add
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted small">
                  Nothing new on Strava: star segments or save routes there, then look again. (Private routes stay
                  hidden.)
                </p>
              )}
              <button type="button" className="link-btn small" onClick={() => setFromStrava(null)}>
                Close
              </button>
            </div>
          )}
          <form className="stack favourite-form" onSubmit={add}>
            <div className="row wrap">
              <input
                className="grow"
                value={draft.link}
                onChange={(e) => setDraft({ ...draft, link: e.target.value })}
                placeholder="Strava route, segment or ride link, e.g. https://www.strava.com/activities/…"
                required
              />
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder="Name (optional)"
                maxLength={120}
              />
            </div>
            <div className="chips tight" aria-label="What it's for">
              {uses.map((u) => (
                <button
                  key={u}
                  type="button"
                  className={`chip small ${draft.uses.includes(u) ? "on" : ""}`}
                  onClick={() =>
                    setDraft({
                      ...draft,
                      uses: draft.uses.includes(u) ? draft.uses.filter((x) => x !== u) : [...draft.uses, u],
                    })
                  }
                >
                  {u}
                </button>
              ))}
            </div>
            <div className="row wrap">
              <input
                className="grow"
                value={draft.notes}
                onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
                placeholder="Notes for the coach, e.g. 4-8 repeats, easy back down"
                maxLength={300}
              />
              <button className="btn" disabled={busy}>
                {busy ? "Adding…" : "Add favourite"}
              </button>
            </div>
          </form>
        </>
      )}
      {error && <div className="error">{error}</div>}
    </section>
  );
}
