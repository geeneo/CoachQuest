import { CheckCircle2, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { dateTime, formatDate } from "../lib/format.js";

// Background the AI coach should know about the athlete (backend athlete_notes.py).
export default function AthleteNotes({ id, isMe }) {
  const res = useApi(`/api/athletes/${id}/notes`);
  const [draft, setDraft] = useState({ category: "health", body: "", review_by: "" });
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState(null);
  const url = `/api/athletes/${id}/notes`;
  const call = async (path, method, body) => {
    setError(null);
    try {
      await api(url + path, { method, body });
      res.reload();
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    }
  };
  const add = async (e) => {
    e.preventDefault();
    if (await call("", "POST", { ...draft, review_by: draft.review_by || null }))
      setDraft({ ...draft, body: "", review_by: "" });
  };
  const save = async (e) => {
    e.preventDefault();
    const { id: nid, ...body } = editing;
    if (await call(`/${nid}`, "PATCH", { ...body, review_by: body.review_by || null })) setEditing(null);
  };
  const cats = res.data?.categories || {};
  const notes = res.data?.notes || [];
  const groups = Object.keys(cats)
    .map((k) => [k, notes.filter((n) => n.category === k)])
    .filter(([, list]) => list.length);

  return (
    <section className="card">
      <h2>Athlete notes</h2>
      <p className="muted small">
        Background the AI coach takes into account in plans, readiness notes, reviews and chat: things the data can't
        show. {isMe ? "You and your coaches" : "The athlete and their coaches"} can add and edit them. Health notes come
        up for review after 6 weeks; a note past its review date is left out until someone confirms it.
      </p>
      {res.error && <div className="error">{res.error.message}</div>}
      {groups.map(([cat, list]) => (
        <div key={cat} className="note-group">
          <h3>{cats[cat]}</h3>
          <ul className="instructions">
            {list.map((n) =>
              editing?.id === n.id ? (
                <li key={n.id}>
                  <form className="instruction-form" onSubmit={save}>
                    <textarea
                      rows={2}
                      maxLength={300}
                      minLength={3}
                      required
                      value={editing.body}
                      onChange={(e) => setEditing({ ...editing, body: e.target.value })}
                    />
                    <select value={editing.category} onChange={(e) => setEditing({ ...editing, category: e.target.value })}>
                      {Object.entries(cats).map(([k, label]) => (
                        <option key={k} value={k}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <label className="inline small">
                      Review by
                      <input
                        type="date"
                        value={editing.review_by || ""}
                        onChange={(e) => setEditing({ ...editing, review_by: e.target.value })}
                      />
                    </label>
                    <button className="btn small primary">Save</button>
                    <button type="button" className="btn small" onClick={() => setEditing(null)}>
                      Cancel
                    </button>
                  </form>
                </li>
              ) : (
                <li key={n.id} className={`note ${n.current ? "" : "inactive"}`}>
                  <div className="instruction-body">{n.body}</div>
                  <div className="small muted">
                    {n.author} ({n.role}) · {formatDate(n.created_at)}
                    {n.updated_by && ` · changed by ${n.updated_by} ${dateTime(n.updated_at)}`}
                    {n.review_by &&
                      (n.current ? ` · review by ${formatDate(n.review_by)}` : ` · review was due ${formatDate(n.review_by)}`)}
                    {!n.current && <span className="badge warn"> not sent to the AI</span>}
                  </div>
                  {n.history.length > 0 && (
                    <details className="small muted">
                      <summary>Earlier versions ({n.history.length})</summary>
                      <ul className="plain">
                        {n.history.map((h, i) => (
                          <li key={i}>
                            {dateTime(h.at)}: {h.body}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  <div className="row tight">
                    {!n.current && (
                      <button
                        className="icon-btn"
                        title="Still true: send it to the AI again"
                        aria-label="Confirm"
                        onClick={() => call(`/${n.id}/confirm`, "POST")}
                      >
                        <CheckCircle2 size={15} />
                      </button>
                    )}
                    <button
                      className="icon-btn"
                      title="Edit"
                      aria-label="Edit"
                      onClick={() =>
                        setEditing({ id: n.id, body: n.body, category: n.category, review_by: n.review_by || "" })
                      }
                    >
                      <Pencil size={15} />
                    </button>
                    <button
                      className="icon-btn"
                      title="Delete"
                      aria-label="Delete"
                      onClick={() => confirm("Delete this note?") && call(`/${n.id}`, "DELETE")}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </li>
              ),
            )}
          </ul>
        </div>
      ))}
      {res.data && !notes.length && <p className="muted small">No notes yet.</p>}
      <form className="instruction-form" onSubmit={add}>
        <textarea
          rows={2}
          maxLength={300}
          minLength={3}
          required
          placeholder='e.g. "Left knee sore after long climbs", "Power meter on the road bike only", "Night shifts every second week"'
          value={draft.body}
          onChange={(e) => setDraft({ ...draft, body: e.target.value })}
        />
        <select aria-label="Category" value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })}>
          {Object.entries(cats).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <label className="inline small">
          Review by {draft.category === "health" ? "(default: 6 weeks)" : "(optional)"}
          <input type="date" value={draft.review_by} onChange={(e) => setDraft({ ...draft, review_by: e.target.value })} />
        </label>
        <button className="btn primary small">Add note</button>
      </form>
      {error && <div className="error small">{error}</div>}
    </section>
  );
}
