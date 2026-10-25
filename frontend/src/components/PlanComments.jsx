import { MessageSquare } from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api.js";
import { dateTime } from "../lib/format.js";

const fmtDay = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

// Comments on a plan, or on one day of it, from the athlete and their coaches.
// `comments` and `setComments` are owned by the tracker so days can show their counts.
export default function PlanComments({ base, comments, setComments, day, setDay }) {
  const [text, setText] = useState("");
  const [editing, setEditing] = useState(null); // {id, body}
  const [error, setError] = useState(null);
  const call = async (path, method, body) => {
    setError(null);
    try {
      setComments(await api(`${base}/comments${path}`, { method, body }));
      return true;
    } catch (err) {
      setError(err.message);
      return false;
    }
  };
  const add = async (e) => {
    e.preventDefault();
    if (await call("", "POST", { body: text, day })) setText("");
  };
  const shown = day ? comments.filter((c) => c.day === day) : comments;

  return (
    <section className="card plan-comments" id="plan-comments">
      <div className="row between">
        <h2>
          <MessageSquare size={18} /> Comments{day ? ` on ${fmtDay(day)}` : ""}
        </h2>
        {day && (
          <button className="btn small" onClick={() => setDay(null)}>
            Show all comments
          </button>
        )}
      </div>
      <p className="muted small">
        For the athlete and their coaches: everyone here can add, edit and delete comments. New comments are emailed to
        the others (switch this off in Profile), and re-planning with the AI coach reads them, the coach's carrying the
        most weight.
      </p>
      {shown.length === 0 && <p className="muted small">No comments yet.</p>}
      <ul className="comments">
        {shown.map((c) => (
          <li key={c.id} className={`comment ${c.role}`}>
            <div className="comment-head small">
              <strong>{c.author}</strong> <span className="badge">{c.role === "coach" ? "Coach" : "Athlete"}</span>
              {c.day && !day && (
                <button className="link-btn small" onClick={() => setDay(c.day)}>
                  {fmtDay(c.day)}
                </button>
              )}
              <span className="muted">
                {" "}
                · {dateTime(c.created_at)}
                {c.edited_at ? ` · edited${c.edited_by && c.edited_by !== c.author ? ` by ${c.edited_by}` : ""}` : ""}
              </span>
            </div>
            {editing?.id === c.id ? (
              <form
                className="stack"
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (await call(`/${c.id}`, "PATCH", { body: editing.body, day: c.day })) setEditing(null);
                }}
              >
                <textarea rows={3} maxLength={4000} value={editing.body} onChange={(e) => setEditing({ ...editing, body: e.target.value })} />
                <div className="row">
                  <button className="btn small primary">Save</button>
                  <button type="button" className="btn small" onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <p className="comment-body">{c.body}</p>
            )}
            {editing?.id !== c.id && (c.can_edit || c.can_delete) && (
              <div className="row tight">
                {c.can_edit && (
                  <button className="link-btn small" onClick={() => setEditing({ id: c.id, body: c.body })}>
                    Edit
                  </button>
                )}
                {c.can_delete && (
                  <button
                    className="link-btn small"
                    onClick={() => window.confirm("Delete this comment?") && call(`/${c.id}`, "DELETE")}
                  >
                    Delete
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
      <form className="stack" onSubmit={add}>
        <textarea
          rows={3}
          maxLength={4000}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={day ? `Comment on ${fmtDay(day)}…` : "Comment on the whole plan…"}
        />
        {error && <div className="error small">{error}</div>}
        <div>
          <button className="btn primary" disabled={!text.trim()}>
            Add comment
          </button>
        </div>
      </form>
    </section>
  );
}
