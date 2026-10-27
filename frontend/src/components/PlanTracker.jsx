import { ArrowLeftRight, Lock, MessageSquare, Sparkles, Unlock } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { api, download } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { duration, shortDate } from "../lib/format.js";
import Markdown from "./Markdown.jsx";
import PlanComments from "./PlanComments.jsx";

const PHASES = ["Base", "Build", "Recovery", "Peak", "Taper", "Race", "Transition"];
const DAY_LABEL = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };
const fmtDate = shortDate;

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
    if (r)
      setNotice(
        `${r.changed} future day${r.changed === 1 ? "" : "s"} changed to your weekday preferences.` +
          (r.to_plan
            ? ` ${r.to_plan} new training day${r.to_plan === 1 ? " has" : "s have"} no session yet: use "Re-plan from this week" to fill ${r.to_plan === 1 ? "it" : "them"} in.`
            : ""),
      );
  };

  const [replan, setReplan] = useState(null); // null = closed, else the reason being typed
  const [coachNotes, setCoachNotes] = useState("");
  const [replanning, setReplanning] = useState(false);
  const isCoach = plan.viewer_role === "coach";
  const runReplan = async (e) => {
    e.preventDefault();
    setReplanning(true);
    const r = await call("/replan", "POST", { reason: replan, ...(isCoach ? { coach_notes: coachNotes } : {}) });
    setReplanning(false);
    if (r) {
      setReplan(null);
      setCoachNotes("");
      const days = `${r.changed} day${r.changed === 1 ? "" : "s"}`;
      setNotice(
        r.pending
          ? `Re-plan proposed (${days} would change) and sent to your coach. Your plan stays as it is until they approve.`
          : r.approval === "awaiting"
            ? `Re-planned: ${days} changed. It waits for your coach's approval.`
            : `Re-planned: ${days} changed. Past and locked days were kept.`,
      );
    }
  };

  const [comments, setComments] = useState([]);
  const [commentDay, setCommentDay] = useState(null);
  useEffect(() => {
    api(`${base}/comments`).then(setComments, () => {});
  }, [base]);
  const countByDay = comments.reduce((m, c) => (c.day ? { ...m, [c.day]: (m[c.day] || 0) + 1 } : m), {});
  const openComments = (date) => {
    setCommentDay(date);
    document.getElementById("plan-comments")?.scrollIntoView({ behavior: "smooth" });
  };

  const get = (path) => download(base + path).catch((err) => setError(err.message));
  const replanDay = async (date, body) => {
    const r = await call(`/days/${date}/replan`, "POST", body);
    if (r) {
      setNotice(`Proposed a new ${fmtDate(date)}: see the box at the top, then approve it to use it.`);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
    return r;
  };
  const ctx = {
    prefs: prefs.data,
    editDay,
    swap,
    swapFrom,
    countByDay,
    openComments,
    get,
    replanDay,
    isCoach: plan.viewer_role === "coach",
    usePlatform: (date, m) =>
      confirm(
        `Use ${m.platform_name}'s "${m.name}" on ${fmtDate(date)}? It takes ${duration(m.duration_s)}` +
          (m.tss != null ? ` (training load ${m.tss} TSS)` : "") +
          `, so the day's load changes. You can swap back to the plan's workout at any time.`,
      ) && call(`/days/${date}/platform-workout`, "POST", { platform_workout_id: m.id }),
    restorePlan: (date) => call(`/days/${date}/platform-workout`, "DELETE"),
    maxSessions: plan.max_sessions_per_day || 1,
  };
  const matching = plan.platform_matching || {};
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
          {isCoach && (
            <label>
              Coach's notes (the AI coach must follow these)
              <textarea
                rows={2}
                value={coachNotes}
                maxLength={2000}
                placeholder="e.g. Keep next week easy; move the long ride to Sunday"
                onChange={(e) => setCoachNotes(e.target.value)}
              />
            </label>
          )}
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
      <MatchStatus matching={matching} />
      {swapFrom && <div className="ok small">Pick the day to swap with {fmtDate(swapFrom)}, or click ⇄ again to cancel.</div>}
      {notice && <div className="ok small">{notice}</div>}
      {error && <div className="error">{error}</div>}
      {plan.weeks.map((w, i) => (
        <Week key={w.start} week={w} index={i} editWeek={editWeek} ctx={ctx} />
      ))}
      <PlanComments base={base} comments={comments} setComments={setComments} day={commentDay} setDay={setCommentDay} />
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
          {week.days.some((d) => d.workout) && (
            <button
              className="btn small"
              title="This week's indoor workouts as Zwift files, with install steps"
              onClick={() => ctx.get(`/weeks/${index}/workouts.zip`)}
            >
              ⬇ Indoor workouts
            </button>
          )}
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
  const [replanning, setReplanning] = useState(null); // null = closed, else {note, coach_notes, busy}
  const save = (body) => ctx.editDay(day.date, body);
  const canReplan = !day.locked && day.date >= new Date().toISOString().slice(0, 10);
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
          <button
            className={`icon-btn ${ctx.countByDay[day.date] ? "active" : ""}`}
            title="Comments on this day"
            aria-label="Comments"
            onClick={() => ctx.openComments(day.date)}
          >
            <MessageSquare size={14} />
            {ctx.countByDay[day.date] ? <span className="count">{ctx.countByDay[day.date]}</span> : null}
          </button>
          {canReplan && (
            <button
              className={`icon-btn ${replanning ? "active" : ""}`}
              title="Re-plan this day with the AI coach (uses this day's comments)"
              aria-label="Re-plan this day"
              onClick={() => setReplanning(replanning ? null : { note: "", coach_notes: "" })}
            >
              <Sparkles size={14} />
            </button>
          )}
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
        {!editing && (day.intensity.length > 0 || day.gear || day.route || day.workout) && (
          <div className="chips tight">
            {day.intensity.map((c) => (
              <span key={c} className="badge intensity">
                {c}
              </span>
            ))}
            {day.workout && (
              <button
                type="button"
                className="badge workout"
                title="Download for Zwift / MyWhoosh (.zwo)"
                onClick={() => ctx.get(`/days/${day.date}/zwo`)}
              >
                ⬇ {day.workout.name}
              </button>
            )}
            {day.gear && <span className="badge">🚲 {day.gear}</span>}
            {day.route && <span className="badge">🗺 {day.route}</span>}
          </div>
        )}
        {!editing && <PlatformMatches day={day} ctx={ctx} />}
        {!editing && <ExtraSessions day={day} types={types} max={ctx.maxSessions} save={save} />}
        <Actual day={day} tags={tags} save={save} />
        {replanning && (
          <form
            className="card replan day-replan"
            onSubmit={async (e) => {
              e.preventDefault();
              setReplanning({ ...replanning, busy: true });
              const ok = await ctx.replanDay(day.date, { note: replanning.note, coach_notes: replanning.coach_notes });
              setReplanning(ok ? null : { ...replanning, busy: false });
            }}
          >
            <p className="small">
              The AI coach rewrites only {DAY_LABEL[day.weekday]} {fmtDate(day.date)}, fitting it into the rest of the
              week and using this day's comments. You see the new day before it's used.
            </p>
            <label>
              What should change? (optional)
              <input
                value={replanning.note}
                maxLength={1000}
                placeholder="e.g. rest before the race, only 45 min, outdoors instead"
                onChange={(e) => setReplanning({ ...replanning, note: e.target.value })}
              />
            </label>
            {ctx.isCoach && (
              <label>
                Coach's notes (the AI coach must follow these)
                <input
                  value={replanning.coach_notes}
                  maxLength={2000}
                  onChange={(e) => setReplanning({ ...replanning, coach_notes: e.target.value })}
                />
              </label>
            )}
            <div className="row">
              <button className="btn primary" disabled={replanning.busy}>
                {replanning.busy ? "Re-planning…" : "Re-plan this day"}
              </button>
              <button type="button" className="btn" onClick={() => setReplanning(null)} disabled={replanning.busy}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

// Why indoor days show no Zwift / MyWhoosh match: no platform picked, an empty catalog, or nothing close.
function MatchStatus({ matching }) {
  const { user } = useAuth();
  if (!matching.enabled || !matching.indoor_days) return null;
  const fix = user.is_admin ? (
    <>
      Add some under <Link to="/admin">Admin → Platform workouts</Link>.
    </>
  ) : (
    "Ask your CoachQuest administrator to add some."
  );
  let text;
  if (!matching.platforms.length) {
    text = (
      <>
        Ride on Zwift or MyWhoosh? Tick it under <Link to="/connections">Connections → preferred platforms</Link> to see
        the closest workout there for each indoor day.
      </>
    );
  } else {
    const empty = matching.platforms.filter((p) => !matching.catalog[p]).map((p) => matching.platform_names[p]);
    const names = matching.platforms.map((p) => matching.platform_names[p]).join(" or ");
    if (empty.length) {
      text = (
        <>
          No {empty.join(" or ")} workouts in the catalog yet, so indoor days can't show the closest{" "}
          {empty.join(" or ")} workout. {fix}
        </>
      );
    } else if (!matching.matched_days) {
      text = (
        <>
          None of the {matching.indoor_days} upcoming indoor days has a close {names} workout in the catalog (a{" "}
          {matching.min_score}% match or better). {fix}
        </>
      );
    }
  }
  return text ? <p className="match-status small">{text}</p> : null;
}

// The day's other sessions (e.g. Strength after the ride): each its own type, text and time.
function ExtraSessions({ day, types, max, save }) {
  const extras = day.extra_sessions || [];
  const choices = types.filter((t) => t !== "Rest");
  const canAdd = day.type !== "Rest" && extras.length + 1 < max;
  if (!extras.length && !canAdd) return null;
  const put = (i, patch) => save({ extra_sessions: extras.map((e, j) => (j === i ? { ...e, ...patch } : e)) });
  const add = () => {
    const used = new Set([day.type, ...extras.map((e) => e.type)]);
    const type = choices.find((t) => !used.has(t)) || choices[0];
    save({ extra_sessions: [...extras, { type, description: "", duration_min: 0, intensity: [] }] });
  };
  return (
    <div className="extra-sessions">
      {extras.map((e, i) => (
        <div key={i} className="extra-session">
          <span className="muted">+</span>
          <select
            aria-label="Session type"
            className="type-pick"
            value={e.type}
            onChange={(ev) => put(i, { type: ev.target.value })}
          >
            {[...new Set([e.type, ...choices])].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <EditableText
            className="extra-desc"
            value={e.description}
            placeholder="What to do…"
            onSave={(description) => put(i, { description })}
          />
          <label className="inline small muted" title="Minutes">
            <input
              type="number"
              min={0}
              max={1440}
              className="minutes"
              defaultValue={e.duration_min}
              key={`${day.date}-${i}-${e.duration_min}`}
              onBlur={(ev) =>
                Number(ev.target.value) !== e.duration_min && put(i, { duration_min: Number(ev.target.value) || 0 })
              }
            />{" "}
            min
          </label>
          {e.intensity.map((c) => (
            <span key={c} className="badge intensity">
              {c}
            </span>
          ))}
          <button
            type="button"
            className="icon-btn"
            title="Remove this session"
            aria-label="Remove session"
            onClick={() => save({ extra_sessions: extras.filter((_, j) => j !== i) })}
          >
            ✕
          </button>
        </div>
      ))}
      {canAdd && (
        <button type="button" className="link-btn small add-session" onClick={add}>
          + Add a session this day
        </button>
      )}
    </div>
  );
}

// The closest Zwift / MyWhoosh workouts for an indoor day, and swapping to one (and back).
function PlatformMatches({ day, ctx }) {
  const w = day.workout;
  if (!w) return null;
  const matches = (day.platform_matches || []).filter((m) => m.id !== w.platform?.id);
  if (!w.platform && !matches.length) return null;
  return (
    <div className="platform-matches small">
      {w.platform && (
        <span className="row tight">
          <span className="muted">
            Using {w.platform.name}'s workout instead of the plan's "{w.original?.name}".
          </span>
          <button type="button" className="link-btn small" onClick={() => ctx.restorePlan(day.date)}>
            Back to the plan's workout
          </button>
        </span>
      )}
      {matches.map((m) => (
        <span key={m.id} className="row tight">
          <span title={`${duration(m.duration_s)}${m.tss != null ? ` · ${m.tss} TSS` : ""}`}>
            Closest on {m.platform_name}: <strong>{m.name}</strong>
            {m.collection && <span className="muted"> · {m.collection}</span>}{" "}
            <span className="muted">({m.score}% match)</span>
          </span>
          <button type="button" className="link-btn small" onClick={() => ctx.usePlatform(day.date, m)}>
            Use this
          </button>
        </span>
      ))}
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
