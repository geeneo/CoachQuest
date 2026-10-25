import { Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { dateTime } from "../lib/format.js";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function PlansPanel({ id, athlete }) {
  const plans = useApi(`/api/athletes/${id}/plans`);
  const navigate = useNavigate();
  const [form, setForm] = useState({
    title: "",
    goal: athlete.goal || "",
    event_date: "",
    weeks: 4,
    hours_per_week: 8,
    available_days: ["Tue", "Thu", "Sat", "Sun"],
    notes: "",
  });
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

  return (
    <>
      <section className="card">
        <h2>
          <Sparkles size={18} /> New plan from the AI coach
        </h2>
        <p className="muted small">
          Claude gets only the data {athlete.is_me ? "you have" : `${athlete.display_name} has`} shared, plus load and
          readiness facts computed by CoachQuest. Generating can take a minute or two.
        </p>
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
            Weeks
            <input type="number" min={1} max={16} value={form.weeks} onChange={set("weeks")} />
          </label>
          <label>
            Hours per week
            <input type="number" min={1} max={30} step={0.5} value={form.hours_per_week} onChange={set("hours_per_week")} />
          </label>
          <fieldset>
            <legend>Training days</legend>
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
            Notes for the coach
            <textarea
              rows={3}
              value={form.notes}
              onChange={set("notes")}
              maxLength={2000}
              placeholder="Indoor trainer on weekdays, knee niggle, travelling week 3…"
            />
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
