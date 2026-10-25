import { ArrowLeftRight, Lock, Unlock } from "lucide-react";
import { useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api, download } from "../lib/api.js";
import { duration } from "../lib/format.js";
import Markdown from "./Markdown.jsx";

const PHASES = ["Base", "Build", "Recovery", "Peak", "Taper", "Race", "Transition"];
const DAY_LABEL = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };
const fmtDate = (iso) => new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" });

export default function PlanTracker({ plan, athleteId, setPlan }) {
  const prefs = useApi(`/api/athletes/${athleteId}/preferences`);
  const [swapFrom, setSwapFrom] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const base = `/api/athletes/${athleteId}/plans/${plan.id}`;

  const call = async (path, method, body) => {
    setError(null);
    try {
      const updated = await api(base + path, { method, body });
      setPlan(updated);
      return updated;
    } catch (err) {
      setError(err.message);
    }
  };
  const editDay = (date, body) => call(`/days/${date}`, "PATCH", body);
  const editWeek = (i, body) => call(`/weeks/${i}`, "PATCH", body);
  const swap = async (date) => {
    if (!swapFrom) return setSwapFrom(date);
    if (swapFrom !== date) await call("/swap", "POST", { a: swapFrom, b: date });
    setSwapFrom(null);
  };
  const applyPrefs = async () => {
    const r = await call("/apply-preferences", "POST");
    if (r) setNotice(`${r.changed} future day${r.changed === 1 ? "" : "s"} changed to your weekday preferences.`);
  };

  const [replan, setReplan] = useState(null); // null = closed, else the reason being typed
  const [replanning, setReplanning] = useState(false);
  const runReplan = async (e) => {
    e.preventDefault();
    setReplanning(true);
    const r = await call("/replan", "POST", { reason: replan });
    setReplanning(false);
    if (r) {
      setReplan(null);
      setNotice(`Re-planned: ${r.changed} day${r.changed === 1 ? "" : "s"} changed. Past and locked days were kept.`);
    }
  };

  const ctx = { prefs: prefs.data, editDay, swap, swapFrom };
  return (
    <>
      <div className="row between tracker-bar">
        <p className="muted small">
          Click a day's type to change it, click a description to edit it. 🔒 locks a day so re-planning and swaps leave
          it alone.
        </p>
        <div className="row">
          <button className="btn" onClick={applyPrefs}>
            Apply weekday preferences to future days
          </button>
          <button
            className="btn"
            title="Workouts scheduled on the calendar in this plan's dates, as Zwift files"
            onClick={() =>
              download(`/api/athletes/${athleteId}/workouts/export.zip?plan_id=${plan.id}`).catch((err) =>
                setError(err.message),
              )
            }
          >
            Download plan workouts (ZIP)
          </button>
          <button className="btn primary" onClick={() => setReplan(replan === null ? "" : null)}>
            Re-plan from this week
          </button>
        </div>
      </div>
      {replan !== null && (
        <form className="card replan" onSubmit={runReplan}>
          <p className="small">
            The AI coach rewrites the rest of the plan from this week, using what you've logged so far. Past days and
            🔒 locked days stay as they are.
          </p>
          <label>
            What changed? (optional)
            <input
              value={replan}
              maxLength={1000}
              placeholder="e.g. sick for 3 days, travelling next week, felt strong"
              onChange={(e) => setReplan(e.target.value)}
            />
          </label>
          <div className="row">
            <button className="btn primary" disabled={replanning}>
              {replanning ? "Re-planning… (up to a minute)" : "Re-plan"}
            </button>
            <button type="button" className="btn" onClick={() => setReplan(null)} disabled={replanning}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {swapFrom && <div className="ok small">Pick the day to swap with {fmtDate(swapFrom)}, or click ⇄ again to cancel.</div>}
      {notice && <div className="ok small">{notice}</div>}
      {error && <div className="error">{error}</div>}
      {plan.weeks.map((w, i) => (
        <Week key={w.start} week={w} index={i} editWeek={editWeek} ctx={ctx} />
      ))}
      {plan.content_md && (
        <details className="card">
          <summary>Coach's summary and "adjust if" rules</summary>
          <Markdown>{plan.content_md.split("\n### Week 1")[0]}</Markdown>
        </details>
      )}
    </>
  );
}

function Week({ week, index, editWeek, ctx }) {
  const s = week.summary;
  return (
    <section className={`card week ${week.is_current ? "current" : ""}`}>
      <div className="row between week-head">
        <div className="row">
          {week.is_current && <span className="muted small">THIS WEEK — </span>}
          <strong>Week {index + 1}</strong>
          <select
            aria-label="Phase"
            className="phase"
            value={week.phase}
            onChange={(e) => editWeek(index, { phase: e.target.value })}
          >
            {PHASES.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
          <span className="muted small">
            {fmtDate(week.start)} – {fmtDate(week.days[6].date)}
          </span>
        </div>
        <div className="row small">
          <span className="muted">
            {s.sessions_done}/{s.sessions_due} sessions · {duration(s.logged_minutes * 60)} of{" "}
            {duration(s.planned_minutes * 60)} planned
          </span>
          <button
            className={`chip ${week.status === "confirmed" ? "on" : ""}`}
            onClick={() => editWeek(index, { status: week.status === "confirmed" ? "draft" : "confirmed" })}
          >
            {week.status === "confirmed" ? "Confirmed" : "Draft"}
          </button>
        </div>
      </div>
      <EditableText
        className="week-focus"
        value={week.focus}
        placeholder="Focus for this week…"
        onSave={(focus) => editWeek(index, { focus })}
      />
      <div className="days">
        {week.days.map((d) => (
          <Day key={d.date} day={d} ctx={ctx} />
        ))}
      </div>
    </section>
  );
}

function Day({ day, ctx }) {
  const types = ctx.prefs?.session_types || [day.type];
  const tags = ctx.prefs?.note_tags || [];
  const [editing, setEditing] = useState(false);
  const save = (body) => ctx.editDay(day.date, body);
  return (
    <div className={`day status-${day.status} ${day.is_today ? "today" : ""} ${day.type === "Rest" ? "rest" : ""}`}>
      <div className="day-label">
        {DAY_LABEL[day.weekday]}
        {day.is_today && " ←"}
        <span className="muted small">{fmtDate(day.date)}</span>
      </div>
      <div className="day-tools">
        <select aria-label="Session type" className="type-pick" value={day.type} onChange={(e) => save({ type: e.target.value })}>
          {[...new Set([day.type, ...types])].map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        <div className="row tight">
          <button
            className={`icon-btn ${ctx.swapFrom === day.date ? "active" : ""}`}
            title="Swap with another day"
            aria-label="Swap"
            disabled={day.locked}
            onClick={() => ctx.swap(day.date)}
          >
            <ArrowLeftRight size={14} />
          </button>
          <button
            className="icon-btn"
            title={day.locked ? "Unlock" : "Lock"}
            aria-label={day.locked ? "Unlock" : "Lock"}
            onClick={() => save({ locked: !day.locked })}
          >
            {day.locked ? <Lock size={14} /> : <Unlock size={14} />}
          </button>
        </div>
      </div>
      <div className="day-body">
        {editing ? (
          <DayEditor day={day} onDone={(body) => (setEditing(false), body && save(body))} />
        ) : (
          <button className="day-desc" onClick={() => setEditing(true)} title="Click to edit">
            {day.description || (day.type === "Rest" ? "Recovery day." : <span className="muted">Add a description…</span>)}
            {day.duration_min > 0 && <span className="muted"> ~{duration(day.duration_min * 60)}</span>}
          </button>
        )}
        {!editing && (day.intensity.length > 0 || day.gear || day.route) && (
          <div className="chips tight">
            {day.intensity.map((c) => (
              <span key={c} className="badge intensity">
                {c}
              </span>
            ))}
            {day.gear && <span className="badge">🚲 {day.gear}</span>}
            {day.route && <span className="badge">🗺 {day.route}</span>}
          </div>
        )}
        <Actual day={day} tags={tags} save={save} />
      </div>
    </div>
  );
}

function Actual({ day, tags, save }) {
  const a = day.actual;
  const logged = a && (
    <span className="muted">
      Logged: {a.km} km · {a.elevation_m.toLocaleString()} m↑ · {duration(a.minutes * 60)}
      {a.relative_effort ? ` · RE ${a.relative_effort}` : ""}
      {a.avg_power ? ` · ${a.avg_power}W avg` : ""}
      {a.avg_hr ? ` · ${a.avg_hr}bpm avg` : ""} ({a.types.join(", ")})
    </span>
  );
  switch (day.status) {
    case "goal_met":
      return <div className="actual ok-text">✓ Goal met {logged}</div>;
    case "partial":
      return <div className="actual warn-text">◐ Partly done {logged}</div>;
    case "extra":
      return <div className="actual muted">+ Trained on a rest day {logged}</div>;
    case "missed":
      return (
        <div className="actual bad-text row tight">
          ✗ Not logged
          <select
            aria-label="Why missed"
            value={day.missed_reason || ""}
            onChange={(e) => save({ missed_reason: e.target.value || null })}
          >
            <option value="">why missed?</option>
            {[...new Set([...tags, ...(day.missed_reason ? [day.missed_reason] : [])])].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
      );
    default:
      return null;
  }
}

function DayEditor({ day, onDone }) {
  const [form, setForm] = useState({
    description: day.description,
    duration_min: day.duration_min,
    intensity: day.intensity.join(", "),
    gear: day.gear || "",
    route: day.route || "",
  });
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = (e) => {
    e.preventDefault();
    onDone({
      description: form.description,
      duration_min: Number(form.duration_min) || 0,
      intensity: form.intensity.split(",").map((s) => s.trim()).filter(Boolean),
      gear: form.gear || null,
      route: form.route || null,
    });
  };
  return (
    <form className="day-editor" onSubmit={submit}>
      <textarea rows={2} value={form.description} onChange={set("description")} autoFocus />
      <div className="row tight">
        <label className="inline">
          Minutes <input type="number" min={0} value={form.duration_min} onChange={set("duration_min")} />
        </label>
        <label className="inline grow">
          Intensity <input value={form.intensity} onChange={set("intensity")} placeholder="Z2, 95-105% FTP" />
        </label>
        <label className="inline">
          Bike / gear <input value={form.gear} onChange={set("gear")} placeholder="Trek Domane" />
        </label>
        <label className="inline grow">
          Route <input value={form.route} onChange={set("route")} placeholder="Stellies / Devon loop or link" />
        </label>
      </div>
      <div className="row tight">
        <button className="btn primary">Save</button>
        <button type="button" className="btn" onClick={() => onDone(null)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function EditableText({ value, placeholder, onSave, className }) {
  const [editing, setEditing] = useState(false);
  if (editing) {
    return (
      <input
        className={className}
        defaultValue={value}
        autoFocus
        onBlur={(e) => {
          setEditing(false);
          if (e.target.value !== value) onSave(e.target.value);
        }}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      />
    );
  }
  return (
    <button className={`${className} text-btn`} onClick={() => setEditing(true)}>
      {value || <span className="muted">{placeholder}</span>}
    </button>
  );
}
