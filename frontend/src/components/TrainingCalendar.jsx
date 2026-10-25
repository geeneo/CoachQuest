import { ChevronLeft, ChevronRight, Download } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { api, download } from "../lib/api.js";
import { duration } from "../lib/format.js";
import { addDays, localToday } from "../lib/workout.js";
import WorkoutChart from "./WorkoutChart.jsx";

const STATUS = {
  planned: { label: "Planned", cls: "" },
  today: { label: "Today", cls: "info" },
  done: { label: "✓ Done", cls: "good" },
  partial: { label: "◐ Partly done", cls: "warn" },
  missed: { label: "✗ Missed", cls: "bad" },
  skipped: { label: "Skipped", cls: "" },
  cancelled: { label: "Cancelled", cls: "" },
};
const WEEKDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function weekdayOf(iso) {
  return (new Date(`${iso}T12:00:00`).getDay() + 6) % 7; // 0 = Monday
}

// The athlete's calendar: the plan's session for each day, scheduled workouts
// (drag to move, drop a library workout to add), and what was logged.
export default function TrainingCalendar({ id, isMe }) {
  const [anchor, setAnchor] = useState(localToday());
  const [view, setView] = useState("week");
  const [picked, setPicked] = useState(null); // a library workout chosen by tap, for touch screens
  const [selected, setSelected] = useState(null); // scheduled workout id shown below
  const [error, setError] = useState(null);
  const cal = useApi(`/api/athletes/${id}/calendar?start=${addDays(anchor, -7)}&end=${addDays(anchor, 7)}`);
  const library = useApi("/api/workouts");
  const platforms = useApi(`/api/athletes/${id}/platforms`);

  const data = cal.data;
  const weekStart = data ? addDays(anchor, -((weekdayOf(anchor) - data.week_start + 7) % 7)) : null;
  const shownDates = !data ? [] : view === "week" ? [...Array(7)].map((_, i) => addDays(weekStart, i)) : [anchor];
  const days = data ? shownDates.map((d) => data.days.find((x) => x.date === d)).filter(Boolean) : [];
  const allWorkouts = data ? data.days.flatMap((d) => d.workouts) : [];
  const current = allWorkouts.find((w) => w.id === selected);
  // Sending happens just after a change is saved: look again shortly while anything is still on its way.
  const sending = allWorkouts.some((w) => w.delivery.some((d) => d.state === "queued" || d.state === "running"));
  useEffect(() => {
    if (!sending) return;
    const timer = setTimeout(cal.reload, 3000);
    return () => clearTimeout(timer);
  }, [sending, cal.data, cal.reload]);

  const run = async (fn) => {
    setError(null);
    try {
      await fn();
      cal.reload();
    } catch (err) {
      setError(err.message);
    }
  };
  const schedule = (templateId, day) =>
    run(() => api(`/api/athletes/${id}/workouts`, { method: "POST", body: { day, template_id: templateId } }));
  const edit = (workoutId, body) => run(() => api(`/api/athletes/${id}/workouts/${workoutId}`, { method: "PATCH", body }));
  const remove = (workoutId) =>
    run(async () => {
      await api(`/api/athletes/${id}/workouts/${workoutId}`, { method: "DELETE" });
      setSelected(null);
    });

  const onDrop = (e, day) => {
    e.preventDefault();
    const tpl = e.dataTransfer.getData("application/x-cq-template");
    const moved = e.dataTransfer.getData("application/x-cq-scheduled");
    if (tpl) schedule(Number(tpl), day);
    else if (moved) edit(Number(moved), { day });
  };
  const onDayClick = (day) => {
    if (!picked) return;
    schedule(picked.id, day);
    setPicked(null);
  };
  const step = view === "week" ? 7 : 1;

  return (
    <>
      <div className="row between wrap cal-bar">
        <div className="row">
          <button className="icon-btn" aria-label="Previous" onClick={() => setAnchor(addDays(anchor, -step))}>
            <ChevronLeft size={18} />
          </button>
          <button className="btn small" onClick={() => setAnchor(data?.today || localToday())}>
            Today
          </button>
          <button className="icon-btn" aria-label="Next" onClick={() => setAnchor(addDays(anchor, step))}>
            <ChevronRight size={18} />
          </button>
          <strong>{view === "week" && weekStart ? `Week of ${fmtDay(weekStart)}` : fmtDay(anchor, true)}</strong>
        </div>
        <div className="row">
          <div className="chips" role="radiogroup" aria-label="View">
            {["week", "day"].map((v) => (
              <button
                key={v}
                type="button"
                role="radio"
                aria-checked={view === v}
                className={`chip ${view === v ? "on" : ""}`}
                onClick={() => setView(v)}
              >
                {v === "week" ? "Week" : "Day"}
              </button>
            ))}
          </div>
          {weekStart && (
            <button
              className="btn small"
              title="All workouts this week as Zwift files, with install steps"
              onClick={() =>
                download(`/api/athletes/${id}/workouts/export.zip?start=${shownDates[0]}&end=${shownDates.at(-1)}`).catch(
                  (err) => setError(err.message),
                )
              }
            >
              <Download size={14} /> {view === "week" ? "Week" : "Day"} as ZIP
            </button>
          )}
        </div>
      </div>
      {platforms.data && <PlatformLine platforms={platforms.data} isMe={isMe} />}

      <div className="tray">
        <span className="muted small">
          {library.data?.length
            ? picked
              ? `Tap a day to add "${picked.name}", or tap it again to cancel.`
              : "Drag a workout onto a day (or tap it, then tap a day):"
            : "Your workout library is empty."}{" "}
          <Link to="/workouts">{library.data?.length ? "Manage workouts" : "Build a workout"}</Link>
        </span>
        <div className="row wrap">
          {library.data?.map((w) => (
            <button
              key={w.id}
              draggable
              className={`chip drag ${picked?.id === w.id ? "on" : ""}`}
              onDragStart={(e) => e.dataTransfer.setData("application/x-cq-template", String(w.id))}
              onClick={() => setPicked(picked?.id === w.id ? null : w)}
            >
              {w.name} · {duration(w.estimate.duration_s)}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {cal.error && <div className="error">{cal.error.message}</div>}
      {cal.loading && !data && <p className="muted">Loading…</p>}
      <div className={view === "week" ? "cal-week" : "cal-day"}>
        {days.map((d) => (
          <div
            key={d.date}
            className={`cal-cell ${d.is_today ? "today" : ""} ${picked ? "droppable" : ""}`}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => onDrop(e, d.date)}
            onClick={() => onDayClick(d.date)}
          >
            <div className="cal-date">
              <span>{WEEKDAY[weekdayOf(d.date)]}</span> {fmtDay(d.date)}
            </div>
            {d.plan && (
              <div className={`cal-plan ${d.plan.type === "Rest" ? "rest" : ""}`} title={d.plan.description}>
                <span className="badge">{d.plan.type}</span>
                {d.plan.type !== "Rest" && (
                  <span className="small muted">
                    {" "}
                    {d.plan.duration_min}′{view === "day" ? ` · ${d.plan.plan_title}` : ""}
                  </span>
                )}
                {view === "day" && d.plan.description && <p className="small">{d.plan.description}</p>}
              </div>
            )}
            {d.workouts.map((w) => (
              <button
                key={w.id}
                draggable
                className={`cal-workout ${w.status} ${selected === w.id ? "selected" : ""}`}
                onDragStart={(e) => e.dataTransfer.setData("application/x-cq-scheduled", String(w.id))}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelected(selected === w.id ? null : w.id);
                }}
              >
                <span className="cal-workout-name">{w.name}</span>
                <span className="small muted">
                  {duration(w.estimate.duration_s)} · TSS {w.estimate.tss ?? "–"}
                </span>
                <span className={`status ${STATUS[w.status].cls}`}>{STATUS[w.status].label}</span>
                {w.delivery.length > 0 && <DeliveryBadge delivery={w.delivery} />}
                {view === "day" && <WorkoutChart blocks={w.blocks} height={60} compact />}
              </button>
            ))}
            {d.activities.map((a) => (
              <div key={a.id} className="cal-activity small" title={a.name}>
                {a.type} · {a.minutes}′{a.km ? ` · ${a.km} km` : ""}
              </div>
            ))}
          </div>
        ))}
      </div>
      {data && <Compliance id={id} key={complianceKey(data)} />}
      {current && (
        <WorkoutDetail
          w={current}
          ftp={data.ftp_watts}
          id={id}
          edit={edit}
          remove={remove}
          onError={setError}
          reload={cal.reload}
          close={() => setSelected(null)}
        />
      )}
    </>
  );
}

