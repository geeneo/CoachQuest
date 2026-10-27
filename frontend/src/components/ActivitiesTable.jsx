import { Trash2, Undo2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { dateTime, duration, formatDate, shortDate } from "../lib/format.js";

const RANGES = [
  [7, "7d"],
  [30, "30d"],
  [90, "90d"],
  [180, "180d"],
  [365, "1 year"],
  [730, "2 years"],
  [1095, "3 years"],
  [1826, "5 years"],
  [3652, "10 years"],
  [36600, "All time"],
];
const INDOOR = new Set(["Virtual", "Treadmill run"]);
const SOURCES = { strava: "Strava", garmin: "Garmin", intervals_icu: "Intervals.icu" };
const fmt = (n, digits = 0) => (n == null ? "–" : Number(n).toLocaleString(undefined, { maximumFractionDigits: digits }));

function periodQuery(mode, range, month, year) {
  if (mode === "month") {
    const [y, m] = month.split("-").map(Number);
    const last = new Date(y, m, 0).getDate();
    return `since=${month}-01&until=${month}-${String(last).padStart(2, "0")}`;
  }
  if (mode === "year") return `since=${year}-01-01&until=${year}-12-31`;
  return `days=${range}`;
}

// Relative effort: green easy, amber moderate, red hard. The number is always shown.
function reClass(re) {
  if (re == null) return "";
  return re < 100 ? "re-low" : re <= 180 ? "re-mid" : "re-high";
}

export default function Activities({ id, editable }) {
  const now = new Date();
  const [mode, setMode] = useState("range");
  const [range, setRange] = useState(30);
  const [month, setMonth] = useState(now.toISOString().slice(0, 7));
  const [year, setYear] = useState(now.getFullYear());
  const [type, setType] = useState("All");
  const [racesOnly, setRacesOnly] = useState(false);
  const [showNP, setShowNP] = useState(false);
  const [search, setSearch] = useState("");
  const res = useApi(`/api/athletes/${id}/activities?${periodQuery(mode, range, month, year)}`);
  const races = useApi(editable ? "/api/athletes/me/races" : null);
  const prefs = useApi(editable ? "/api/athletes/me/preferences" : null);
  const types = useApi(editable ? "/api/activity-types" : null);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  useEffect(() => {
    setRows(res.data || []);
  }, [res.data]);

  const present = useMemo(() => ["All", ...new Set(rows.map((r) => r.category))], [rows]);
  const shown = rows.filter(
    (r) =>
      (type === "All" || r.category === type) &&
      (!racesOnly || r.is_race) &&
      (!search || r.name.toLowerCase().includes(search.toLowerCase())),
  );
  const total = (f) => shown.reduce((s, r) => s + (f(r) || 0), 0);
  const raceName = Object.fromEntries((races.data || []).map((r) => [r.id, r.short_name || r.code]));

  const edit = async (row, field, value) => {
    setError(null);
    try {
      const updated = await api(`/api/activities/${row.id}`, { method: "PATCH", body: { [field]: value || null } });
      setRows((rs) => rs.map((r) => (r.id === row.id ? updated : r)));
    } catch (err) {
      setError(err.message);
    }
  };

  // Deleting (the athlete's own activities only; never on Strava, Garmin or Intervals.icu).
  const [picked, setPicked] = useState(new Set());
  const [showDeleted, setShowDeleted] = useState(false);
  const deleted = useApi(editable && showDeleted ? "/api/activities/deleted" : null);
  const toggle = (rid) =>
    setPicked((s) => {
      const n = new Set(s);
      n.has(rid) ? n.delete(rid) : n.add(rid);
      return n;
    });
  const allPicked = shown.length > 0 && shown.every((r) => picked.has(r.id));
  const [cleaned, setCleaned] = useState(null);
  // Clean-up: delete the extra copies of sessions recorded twice (they are already hidden from this list).
  const removeDuplicates = async () => {
    if (
      !confirm(
        "Remove duplicate activities?\n\nWhen a session came in more than once (e.g. from both Strava and Garmin, " +
          "or uploaded twice), the extra copies are deleted and the best one is kept. They stay on Strava / " +
          "Garmin and won't come back on the next sync. You can undo this under Deleted activities.",
      )
    )
      return;
    setError(null);
    try {
      const r = await api("/api/activities/remove-duplicates", { method: "POST" });
      setCleaned(r.removed ? `Removed ${r.removed} duplicate${r.removed === 1 ? "" : "s"}.` : "No duplicates found.");
      res.reload();
      deleted.reload();
    } catch (err) {
      setError(err.message);
    }
  };
  const remove = async (ids) => {
    const one = ids.length === 1 && rows.find((r) => r.id === ids[0]);
    const what = one ? `"${one.name}" (${shortDate(one.start_time)})` : `${ids.length} activities`;
    if (
      !confirm(
        `Delete ${what} from CoachQuest?\n\nThey stay on Strava / Garmin and won't come back on the next sync. ` +
          "Training load, volume and plans are recalculated. You can undo this under Deleted activities.",
      )
    )
      return;
    setError(null);
    try {
      await api("/api/activities/delete", { method: "POST", body: { ids } });
      setPicked(new Set());
      res.reload();
      deleted.reload();
    } catch (err) {
      setError(err.message);
    }
  };
  const restore = async (ids) => {
    setError(null);
    try {
      await api("/api/activities/deleted/restore", { method: "POST", body: { ids } });
      res.reload();
      deleted.reload();
    } catch (err) {
      setError(err.message);
    }
  };

  const years = [];
  for (let y = now.getFullYear(); y >= 2009; y--) years.push(y);

  return (
    <section className="card">
      <h2>Recent activities</h2>
      <div className="filters">
        <div className="chips">
          {[
            ["range", "Date range"],
            ["month", "Month"],
            ["year", "Year"],
          ].map(([m, label]) => (
            <button key={m} type="button" className={`chip ${mode === m ? "on" : ""}`} onClick={() => setMode(m)}>
              {label}
            </button>
          ))}
        </div>
        {mode === "range" && (
          <div className="chips">
            {RANGES.map(([d, label]) => (
              <button key={d} type="button" className={`chip ${range === d ? "on" : ""}`} onClick={() => setRange(d)}>
                {label}
              </button>
            ))}
          </div>
        )}
        {mode === "month" && (
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="inline-input" />
        )}
        {mode === "year" && (
          <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {years.map((y) => (
              <option key={y}>{y}</option>
            ))}
          </select>
        )}
        <div className="chips">
          <span className="muted small">Type:</span>
          {present.map((t) => (
            <button key={t} type="button" className={`chip ${type === t ? "on" : ""}`} onClick={() => setType(t)}>
              {t}
            </button>
          ))}
          <button type="button" className={`chip ${racesOnly ? "on" : ""}`} onClick={() => setRacesOnly(!racesOnly)}>
            🏁 Races only
          </button>
          <button type="button" className={`chip ${showNP ? "on" : ""}`} onClick={() => setShowNP(!showNP)}>
            Show NP
          </button>
        </div>
        <input
          className="inline-input"
          placeholder="Search activity name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <p className="summary-line">
        <strong>{shown.length}</strong> activities · <strong>{fmt(total((r) => r.distance_km))} km</strong> ·{" "}
        <strong>{fmt(total((r) => r.elevation_m))} m ↑</strong>{" "}
        <span className="muted">
          ({fmt(total((r) => (r.indoor || INDOOR.has(r.category) ? 0 : r.elevation_m)))} m outdoor)
        </span>{" "}
        · <strong>{fmt(total((r) => r.duration_s) / 3600, 1)} hrs</strong>
      </p>
      {editable && (
        <div className="row wrap delete-bar">
          <button className="btn small danger" disabled={!picked.size} onClick={() => remove([...picked])}>
            <Trash2 size={14} /> Delete selected{picked.size ? ` (${picked.size})` : ""}
          </button>
          <button className="btn small" onClick={removeDuplicates} title="Delete extra copies of sessions recorded twice">
            Remove duplicates
          </button>
          {cleaned && <span className="small muted">{cleaned}</span>}
          <button className="link-btn small" onClick={() => setShowDeleted(!showDeleted)}>
            {showDeleted ? "Hide deleted activities" : "Deleted activities…"}
          </button>
        </div>
      )}
      {editable && showDeleted && (
        <div className="deleted-list">
          {deleted.data?.length ? (
            <table className="small">
              <tbody>
                {deleted.data.map((d) => (
                  <tr key={d.id}>
                    <td>{formatDate(d.start_time)}</td>
                    <td>{d.name || d.sport}</td>
                    <td className="muted">
                      {d.source} · {d.distance_km} km · {duration(d.duration_s)}
                    </td>
                    <td className="muted">deleted {dateTime(d.deleted_at)}</td>
                    <td>
                      <button className="link-btn small" onClick={() => restore([d.id])}>
                        <Undo2 size={14} /> Restore
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted small">{deleted.loading ? "Loading…" : "Nothing deleted."}</p>
          )}
        </div>
      )}
      {error && <div className="error">{error}</div>}
      {res.error && <div className="error">{res.error.message}</div>}
      {shown.length === 0 ? (
        <p className="muted">No activities match.</p>
      ) : (
        <div className="table-wrap">
          <table className="activities">
            <thead>
              <tr>
                {editable && (
                  <th>
                    <input
                      type="checkbox"
                      aria-label="Select all shown"
                      checked={allPicked}
                      onChange={() => setPicked(allPicked ? new Set() : new Set(shown.map((r) => r.id)))}
                    />
                  </th>
                )}
                <th>Date</th>
                <th>Type</th>
                <th>Activity</th>
                <th className="num">Dist</th>
                <th className="num">Elev</th>
                <th className="num">Time</th>
                <th className="num">Speed</th>
                <th className="num">Power</th>
                {showNP && <th className="num">NP</th>}
                <th className="num">HR</th>
                <th className="num">Cadence</th>
                <th className="num">Cal</th>
                <th className="num">RE</th>
                <th>Race</th>
                <th>Note</th>
                {editable && <th />}
              </tr>
            </thead>
            <tbody>
              {shown.map((a) => (
                <tr key={a.id} className={picked.has(a.id) ? "picked" : ""}>
                  {editable && (
                    <td>
                      <input type="checkbox" aria-label="Select" checked={picked.has(a.id)} onChange={() => toggle(a.id)} />
                    </td>
                  )}
                  <td>{shortDate(a.start_time)}</td>
                  <td>
                    {editable ? (
                      <select
                        aria-label="Type"
                        value={a.category}
                        onChange={(e) => edit(a, "type_override", e.target.value)}
                      >
                        {[...new Set([a.category, ...(types.data || [])])].map((t) => (
                          <option key={t}>{t}</option>
                        ))}
                      </select>
                    ) : (
                      a.category
                    )}
                  </td>
                  <td className="name-cell" title={`${a.name} (from ${SOURCES[a.source] || a.source})`}>
                    {a.name}
                  </td>
                  <td className="num">{fmt(a.distance_km, 1)} km</td>
                  <td className="num">{fmt(a.elevation_m)} m</td>
                  <td className="num">{duration(a.duration_s)}</td>
                  <td className="num">{a.avg_speed_kmh ? `${fmt(a.avg_speed_kmh, 1)} km/h` : "–"}</td>
                  <td className="num">{a.avg_power ? `${fmt(a.avg_power)}W` : "–"}</td>
                  {showNP && <td className="num">{a.norm_power ? `${fmt(a.norm_power)}W` : "–"}</td>}
                  <td className="num">{a.avg_hr ? `${fmt(a.avg_hr)} bpm` : "–"}</td>
                  <td className="num">
                    {a.avg_cadence ? `${a.avg_cadence} ${/run|walk|hike/i.test(a.category) ? "spm" : "rpm"}` : "–"}
                  </td>
                  <td className="num">{fmt(a.calories)}</td>
                  <td className="num">
                    {a.relative_effort != null ? (
                      <span className={`re-badge ${reClass(a.relative_effort)}`}>{fmt(a.relative_effort)}</span>
                    ) : (
                      "–"
                    )}
                  </td>
                  <td>
                    {editable ? (
                      <select aria-label="Race" value={a.race_id ?? ""} onChange={(e) => edit(a, "race_id", e.target.value ? Number(e.target.value) : null)}>
                        <option value="">—</option>
                        {(races.data || []).map((r) => (
                          <option key={r.id} value={r.id}>
                            🏁 {r.short_name || r.code}
                          </option>
                        ))}
                      </select>
                    ) : (
                      raceName[a.race_id] || (a.is_race ? "race" : "–")
                    )}
                  </td>
                  <td>
                    {editable ? (
                      <select aria-label="Note" value={a.note_tag ?? ""} onChange={(e) => edit(a, "note_tag", e.target.value)}>
                        <option value="">—</option>
                        {[...new Set([...(prefs.data?.note_tags || []), ...(a.note_tag ? [a.note_tag] : [])])].map((t) => (
                          <option key={t}>{t}</option>
                        ))}
                      </select>
                    ) : (
                      a.note_tag || "–"
                    )}
                  </td>
                  {editable && (
                    <td>
                      <button className="icon-btn" title="Delete from CoachQuest" aria-label="Delete" onClick={() => remove([a.id])}>
                        <Trash2 size={15} />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
