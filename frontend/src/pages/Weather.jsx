import { CloudSun, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { duration, shortDate } from "../lib/format.js";

// Weather on your routes (backend weather.py, ride_routes.py): your rides grouped by route plus your
// favourite routes; for the one you pick, each of the next 16 days at your start time, the wind on every
// stretch (head, cross or tail), the worst conditions anywhere on it, and the best days ranked.

const KINDS = [
  ["all", "All", () => true],
  ["Road", "Road", (c) => c === "Road"],
  ["MTB", "MTB", (c) => c === "MTB"],
  ["Gravel", "Gravel", (c) => c === "Gravel"],
  ["E", "E-MTB / E-bike", (c) => c === "E-MTB" || c === "E-Bike"],
];
const DISTANCES = [
  ["any", "Any distance", () => true],
  ["lt30", "< 30km", (km) => km < 30],
  ["30-60", "30–60km", (km) => km >= 30 && km < 60],
  ["60-100", "60–100km", (km) => km >= 60 && km < 100],
  ["100", "100km+", (km) => km >= 100],
];
const SOURCES = [
  ["all", "All routes", () => true],
  ["rides", "Ridden", (s) => s === "rides"],
  ["favourite", "★ Favourites", (s) => s === "favourite"],
];
const SORTS = {
  ridden: ["Most ridden", (a, b) => b.count - a.count || b.distance_km - a.distance_km],
  longest: ["Longest first", (a, b) => b.distance_km - a.distance_km],
  recent: ["Ridden lately", (a, b) => String(b.last || "").localeCompare(String(a.last || ""))],
};
const WIND_CLASS = { head: "wind-head", cross: "wind-cross", tail: "wind-tail", calm: "wind-calm" };
const RANK = { 1: "Best day", 2: "2nd best", 3: "3rd best" };
const STARTS = Array.from({ length: 29 }, (_, i) => {
  const m = 4 * 60 + i * 30;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
});

export default function Weather({ id = "me" }) {
  const list = useApi(`/api/athletes/${id}/weather/routes`);
  const [source, setSource] = useState("all");
  const [kind, setKind] = useState("all");
  const [dist, setDist] = useState("any");
  const [sort, setSort] = useState("ridden");
  // A plan day links here with ?route=<key>&day=<date> (PlanTracker.jsx).
  const [params] = useSearchParams();
  const [picked, setPicked] = useState(params.get("route")); // route key, or "home"
  const routes = list.data?.routes || [];
  const sourceOk = (r) => SOURCES.find(([k]) => k === source)[2](r.source);
  const kindOk = (r) => KINDS.find(([k]) => k === kind)[2](r.category);
  const distOk = (r) => DISTANCES.find(([k]) => k === dist)[2](r.distance_km);
  const shown = useMemo(
    () => routes.filter((r) => sourceOk(r) && kindOk(r) && distOk(r)).sort(SORTS[sort][1]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [routes, source, kind, dist, sort],
  );
  const current = picked || shown[0]?.key || (list.data && "home");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>
            <CloudSun size={22} /> Weather
          </h1>
          <p className="muted small">
            The forecast along your routes: the worst conditions anywhere on the route, and the wind on each stretch
            at the time you'd ride it. Weather by Open-Meteo.
          </p>
        </div>
      </div>
      {list.error && <div className="error">{list.error.message}</div>}
      <div className="weather-layout">
        <aside className="weather-routes">
          <div className="chips tight">
            {SOURCES.map(([k, label, ok]) => (
              <button
                key={k}
                type="button"
                className={`chip small ${source === k ? "on" : ""}`}
                onClick={() => setSource(k)}
              >
                {label} <span className="muted">{routes.filter((r) => ok(r.source) && kindOk(r) && distOk(r)).length}</span>
              </button>
            ))}
          </div>
          <div className="chips tight">
            {KINDS.map(([k, label, ok]) => (
              <button key={k} type="button" className={`chip small ${kind === k ? "on" : ""}`} onClick={() => setKind(k)}>
                {label}{" "}
                <span className="muted">{routes.filter((r) => ok(r.category) && sourceOk(r) && distOk(r)).length}</span>
              </button>
            ))}
          </div>
          <div className="chips tight">
            {DISTANCES.map(([k, label, ok]) => (
              <button key={k} type="button" className={`chip small ${dist === k ? "on" : ""}`} onClick={() => setDist(k)}>
                {label}{" "}
                <span className="muted">{routes.filter((r) => ok(r.distance_km) && sourceOk(r) && kindOk(r)).length}</span>
              </button>
            ))}
          </div>
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
            {Object.entries(SORTS).map(([k, [label]]) => (
              <option key={k} value={k}>
                Sort: {label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={`route-item home ${current === "home" ? "on" : ""}`}
            onClick={() => setPicked("home")}
          >
            <strong>🏠 Home forecast</strong>
            <span className="muted small">{list.data?.home?.name || "Where your latest outdoor ride started"}</span>
          </button>
          {shown.map((r) => (
            <button
              key={r.key}
              type="button"
              className={`route-item ${current === r.key ? "on" : ""}`}
              onClick={() => setPicked(r.key)}
            >
              <span className="row between">
                <strong>
                  {r.distance_km}km · {r.elevation_m}m↑
                </strong>
                <span className="small accent">{r.source === "favourite" ? "★ favourite" : r.category}</span>
              </span>
              <span className="route-name">{r.name}</span>
              <span className="muted small">
                {r.avg_minutes ? `~${duration(r.avg_minutes * 60)}` : ""}
                {r.count
                  ? ` · ${r.this_year}× this year · ${r.count}× total · last ${shortDate(r.last)}`
                  : " · from your Routes"}
              </span>
            </button>
          ))}
          {list.data && !routes.length && (
            <p className="muted small">
              No routes yet: rides from Strava show here once they have their map line (CoachQuest fetches them
              for rides you already have; this can take a while), and favourites from Routes.
            </p>
          )}
          {list.data?.rides_without_line > 0 && (
            <p className="muted small">
              {list.data.rides_without_line} Strava activities without a map line yet (indoor, or still being
              fetched).
            </p>
          )}
        </aside>
        <div className="weather-main">
          {current === "home" ? (
            <HomeForecast id={id} onHomeChanged={list.reload} />
          ) : (
            current && (
              <RouteForecast
                id={id}
                routeKey={current}
                usualStart={list.data?.usual_start || "07:00"}
                firstDay={current === params.get("route") ? params.get("day") : null}
              />
            )
          )}
        </div>
      </div>
    </>
  );
}

function HomeForecast({ id, onHomeChanged }) {
  const res = useApi(`/api/athletes/${id}/weather/home`);
  const [editing, setEditing] = useState(false);
  const home = res.data?.home;
  const changed = () => {
    setEditing(false);
    res.reload();
    onHomeChanged();
  };
  const editor = editing && <HomeLocation id={id} home={home} onSaved={changed} onCancel={() => setEditing(false)} />;
  if (res.error)
    return (
      <section className="card">
        <h2>Home forecast</h2>
        <div className="error">{res.error.message}</div>
        {editor || (
          <button type="button" onClick={() => setEditing(true)}>
            Set your home location
          </button>
        )}
      </section>
    );
  if (!res.data) return <p className="muted">Loading the forecast…</p>;
  return (
    <section className="card">
      <div className="row between">
        <h2>Home forecast</h2>
        {id === "me" && !editing && (
          <button type="button" className="link-btn small" onClick={() => setEditing(true)}>
            Change home location
          </button>
        )}
      </div>
      <p className="muted small">
        {home?.set ? `${home.name}, day by day.` : "Where your latest outdoor ride started, day by day."} Rides
        without a route on your plan use this forecast too.
      </p>
      {editor}
      <DayStrip days={res.data.days} />
    </section>
  );
}

// Pick a home location: search a town (Open-Meteo's place search), use this device's location, or go
// back to where the latest ride started.
function HomeLocation({ id, home, onSaved, onCancel }) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const save = async (body) => {
    setError(null);
    setBusy(true);
    try {
      await api(`/api/athletes/${id}/weather/home-location`, { method: "PUT", body });
      onSaved();
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  };
  const search = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      setFound((await api(`/api/athletes/${id}/weather/places?q=${encodeURIComponent(q.trim())}`)).places);
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };
  const here = () => {
    if (!navigator.geolocation) return setError("This browser can't share its location");
    setBusy(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => save({ lat: pos.coords.latitude, lng: pos.coords.longitude, name: "My location" }),
      () => {
        setBusy(false);
        setError("Couldn't get your location (allow it in the browser, or search for your town)");
      },
      { timeout: 15000 },
    );
  };
  return (
    <div className="home-location">
      <form className="row tight" onSubmit={search}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Town or suburb, e.g. Stellenbosch"
          aria-label="Search a place"
          minLength={2}
          required
        />
        <button type="submit" disabled={busy || q.trim().length < 2}>
          Search
        </button>
      </form>
      {found && !found.length && <p className="muted small">Nothing found; try another spelling or a nearby town.</p>}
      {found?.length > 0 && (
        <div className="place-list">
          {found.map((f) => (
            <button
              key={`${f.lat},${f.lng}`}
              type="button"
              className="route-item"
              disabled={busy}
              onClick={() => save({ lat: f.lat, lng: f.lng, name: f.name })}
            >
              <strong>{f.name}</strong>
              <span className="muted small">{f.where}</span>
            </button>
          ))}
        </div>
      )}
      <div className="row tight">
        <button type="button" className="link-btn small" disabled={busy} onClick={here}>
          📍 Use where I am now
        </button>
        {home?.set && (
          <button type="button" className="link-btn small" disabled={busy} onClick={() => save(undefined)}>
            Use where my latest ride started
          </button>
        )}
        <button type="button" className="link-btn small" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {error && <div className="error">{error}</div>}
    </div>
  );
}

function RouteForecast({ id, routeKey, usualStart, firstDay }) {
  const [start, setStart] = useState(usualStart);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [day, setDay] = useState(firstDay);
  const load = async () => {
    setError(null);
    try {
      const d = await api(`/api/athletes/${id}/weather/routes/${routeKey}?start=${start}`);
      setData(d);
      setDay((cur) => (d.days.some((x) => x.date === cur) ? cur : d.best[0] || d.days[0]?.date));
    } catch (e) {
      setError(e.message);
    }
  };
  useEffect(() => {
    setData(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeKey, start]);
  if (error)
    return (
      <div className="error">
        {error}{" "}
        <button type="button" className="link-btn small" onClick={load}>
          <RefreshCw size={12} /> Try again
        </button>
      </div>
    );
  if (!data) return <p className="muted">Loading the forecast along the route…</p>;
  const r = data.route;
  const d = data.days.find((x) => x.date === day) || data.days[0];
  const ride = d?.ride;
  const best = data.best.map((date) => data.days.find((x) => x.date === date));
  return (
    <>
      <div className="best-days">
        {best.map((b) => (
          <button key={b.date} type="button" className={`best-day rank-${b.rank}`} onClick={() => setDay(b.date)}>
            <span className="small accent">{RANK[b.rank]}</span>
            <strong>
              {b.ride.icon} {dayName(b.date)}
            </strong>
            <span className="small muted">
              {b.ride.wind_kmh}km/h wind, gusts {b.ride.gusts_kmh}km/h, {b.ride.rain_chance > 30 ? "rain likely" : "dry"},{" "}
              {b.ride.temp_min}–{b.ride.temp_max}°C
            </span>
          </button>
        ))}
      </div>
      <p className="muted small">
        Ranked for {r.name} on wind, gusts, headwind, rain and temperature during the hours you'd be riding from {start}.
        Tap a day to see it.
      </p>
      <section className="card route-card">
        <div className="route-head">
          <span className="small accent">{r.source === "favourite" ? "★ Favourite route" : r.category}</span>
          <h2>{r.name}</h2>
          {r.count > 0 && (
            <p className="muted small">
              Ridden {r.count}× since {shortDate(r.first)} · last {shortDate(r.last)}
            </p>
          )}
        </div>
        <div className="stats">
          <Tile label="Distance" value={`${r.distance_km}km`} />
          <Tile label="Climbing" value={`${r.elevation_m}m`} />
          {r.avg_minutes && <Tile label={r.count ? "Avg time" : "Est. time"} value={duration(r.avg_minutes * 60)} />}
          {r.fastest_minutes && <Tile label="Fastest" value={duration(r.fastest_minutes * 60)} />}
          {r.avg_speed_kmh && <Tile label="Avg speed" value={`${r.avg_speed_kmh}km/h`} />}
          {r.avg_hr && <Tile label="Avg HR" value={`${r.avg_hr}bpm`} />}
          {r.avg_power && <Tile label="Avg power" value={`${r.avg_power}W`} />}
        </div>
        <div className="route-body">
          <RouteMap line={data.line} kinds={ride?.stretches} windDeg={ride?.wind_deg} windFrom={ride?.wind_from} />
          <div className="ride-day">
            <h3>{dayName(d.date)} on this route</h3>
            <label className="inline">
              Ride start
              <select value={start} onChange={(e) => setStart(e.target.value)}>
                {[...new Set([...STARTS, start])].sort().map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
              {ride && <span className="muted small">→ finish ~{ride.finish}</span>}
            </label>
            {ride ? (
              <>
                <div className="stats">
                  <Tile label="Conditions" value={`${ride.icon} ${ride.label}`} />
                  <Tile label="Temp on ride" value={`${ride.temp_min}–${ride.temp_max}°C`} />
                  <Tile label="Rain chance" value={`${ride.rain_chance}%`} />
                  <Tile label="Rain (max/h)" value={`${ride.rain_mm}mm`} />
                  <Tile label="Wind" value={`${ride.wind_kmh}km/h ${ride.wind_from}`} />
                  <Tile label="Gusts" value={`${ride.gusts_kmh}km/h`} />
                </div>
                <WindBar share={ride.share} />
                <p className="small muted">
                  First half: {ride.first_half} · Second half: {ride.second_half}
                </p>
                {ride.direction && <p className="small">🧭 {ride.direction}</p>}
              </>
            ) : (
              <p className="muted small">No hourly forecast for this day yet.</p>
            )}
          </div>
        </div>
        {r.rides?.length > 0 && (
          <details>
            <summary className="small">Recent rides on this route ({r.count})</summary>
            <ul className="small">
              {r.rides.map((x) => (
                <li key={x.id}>
                  {shortDate(x.date)} · {x.name} · {duration(x.minutes * 60)}
                  {x.avg_power ? ` · ${Math.round(x.avg_power)}W` : ""}
                  {x.avg_hr ? ` · ${Math.round(x.avg_hr)}bpm` : ""}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
      <p className="small muted">{data.days.length} days on this route · click a day to see the wind for your ride</p>
      <DayStrip days={data.days} picked={d.date} onPick={setDay} />
    </>
  );
}

function Tile({ label, value }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value small-value">{value}</div>
    </div>
  );
}

function WindBar({ share }) {
  const parts = [
    ["head", "Headwind"],
    ["cross", "Crosswind"],
    ["tail", "Tailwind"],
    ["calm", "Calm"],
  ].filter(([k]) => share[k] > 0);
  return (
    <>
      <div className="wind-bar" aria-hidden="true">
        {parts.map(([k]) => (
          <span key={k} className={WIND_CLASS[k]} style={{ width: `${share[k]}%` }} />
        ))}
      </div>
      <p className="small">
        {parts.map(([k, label]) => (
          <span key={k} className="wind-key">
            <span className={`dot ${WIND_CLASS[k]}`} /> {label} {share[k]}%
          </span>
        ))}
      </p>
    </>
  );
}

// The route drawn from its points (no map tiles), each stretch coloured by its wind; an arrow shows
// where the wind blows to.
function RouteMap({ line, kinds, windDeg, windFrom }) {
  const W = 520;
  const H = 300;
  const lats = line.map((p) => p[0]);
  const lngs = line.map((p) => p[1]);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const k = Math.cos((midLat * Math.PI) / 180);
  const xs = lngs.map((v) => v * k);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...lats), Math.max(...lats)];
  const scale = Math.min((W - 40) / (x1 - x0 || 1e-6), (H - 40) / (y1 - y0 || 1e-6));
  const pt = (p) => [
    20 + (p[1] * k - x0) * scale + (W - 40 - (x1 - x0) * scale) / 2,
    20 + (y1 - p[0]) * scale + (H - 40 - (y1 - y0) * scale) / 2,
  ];
  const pts = line.map(pt);
  return (
    <div className="route-map">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="The route, coloured by the wind on each stretch">
        {pts.slice(0, -1).map((a, i) => (
          <line
            key={i}
            x1={a[0]}
            y1={a[1]}
            x2={pts[i + 1][0]}
            y2={pts[i + 1][1]}
            className={kinds ? WIND_CLASS[kinds[i]] : "wind-calm"}
            strokeWidth="4"
            strokeLinecap="round"
          />
        ))}
        <circle cx={pts[0][0]} cy={pts[0][1]} r="5" className="map-start" />
        {windDeg != null && (
          <g transform={`translate(${W - 36}, 36)`}>
            <circle r="22" className="map-compass" />
            <g transform={`rotate(${windDeg + 180})`}>
              <path d="M0,-14 L6,6 L0,2 L-6,6 Z" className="map-arrow" />
            </g>
            <text y="38" textAnchor="middle" className="map-label">
              from {windFrom}
            </text>
          </g>
        )}
      </svg>
      <p className="muted small">● start · route coloured by the wind on each stretch</p>
    </div>
  );
}

function DayStrip({ days, picked, onPick }) {
  return (
    <div className="day-strip">
      {days.map((x) => {
        const wet = x.rain_chance >= 50;
        return (
          <button
            key={x.date}
            type="button"
            className={`strip-day ${picked === x.date ? "on" : ""} ${wet ? "wet" : ""} ${x.rank ? `rank-${x.rank}` : ""}`}
            onClick={() => onPick?.(x.date)}
            disabled={!onPick}
          >
            {x.rank && <span className="tiny accent">{RANK[x.rank]}</span>}
            <strong>{dayName(x.date).split(" ")[0]}</strong>
            <span className="muted tiny">{dayName(x.date).split(" ").slice(1).join(" ")}</span>
            <span className="strip-icon">{x.icon}</span>
            <span className="tiny">{x.label}</span>
            <span className="small">
              {x.temp_min}° / {x.temp_max}°
            </span>
            <span className={`tiny ${wet ? "error-text" : "muted"}`}>💧 {x.rain_chance}%</span>
            <span className="tiny muted">
              🌬 {x.wind_kmh}km/h {x.wind_from}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function dayName(iso) {
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short" });
}