function fmtDay(iso, long = false) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, {
    weekday: long ? "long" : undefined,
    day: "numeric",
    month: "short",
  });
}

function PlatformLine({ platforms, isMe }) {
  const text = {
    connected: "✓ connected",
    error: "⚠ needs attention",
    not_connected: "not connected",
    export_only: "file download",
    not_available: "not available yet",
  };
  return (
    <p className="small muted">
      Platforms:{" "}
      {platforms
        .filter((p) => p.status !== "not_available")
        .map((p) => `${p.name} ${text[p.status]}`)
        .join(" · ")}
      .{" "}
      {platforms.some((p) => p.auto_sync)
        ? "Scheduled workouts are sent automatically to: " +
          platforms
            .filter((p) => p.auto_sync)
            .map((p) => p.name)
            .join(", ") +
          ". "
        : "Workouts aren't sent anywhere automatically; download them as .zwo files, or connect Intervals.icu. "}
      {isMe && <Link to="/connections">Connected platforms</Link>}
    </p>
  );
}

function WorkoutDetail({ w, ftp, id, edit, remove, onError, close, reload }) {
  const est = w.estimate;
  const act = w.actual;
  const plannedW = est.avg_watts;
  return (
    <section className="card workout-detail">
      <div className="row between">
        <h2>
          {w.name} <span className="muted small">· {fmtDay(w.date, true)}</span>
        </h2>
        <button className="btn small" onClick={close}>
          Close
        </button>
      </div>
      <WorkoutChart blocks={w.blocks} ftp={ftp} />
      {w.description && <p>{w.description}</p>}
      {w.instructions && (
        <p className="small">
          <strong>Coach:</strong> {w.instructions}
        </p>
      )}
      <table className="table compact">
        <thead>
          <tr>
            <th></th>
            <th>Planned</th>
            <th>Actual</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Duration</td>
            <td>{duration(est.duration_s)}</td>
            <td>
              {act ? `${duration(act.minutes * 60)}${act.completion_pct != null ? ` (${act.completion_pct}%)` : ""}` : "–"}
            </td>
          </tr>
          <tr>
            <td>Avg power</td>
            <td>{plannedW ? `${plannedW} W` : `${Math.round(est.avg_power * 100)}% FTP`}</td>
            <td>{act?.avg_power ? `${act.avg_power} W` : "–"}</td>
          </tr>
          <tr>
            <td>Normalised power</td>
            <td>{est.np_watts ? `${est.np_watts} W` : "–"}</td>
            <td>{act?.norm_power ? `${act.norm_power} W` : "–"}</td>
          </tr>
          <tr>
            <td>IF / TSS</td>
            <td>
              {est.intensity_factor ?? "–"} / {est.tss ?? "–"}
            </td>
            <td>
              {act?.intensity_factor ?? "–"} / {act?.tss ?? "–"}
            </td>
          </tr>
          <tr>
            <td>Heart rate / cadence</td>
            <td>–</td>
            <td>
              {act?.avg_hr ? `${act.avg_hr} bpm` : "–"} / {act?.avg_cadence ? `${act.avg_cadence} rpm` : "–"}
            </td>
          </tr>
        </tbody>
      </table>
      <p className="small muted">
        {!act
          ? "Not ridden yet. A bike ride logged on this day (from Strava or Garmin) is matched automatically. "
          : act.activities.length
            ? `Matched to: ${act.activities.map((a) => `${a.name} (${a.source})`).join(", ")}. `
            : "Ridden. Ride details are shown only with the Activities permission. "}
        {w.assigned_by && `Assigned by ${w.assigned_by}. `}
        {w.delivery.length ? "" : "Delivery: download (.zwo) — not sent to any platform."}
        {w.from_plan ? " Made by the training plan: re-planning updates it until you edit it here." : ""}
      </p>
      <RideMatch w={w} id={id} edit={edit} />
      {w.delivery.length > 0 && <DeliveryList w={w} id={id} onError={onError} reload={reload} />}
      <div className="row wrap">
        <button
          className="btn small primary"
          onClick={() => download(`/api/athletes/${id}/workouts/${w.id}/zwo`).catch((err) => onError(err.message))}
        >
          <Download size={14} /> Download .zwo
        </button>
        <label className="inline small">
          Move to
          <input type="date" value={w.date} onChange={(e) => e.target.value && edit(w.id, { day: e.target.value })} />
        </label>
        {w.status === "skipped" || w.status === "cancelled" ? (
          <button className="btn small" onClick={() => edit(w.id, { status: "planned" })}>
            Restore
          </button>
        ) : (
          <>
            <button className="btn small" onClick={() => edit(w.id, { status: "skipped" })}>
              Skip
            </button>
            <button className="btn small" onClick={() => edit(w.id, { status: "cancelled" })}>
              Cancel
            </button>
          </>
        )}
        <button
          className="btn small danger"
          onClick={() => window.confirm(`Remove "${w.name}" from the calendar?`) && remove(w.id)}
        >
          Remove
        </button>
      </div>
    </section>
  );
}

