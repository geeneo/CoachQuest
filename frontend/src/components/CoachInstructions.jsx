import { Pause, Pencil, Play, Trash2 } from "lucide-react";
import { useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { dateTime, formatDate } from "../lib/format.js";
import { useReadOnly } from "../lib/readOnly.js";

// Standing instructions the AI coach follows for this athlete (see backend instructions.py).
export default function CoachInstructions({ id, isMe }) {
  const ro = useReadOnly();
  const res = useApi(`/api/athletes/${id}/instructions`);
  const [draft, setDraft] = useState({ body: "", until: "" });
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState(null);
  const url = `/api/athletes/${id}/instructions`;
  const call = (path, method, body) => {
    setError(null);
    return api(url + path, { method, body }).then(
      () => {
        res.reload();
        return true;
      },
      (e) => {
        setError(e.message);
        return false;
      },
    );
  };
  const add = async (e) => {
    e.preventDefault();
    if (await call("", "POST", { body: draft.body, until: draft.until || null })) setDraft({ body: "", until: "" });
  };
  const save = async (e) => {
    e.preventDefault();
    if (await call(`/${editing.id}`, "PATCH", { body: editing.body, until: editing.until || null })) setEditing(null);
  };
  const rows = res.data || [];
  const current = rows.filter((r) => r.current).length;

  return (
    <section className="card">
      <h2>Coach instructions</h2>
      <p className="muted small">
        Standing instructions the AI coach must follow in every plan, re-plan, readiness note, weekly review and chat
        for {isMe ? "you" : "this athlete"}. They count for more than the AI's own judgement; if one clashes with the
        data (for example fatigue), the AI says so instead of ignoring it.{" "}
        {isMe ? "Your coaches and you can add them." : "The athlete sees them and is emailed."}
      </p>
      {res.error && <div className="error">{res.error.message}</div>}
      {rows.length > 0 && (
        <ul className="instructions">
          {rows.map((r) =>
            editing?.id === r.id ? (
              <li key={r.id}>
                <form className="instruction-form" onSubmit={save}>
                  <textarea
                    rows={2}
                    maxLength={500}
                    value={editing.body}
                    onChange={(e) => setEditing({ ...editing, body: e.target.value })}
                    required
                    minLength={3}
                  />
                  <label className="inline small">
                    Until
                    <input
                      type="date"
                      value={editing.until || ""}
                      onChange={(e) => setEditing({ ...editing, until: e.target.value })}
                    />
                  </label>
                  <button className="btn small primary">Save</button>
                  <button type="button" className="btn small" onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </form>
              </li>
            ) : (
              <li key={r.id} className={r.current ? "" : "inactive"}>
                <div className="instruction-body">{r.body}</div>
                <div className="small muted">
                  {r.author} ({r.role}) · {dateTime(r.created_at)}
                  {r.until && ` · until ${formatDate(r.until)}`}
                  {r.updated_by && ` · changed by ${r.updated_by}`}
                  {!r.active && <span className="badge"> paused</span>}
                  {r.expired && <span className="badge"> ended</span>}
                </div>
                {!ro && (
                  <div className="row tight">
                    <button
                      className="icon-btn"
                      title="Edit"
                      aria-label="Edit"
                      onClick={() => setEditing({ id: r.id, body: r.body, until: r.until || "" })}
                    >
                      <Pencil size={15} />
                    </button>
                    <button
                      className="icon-btn"
                      title={r.active ? "Pause (the AI ignores it until resumed)" : "Resume"}
                      aria-label={r.active ? "Pause" : "Resume"}
                      onClick={() => call(`/${r.id}`, "PATCH", { active: !r.active })}
                    >
                      {r.active ? <Pause size={15} /> : <Play size={15} />}
                    </button>
                    <button
                      className="icon-btn"
                      title="Delete"
                      aria-label="Delete"
                      onClick={() => confirm("Delete this instruction?") && call(`/${r.id}`, "DELETE")}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                )}
              </li>
            ),
          )}
        </ul>
      )}
      {res.data && !rows.length && <p className="muted small">No instructions yet.</p>}
      {rows.length > 0 && (
        <p className="small muted">
          {current} in force now{rows.length > current ? `, ${rows.length - current} paused or ended` : ""}.
        </p>
      )}
      {!ro && (
        <form className="instruction-form" onSubmit={add}>
          <textarea
            rows={2}
            maxLength={500}
            minLength={3}
            required
            placeholder='e.g. "No intervals on Mondays" or "Keep long rides under 4 h until the knee is fine"'
            value={draft.body}
            onChange={(e) => setDraft({ ...draft, body: e.target.value })}
          />
          <label className="inline small">
            Until (optional)
            <input type="date" value={draft.until} onChange={(e) => setDraft({ ...draft, until: e.target.value })} />
          </label>
          <button className="btn primary small">Add instruction</button>
        </form>
      )}
      {error && <div className="error small">{error}</div>}
    </section>
  );
}
