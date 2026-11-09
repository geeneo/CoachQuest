import { CalendarDays, Sparkles, Trash2, X } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import RoutePicker from "../components/RoutePicker.jsx";
import { duration, shortDate } from "../lib/format.js";

// Click a field, change it, click away: it saves. Empty number fields clear the value.
const FIELDS = [
  ["name", "Name", "text", "wide-cell"],
  ["short_name", "Short", "text", "short-cell"],
  ["distance_km", "Dist (km)", "number", "num-cell"],
  ["elevation_m", "Elev (m)", "number", "num-cell"],
  ["discipline", "Discipline", "select", ""],
  ["target_date", "Date / start", "date", "date-cell"], // the start time sits under the date
  ["target_time", "Target time", "text", "short-cell"],
  ["target_ctl", "Target CTL", "number", "num-cell"],
  ["days", "Days", "number", "num-cell"],
];

function toBody(field, raw) {
  if (["distance_km", "elevation_m", "target_ctl", "days"].includes(field)) return raw === "" ? null : Number(raw);
  return raw === "" ? null : raw;
}

export default function Races() {
  const races = useApi("/api/athletes/me/races");
  const disciplines = useApi("/api/races/disciplines");
  const [error, setError] = useState(null);
  const [asking, setAsking] = useState(null);
  const [openStages, setOpenStages] = useState(null); // race id whose days are shown
  const favourites = useApi("/api/athletes/me/segments");
  const stagesOf = races.data?.find((r) => r.id === openStages);
  useEffect(() => {
    if (openStages) document.getElementById("race-days")?.scrollIntoView({ behavior: "smooth" });
  }, [openStages]);

  const askAi = async (race) => {
    setError(null);
    setAsking(race.id);
    try {
      await api(`/api/races/${race.id}/ctl-advice`, { method: "POST" });
      races.reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setAsking(null);
    }
  };
  const hideAdvice = (race) =>
    api(`/api/races/${race.id}/ctl-advice`, { method: "DELETE" }).then(races.reload, (e) => setError(e.message));

  const save = (race, field, raw) => {
    const value = toBody(field, raw);
    if ((race[field] ?? null) === value) return;
    setError(null);
    api(`/api/races/${race.id}`, { method: "PATCH", body: { [field]: value } }).then(races.reload, (e) =>
      setError(e.message),
    );
  };
  const remove = (race) =>
    confirm(`Delete ${race.name}?`) &&
    api(`/api/races/${race.id}`, { method: "DELETE" }).then(races.reload, (e) => setError(e.message));

  return (
    <>
      <h1>Races</h1>
      <p className="muted">
        Events you're training for. They show as a countdown on My training, can be linked to activities, and the AI
        coach plans toward the active ones (date and target CTL). Click a field and click away to save.
      </p>
      <p className="muted small">
        Set a target finish time (h:mm) and CoachQuest works out the power or pace it takes; <Sparkles size={12} /> asks
        the AI coach which target CTL that needs and whether it's realistic. Its suggestion is only saved when you click
        Use.
      </p>
      {error && <div className="error">{error}</div>}
      <section className="card">
        <div className="table-wrap">
          <table className="edit-table races-table">
            <thead>
              <tr>
                {FIELDS.map(([f, label]) => (
                  <th key={f}>{label}</th>
                ))}
                <th>Route</th>
                <th>Active</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {races.data?.map((r) => (
                <Fragment key={r.id}>
                <tr className={r.days_to_go != null && r.days_to_go < 0 ? "past" : ""}>
                  {FIELDS.map(([f, label, type, cls]) => (
                    <td key={f} className={cls}>
                      <span className={f === "target_ctl" ? "cell-with-btn" : undefined}>
                        <Cell race={r} field={f} label={label} type={type} options={disciplines.data} save={save} />
                        {/* The race's code (used to link activities) under its name, not a column of its own. */}
                        {f === "name" && <span className="race-code muted small">{r.code}</span>}
                        {f === "target_date" && (
                          <Cell race={r} field="start_time" label="Start" type="time" save={save} />
                        )}
                        {f === "target_ctl" && r.target_time && r.days_to_go >= 0 && (
                          <button
                            className="icon-btn"
                            title="Ask the AI coach for a target CTL for this time"
                            aria-label={`Suggest a target CTL for ${r.name}`}
                            disabled={asking != null}
                            onClick={() => askAi(r)}
                          >
                            <Sparkles size={16} className={asking === r.id ? "spin" : undefined} />
                          </button>
                        )}
                      </span>
                    </td>
                  ))}
                  <td className="race-route">
                    <RoutePicker
                      label={`Route of ${r.name}`}
                      saved={favourites.data?.favourites || []}
                      stravaLinked={!!favourites.data?.strava_linked}
                      routesOnly
                      value={r.segment_id}
                      onSaved={favourites.reload}
                      onPick={(id) => save(r, "segment_id", id)}
                    />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label="Active"
                      checked={r.active}
                      onChange={(e) => save(r, "active", e.target.checked)}
                    />
                  </td>
                  <td className="row tight">
                    <button
                      className={`icon-btn ${openStages === r.id || r.stages.length ? "active" : ""}`}
                      title={r.stages.length ? `${r.stages.length} days: show or edit` : "Multi-day event: add its days"}
                      aria-label={`Days of ${r.name}`}
                      onClick={() => setOpenStages(openStages === r.id ? null : r.id)}
                    >
                      <CalendarDays size={16} />
                    </button>
                    <button className="icon-btn" aria-label={`Delete ${r.name}`} onClick={() => remove(r)}>
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
                {(r.estimate || r.ctl_advice) && r.days_to_go >= 0 && (
                  <tr className="race-extra">
                    <td colSpan={FIELDS.length + 3}>
                      <Estimate e={r.estimate} time={r.target_time} />
                      {r.ctl_advice && (
                        <Advice
                          race={r}
                          a={r.ctl_advice}
                          use={() => save(r, "target_ctl", String(r.ctl_advice.target_ctl))}
                          hide={() => hideAdvice(r)}
                        />
                      )}
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {races.data?.length === 0 && <p className="muted">No races yet. Add your first one below.</p>}
        <AddRace disciplines={disciplines.data || []} onAdded={races.reload} />
      </section>
      {stagesOf && (
        <section className="card" id="race-days">
          <div className="row between">
            <h2>
              <CalendarDays size={18} /> Days of {stagesOf.name}
            </h2>
            <button className="icon-btn" aria-label="Close the days" onClick={() => setOpenStages(null)}>
              <X size={16} />
            </button>
          </div>
          <StageTable
            key={stagesOf.id}
            race={stagesOf}
            routes={(favourites.data?.favourites || []).filter((f) => f.kind !== "segment")}
            onSaved={races.reload}
          />
        </section>
      )}
    </>
  );
}

const KINDS = ["prologue", "stage", "time trial", "marathon", "rest"];
const TERRAINS = ["", "road", "gravel", "mtb", "mixed", "trail"];
const blankStage = (day) => ({ day, kind: "stage", name: "", distance_km: "", elevation_m: "", terrain: "", start_time: "", notes: "", segment_id: "" });

// A multi-day event's days (backend race_stages.py): one row each, saved together. The race's distance,
// climbing and days become their totals. After the event, each day shows what was logged.
function StageTable({ race, routes, onSaved }) {
  const [rows, setRows] = useState(() =>
    race.stages.length
      ? race.stages.map((s) => ({ ...blankStage(s.day), ...s, distance_km: s.distance_km ?? "", elevation_m: s.elevation_m ?? "", segment_id: s.segment_id ?? "" }))
      : [blankStage(1), blankStage(2)],
  );
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const set = (i, k, v) => {
    setSaved(false);
    setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  };
  const dateOf = (day) => {
    if (!race.target_date) return "";
    const d = new Date(`${race.target_date}T12:00:00`);
    d.setDate(d.getDate() + day - 1);
    return shortDate(d.toISOString().slice(0, 10));
  };
  const riding = rows.filter((r) => r.kind !== "rest");
  const num = (v) => (v === "" || v == null ? 0 : Number(v));
  const effort = (r) => num(r.distance_km) + num(r.elevation_m) / 100;
  const longest = riding.length ? riding.reduce((a, b) => (num(b.distance_km) > num(a.distance_km) ? b : a)).day : null;
  const hardest = riding.length ? riding.reduce((a, b) => (effort(b) > effort(a) ? b : a)).day : null;
  const save = async (list) => {
    setError(null);
    try {
      await api(`/api/races/${race.id}/stages`, {
        method: "PUT",
        body: {
          stages: list.map((r) => ({
            ...r,
            distance_km: r.distance_km === "" ? null : Number(r.distance_km),
            elevation_m: r.elevation_m === "" ? null : Number(r.elevation_m),
            segment_id: r.segment_id === "" ? null : Number(r.segment_id),
          })),
        },
      });
      setSaved(true);
      onSaved();
    } catch (e) {
      setError(e.message);
    }
  };
  return (
    <div className="stage-table">
      <p className="small muted">
        A multi-day event (stage race): one line per day, rest days too. Saving makes the race's distance, climbing and
        days the totals, and the AI coach plans for riding hard on consecutive days. Day 1 is the race's date.
      </p>
      <div className="table-wrap">
        <table className="edit-table">
          <thead>
            <tr>
              <th>Day</th>
              <th>Kind</th>
              <th>Name</th>
              <th>Dist (km)</th>
              <th>Elev (m)</th>
              <th>Terrain</th>
              <th>Start</th>
              <th>Route</th>
              <th>Notes</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const rest = r.kind === "rest";
              const logged = race.stages.find((s) => s.day === r.day)?.logged;
              return (
                <Fragment key={i}>
                  <tr className={rest ? "past" : ""}>
                    <td className="num-cell">
                      <strong>{r.day}</strong> <span className="muted small">{dateOf(r.day)}</span>
                      {r.day === hardest && <span className="badge bad" title="Hardest day: distance and climbing">hardest</span>}
                      {r.day === longest && r.day !== hardest && <span className="badge">longest</span>}
                    </td>
                    <td>
                      <select aria-label={`Kind of day ${r.day}`} value={r.kind} onChange={(e) => set(i, "kind", e.target.value)}>
                        {KINDS.map((k) => (
                          <option key={k}>{k}</option>
                        ))}
                      </select>
                    </td>
                    <td className="wide-cell">
                      <input aria-label={`Name of day ${r.day}`} value={r.name} onChange={(e) => set(i, "name", e.target.value)} placeholder={rest ? "Rest day" : `Stage ${r.day}`} />
                    </td>
                    <td className="num-cell">
                      <input type="number" min={0} aria-label={`Distance of day ${r.day}`} disabled={rest} value={r.distance_km} onChange={(e) => set(i, "distance_km", e.target.value)} />
                    </td>
                    <td className="num-cell">
                      <input type="number" min={0} aria-label={`Climbing of day ${r.day}`} disabled={rest} value={r.elevation_m} onChange={(e) => set(i, "elevation_m", e.target.value)} />
                    </td>
                    <td>
                      <select aria-label={`Terrain of day ${r.day}`} disabled={rest} value={r.terrain} onChange={(e) => set(i, "terrain", e.target.value)}>
                        {TERRAINS.map((t) => (
                          <option key={t} value={t}>
                            {t || "—"}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input type="time" aria-label={`Start of day ${r.day}`} disabled={rest} value={r.start_time} onChange={(e) => set(i, "start_time", e.target.value)} />
                    </td>
                    <td>
                      <select aria-label={`Route of day ${r.day}`} disabled={rest || !routes.length} value={r.segment_id} onChange={(e) => set(i, "segment_id", e.target.value)}>
                        <option value="">—</option>
                        {routes.map((f) => (
                          <option key={f.id} value={f.id}>
                            {f.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="wide-cell">
                      <input aria-label={`Notes for day ${r.day}`} value={r.notes} maxLength={300} onChange={(e) => set(i, "notes", e.target.value)} placeholder="e.g. long climb at 60 km, tech descent" />
                    </td>
                    <td>
                      <button className="icon-btn" aria-label={`Remove day ${r.day}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                  {logged && (
                    <tr className="stage-logged">
                      <td />
                      <td colSpan={9} className="small">
                        ✅ Logged: {logged.km} km · {logged.elevation_m} m↑ · {duration(logged.minutes * 60)} ({logged.types.join(", ")})
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            <tr className="stage-totals">
              <td>
                <strong>{rows.length ? Math.max(...rows.map((r) => r.day)) : 0} days</strong>
              </td>
              <td className="small muted">{rows.length - riding.length ? `${rows.length - riding.length} rest` : ""}</td>
              <td className="small muted">Total</td>
              <td className="num-cell">
                <strong>{Math.round(riding.reduce((t, r) => t + num(r.distance_km), 0) * 10) / 10}</strong>
              </td>
              <td className="num-cell">
                <strong>{Math.round(riding.reduce((t, r) => t + num(r.elevation_m), 0))}</strong>
              </td>
              <td colSpan={5} />
            </tr>
          </tbody>
        </table>
      </div>
      <div className="row tight">
        <button type="button" className="btn small" onClick={() => setRows([...rows, blankStage((rows.length ? Math.max(...rows.map((r) => r.day)) : 0) + 1)])}>
          + Add day
        </button>
        <button type="button" className="btn small primary" onClick={() => save(rows)}>
          Save days
        </button>
        {race.stages.length > 0 && (
          <button
            type="button"
            className="link-btn small"
            onClick={() => confirm("Make this a one-day race again? Its days are removed.") && save([])}
          >
            Make it a one-day race
          </button>
        )}
        {saved && <span className="small ok-text">Saved: the race's distance, climbing and days are the totals now.</span>}
      </div>
      {error && <div className="error">{error}</div>}
    </div>
  );
}

// What the target time asks for, worked out by CoachQuest (no AI).
function Estimate({ e, time }) {
  if (!e) return null;
  const parts =
    e.kind === "ride"
      ? [
          `≈${e.avg_power_w} W average (${e.w_per_kg} W/kg)`,
          e.intensity_factor != null && `IF ${e.intensity_factor}, about ${e.tss} TSS`,
          `${e.avg_speed_kmh} km/h`,
        ]
      : e.kind === "run"
        ? [`${pace(e.pace_min_km)}/km`, `${pace(e.flat_pace_min_km)}/km on the flat (${e.flat_km} km equivalent)`]
        : [`${e.avg_speed_kmh} km/h`];
  return (
    <p className="small muted race-estimate">
      {time} takes {parts.filter(Boolean).join(" · ")}
      {e.assumptions?.length ? ` (assumes ${e.assumptions.join("; ")})` : ""}.
    </p>
  );
}

function pace(minutes) {
  const m = Math.floor(minutes);
  return `${m}:${String(Math.round((minutes - m) * 60)).padStart(2, "0")}`;
}

const VERDICT = { realistic: "Realistic", stretch: "A stretch", unlikely: "Unlikely" };

function Advice({ race, a, use, hide }) {
  const stale = a.for_time !== race.target_time;
  return (
    <div className={`ctl-advice ${a.verdict}`}>
      <Sparkles size={14} />
      <div>
        <strong>
          AI coach: target CTL {a.target_ctl} for {a.for_time} · {VERDICT[a.verdict] || a.verdict}
        </strong>
        {a.realistic_time && <span> · a realistic time: {a.realistic_time}</span>}
        {stale && <span className="muted"> · for an earlier target time, ask again</span>}
        <p className="small">{a.why}</p>
        {race.target_ctl !== a.target_ctl && !stale && (
          <button type="button" className="btn small" onClick={use}>
            Use {a.target_ctl}
          </button>
        )}
      </div>
      <button className="icon-btn" aria-label="Hide the suggestion" onClick={hide}>
        <X size={14} />
      </button>
    </div>
  );
}

function Cell({ race, field, label, type, options, save }) {
  const value = race[field] ?? "";
  if (type === "select") {
    return (
      <select aria-label={label} value={value} onChange={(e) => save(race, field, e.target.value)}>
        <option value="">— not set</option>
        {(options || []).map((d) => (
          <option key={d}>{d}</option>
        ))}
      </select>
    );
  }
  return (
    <input
      aria-label={label}
      type={type}
      defaultValue={value}
      key={`${race.id}-${field}-${value}`}
      min={type === "number" ? 0 : undefined}
      onBlur={(e) => save(race, field, e.target.value)}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
    />
  );
}

function AddRace({ disciplines, onAdded }) {
  const empty = { code: "", name: "", short_name: "", distance_km: "", elevation_m: "", discipline: "", target_date: "", start_time: "", target_time: "", target_ctl: "", days: "1" };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    const body = Object.fromEntries(
      Object.entries(form)
        .filter(([, v]) => v !== "")
        .map(([k, v]) => [k, toBody(k, v)]),
    );
    try {
      await api("/api/races", { method: "POST", body });
      setForm(empty);
      onAdded();
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <form className="add-race" onSubmit={submit}>
      <h3>Add a race</h3>
      <div className="row">
        <input placeholder="code (e.g. k2c)" value={form.code} onChange={set("code")} required size={10} />
        <input placeholder="Full name" value={form.name} onChange={set("name")} required />
        <input placeholder="Short (e.g. K2C)" value={form.short_name} onChange={set("short_name")} size={8} />
        <input type="number" min={0} placeholder="Dist km" value={form.distance_km} onChange={set("distance_km")} />
        <input type="number" min={0} placeholder="Elev m" value={form.elevation_m} onChange={set("elevation_m")} />
        <select value={form.discipline} onChange={set("discipline")}>
          <option value="">— discipline</option>
          {disciplines.map((d) => (
            <option key={d}>{d}</option>
          ))}
        </select>
        <input type="date" value={form.target_date} onChange={set("target_date")} aria-label="Date" />
        <input type="time" value={form.start_time} onChange={set("start_time")} aria-label="Start time" />
        <input placeholder="Target time (h:mm)" value={form.target_time} onChange={set("target_time")} size={10} />
        <input type="number" min={0} placeholder="Target CTL" value={form.target_ctl} onChange={set("target_ctl")} />
        <input type="number" min={1} placeholder="Days" value={form.days} onChange={set("days")} aria-label="Days" />
        <button className="btn primary">+ Add race</button>
      </div>
      {error && <div className="error">{error}</div>}
    </form>
  );
}
