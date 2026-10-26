import { Check, Undo2 } from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api.js";
import { dateTime, formatDate } from "../lib/format.js";
import Markdown from "./Markdown.jsx";

const EVENTS = {
  created: "Created",
  approved: "Approved",
  sent_back: "Sent back",
  replan_proposed: "Re-plan proposed",
  replanned: "Re-planned",
  day_proposed: "Day re-plan proposed",
  reminded: "Coaches reminded",
};

// Coach approval for AI plans (backend plan_approval.py): the banner, the re-plan proposal and the buttons.
export function PlanApproval({ plan, athleteId, setPlan }) {
  const [note, setNote] = useState(null); // null = send-back form closed
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const base = `/api/athletes/${athleteId}/plans/${plan.id}`;
  const act = async (path, body) => {
    setBusy(true);
    setError(null);
    try {
      setPlan(await api(base + path, { method: "POST", body }));
      setNote(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const p = plan.pending;
  const waiting = plan.approval === "awaiting" || p;
  if (!waiting && plan.approval !== "sent_back") return null;

  return (
    <section
      className={`card approval ${plan.approval === "sent_back" && !p ? "sent-back" : ""}`}
    >
      {plan.approval === "awaiting" && (
        <>
          <h2>Waiting for coach approval</h2>
          <p className="small">
            The AI coach wrote this plan for{" "}
            {plan.viewer_role === "athlete" ? "you" : "the athlete"}. Its
            workouts go to the calendar, Zwift and MyWhoosh only once a coach
            approves it.{" "}
            {plan.can_approve
              ? "Edit days below first if you like."
              : "Your coach has been emailed."}
          </p>
        </>
      )}
      {plan.approval === "sent_back" && !p && (
        <>
          <h2>Sent back by the coach</h2>
          <p className="small">
            The coach's note is in the comments below. Re-plan to get a new
            version (the AI reads the note); it comes back for approval.
          </p>
        </>
      )}
      {p && p.day_patch && (
        <>
          <h2>
            {plan.can_approve
              ? "Re-planned day: check it, then approve"
              : "Re-planned day waiting for coach approval"}
          </h2>
          <p className="small">
            {p.by} asked the AI coach to re-plan{" "}
            {formatDate(p.day_patch.date, { weekday: "short", year: false })} on{" "}
            {dateTime(p.at)}
            {p.reason && <> — "{p.reason}"</>}. The plan keeps the current day
            until {plan.can_approve ? "you approve" : "a coach approves"}.
          </p>
          <ChangesTable changes={p.changes} />
          {p.summary && (
            <p className="small">
              <strong>Why:</strong> {p.summary}
            </p>
          )}
        </>
      )}
      {p && !p.day_patch && (
        <>
          <h2>Re-plan waiting for coach approval</h2>
          <p className="small">
            {p.by} asked for a re-plan on {dateTime(p.at)}
            {p.reason && <> — "{p.reason}"</>}. The plan below stays as it is
            until a coach approves. {p.changed} day{p.changed === 1 ? "" : "s"}{" "}
            would change:
          </p>
          {p.coach_notes && (
            <p className="small">
              <strong>Coach's notes:</strong> {p.coach_notes}
            </p>
          )}
          <ChangesTable changes={p.changes} />
          {p.summary && !p.day_patch && (
            <details>
              <summary className="small">The AI coach's summary</summary>
              <Markdown>{p.summary}</Markdown>
            </details>
          )}
        </>
      )}
      {plan.viewer_role === "athlete" && waiting && plan.athlete_decides_at !== undefined && (
        <p className="small muted">
          {plan.can_approve
            ? "No coach has answered in time (or the day comes first), so you can decide yourself."
            : plan.athlete_decides_at
              ? `If no coach answers, you can approve or send it back yourself from ${dateTime(plan.athlete_decides_at)}.`
              : "Only your coach can approve this."}
        </p>
      )}
      {plan.can_approve && waiting && (
        <div className="row wrap">
          <button
            className="btn primary"
            disabled={busy}
            onClick={() => act("/approve")}
          >
            <Check size={16} /> Approve
            {p?.day_patch ? " this day" : p ? " re-plan" : " plan"}
          </button>
          <button
            className="btn"
            disabled={busy}
            onClick={() => setNote(note === null ? "" : null)}
          >
            <Undo2 size={16} /> Send back
          </button>
        </div>
      )}
      {note !== null && (
        <form
          className="instruction-form"
          onSubmit={(e) => {
            e.preventDefault();
            act("/send-back", { note });
          }}
        >
          <textarea
            rows={2}
            required
            minLength={3}
            maxLength={4000}
            value={note}
            placeholder="What should change? The athlete is emailed and the next re-plan reads this."
            onChange={(e) => setNote(e.target.value)}
          />
          <button className="btn small primary" disabled={busy}>
            Send back
          </button>
        </form>
      )}
      {error && <div className="error small">{error}</div>}
    </section>
  );
}

function ChangesTable({ changes }) {
  return (
    <div className="table-wrap">
      <table className="small">
        <thead>
          <tr>
            <th>Day</th>
            <th>Now</th>
            <th>Proposed</th>
          </tr>
        </thead>
        <tbody>
          {changes.map((c) => (
            <tr key={c.date}>
              <td>{formatDate(c.date, { weekday: "short", year: false })}</td>
              <td className="muted">
                {c.before.type}
                {c.before.duration_min
                  ? ` · ${c.before.duration_min}′`
                  : ""} — {c.before.description}
              </td>
              <td>
                <strong>{c.after.type}</strong>
                {c.after.duration_min
                  ? ` · ${c.after.duration_min}′`
                  : ""} — {c.after.description}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// What shaped the plan: the requests, coach's notes and approvals, newest last.
export function PlanHistory({ plan }) {
  const notes = plan.request?.notes;
  const coachNotes = plan.request?.coach_notes;
  if (!notes && !coachNotes && !plan.history?.length) return null;
  return (
    <details className="card plan-history" open={!!coachNotes}>
      <summary>What shaped this plan</summary>
      {coachNotes && (
        <p className="small">
          <strong>Coach's notes:</strong> {coachNotes}
        </p>
      )}
      {notes && (
        <p className="small">
          <strong>Notes for the AI coach:</strong> {notes}
        </p>
      )}
      {plan.history?.length > 0 && (
        <ul className="plain small">
          {plan.history.map((h, i) => (
            <li key={i}>
              {dateTime(h.at)} · <strong>{EVENTS[h.event] || h.event}</strong>{" "}
              by {h.by} ({h.role}){h.reason && <> · "{h.reason}"</>}
              {h.coach_notes && h.event !== "created" && (
                <> · coach's notes: "{h.coach_notes}"</>
              )}
              {h.note && <> · "{h.note}"</>}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
