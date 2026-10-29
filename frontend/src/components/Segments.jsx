import { ExternalLink, Mountain, Route, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
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
  const [privateRoutes, setPrivateRoutes] = useState(true); // false: linked before private routes were asked for
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
      const { found, private_routes } = await api(`${url}/strava`);
      setPrivateRoutes(private_routes);
      setFromStrava(found);
    } catch (e) {
      setError(e.message);
      setFromStrava(null);
    }
  };
  const addFromStrava = async (items, uses) => {
    setError(null);
    try {
      const { added } = await api(`${url}/from-strava`, { method: "POST", body: { items, uses } });
      const done = new Set(added.map((a) => `${a.kind}:${a.strava_id}`));
      setFromStrava(fromStrava.filter((f) => !done.has(`${f.kind}:${f.strava_id}`)));
      res.reload();
      return added.length;
    } catch (e) {
      setError(e.message);
      return null;
    }
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
            <StravaPicker
              found={fromStrava}
              uses={uses}
              add={addFromStrava}
              close={() => setFromStrava(null)}
              note={!privateRoutes && <PrivateRoutesNote self={id === "me"} />}
            />
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

// The athlete's Strava routes and starred segments: filter, tick several (or a whole group), say what
// they're for, add them together (POST /segments/from-strava).
function StravaPicker({ found, uses, add, close, note }) {
  const [show, setShow] = useState("both"); // both | route | segment
  const [picked, setPicked] = useState(() => new Set());
  const [pickUses, setPickUses] = useState([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const key = (f) => `${f.kind}:${f.strava_id}`;
  const flip = (keys, on) => {
    const next = new Set(picked);
    keys.forEach((k) => (on ? next.add(k) : next.delete(k)));
    setPicked(next);
    setDone(null);
  };
  const submit = async () => {
    setBusy(true);
    const items = found.filter((f) => picked.has(key(f))).map((f) => ({ kind: f.kind, strava_id: f.strava_id }));
    const n = await add(items, pickUses);
    setBusy(false);
    if (n != null) {
      setPicked(new Set());
      setDone(n);
    }
  };
  if (!found.length && done == null) {
    return (
      <div className="card inset">
        <p className="muted small">
          Nothing new on Strava: star segments or save routes there, then look again.
        </p>
        {note}
        <button type="button" className="link-btn small" onClick={close}>
          Close
        </button>
      </div>
    );
  }
  const groups = ["route", "segment"].filter((k) => show === "both" || show === k);
  return (
    <div className="card inset strava-picker">
      <div className="chips tight" role="group" aria-label="Show">
        {[
          ["both", "Routes and segments"],
          ["route", "Routes"],
          ["segment", "Segments"],
        ].map(([v, label]) => (
          <button key={v} type="button" className={`chip small ${show === v ? "on" : ""}`} onClick={() => setShow(v)}>
            {label}
          </button>
        ))}
      </div>
      {groups.map((kind) => {
        const list = found.filter((f) => f.kind === kind);
        if (!list.length) {
          return kind === "route" && !note ? (
            <p key={kind} className="muted small">
              No new routes on Strava: save one there (Maps → Saved routes), then look again.
            </p>
          ) : null;
        }
        const keys = list.map(key);
        const all = keys.every((k) => picked.has(k));
        return (
          <div key={kind} className="favourite-group">
            <label className="pick-all">
              <input type="checkbox" checked={all} onChange={() => flip(keys, !all)} />
              <strong>
                {KIND[kind][1]} {KIND[kind][0]}
              </strong>{" "}
              <span className="muted small">
                {list.length} on Strava · select all
              </span>
            </label>
            <ul className="list segments picks">
              {list.map((f) => (
                <li key={key(f)}>
                  <label>
                    <input type="checkbox" checked={picked.has(key(f))} onChange={(e) => flip([key(f)], e.target.checked)} />{" "}
                    <strong>{f.name}</strong>
                    <span className="muted small">{stats(f).map((x) => ` · ${x}`).join("")}</span>
                  </label>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      {groups.includes("route") && note}
      <div className="small strong-label">What they're for</div>
      <div className="chips tight" aria-label="What they're for">
        {uses.map((u) => (
          <button
            key={u}
            type="button"
            className={`chip small ${pickUses.includes(u) ? "on" : ""}`}
            onClick={() => setPickUses(pickUses.includes(u) ? pickUses.filter((x) => x !== u) : [...pickUses, u])}
          >
            {u}
          </button>
        ))}
      </div>
      <p className="muted small">None ticked: routes are for endurance, segments for hill repeats. Change each later.</p>
      <div className="row wrap">
        <button type="button" className="btn primary" disabled={!picked.size || busy} onClick={submit}>
          {busy ? "Adding…" : `Add ${picked.size || ""} to favourites`}
        </button>
        <button type="button" className="link-btn small" onClick={close}>
          Close
        </button>
        {done != null &&
          (done ? (
            <span className="ok-text small">Added {done}.</span>
          ) : (
            <span className="bad-text small">
              None added: they're already favourites, or Strava doesn't list them any more. Close and open again.
            </span>
          ))}
      </div>
    </div>
  );
}

// Strava only shares private routes (its default for saved routes) when the link allowed it; links made
// before CoachQuest asked for that show public routes only, until Strava is connected again.
function PrivateRoutesNote({ self }) {
  return (
    <p className="muted small">
      Routes missing? Strava only shares private routes (its default) with permission to see them.{" "}
      {self ? (
        <>
          Connect Strava again on <Link to="/connections">Connections</Link> and allow it.
        </>
      ) : (
        "Ask the athlete to connect Strava again on Connections and allow it."
      )}
    </p>
  );
}