const DELIVERY = {
  sent: { icon: "✓", label: "Sent" },
  queued: { icon: "…", label: "Queued" },
  running: { icon: "…", label: "Sending" },
  retrying: { icon: "↻", label: "Retrying" },
  failed: { icon: "✗", label: "Failed" },
  blocked: { icon: "⚠", label: "Reconnect needed" },
};
const PLATFORM = { intervals_icu: "Intervals.icu", zwift: "Zwift", mywhoosh: "MyWhoosh" };

function DeliveryBadge({ delivery }) {
  return (
    <span className="delivery small">
      {delivery.map((d) => (
        <span key={d.provider} className={`delivery-${d.state}`} title={d.message || ""}>
          {DELIVERY[d.state]?.icon} {PLATFORM[d.provider] || d.provider}
        </span>
      ))}
    </span>
  );
}

function DeliveryList({ w, id, onError, reload }) {
  const retry = async (jobId) => {
    try {
      await api(`/api/athletes/${id}/sync/${jobId}/retry`, { method: "POST" });
      reload();
    } catch (err) {
      onError(err.message);
    }
  };
  return (
    <ul className="delivery-list small">
      {w.delivery.map((d) => (
        <li key={d.provider}>
          {DELIVERY[d.state]?.icon} {PLATFORM[d.provider] || d.provider}: {DELIVERY[d.state]?.label}
          {d.action === "delete" ? " (removing)" : ""}
          {d.at ? ` · ${new Date(d.at.endsWith("Z") ? d.at : d.at + "Z").toLocaleString()}` : ""}
          {d.message && <span className="muted"> — {d.message}</span>}
          {d.state === "blocked" && <Link to="/connections#platforms"> Reconnect</Link>}
          {d.state === "failed" && d.job_id && (
            <button className="btn small" onClick={() => retry(d.job_id)}>
              Retry
            </button>
          )}
          {d.provider === "intervals_icu" && d.state === "sent" && (
            <span className="muted"> — appears in Zwift if Zwift is linked in Intervals.icu</span>
          )}
        </li>
      ))}
    </ul>
  );
}

