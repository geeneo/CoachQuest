import { Plus, Trash2 } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { formatDate } from "../lib/format.js";

// After a race: the ride (elapsed, moving and stopped time), the post-race update, earlier years, the
// segments, the weather each year had, and other riders (athletes who share with you, and riders you add).

export function hms(s) {
  if (s == null) return "–";
  const sign = s < 0 ? "−" : "";
  const a = Math.abs(Math.round(s));
  const h = Math.floor(a / 3600);
  const m = Math.floor((a % 3600) / 60);
  const sec = a % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h ? `${sign}${h}:${mm}:${ss}` : `${sign}${m}:${ss}`;
}

export function gap(s) {
  if (s == null) return "–";
  if (s === 0) return "0";
  return s > 0 ? `+${hms(s)}` : hms(s);
}

const fmt = (v, unit = "") => (v == null ? "–" : `${v}${unit}`);

const FEELINGS = [
  [1, "1 · Terrible"],
  [2, "2 · Hard going"],
  [3, "3 · OK"],
  [4, "4 · Good"],
  [5, "5 · Flying"],
];

const TEXTS = [
  ["went_well", "What went well"],
  ["went_badly", "What didn't go well"],
  ["nutrition", "Food and drink"],
  ["problems", "Problems (mechanicals, crashes, cramps)"],
  ["next_time", "Next time I will…"],
];

function windText(w) {
  if (!w) return "…";
  if (w.error) return w.error;
  const head = w.share?.head ?? 0;
  const tail = w.share?.tail ?? 0;
  return `${w.wind_kmh} km/h from the ${w.wind_from}, gusts ${fmt(w.gusts_kmh)} · ${head}% headwind, ${tail}% tailwind`;
}

// Short, for the year-by-year table.
function windShort(w) {
  if (!w) return "…";
  if (w.error) return "–";
  return `${w.wind_kmh} km/h ${w.wind_from} · ${w.share?.head ?? 0}% head`;
}

function weatherLine(w) {
  if (!w || w.error) return null;
  const temp = w.temp_min === w.temp_max ? `${w.temp_min}°C` : `${w.temp_min}–${w.temp_max}°C`;
  const rain = w.rain_mm ? `, rain up to ${w.rain_mm} mm/h` : ", dry";
  return `${w.icon} ${w.label}, ${temp}${rain}. Out: ${w.first_half}, back: ${w.second_half}.`;
}

