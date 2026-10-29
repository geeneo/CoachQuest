import { ArrowLeftRight, Lock, Map as MapIcon, MessageSquare, Sparkles, Unlock } from "lucide-react";
import { createContext, useContext, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { api, download } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { duration, shortDate } from "../lib/format.js";
import { blocks } from "../lib/workout.js";
import Markdown from "./Markdown.jsx";
import MuscleMap from "./MuscleMap.jsx";
import PlanComments from "./PlanComments.jsx";
import WorkoutChart from "./WorkoutChart.jsx";
import { useReadOnly } from "../lib/readOnly.js";

const PHASES = ["Base", "Build", "Recovery", "Peak", "Taper", "Race", "Transition", "Maintain"];
const DAY_LABEL = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };
const fmtDate = shortDate;

export default function PlanTracker({ plan, athleteId, setPlan }) {
  const ro = useReadOnly();
  const prefs = useApi(`/api/athletes/${athleteId}/preferences`);
  const segments = useApi(`/api/athletes/${athleteId}/segments`);
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
    ro,
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
    useLibrary: (date, m) =>
      confirm(
        `Use "${m.name}" from the CoachQuest library on ${fmtDate(date)}? It takes ${duration(m.duration_s)}` +
          (m.tss != null ? ` (training load ${m.tss} TSS)` : "") +
          `, so the day's load changes. You can swap back to the plan's workout at any time.`,
      ) && call(`/days/${date}/library-workout`, "POST", { slug: m.slug }),
    restorePlan: (date) => call(`/days/${date}/platform-workout`, "DELETE"),
    maxSessions: plan.max_sessions_per_day || 1,
    segments: segments.data?.favourites || [],
  };
  const matching = plan.platform_matching || {};
  return (
    <Photos.Provider value={!!plan.exercise_photos}>
      <div className="row between tracker-bar">
        <p className="muted small">
          {ro
            ? "View only."
            : "Click a day's type to change it, click a description to edit it. 🔒 locks a day so re-planning and swaps leave it alone."}
        </p>
        <div className="row">
          {!ro && (
            <button className="btn" onClick={applyPrefs}>
              Apply weekday preferences to future days
            </button>
          )}
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
          {!ro && (
            <button className="btn primary" onClick={() => setReplan(replan === null ? "" : null)}>
              Re-plan from this week
            </button>
          )}
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
    </Photos.Provider>
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
          {ctx.ro ? (
            <span className="badge">{week.phase}</span>
          ) : (
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
          )}
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
            disabled={ctx.ro}
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
        readOnly={ctx.ro}
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
  const [pickRoute, setPickRoute] = useState(false);
  // A route picked whose name isn't in the day's text: the text still describes the old ride.
  const [routeHint, setRouteHint] = useState(null);
  const canRoute = !ctx.ro && takesRoute(day.type) && ctx.segments.length > 0;
  const save = (body) => ctx.editDay(day.date, body);
  const canReplan = !ctx.ro && !day.locked && day.date >= new Date().toISOString().slice(0, 10);
  return (
    <div className={`day status-${day.status} ${day.is_today ? "today" : ""} ${day.type === "Rest" ? "rest" : ""}`}>
      <div className="day-label">
        {DAY_LABEL[day.weekday]}
        {day.is_today && " ←"}
        <span className="muted small">{fmtDate(day.date)}</span>
      </div>
      <div className="day-tools">
        {ctx.ro ? (
          <span className="badge type-pick">{day.type}</span>
        ) : (
          <select
            aria-label="Session type"
            className="type-pick"
            value={day.type}
            onChange={(e) => save({ type: e.target.value })}
          >
            {[...new Set([day.type, ...types])].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        )}
        <div className="row tight">
          {!ctx.ro && (
            <>
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
            </>
          )}
          {canRoute && (
            <button
              className={`icon-btn ${pickRoute || day.segment ? "active" : ""}`}
              title="Ride a favourite route or segment"
              aria-label="Route"
              onClick={() => setPickRoute(!pickRoute)}
            >
              <MapIcon size={14} />
            </button>
          )}
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
        {routeHint && day.segment?.id === routeHint.id && !replanning && (
          <div className="hint route-hint">
            The text still describes the old ride.{" "}
            {canReplan && (
              <button
                type="button"
                className="link-btn small"
                onClick={() => {
                  setReplanning({ note: `Ride ${routeHint.name} on this day.`, coach_notes: "" });
                  setRouteHint(null);
                }}
              >
                Re-plan this day for {routeHint.name}
              </button>
            )}{" "}
            or click the text to change it yourself.{" "}
            <button type="button" className="link-btn small" onClick={() => setRouteHint(null)}>
              Keep it
            </button>
          </div>
        )}
        {pickRoute && canRoute && (
          <label className="inline small route-pick">
            Ride
            <select
              autoFocus
              value={day.segment ? String(day.segment.id) : ""}
              onChange={(e) => {
                const picked = ctx.segments.find((s) => String(s.id) === e.target.value);
                save({ segment_id: picked ? picked.id : null });
                setPickRoute(false);
                const text = (day.description || "").toLowerCase();
                setRouteHint(picked && !text.includes(picked.name.toLowerCase()) ? picked : null);
              }}
            >
              <option value="">– no route –</option>
              {ctx.segments.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.kind === "segment" ? "⛰" : "🗺"} {s.name}
                </option>
              ))}
            </select>
            <button type="button" className="link-btn small" onClick={() => setPickRoute(false)}>
              Cancel
            </button>
          </label>
        )}
        {editing ? (
          <DayEditor
            day={day}
            segments={ctx.segments}
            onDone={(body) => (setEditing(false), body && save(body))}
          />
        ) : (
          <button
            className="day-desc"
            disabled={ctx.ro}
            onClick={() => setEditing(true)}
            title={ctx.ro ? undefined : "Click to edit"}
          >
            {day.description ||
              (day.type === "Rest" ? "Recovery day." : <span className="muted">{ctx.ro ? "" : "Add a description…"}</span>)}
            {day.duration_min > 0 && <span className="muted"> ~{duration(day.duration_min * 60)}</span>}
          </button>
        )}
        {!editing && (day.intensity.length > 0 || day.gear || day.route || day.workout || day.segment) && (
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
            {day.segment && <SegmentLink segment={day.segment} />}
            {day.gear && <span className="badge">🚲 {day.gear}</span>}
            {day.route && <span className="badge">🗺 {day.route}</span>}
          </div>
        )}
        {!editing && day.workout?.steps?.length > 0 && (
          <WorkoutChart blocks={blocks(day.workout.steps)} height={90} />
        )}
        {!editing && day.strength && <StrengthSession session={day.strength} />}
        {!editing && <PlatformMatches day={day} ctx={ctx} />}
        {!editing && (
          <ExtraSessions day={day} types={types} max={ctx.maxSessions} save={save} readOnly={ctx.ro} />
        )}
        <Actual day={day} tags={tags} save={save} readOnly={ctx.ro} />
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
  const fromLibrary = matching.library_days > 0 && (
    <>
      {" "}
      {text ? "Meanwhile, " : ""}
      {matching.library_days} indoor day{matching.library_days === 1 ? "" : "s"} without a{" "}
      {matching.platforms.length ? "platform" : "Zwift / MyWhoosh"} match show{matching.library_days === 1 ? "s" : ""}{" "}
      the closest workout from the <Link to="/workouts">CoachQuest library</Link>.
    </>
  );
  return text || fromLibrary ? (
    <p className="match-status small">
      {text}
      {fromLibrary}
    </p>
  ) : null;
}