// Which ride completed this workout: matched automatically, picked by hand, or "not done".
function RideMatch({ w, id, edit }) {
  const cands = useApi(w.date <= localToday() ? `/api/athletes/${id}/workouts/${w.id}/candidates` : null);
  if (!cands.data) return null; // future workout, or no access to activities
  const value = w.match === "manual" ? String(w.actual?.activities[0]?.id ?? "auto") : w.match;
  const change = (v) =>
    edit(w.id, v === "auto" ? { match: "auto" } : v === "none" ? { match: "none" } : { activity_id: Number(v) });
  return (
    <label className="inline small ride-match">
      Completed by
      <select value={value} onChange={(e) => change(e.target.value)}>
        <option value="auto">Match automatically{w.match === "auto" && w.actual ? " (current)" : ""}</option>
        <option value="none">Not done</option>
        {cands.data.map((c) => (
          <option key={c.id} value={String(c.id)}>
            {c.date} · {c.name} · {c.minutes}′{c.used_by ? ` (now on "${c.used_by}")` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

function complianceKey(data) {
  return data.days
    .flatMap((d) => d.workouts.map((w) => `${w.id}:${w.status}:${w.actual?.minutes ?? ""}`))
    .join(",");
}

const FLAG = { short: "short", under_target: "under target", over_target: "over target" };

// Planned vs actual, week by week (computed by the API from the matched rides).
function Compliance({ id }) {
  const res = useApi(`/api/athletes/${id}/compliance?weeks=6`);
  const [open, setOpen] = useState(null);
  const weeks = (res.data?.weeks || []).filter((w) => w.scheduled);
  if (!weeks.length) return null;
  return (
    <section className="card compliance">
      <h2>Planned vs actual</h2>
      <p className="muted small">
        Structured workouts against the rides that completed them. Compliance is ridden time against the time planned so
        far (skipped workouts don't count against it).
      </p>
      <div className="table-wrap">
        <table className="compact">
          <thead>
            <tr>
              <th>Week of</th>
              <th>Done</th>
              <th>Time</th>
              <th>Compliance</th>
              <th>TSS</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {weeks.map((w) => (
              <Fragment key={w.week_start}>
                <tr className="clickable" onClick={() => setOpen(open === w.week_start ? null : w.week_start)}>
                  <td>
                    {fmtDay(w.week_start)}
                    {w.is_current && <span className="muted"> (this week)</span>}
                  </td>
                  <td>
                    {w.done}
                    {w.partial ? ` + ${w.partial} partly` : ""} of {w.scheduled}
                    {w.upcoming ? <span className="muted"> · {w.upcoming} to come</span> : null}
                  </td>
                  <td>
                    {duration(w.actual_min * 60)} / {duration(w.planned_min * 60)}
                  </td>
                  <td>
                    {w.compliance_pct == null ? (
                      "–"
                    ) : (
                      <span className={w.compliance_pct >= 80 ? "ok-text" : w.compliance_pct >= 50 ? "warn-text" : "error-text"}>
                        {w.compliance_pct}%
                      </span>
                    )}
                  </td>
                  <td>
                    {w.actual_tss ?? "–"} / {w.planned_tss ?? "–"}
                  </td>
                  <td className="small">
                    {[
                      w.missed && `${w.missed} missed`,
                      w.skipped && `${w.skipped} skipped`,
                      w.short && `${w.short} short`,
                      w.under_target && `${w.under_target} under target`,
                    ]
                      .filter(Boolean)
                      .join(" · ") || "–"}
                  </td>
                </tr>
                {open === w.week_start &&
                  w.workouts.map((r) => (
                    <tr key={r.id} className="sub-row small">
                      <td>{fmtDay(r.date)}</td>
                      <td colSpan={2}>
                        {r.name} <span className="muted">· {STATUS[r.status]?.label || r.status}</span>
                      </td>
                      <td>{r.completion_pct != null ? `${r.completion_pct}% of time` : "–"}</td>
                      <td>
                        {r.power_pct != null ? `NP ${r.actual_np} W = ${r.power_pct}% of plan` : r.actual_tss ?? ""}
                      </td>
                      <td>{r.flags.map((f) => FLAG[f]).join(", ")}</td>
                    </tr>
                  ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Click a week to see each workout.</p>
    </section>
  );
}