export default function RaceReview() {
  const { raceId, athleteId } = useParams();
  const base = `/api/athletes/${athleteId || "me"}/races/${raceId}/review`;
  const res = useApi(base);
  const [weather, setWeather] = useState(null);
  const [weatherError, setWeatherError] = useState(null);
  const d = res.data;

  // The weather is slower (a request per ride): asked for after the rest is shown.
  useEffect(() => {
    if (!d?.ride && !d?.earlier?.length) return;
    setWeather(null);
    api(`${base}/weather`)
      .then(setWeather)
      .catch((e) => setWeatherError(e.message));
  }, [base, d?.ride?.activity_id, d?.earlier?.length]);

  if (res.loading && !d) return <p className="muted">Loading the race…</p>;
  if (res.error) return <div className="error">{res.error.message}</div>;
  if (!d) return null;
  const race = d.race;
  const rides = [...(d.ride ? [d.ride] : []), ...d.earlier];
  const w = (id) => (weather ? weather[String(id)] : null);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>
            {race.name}: after the race{d.own ? "" : ` · ${d.athlete.name}`}
          </h1>
          <p className="muted small">
            {race.target_date ? formatDate(race.target_date, { weekday: true }) : "No date"}
            {race.distance_km ? ` · ${race.distance_km} km` : ""}
            {race.target_time ? ` · target ${race.target_time}` : ""} ·{" "}
            {d.own ? (
              <Link to="/races">Back to Races</Link>
            ) : (
              <Link to={`/athletes/${d.athlete.id}?tab=races`}>Back to {d.athlete.name}</Link>
            )}
          </p>
        </div>
      </div>
      {d.notes.map((n) => (
        <p key={n} className="notice">
          {n}
        </p>
      ))}

      {d.ride && (
        <section className="card">
          <h2>Your ride</h2>
          {d.own && d.candidates.length > 1 && (
            <RidePicker raceId={raceId} d={d} reload={res.reload} />
          )}
          <RideStats r={d.ride} target={race.target_time} />
          <p className="small">
            <strong>Weather:</strong>{" "}
            {weatherError || (w(d.ride.activity_id) ? weatherLine(w(d.ride.activity_id)) : "Loading…")}{" "}
            {w(d.ride.activity_id) && !w(d.ride.activity_id).error && windText(w(d.ride.activity_id))}
          </p>
          {d.ride.strava_id && (
            <p className="small">
              <a href={`https://www.strava.com/activities/${d.ride.strava_id}`} target="_blank" rel="noreferrer">
                Open on Strava
              </a>
            </p>
          )}
        </section>
      )}

      {d.own ? (
        <PostRaceForm raceId={raceId} result={d.result} reload={res.reload} />
      ) : (
        <PostRaceRead result={d.result} />
      )}

      {rides.length > 1 && (
        <section className="card">
          <h2>Year by year</h2>
          <p className="muted small">
            Your rides of this race, found by date (within three weeks of it each year) and route. Elapsed is start to
            finish with stops; CTL is your fitness going in.
          </p>
          <div className="table-wrap audit-table">
            <table>
              <thead>
                <tr>
                  <th>Year</th>
                  <th className="num">Elapsed</th>
                  <th className="num">Moving</th>
                  <th className="num">Stopped</th>
                  <th className="num">km/h</th>
                  <th className="num">NP</th>
                  <th className="num">Avg HR</th>
                  <th className="num">TSS</th>
                  <th className="num">CTL in</th>
                  <th className="num">Temp</th>
                  <th>Wind</th>
                </tr>
              </thead>
              <tbody>
                {rides.map((r) => (
                  <tr key={r.activity_id}>
                    <td>
                      {r.year}
                      {d.ride && r.activity_id === d.ride.activity_id ? " (this race)" : ""}
                    </td>
                    <td className="num">{hms(r.elapsed_s)}</td>
                    <td className="num">{hms(r.moving_s)}</td>
                    <td className="num">{hms(r.stopped_s)}</td>
                    <td className="num">{fmt(r.speed_moving)}</td>
                    <td className="num">{fmt(r.norm_power, " W")}</td>
                    <td className="num">{fmt(r.avg_hr)}</td>
                    <td className="num">{fmt(r.tss)}</td>
                    <td className="num">{fmt(r.ctl_before)}</td>
                    <td className="num">
                      {r.device_temp != null
                        ? `${r.device_temp}°`
                        : w(r.activity_id) && !w(r.activity_id).error
                          ? `${w(r.activity_id).temp_max}°`
                          : "–"}
                    </td>
                    <td className="small" title={w(r.activity_id) ? windText(w(r.activity_id)) : ""}>
                      {weatherError ? "–" : windShort(w(r.activity_id))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {d.segments.length > 0 && <SegmentTable segments={d.segments} rides={rides} />}

      {d.laps.length > 0 && (
        <section className="card">
          <h2>Laps</h2>
          <div className="table-wrap audit-table">
            <table>
              <thead>
                <tr>
                  <th>Lap</th>
                  <th className="num">Time</th>
                  <th className="num">km</th>
                  <th className="num">Power</th>
                  <th className="num">HR</th>
                </tr>
              </thead>
              <tbody>
                {d.laps.map((l, i) => (
                  <tr key={i}>
                    <td>{l.name || i + 1}</td>
                    <td className="num">{hms(l.elapsed_s)}</td>
                    <td className="num">{(l.distance_m / 1000).toFixed(1)}</td>
                    <td className="num">{fmt(l.watts, " W")}</td>
                    <td className="num">{fmt(l.hr)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {(d.own || d.standings.length > 0) && (
        <Riders raceId={raceId} d={d} reload={res.reload} />
      )}
    </>
  );
}

function RideStats({ r, target }) {
  const tiles = [
    ["Elapsed", hms(r.elapsed_s), target ? `target ${target}` : "start to finish"],
    ["Moving", hms(r.moving_s), r.stopped_s != null ? `stopped ${hms(r.stopped_s)}` : ""],
    ["Distance", `${r.distance_km} km`, `${r.elevation_m} m climbing`],
    ["Speed", fmt(r.speed_moving, " km/h"), r.speed_elapsed ? `${r.speed_elapsed} km/h overall` : ""],
    ["Power", fmt(r.norm_power, " W NP"), r.avg_power ? `${r.avg_power} W average` : ""],
    ["Heart rate", fmt(r.avg_hr, " bpm"), r.max_hr ? `max ${r.max_hr}` : ""],
    ["TSS", fmt(r.tss), r.kj ? `${r.kj} kJ` : ""],
    ["Fitness going in", fmt(r.ctl_before), "CTL"],
  ];
  if (r.device_temp != null) tiles.push(["Temperature", `${r.device_temp}°C`, "your device's average"]);
  return (
    <div className="stats">
      {tiles.map(([label, value, sub]) => (
        <div key={label} className="stat">
          <div className="stat-label">{label}</div>
          <div className="stat-value">{value}</div>
          {sub && <div className="stat-sub">{sub}</div>}
        </div>
      ))}
    </div>
  );
}

function RidePicker({ raceId, d, reload }) {
  const [error, setError] = useState(null);
  const pick = async (id) => {
    setError(null);
    try {
      await api(`/api/races/${raceId}/result`, { method: "PUT", body: { activity_id: id ? Number(id) : null } });
      reload();
    } catch (e) {
      setError(e.message);
    }
  };
  return (
    <p className="small">
      <label>
        The race was:{" "}
        <select value={d.ride.activity_id} onChange={(e) => pick(e.target.value)}>
          {d.candidates.map((c) => (
            <option key={c.activity_id} value={c.activity_id}>
              {c.name} · {c.distance_km} km · {c.minutes} min
            </option>
          ))}
        </select>
      </label>
      {error && <span className="error"> {error}</span>}
    </p>
  );
}

function PostRaceRead({ result }) {
  const shown = TEXTS.filter(([k]) => result[k]);
  if (!result.official_time && !result.position && !shown.length) return null;
  return (
    <section className="card">
      <h2>Post-race update</h2>
      <p>
        {result.official_time && <>Official time {result.official_time}. </>}
        {result.position && (
          <>
            Position {result.position}
            {result.field_size ? ` of ${result.field_size}` : ""}.{" "}
          </>
        )}
        {result.category_position && (
          <>
            {result.category || "Category"}: {result.category_position}
            {result.category_size ? ` of ${result.category_size}` : ""}.
          </>
        )}
      </p>
      {shown.map(([k, label]) => (
        <p key={k}>
          <strong>{label}:</strong> {result[k]}
        </p>
      ))}
    </section>
  );
}

function PostRaceForm({ raceId, result, reload }) {
  const empty = (v) => (v == null ? "" : String(v));
  const initial = () => ({
    official_time: empty(result.official_time),
    position: empty(result.position),
    field_size: empty(result.field_size),
    category: empty(result.category),
    category_position: empty(result.category_position),
    category_size: empty(result.category_size),
    feeling: empty(result.feeling),
    ...Object.fromEntries(TEXTS.map(([k]) => [k, empty(result[k])])),
  });
  const [form, setForm] = useState(initial);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => {
    setSaved(false);
    setForm({ ...form, [k]: e.target.value });
  };
  const save = async (e) => {
    e.preventDefault();
    setError(null);
    const num = (v) => (v === "" ? null : Number(v));
    const body = {
      official_time: form.official_time.trim() || null,
      position: num(form.position),
      field_size: num(form.field_size),
      category: form.category.trim() || null,
      category_position: num(form.category_position),
      category_size: num(form.category_size),
      feeling: num(form.feeling),
      ...Object.fromEntries(TEXTS.map(([k]) => [k, form[k]])),
    };
    try {
      await api(`/api/races/${raceId}/result`, { method: "PUT", body });
      setSaved(true);
      reload();
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <section className="card">
      <h2>Post-race update</h2>
      <p className="muted small">
        For you and your coach; the AI coach reads it too, so the next plan builds on it (food, pacing, what to change).
      </p>
      <form className="grid-form" onSubmit={save}>
        <label>
          Official time
          <input value={form.official_time} onChange={set("official_time")} placeholder="h:mm:ss" maxLength={10} />
          <span className="hint">From the results; your ride's elapsed time otherwise.</span>
        </label>
        <label>
          Position overall
          <span className="inline-pair">
            <input type="number" min="1" value={form.position} onChange={set("position")} aria-label="Position" />
            of
            <input type="number" min="1" value={form.field_size} onChange={set("field_size")} aria-label="Field size" />
          </span>
        </label>
        <label>
          Category
          <input value={form.category} onChange={set("category")} placeholder="e.g. M40" maxLength={40} />
        </label>
        <label>
          Position in category
          <span className="inline-pair">
            <input
              type="number"
              min="1"
              value={form.category_position}
              onChange={set("category_position")}
              aria-label="Position in category"
            />
            of
            <input
              type="number"
              min="1"
              value={form.category_size}
              onChange={set("category_size")}
              aria-label="Riders in category"
            />
          </span>
        </label>
        <label>
          How it felt
          <select value={form.feeling} onChange={set("feeling")}>
            <option value="">–</option>
            {FEELINGS.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {TEXTS.map(([k, label]) => (
          <label key={k} className="wide">
            {label}
            <textarea rows={2} value={form[k]} onChange={set(k)} maxLength={2000} />
          </label>
        ))}
        <button className="btn" type="submit">
          Save
        </button>
        {saved && <span className="ok-text">Saved.</span>}
        {error && <div className="error wide">{error}</div>}
      </form>
    </section>
  );
}

// Which segments to show, and in which order.
const SEG_FILTERS = [
  ["all", "All", () => true],
  ["climbs", "Climbs", (s) => s.climb > 0 || (s.grade ?? 0) >= 3],
  ["short", "Under 10 km", (s) => s.distance_m < 10000],
  ["long", "10 km and more", (s) => s.distance_m >= 10000],
];
const SEG_SORTS = [
  ["course", "Course order", null],
  ["gained", "Most time gained", (a, b) => (a.vs_best_before ?? 1e9) - (b.vs_best_before ?? 1e9)],
  ["lost", "Most time lost", (a, b) => (b.vs_best_before ?? -1e9) - (a.vs_best_before ?? -1e9)],
];
const SEG_FIRST = 15;

function SegCell({ t, best }) {
  if (!t) return <span className="muted">–</span>;
  const sub = [t.watts && `${t.watts} W`, t.hr && `${t.hr} bpm`, t.kmh && `${t.kmh} km/h`].filter(Boolean);
  return (
    <>
      <span className={best ? "seg-time best" : "seg-time"}>{hms(t.elapsed_s)}</span>
      {sub.length > 0 && <span className="seg-sub">{sub.join(" · ")}</span>}
    </>
  );
}

// Segments covering the same stretch (Strava has many "start to X" copies): starting within a km of each
// other and about as long (3%). Each group is led by the one ridden in the most years; the rest fold under it.
export function groupSimilar(list) {
  const groups = [];
  for (const s of list) {
    const g = groups.find(({ members: [m] }) => {
      const sameStart =
        m.start_km == null || s.start_km == null ? m.start_km === s.start_km : Math.abs(m.start_km - s.start_km) <= 1;
      return sameStart && Math.abs(m.distance_m - s.distance_m) <= 0.03 * Math.max(m.distance_m, s.distance_m);
    });
    if (g) g.members.push(s);
    else groups.push({ members: [s] });
  }
  return groups.map(({ members }) => {
    const years = (x) => Object.keys(x.times).length;
    const lead = members.reduce((best, x) => (years(x) > years(best) ? x : best), members[0]);
    return { lead, similar: members.filter((x) => x !== lead) };
  });
}

function SegRow({ s, years, similar = 0, open, toggle, child }) {
  return (
    <tr className={child ? "seg-child" : undefined}>
      <td className="num seg-at">{s.start_km != null ? s.start_km.toFixed(1) : "–"}</td>
      <td className="seg-name">
        <a href={`https://www.strava.com/segments/${s.id}`} target="_blank" rel="noreferrer">
          {s.name}
        </a>
        {s.climb > 0 && <span className="badge seg-climb">Cat {s.climb === 5 ? "HC" : 5 - s.climb}</span>}
        <span className="seg-sub">
          {(s.distance_m / 1000).toFixed(1)} km{s.grade != null ? ` · ${s.grade.toFixed(1)}%` : ""}
          {similar > 0 && (
            <>
              {" · "}
              <button className="link-btn" aria-expanded={open} onClick={toggle}>
                {open ? "hide similar" : `+${similar} similar`}
              </button>
            </>
          )}
        </span>
      </td>
      {years.map((y) => (
        <td key={y} className="num seg-cell">
          <SegCell t={s.times[y]} best={s.best === y && Object.keys(s.times).length > 1} />
        </td>
      ))}
      <td className={`num seg-vs ${s.vs_best_before < 0 ? "ok-text" : s.vs_best_before > 0 ? "bad-text" : ""}`}>
        {gap(s.vs_best_before)}
      </td>
    </tr>
  );
}

function SegmentTable({ segments, rides }) {
  const years = rides.map((r) => String(r.year));
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("course");
  const [all, setAll] = useState(false);
  const [opened, setOpened] = useState(() => new Set());
  const keep = SEG_FILTERS.find(([k]) => k === filter)[2];
  const order = SEG_SORTS.find(([k]) => k === sort)[2];
  const shown = segments.filter(keep);
  if (order) shown.sort(order);
  const groups = groupSimilar(shown);
  const rows = all ? groups : groups.slice(0, SEG_FIRST);
  const toggle = (id) => {
    const next = new Set(opened);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setOpened(next);
  };
  return (
    <section className="card">
      <h2>Segment by segment</h2>
      <p className="muted small">
        Your time on each Strava segment of the course, each year, with your average power, heart rate and speed on it.
        The best year is in bold; "vs best" is this race against your best earlier year (green: faster). Segments over
        the same stretch are folded together.
      </p>
      <div className="seg-controls">
        <div className="seg-chips" role="group" aria-label="Show segments">
          {SEG_FILTERS.map(([k, label, f]) => (
            <button
              key={k}
              className={`btn small ${filter === k ? "active" : ""}`}
              aria-pressed={filter === k}
              onClick={() => setFilter(k)}
            >
              {label} <span className="muted">{segments.filter(f).length}</span>
            </button>
          ))}
        </div>
        <label className="small seg-sort">
          Sort
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            {SEG_SORTS.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="table-wrap seg-table">
        <table>
          <thead>
            <tr>
              <th className="num seg-at">At km</th>
              <th>Segment</th>
              {years.map((y) => (
                <th key={y} className="num">
                  {y}
                </th>
              ))}
              <th className="num seg-vs">vs best</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ lead, similar }) => (
              <Fragment key={lead.id}>
                <SegRow
                  s={lead}
                  years={years}
                  similar={similar.length}
                  open={opened.has(lead.id)}
                  toggle={() => toggle(lead.id)}
                />
                {opened.has(lead.id) && similar.map((s) => <SegRow key={s.id} s={s} years={years} child />)}
              </Fragment>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={years.length + 3} className="muted">
                  No segments of this kind on the course.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {groups.length > SEG_FIRST && (
        <button className="btn small" onClick={() => setAll(!all)}>
          {all ? `Show the first ${SEG_FIRST}` : `Show all ${groups.length}`}
        </button>
      )}
    </section>
  );
}

function Riders({ raceId, d, reload }) {
  const toRows = () => (d.result.riders || []).map((r) => ({ name: r.name, time: r.time || "", category: r.category || "" }));
  const [rows, setRows] = useState(toRows);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const change = (i, k, v) => {
    setSaved(false);
    setRows(rows.map((r, n) => (n === i ? { ...r, [k]: v } : r)));
  };
  const save = async () => {
    setError(null);
    const riders = rows
      .filter((r) => r.name.trim() && r.time.trim())
      .map((r) => ({ name: r.name.trim(), time: r.time.trim(), category: r.category.trim() || null }));
    try {
      await api(`/api/races/${raceId}/result`, { method: "PUT", body: { riders } });
      setSaved(true);
      reload();
    } catch (e) {
      setError(e.message);
    }
  };
  return (
    <section className="card">
      <h2>Other riders</h2>
      <p className="muted small">
        Athletes on CoachQuest who share their activities with you and rode this race (same day, same route), and riders
        you add. Strava doesn't let apps read other riders' rides or segment leaderboards, so add the ones you want to
        compare with from the results.
      </p>
      {d.standings.length > 0 && (
        <div className="table-wrap audit-table">
          <table>
            <thead>
              <tr>
                <th className="num">#</th>
                <th>Rider</th>
                <th className="num">Time</th>
                <th className="num">Gap to you</th>
                <th>Category</th>
              </tr>
            </thead>
            <tbody>
              {d.standings.map((s) => (
                <tr key={`${s.kind}-${s.name}-${s.time_s}`} className={s.kind === "you" ? "diff" : ""}>
                  <td className="num">{s.place}</td>
                  <td>
                    {s.name}
                    {s.kind === "athlete" && <span className="muted small"> · CoachQuest</span>}
                  </td>
                  <td className="num">{hms(s.time_s)}</td>
                  <td className="num">{gap(s.gap_s)}</td>
                  <td>{s.category || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {d.others.length > 0 && (
        <>
          <h3>Riders on CoachQuest</h3>
          <div className="table-wrap audit-table">
            <table>
              <thead>
                <tr>
                  <th>Rider</th>
                  <th className="num">Elapsed</th>
                  <th className="num">Moving</th>
                  <th className="num">km/h</th>
                  <th className="num">NP</th>
                  <th className="num">Avg HR</th>
                  <th className="num">TSS</th>
                </tr>
              </thead>
              <tbody>
                {d.others.map((o) => (
                  <tr key={o.athlete_id}>
                    <td>
                      <Link to={`/athletes/${o.athlete_id}`}>{o.name}</Link>
                    </td>
                    <td className="num">{hms(o.elapsed_s)}</td>
                    <td className="num">{hms(o.moving_s)}</td>
                    <td className="num">{fmt(o.speed_moving)}</td>
                    <td className="num">{fmt(o.norm_power, " W")}</td>
                    <td className="num">{fmt(o.avg_hr)}</td>
                    <td className="num">{fmt(o.tss)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {d.own && (
        <>
          <h3>Riders you add</h3>
          {rows.map((r, i) => (
            <div key={i} className="rider-row">
              <input value={r.name} onChange={(e) => change(i, "name", e.target.value)} placeholder="Name" maxLength={80} aria-label="Rider name" />
              <input value={r.time} onChange={(e) => change(i, "time", e.target.value)} placeholder="h:mm:ss" maxLength={10} aria-label="Rider time" />
              <input value={r.category} onChange={(e) => change(i, "category", e.target.value)} placeholder="Category" maxLength={40} aria-label="Rider category" />
              <button className="icon-btn" aria-label={`Remove ${r.name || "rider"}`} onClick={() => {
                  setSaved(false);
                  setRows(rows.filter((_, n) => n !== i));
                }}>
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          <div className="row tight">
            <button className="btn small" onClick={() => setRows([...rows, { name: "", time: "", category: "" }])}>
              <Plus size={14} /> Add a rider
            </button>
            <button className="btn small" onClick={save}>
              Save riders
            </button>
            {saved && <span className="ok-text">Saved.</span>}
          </div>
          {error && <div className="error">{error}</div>}
        </>
      )}
    </section>
  );
}