// A strength session the AI coach wrote: each exercise with sets x reps, effort and rest; click one for how.
// Whether exercise photos are on (Admin → Settings, super admin): plan_out's exercise_photos.
const Photos = createContext(false);
const photoUrl = (id, n) => `/api/exercises/${encodeURIComponent(id)}/photo/${n}`;

// A photo of the movement; hides itself if there isn't one.
function ExercisePhoto({ id, n, className }) {
  const [gone, setGone] = useState(false);
  if (gone) return null;
  return <img className={className} src={photoUrl(id, n)} alt="" loading="lazy" onError={() => setGone(true)} />;
}

function StrengthSession({ session }) {
  const photos = useContext(Photos);
  const [open, setOpen] = useState(null); // exercise id shown with instructions
  const [info, setInfo] = useState({});
  const show = async (id) => {
    setOpen(open === id ? null : id);
    if (!info[id]) {
      try {
        const e = await api(`/api/exercises/${encodeURIComponent(id)}`);
        setInfo((i) => ({ ...i, [id]: e }));
      } catch {
        setInfo((i) => ({ ...i, [id]: { instructions: ["Couldn't load the instructions."] } }));
      }
    }
  };
  const rest = (s) => (s >= 60 ? `${Math.round((s / 60) * 2) / 2} min` : `${s} s`);
  return (
    <div className="strength-session small">
      {session.focus && <strong>🏋 {session.focus}</strong>}
      <ol>
        {session.exercises.map((x) => (
          <li key={x.id}>
            {photos && <ExercisePhoto id={x.id} n={0} className="exercise-thumb" />}
            <button type="button" className="link-btn" onClick={() => show(x.id)}>
              {x.name}
            </button>{" "}
            <span>
              {x.sets} × {x.reps}
            </span>
            {x.effort && <span className="muted"> · {x.effort}</span>}
            {x.rest_s > 0 && <span className="muted"> · rest {rest(x.rest_s)}</span>}
            {x.note && <span className="muted"> · {x.note}</span>}
            {open === x.id && info[x.id] && (
              <div className="exercise-how muted">
                <div className="exercise-pictures">
                  {photos &&
                    info[x.id].photos > 0 &&
                    [0, 1].map((n) => <ExercisePhoto key={n} id={x.id} n={n} className="exercise-photo" />)}
                  {info[x.id].muscles && (
                    <MuscleMap primary={info[x.id].muscles} secondary={info[x.id].secondary_muscles || []} />
                  )}
                </div>
                {info[x.id].equipment && (
                  <div>
                    {info[x.id].equipment} · {info[x.id].muscles?.join(", ")}
                    {info[x.id].secondary_muscles?.length > 0 && <> (also {info[x.id].secondary_muscles.join(", ")})</>}
                  </div>
                )}
                <ol>
                  {info[x.id].instructions.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ol>
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

// A favourite Strava route or segment on a session: opens it in Strava.
function SegmentLink({ segment }) {
  const route = segment.kind !== "segment";
  return (
    <a
      className="badge segment"
      href={segment.url}
      target="_blank"
      rel="noreferrer"
      title={`Open the ${segment.kind} in Strava`}
    >
      {route ? "🗺" : "⛰"} {segment.name}
    </a>
  );
}

// The day's other sessions (e.g. Strength after the ride): each its own type, text and time.
function ExtraSessions({ day, types, max, save, readOnly }) {
  const extras = day.extra_sessions || [];
  if (readOnly) {
    return extras.length ? (
      <div className="extra-sessions">
        {extras.map((e, i) => (
          <div key={i} className="extra-session">
            <span className="muted">+</span> <strong>{e.type}</strong> {e.description}
            {e.duration_min > 0 && <span className="muted"> ~{duration(e.duration_min * 60)}</span>}
            {e.intensity.map((c) => (
              <span key={c} className="badge intensity">
                {c}
              </span>
            ))}
            {e.segment && <SegmentLink segment={e.segment} />}
            {e.strength && <StrengthSession session={e.strength} />}
          </div>
        ))}
      </div>
    ) : null;
  }
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
          {e.segment && <SegmentLink segment={e.segment} />}
          <button
            type="button"
            className="icon-btn"
            title="Remove this session"
            aria-label="Remove session"
            onClick={() => save({ extra_sessions: extras.filter((_, j) => j !== i) })}
          >
            ✕
          </button>
          {e.strength && <StrengthSession session={e.strength} />}
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

// The closest Zwift / MyWhoosh workouts for an indoor day (or, without one, the closest from CoachQuest's
// library), and swapping to one (and back).
function PlatformMatches({ day, ctx }) {
  const w = day.workout;
  if (!w) return null;
  const matches = (day.platform_matches || []).filter((m) => m.id !== w.platform?.id);
  const lib = day.library_match && day.library_match.slug !== w.library?.slug ? day.library_match : null;
  const swapped = w.platform || w.library;
  if (!swapped && !matches.length && !lib) return null;
  return (
    <div className="platform-matches small">
      {swapped && (
        <span className="row tight">
          <span className="muted">
            Using {w.platform ? `${w.platform.name}'s workout` : "a CoachQuest library workout"} instead of the plan's
            "{w.original?.name}".
          </span>
          {!ctx.ro && (
            <button type="button" className="link-btn small" onClick={() => ctx.restorePlan(day.date)}>
              Back to the plan's workout
            </button>
          )}
        </span>
      )}
      {matches.map((m) => (
        <span key={m.id} className="row tight">
          <span title={`${duration(m.duration_s)}${m.tss != null ? ` · ${m.tss} TSS` : ""}`}>
            Closest on {m.platform_name}: <strong>{m.name}</strong>
            {m.collection && <span className="muted"> · {m.collection}</span>}{" "}
            <span className="muted">({m.score}% match)</span>
          </span>
          {!ctx.ro && (
            <button type="button" className="link-btn small" onClick={() => ctx.usePlatform(day.date, m)}>
              Use this
            </button>
          )}
        </span>
      ))}
      {lib && (
        <span className="row tight">
          <span title={`${duration(lib.duration_s)}${lib.tss != null ? ` · ${lib.tss} TSS` : ""}`}>
            From the CoachQuest library: <strong>{lib.name}</strong>
            <span className="muted"> · {lib.collection}</span> <span className="muted">({lib.score}% match)</span>
          </span>
          {!ctx.ro && (
            <button type="button" className="link-btn small" onClick={() => ctx.useLibrary(day.date, lib)}>
              Use this
            </button>
          )}
        </span>
      )}
    </div>
  );
}

function Actual({ day, tags, save, readOnly }) {
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
      return <div className="actual ok-text">✅ Goal met {logged}</div>;
    case "partial":
      return <div className="actual warn-text">⚠️ Partly done {logged}</div>;
    case "extra":
      return <div className="actual muted">💪 Trained on a rest day {logged}</div>;
    case "missed":
      if (readOnly) return <div className="actual bad-text">❌ Not logged{day.missed_reason ? ` · ${day.missed_reason}` : ""}</div>;
      return (
        <div className="actual bad-text row tight">
          ❌ Not logged
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

// Sessions that don't ride a Strava route or segment (backend plan_tracker.NO_ROUTE_TYPES): indoor days
// are their structured workout only.
const NO_ROUTE_TYPES = new Set(["Rest", "Zwift / indoor", "Treadmill run", "Strength", "Yoga / mobility", "Swim"]);
const takesRoute = (type) => !NO_ROUTE_TYPES.has(type);

function DayEditor({ day, segments, onDone }) {
  const [form, setForm] = useState({
    description: day.description,
    duration_min: day.duration_min,
    intensity: day.intensity.join(", "),
    gear: day.gear || "",
    route: day.route || "",
    segment_id: day.segment ? String(day.segment.id) : "",
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
      segment_id: form.segment_id ? Number(form.segment_id) : null,
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
        {segments.length > 0 && takesRoute(day.type) && (
          <label className="inline">
            Route / segment
            <select value={form.segment_id} onChange={set("segment_id")}>
              <option value="">–</option>
              {segments.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.kind === "segment" ? "⛰" : "🗺"} {s.name}
                </option>
              ))}
            </select>
          </label>
        )}
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

function EditableText({ value, placeholder, onSave, className, readOnly }) {
  const [editing, setEditing] = useState(false);
  if (readOnly) return value ? <span className={className}>{value}</span> : null;
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
