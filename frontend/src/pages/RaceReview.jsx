import { Plus, Sparkles, Trash2 } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { dateTime, formatDate } from "../lib/format.js";
import Markdown from "../components/Markdown.jsx";

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
  // A stage race is reviewed a day at a time (?stage=3, so a link opens that day).
  const [search, setSearch] = useSearchParams();
  const stage = Number(search.get("stage")) || null;
  const q = stage ? `?stage=${stage}` : "";
  const root = `/api/athletes/${athleteId || "me"}/races/${raceId}/review`;
  const base = `${root}${q}`; // also the key of each part below: another race or day starts it afresh
  const res = useApi(base);
  // Each part below is keyed by `base`: moving to another race (a rider's review, say) starts them afresh,
  // so the rider columns, the form and the filters belong to the race shown.
  const [weather, setWeather] = useState(null);
  const [weatherError, setWeatherError] = useState(null);
  const [pacing, setPacing] = useState(null);
  const d = res.data;

  // The plan against the race: also slower (the route, and the race's track from Strava once). `paceAsk`:
  // the clock and neutral zone picked on the page (else the race's saved choice).
  const [paceAsk, setPaceAsk] = useState({});
  useEffect(() => {
    if (!d?.ride) return;
    setPacing(null);
    const params = new URLSearchParams(stage ? { stage: String(stage) } : {});
    if (paceAsk.basis) params.set("basis", paceAsk.basis);
    if (paceAsk.neutral_km !== undefined && paceAsk.neutral_km !== "") params.set("neutral_km", paceAsk.neutral_km);
    const qs = params.toString();
    api(`${root}/pacing${qs ? `?${qs}` : ""}`)
      .then(setPacing)
      .catch((e) => setPacing({ available: false, why: e.message }));
  }, [base, d?.ride?.activity_id, paceAsk]);

  // The weather is slower (a request per ride): asked for after the rest is shown.
  useEffect(() => {
    if (!d?.ride && !d?.earlier?.length) return;
    setWeather(null);
    api(`${root}/weather${q}`)
      .then(setWeather)
      .catch((e) => setWeatherError(e.message));
  }, [base, d?.ride?.activity_id, d?.earlier?.length]);

  // A stage race opened without a day: its first day.
  useEffect(() => {
    if (!stage && d?.stages?.length) setSearch({ stage: String(d.stages[0].day) }, { replace: true });
  }, [stage, d?.stages, setSearch]);

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

      {d.stages?.length > 0 && (
        <div className="tabs stage-tabs" role="tablist" aria-label="Days of the race">
          {d.stages.map((s) => (
            <button
              key={s.day}
              role="tab"
              aria-selected={stage === s.day}
              className={stage === s.day ? "active" : ""}
              onClick={() => setSearch({ stage: String(s.day) })}
            >
              Day {s.day}
              {s.name ? ` · ${s.name}` : ""}
              {s.distance_km ? ` · ${s.distance_km} km` : ""}
            </button>
          ))}
        </div>
      )}

      {d.ride && (
        <section className="card">
          <h2>{d.stage ? `Day ${d.stage.day}: your ride` : "Your ride"}</h2>
          {d.own && d.candidates.length > 1 && (
            <RidePicker key={`${base}#picker`} raceId={raceId} stage={stage} d={d} reload={res.reload} />
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

      {d.ride && !stage && (
        <section className="card">
          <h2>Plan vs race</h2>
          <PlanVsRace
            key={`${base}#plan`}
            p={pacing}
            own={d.own}
            raceId={raceId}
            ask={setPaceAsk}
            saved={{ basis: d.result.pace_basis, neutral_km: d.result.neutral_km }}
            reload={res.reload}
          />
        </section>
      )}

      {d.ride && (
        <Debrief
          key={`${base}#debrief`}
          raceId={raceId}
          stage={stage}
          debrief={stage ? d.result.stage_debriefs?.[String(stage)] : d.result.debrief}
          own={d.own}
          reload={res.reload}
        />
      )}

      {d.own ? (
        <PostRaceForm key={`${base}#form`} raceId={raceId} result={d.result} reload={res.reload} />
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
          <div className="table-wrap audit-table year-table">
            <table>
              <thead>
                <tr>
                  <th>Year</th>
                  <th className="num">Elapsed</th>
                  <th className="num">km/h</th>
                  <th className="num">NP</th>
                  <th className="num">TSS</th>
                  <th className="num">CTL in</th>
                  <th>Weather</th>
                  <th
                    className="num"
                    title="Time the wind cost (+) or gave (−) for the same steady power on flat ground, and the moving time without it: compare those across years"
                  >
                    Wind cost
                  </th>
                </tr>
              </thead>
              <tbody>
                {rides.map((r) => {
                  const wx = w(r.activity_id);
                  const temp = r.device_temp ?? (wx && !wx.error ? wx.temp_max : null);
                  const wind = wx?.wind;
                  return (
                    <tr key={r.activity_id}>
                      <td>
                        {r.year}
                        {d.ride && r.activity_id === d.ride.activity_id && (
                          <span className="seg-sub">this race</span>
                        )}
                      </td>
                      <td className="num">
                        {hms(r.elapsed_s)}
                        <span className="seg-sub">
                          moving {hms(r.moving_s)}
                          {r.stopped_s ? ` · stops ${hms(r.stopped_s)}` : ""}
                        </span>
                      </td>
                      <td className="num">{fmt(r.speed_moving)}</td>
                      <td className="num">
                        {fmt(r.norm_power, " W")}
                        {r.avg_hr && <span className="seg-sub">{r.avg_hr} bpm</span>}
                      </td>
                      <td className="num">{fmt(r.tss)}</td>
                      <td className="num">{fmt(r.ctl_before)}</td>
                      <td className="small" title={wx ? windText(wx) : ""}>
                        {temp != null ? `${temp}° · ` : ""}
                        {weatherError ? "–" : windShort(wx)}
                      </td>
                      <td className={`num ${wind?.wind_s > 30 ? "bad-text" : wind?.wind_s < -30 ? "ok-text" : ""}`}>
                        {wind ? gap(wind.wind_s) : "–"}
                        {wind && <span className="seg-sub">calm {hms(wind.calm_moving_s)}</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {d.segments.length > 0 && <SegmentTable key={`${base}#segments`} segments={d.segments} rides={rides} columns={d.segment_columns} />}

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

      <OfficialResults key={`${base}#results`} raceId={raceId} own={d.own} results={d.results} reload={res.reload} />

      {(d.own || d.standings.length > 0) && (
        <Riders key={`${base}#riders`} raceId={raceId} d={d} reload={res.reload} />
      )}
    </>
  );
}

// The pacing plan for the target time against the race as ridden: checkpoints and climbs.
const BASES = [
  ["official", "Official finish time"],
  ["moving", "Moving time"],
  ["elapsed", "Ride clock (elapsed)"],
];

function PlanVsRace({ p, own, raceId, ask, saved, reload }) {
  const [basis, setBasis] = useState(saved.basis || "");
  const [neutral, setNeutral] = useState(saved.neutral_km ?? "");
  const [msg, setMsg] = useState(null);
  const shown = p?.basis || basis;
  const apply = (b, n) => ask({ basis: b || undefined, neutral_km: b === "official" ? n : "" });
  const save = async () => {
    setMsg(null);
    try {
      await api(`/api/races/${raceId}/result`, {
        method: "PUT",
        body: {
          pace_basis: shown || null,
          neutral_km: shown === "official" && neutral !== "" ? Number(neutral) : null,
        },
      });
      setMsg("Saved for this race.");
      reload();
    } catch (e) {
      setMsg(e.message);
    }
  };
  const controls = p?.available !== false && (
    <div className="seg-controls">
      <label className="small seg-sort">
        Compare by
        <select
          value={shown}
          onChange={(e) => {
            setBasis(e.target.value);
            apply(e.target.value, neutral);
          }}
        >
          {BASES.map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {shown === "official" && (
        <label className="small seg-sort">
          Timing starts at km
          <input
            type="number"
            min="0"
            step="0.1"
            className="km-input"
            value={neutral}
            placeholder={p?.start_km != null ? String(p.start_km) : "auto"}
            onChange={(e) => setNeutral(e.target.value)}
            onBlur={() => apply("official", neutral)}
            onKeyDown={(e) => e.key === "Enter" && apply("official", neutral)}
            title="Where the race's timing started (the end of a neutral zone). Empty: worked out from your official time."
          />
        </label>
      )}
      {own && (
        <button className="btn small" onClick={save}>
          Save for this race
        </button>
      )}
      {msg && <span className="small muted">{msg}</span>}
    </div>
  );
  if (!p)
    return (
      <>
        {controls}
        <p className="muted small">Working out the plan against the race…</p>
      </>
    );
  if (!p.available) return <p className="muted small">{p.why}</p>;
  const verdict =
    p.final_gap_s == null
      ? null
      : Math.abs(p.final_gap_s) <= 60
        ? "on plan at the finish"
        : p.final_gap_s > 0
          ? `${hms(p.final_gap_s)} behind the plan at the finish`
          : `${hms(-p.final_gap_s)} ahead of the plan at the finish`;
  const gapCell = (g) => (
    <td className={`num ${g > 60 ? "bad-text" : g < -60 ? "ok-text" : ""}`}>{gap(g)}</td>
  );
  const how = {
    official:
      p.start_km != null
        ? `By the official time${p.official_time ? ` (${p.official_time})` : ""}, timed from km ${p.start_km}${
            p.start_found ? " (worked out from it: the neutral zone before)" : ""
          }; the plan from there is scaled to the target, with your ${p.stops_min} min of stops after it.`
        : "By the official time.",
    moving: "By moving time: stops and a neutral zone don't count, and the plan has no stops.",
    elapsed: `By the ride's clock from its start, with your ${p.stops_min} min of stops in the plan.`,
  }[p.basis];
  return (
    <>
      {controls}
      {p.notes?.map((n) => (
        <p key={n} className="notice small">
          {n}
        </p>
      ))}
      <p>
        <strong>
          Target {p.target_time}
          {verdict ? `: ${verdict}` : ""}.
        </strong>{" "}
        {p.behind_from_km != null && <>Behind the plan from km {p.behind_from_km}. </>}
        <span className="muted small">
          {how} The plan rides {p.base_power_w} W on the flat ({p.norm_power_w} W NP).
        </span>
      </p>
      <div className="plan-race">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th className="num">Km</th>
                <th className="num">Plan</th>
                <th className="num">Race</th>
                <th className="num">Gap</th>
              </tr>
            </thead>
            <tbody>
              {p.checkpoints.map((c) => (
                <tr key={c.km}>
                  <td className="num">{c.km}</td>
                  <td className="num">{hms(c.planned_s)}</td>
                  <td className="num">{hms(c.actual_s)}</td>
                  {gapCell(c.gap_s)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {p.climbs.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="num">Climb at km</th>
                  <th className="num">Length</th>
                  <th className="num">Target</th>
                  <th className="num">Race</th>
                  <th className="num">HR</th>
                  <th className="num">Plan</th>
                  <th className="num">Time</th>
                  <th className="num">Gap</th>
                </tr>
              </thead>
              <tbody>
                {p.climbs.map((c) => (
                  <tr key={c.start_km} className={c.neutral ? "muted" : undefined}>
                    <td className="num">
                      {c.start_km}
                      {c.neutral && <span className="seg-sub">neutral zone</span>}
                    </td>
                    <td className="num">
                      {c.length_km} km · {c.grade_pct}%
                    </td>
                    <td className="num">{c.target_w} W</td>
                    <td
                      className={`num ${c.actual_w && c.actual_w > c.target_w * 1.1 ? "bad-text" : ""}`}
                      title="More than 10% over the target is red: it costs later"
                    >
                      {fmt(c.actual_w, " W")}
                    </td>
                    <td className="num">{fmt(c.actual_hr)}</td>
                    <td className="num">{hms(c.planned_s)}</td>
                    <td className="num">{hms(c.actual_s)}</td>
                    {gapCell(c.gap_s)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

// The AI coach's debrief of the race (race_debrief.py): kept with the race, written again on request.
function Debrief({ raceId, stage, debrief, own, reload }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const write = async () => {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/races/${raceId}/debrief${stage ? `?stage=${stage}` : ""}`, { method: "POST" });
      reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  if (!debrief && !own) return null;
  return (
    <section className="card">
      <div className="row between">
        <h2>AI debrief</h2>
        {own && (
          <button className="btn small" onClick={write} disabled={busy}>
            <Sparkles size={14} className={busy ? "spin" : undefined} />{" "}
            {busy ? "Writing…" : debrief ? "Write again" : "Write a debrief"}
          </button>
        )}
      </div>
      {!debrief && (
        <p className="muted small">
          The AI coach reads this review (your ride against the target and earlier years, the plan against the race,
          the segments, the wind and your notes) and writes what went well, where time went, and what to change. The
          lessons go into your next plans.
        </p>
      )}
      {error && <div className="error">{error}</div>}
      {debrief && (
        <>
          <Markdown>{debrief.md}</Markdown>
          {debrief.key_points?.length > 0 && (
            <>
              <h3>For next time</h3>
              <ul>
                {debrief.key_points.map((k) => (
                  <li key={k}>{k}</li>
                ))}
              </ul>
            </>
          )}
          <p className="muted small">Written {dateTime(debrief.at)}. General guidance, not medical advice.</p>
        </>
      )}
    </section>
  );
}

// The official results, pasted in (race_results.py): where the athlete placed, and the riders around them.
function OfficialResults({ raceId, own, results, reload }) {
  const [text, setText] = useState("");
  const [pasting, setPasting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState(null);
  const call = async (path, opts) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api(path, opts);
      setPasting(false);
      setText("");
      setHits(null);
      reload();
      return r;
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const search = async () => {
    setError(null);
    try {
      setHits(await api(`/api/races/${raceId}/results/search?q=${encodeURIComponent(q)}`));
    } catch (e) {
      setError(e.message);
    }
  };
  if (!results && !own) return null;
  const r = results;
  const showPaste = own && (!r || pasting);
  return (
    <section className="card">
      <div className="row between">
        <h2>Official results</h2>
        {own && r && !pasting && (
          <span className="row tight">
            <button className="btn small" onClick={() => setPasting(true)}>
              Paste new results
            </button>
            <button
              className="btn small"
              disabled={busy}
              onClick={() => call(`/api/races/${raceId}/results`, { method: "DELETE" })}
            >
              Remove
            </button>
          </span>
        )}
      </div>
      {showPaste && (
        <>
          <p className="muted small">
            On the race's results page, select the whole table (or open its CSV download and select all), copy, and paste
            it here. CoachQuest finds the names, categories and times, finds you, and fills in your position and
            category in the post-race update where they're empty.
          </p>
          <textarea
            rows={6}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"Pos\tName\tCategory\tTime\n1\tPieter van Wyk\tM40\t2:01:05\n…"}
            aria-label="Results to paste"
            className="results-paste"
          />
          <div className="row tight">
            <button
              className="btn small"
              disabled={busy || !text.trim()}
              onClick={() => call(`/api/races/${raceId}/results`, { method: "PUT", body: { text } })}
            >
              {busy ? "Reading…" : "Import the results"}
            </button>
            {pasting && (
              <button className="btn small" onClick={() => setPasting(false)}>
                Cancel
              </button>
            )}
          </div>
        </>
      )}
      {error && <div className="error">{error}</div>}
      {r && !pasting && (
        <>
          {r.position ? (
            <p>
              <strong>
                {r.position} of {r.field}
              </strong>{" "}
              {r.percentile != null && <span className="muted">(ahead of {100 - r.percentile}% of finishers)</span>}
              {r.category && r.category_position ? (
                <>
                  {" "}
                  · <strong>{r.category}</strong>: {r.category_position} of {r.category_size}
                </>
              ) : null}
              {r.gap_to_winner_s != null && r.winner && (
                <>
                  {" "}
                  · {hms(r.gap_to_winner_s)} behind the winner ({r.winner.name}, {r.winner.time})
                </>
              )}
            </p>
          ) : (
            <p className="muted small">
              {r.field} finishers{r.winner ? `, won by ${r.winner.name} in ${r.winner.time}` : ""}.{" "}
              {own ? "CoachQuest didn't find you in them: search for your name." : ""}
            </p>
          )}
          {own && r.me == null && (
            <div className="row tight">
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Your name as in the results" />
              <button className="btn small" disabled={q.trim().length < 2} onClick={search}>
                Search
              </button>
              {hits && hits.length === 0 && <span className="muted small">No one by that name.</span>}
              {hits?.map((h) => (
                <button
                  key={h.index}
                  className="btn small"
                  onClick={() => call(`/api/races/${raceId}/results/me`, { method: "PUT", body: { index: h.index } })}
                >
                  That's me: {h.name} {h.category ? `(${h.category})` : ""} {h.time || ""}
                </button>
              ))}
            </div>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>Rider</th>
                  <th>Category</th>
                  <th className="num">Time</th>
                  <th className="num">Gap</th>
                </tr>
              </thead>
              <tbody>
                {r.around.map((x) => (
                  <tr key={x.index} className={x.me ? "diff" : ""}>
                    <td className="num">{x.place ?? "–"}</td>
                    <td>{x.name}</td>
                    <td>{x.category || "–"}</td>
                    <td className="num">{x.time || "DNF"}</td>
                    <td className="num">{x.me ? "" : gap(x.gap_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {own && r.me != null && (
            <button
              className="link-btn small"
              onClick={() => call(`/api/races/${raceId}/results/me`, { method: "PUT", body: { index: null } })}
            >
              Not you? Search again
            </button>
          )}
        </>
      )}
    </section>
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

function RidePicker({ raceId, stage, d, reload }) {
  const [error, setError] = useState(null);
  const pick = async (id) => {
    setError(null);
    try {
      await api(`/api/races/${raceId}/result${stage ? `?stage=${stage}` : ""}`, {
        method: "PUT",
        body: { activity_id: id ? Number(id) : null },
      });
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

// `mine`: the athlete's time on the segment in the race, for a rider's cell: the athlete's gap to them.
function SegCell({ t, best, mine }) {
  if (!t) return <span className="muted">–</span>;
  const effort = [t.watts && `${t.watts} W`, t.hr && `${t.hr} bpm`].filter(Boolean);
  const yours = mine != null && t.elapsed_s != null ? mine - t.elapsed_s : null;
  return (
    <>
      <span className={best ? "seg-time best" : "seg-time"}>{hms(t.elapsed_s)}</span>
      {effort.length > 0 && <span className="seg-sub">{effort.join(" · ")}</span>}
      {t.kmh && <span className="seg-sub">{t.kmh} km/h</span>}
      {yours != null && (
        <span className={`seg-sub ${yours < 0 ? "ok-text" : yours > 0 ? "bad-text" : ""}`}>you {gap(yours)}</span>
      )}
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

function SegRow({ s, cols, similar = 0, open, toggle, child }) {
  const race = cols.find((c) => c.kind === "race")?.key;
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
      {cols.map((c) => (
        <td key={c.key} className={`num seg-cell ${c.kind === "rider" ? "seg-rider" : ""}`}>
          <SegCell
            t={s.times[c.key]}
            best={c.kind !== "rider" && s.best === c.key && Object.keys(s.times).length > 1}
            mine={c.kind === "rider" && race ? s.times[race]?.elapsed_s : null}
          />
        </td>
      ))}
      <td className={`num seg-vs ${s.vs_best_before < 0 ? "ok-text" : s.vs_best_before > 0 ? "bad-text" : ""}`}>
        {gap(s.vs_best_before)}
      </td>
    </tr>
  );
}

const RIDERS_SHOWN = 3; // rider columns at first; the chips add or remove them

// The best of the athlete's years shown, and "vs best": the race against the best of the earlier years
// shown (negative is faster). Hiding a year takes it out of both; riders never count.
export function rescore(s, cols) {
  const race = cols.find((c) => c.kind === "race")?.key;
  const own = cols.filter((c) => c.kind === "race" || c.kind === "year").map((c) => c.key);
  const t = (k) => s.times[k]?.elapsed_s;
  const timed = own.filter((k) => t(k));
  const best = timed.length > 1 ? timed.reduce((a, b) => (t(b) < t(a) ? b : a)) : null;
  const earlier = timed.filter((k) => k !== race).map(t);
  const vs = race && t(race) && earlier.length ? t(race) - Math.min(...earlier) : null;
  return { ...s, best, vs_best_before: vs };
}

function SegmentTable({ segments, rides, columns }) {
  const allCols = columns || rides.map((r, i) => ({ key: String(r.year), label: String(r.year), kind: i ? "year" : "race" }));
  const riders = allCols.filter((c) => c.kind === "rider");
  const optional = allCols.filter((c) => c.kind !== "race"); // the race itself is always shown
  // Only the columns switched on or off by hand are kept; the rest follow the default (every year, the first
  // few riders), so it holds for whatever race's data is on screen.
  const [switched, setSwitched] = useState({});
  const isOn = (c) =>
    c.kind === "race" || (switched[c.key] ?? (c.kind === "year" || riders.indexOf(c) < RIDERS_SHOWN));
  const cols = allCols.filter(isOn);
  const flip = (c) => setSwitched({ ...switched, [c.key]: !isOn(c) });
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("course");
  const [all, setAll] = useState(false);
  const [opened, setOpened] = useState(() => new Set());
  const keep = SEG_FILTERS.find(([k]) => k === filter)[2];
  const order = SEG_SORTS.find(([k]) => k === sort)[2];
  const shown = segments.map((s) => rescore(s, cols)).filter(keep);
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
        The best year is in bold; "vs best" is this race against your best earlier year (green: faster), of the years
        shown: pick them under Columns. Other riders on CoachQuest who rode it have their own column, with your gap to
        them. Segments over the same stretch are folded together.
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
        {optional.length > 0 && (
          <div className="seg-chips" role="group" aria-label="Columns: years and riders">
            <span className="small muted">Columns</span>
            {optional.map((c) => (
              <button
                key={c.key}
                className={`btn small ${c.kind === "rider" ? "chip-rider" : ""} ${isOn(c) ? "active" : ""}`}
                aria-pressed={isOn(c)}
                title={c.kind === "rider" ? `${c.label}: show or hide` : `${c.label}: show or hide (also in "vs best")`}
                onClick={() => flip(c)}
              >
                {c.label}
              </button>
            ))}
          </div>
        )}
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
              {cols.map((c) => (
                <th key={c.key} className={`num ${c.kind === "rider" ? "seg-rider" : ""}`}>
                  {c.label}
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
                  cols={cols}
                  similar={similar.length}
                  open={opened.has(lead.id)}
                  toggle={() => toggle(lead.id)}
                />
                {opened.has(lead.id) && similar.map((s) => <SegRow key={s.id} s={s} cols={cols} child />)}
              </Fragment>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={cols.length + 3} className="muted">
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
      {d.own ? (
        <p className="muted small">
          Athletes on CoachQuest who share their activities with you and rode this race (same day, same route), with
          their own post-race update when they share their plans too, and riders you add. Strava doesn't let apps read
          other riders' rides or segment leaderboards, so add the ones you want to compare with from the results.
        </p>
      ) : (
        <p className="muted small">
          Everyone on CoachQuest you may see who rode this race (same day, same route), with their own post-race
          update, and the riders {d.athlete.name} added.
        </p>
      )}
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
                  <th className="num">Official</th>
                  <th>Position</th>
                  <th className="num">Elapsed</th>
                  <th className="num">Moving</th>
                  <th className="num">km/h</th>
                  <th className="num">NP</th>
                  <th className="num">Avg HR</th>
                  <th>Felt</th>
                </tr>
              </thead>
              <tbody>
                {d.others.map((o) => {
                  const u = o.post_race || {};
                  return (
                    <tr key={o.athlete_id}>
                      <td>
                        <Link
                          to={
                            o.race_id ? `/athletes/${o.athlete_id}/races/${o.race_id}/review` : `/athletes/${o.athlete_id}`
                          }
                        >
                          {o.name}
                        </Link>
                      </td>
                      <td className="num">{u.official_time || "–"}</td>
                      <td>
                        {u.position ? `${u.position}${u.field_size ? ` of ${u.field_size}` : ""}` : "–"}
                        {u.category_position ? ` · ${u.category || "cat"} ${u.category_position}` : ""}
                      </td>
                      <td className="num">{hms(o.elapsed_s)}</td>
                      <td className="num">{hms(o.moving_s)}</td>
                      <td className="num">{fmt(o.speed_moving)}</td>
                      <td className="num">{fmt(o.norm_power, " W")}</td>
                      <td className="num">{fmt(o.avg_hr)}</td>
                      <td>{u.feeling ? FEELINGS[u.feeling - 1][1].split(" · ")[1] : "–"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {d.others.some((o) => TEXTS.some(([k]) => o.post_race?.[k])) && (
            <div className="other-updates">
              <h3>Their post-race updates</h3>
              {d.others
                .filter((o) => TEXTS.some(([k]) => o.post_race?.[k]))
                .map((o) => (
                  <div key={o.athlete_id} className="other-update">
                    <strong>{o.name}</strong>
                    {TEXTS.filter(([k]) => o.post_race[k]).map(([k, label]) => (
                      <p key={k} className="small">
                        <span className="muted">{label}:</span> {o.post_race[k]}
                      </p>
                    ))}
                  </div>
                ))}
            </div>
          )}
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
