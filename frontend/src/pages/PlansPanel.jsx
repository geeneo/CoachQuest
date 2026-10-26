import { Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { dateTime } from "../lib/format.js";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function PlansPanel({ id, athlete }) {
  const plans = useApi(`/api/athletes/${id}/plans`);
  const current = useApi(`/api/athletes/${id}/plans/current`);
  const navigate = useNavigate();
  const [form, setForm] = useState({
    title: "",
    goal: athlete.goal || "",
    event_date: "",
    start_date: "",
    weeks: 4,
    hours_per_week: 8,
    available_days: ["Tue", "Thu", "Sat", "Sun"],
    notes: "",
    coach_notes: "",
    structured_workouts: true,
  });
  // Training days start from the weekday preferences (any day not set to Rest), when there are any.
  const prefs = useApi(`/api/athletes/${id}/preferences`);
  useEffect(() => {
    const wp = prefs.data?.weekday_prefs;
    if (!wp || !Object.values(wp).some((t) => t.length)) return;
    const days = DAYS.filter((d) => (wp[d.toLowerCase()] || [])[0] && wp[d.toLowerCase()][0] !== "Rest");
    setForm((f) => ({ ...f, available_days: days }));
  }, [prefs.data]);
  const approval = useApi(`/api/athletes/${id}/plans/approval-setting`);
  const setApproval = async (required) => {
    try {
      await api(`/api/athletes/${id}/plans/approval-setting`, { method: "PUT", body: { required } });
      approval.reload();
    } catch (err) {
      setError(err.message);
    }
  };
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const toggleDay = (d) =>
    setForm({
      ...form,
      available_days: form.available_days.includes(d)
        ? form.available_days.filter((x) => x !== d)
        : DAYS.filter((x) => x === d || form.available_days.includes(x)),
    });

  const generate = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = {
        ...form,
        weeks: Number(form.weeks),
        hours_per_week: Number(form.hours_per_week),
        event_date: form.event_date || null,
        start_date: form.start_date || null,
      };
      const plan = await api(`/api/athletes/${id}/plans`, { method: "POST", body });
      navigate(`/athletes/${athlete.id}/plans/${plan.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (planId) => {
    if (!confirm("Delete this plan?")) return;
    await api(`/api/athletes/${id}/plans/${planId}`, { method: "DELETE" }).catch((err) => alert(err.message));
    plans.reload();
  };

  const cur = current.data;
  const thisWeek = cur?.weeks?.find((w) => w.is_current) || cur?.weeks?.[0];
  return (
    <>
      {cur && thisWeek && (
        <section className="card week current">
          <div className="row between">
            <h2>Current plan: {cur.title}</h2>
            <Link to={`/athletes/${athlete.id}/plans/${cur.id}`}>Open the full plan →</Link>
          </div>
          <div className="mini-week">
            {thisWeek.days.map((d) => (
              <div key={d.date} className={`mini-day status-${d.status} ${d.is_today ? "today" : ""}`}>
                <span className="muted small">{d.weekday.slice(0, 1).toUpperCase() + d.weekday.slice(1)}</span>
                <strong>{d.type}</strong>
                <span className="small mini-status">
                  {{ goal_met: "✓", partial: "◐", missed: "✗", extra: "+" }[d.status] || ""}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
      <section className="card">
        <h2>
          <Sparkles size={18} /> New plan from the AI coach
        </h2>
        <p className="muted small">
          Claude gets only the data {athlete.is_me ? "you have" : `${athlete.display_name} has`} shared, plus load and
          readiness facts computed by CoachQuest. Generating can take a minute or two.
          {athlete.is_me && " If you have a coach, plans you generate wait for their approval before workouts go to your calendar."}
        </p>
        {approval.data?.has_coach &&
          (approval.data.can_change ? (
            <label className="check small">
              <input
                type="checkbox"
                checked={!approval.data.off}
                onChange={(e) => setApproval(e.target.checked)}
              />{" "}
              Plans and re-plans {athlete.display_name} asks the AI for wait for a coach's approval
            </label>
          ) : (
            <p className="small muted">
              {approval.data.required
                ? "Plans and re-plans you ask for wait for your coach's approval before workouts go to your calendar."
                : "Your coach lets your plans and re-plans apply straight away (no approval needed)."}
            </p>
          ))}
        <form className="grid-form" onSubmit={generate}>
          <label>
            Title
            <input value={form.title} onChange={set("title")} required maxLength={200} placeholder="Base block 1" />
          </label>
          <label>
            Goal
            <input value={form.goal} onChange={set("goal")} required maxLength={500} placeholder="160 km gran fondo" />
          </label>
          <label>
            Event date
            <input type="date" value={form.event_date} onChange={set("event_date")} />
          </label>
          <label>
            Start week
            <input type="date" value={form.start_date} onChange={set("start_date")} />
            <span className="hint">Starts on the first day of that week (Profile → My week starts on). Empty: next week.</span>
          </label>
          <label>
            Weeks
            <input type="number" min={1} max={16} value={form.weeks} onChange={set("weeks")} />
          </label>
          <label>
            Hours per week
            <input type="number" min={1} max={30} step={0.5} value={form.hours_per_week} onChange={set("hours_per_week")} />
          </label>
          <fieldset>
            <legend>Training days</legend>
            <span className="hint">
              From {athlete.is_me ? "your" : "the athlete's"} weekday preferences (Profile); re-plans follow them too.
            </span>
            <div className="chips">
              {DAYS.map((d) => (
                <button
                  type="button"
                  key={d}
                  className={`chip ${form.available_days.includes(d) ? "on" : ""}`}
                  onClick={() => toggleDay(d)}
                >
                  {d}
                </button>
              ))}
            </div>
          </fieldset>
          <label className="wide">
            Notes for the AI coach
            <textarea
              rows={3}
              value={form.notes}
              onChange={set("notes")}
              maxLength={2000}
              placeholder="Indoor trainer on weekdays, knee niggle, travelling week 3…"
            />
          </label>
          {!athlete.is_me && (
            <label className="wide">
              Coach's notes (the AI coach must follow these)
              <textarea
                rows={3}
                value={form.coach_notes}
                onChange={set("coach_notes")}
                maxLength={2000}
                placeholder="e.g. No intervals before the race recce; keep week 3 easy; long ride on Saturday"
              />
              <span className="hint">Shown on the plan, so {athlete.display_name} sees what shaped it.</span>
            </label>
          )}
          <label className="check wide">
            <input
              type="checkbox"
              checked={form.structured_workouts}
              onChange={(e) => setForm({ ...form, structured_workouts: e.target.checked })}
            />
            Turn indoor sessions into structured workouts on the calendar (sent to Zwift through Intervals.icu when
            auto-send is on)
          </label>
          {error && <div className="error wide">{error}</div>}
          <button className="btn primary" disabled={busy}>
            {busy ? "Writing your plan…" : "Generate plan"}
          </button>
        </form>
      </section>
      <section className="card">
        <h2>Saved plans</h2>
        {plans.data?.length ? (
          <ul className="list">
            {plans.data.map((p) => (
              <li key={p.id}>
                <Link to={`/athletes/${athlete.id}/plans/${p.id}`}>{p.title}</Link>
                {p.approval === "awaiting" && <span className="badge warn">waiting for coach</span>}
                {p.approval === "sent_back" && <span className="badge bad">sent back</span>}
                {p.has_pending && <span className="badge warn">re-plan waiting for coach</span>}
                <span className="muted small">
                  {p.request?.weeks} weeks · by {p.author} · {dateTime(p.created_at)}
                </span>
                <button className="icon-btn" aria-label="Delete plan" onClick={() => remove(p.id)}>
                  <Trash2 size={16} />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No plans yet.</p>
        )}
      </section>
    </>
  );
}
