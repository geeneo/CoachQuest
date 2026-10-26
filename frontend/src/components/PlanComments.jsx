import { MessageSquare } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { dateTime, formatDate } from "../lib/format.js";

const fmtDay = (iso) => formatDate(iso, { weekday: "short", year: false });

// Where a thread's comments live. Plans have their own URLs (comments can be about one day);
// AI coach notes ("assessment") and calendar workouts ("workout") share one endpoint.
export function planUrls(base) {
  return {
    list: `${base}/comments`,
    create: `${base}/comments`,
    item: (id) => `${base}/comments/${id}`,
    extra: {},
  };
}
export function targetUrls(athleteId, target, targetId) {
  const root = `/api/athletes/${athleteId}/comments`;
  return {
    list: `${root}?target=${target}&target_id=${targetId}`,
    create: root,
    item: (id) => `${root}/${id}`,
    extra: { target, target_id: targetId },
  };
}

// Comments on a plan, or on one day of it, from the athlete and their coaches.
// `comments` and `setComments` are owned by the tracker so days can show their counts.
export default function PlanComments({
  base,
  comments,
  setComments,
  day,
  setDay,
}) {
  return (
    <section className="card plan-comments" id="plan-comments">
      <CommentThread
        urls={planUrls(base)}
        comments={comments}
        setComments={setComments}
        day={day}
        setDay={setDay}
        heading
      />
    </section>
  );
}

// A comment button that opens the thread underneath: for AI coach notes and calendar workouts.
export function CommentsToggle({
  athleteId,
  target,
  targetId,
  count = 0,
  label = "Comments",
}) {
  const [open, setOpen] = useState(false);
  const [n, setN] = useState(count);
  return (
    <div className="comments-toggle">
      <button
        className={`btn small ${n ? "has-comments" : ""}`}
        onClick={() => setOpen(!open)}
      >
        <MessageSquare size={14} /> {label}
        {n ? ` (${n})` : ""}
      </button>
      {open && (
        <CommentThread
          urls={targetUrls(athleteId, target, targetId)}
          onCount={setN}
        />
      )}
    </div>
  );
}

// The thread itself. Controlled (comments + setComments) or loading its own list (urls.list).
export function CommentThread({
  urls,
  comments: given,
  setComments: setGiven,
  day = null,
  setDay,
  heading,
  onCount,
}) {
  const [own, setOwn] = useState(null);
  const comments = given ?? own ?? [];
  const setComments = (list) => {
    (setGiven || setOwn)(list);
    onCount?.(list.length);
  };
  useEffect(() => {
    if (given === undefined) api(urls.list).then(setComments, () => setOwn([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urls.list]);
  const [text, setText] = useState("");
  const [editing, setEditing] = useState(null); // {id, body}
  const [error, setError] = useState(null);
  const call = async (path, method, body) => {
    setError(null);
    try {
      setComments(await api(path, { method, body }));
      return true;
    } catch (err) {
      setError(err.message);
      return false;
    }
  };
  const add = async (e) => {
    e.preventDefault();
    const body = { ...urls.extra, body: text, ...(day ? { day } : {}) };
    if (await call(urls.create, "POST", body)) setText("");
  };
  const shown = day ? comments.filter((c) => c.day === day) : comments;

  return (
    <div className="comment-thread">
      {heading && (
        <div className="row between">
          <h2>
            <MessageSquare size={18} /> Comments
            {day ? ` on ${fmtDay(day)}` : ""}
          </h2>
          {day && (
            <button className="btn small" onClick={() => setDay(null)}>
              Show all comments
            </button>
          )}
        </div>
      )}
      {heading && (
        <p className="muted small">
          For the athlete and their coaches: everyone here can add, edit and
          delete comments. New comments are emailed to the others (switch this
          off in Profile), and re-planning with the AI coach reads them, the
          coach's carrying the most weight.
        </p>
      )}
      {shown.length === 0 && <p className="muted small">No comments yet.</p>}
      <ul className="comments">
        {shown.map((c) => (
          <li key={c.id} className={`comment ${c.role}`}>
            <div className="comment-head small">
              <strong>{c.author}</strong>{" "}
              <span className="badge">
                {c.role === "coach" ? "Coach" : "Athlete"}
              </span>
              {c.day && !day && (
                <button
                  className="link-btn small"
                  onClick={() => setDay(c.day)}
                >
                  {fmtDay(c.day)}
                </button>
              )}
              <span className="muted">
                {" "}
                · {dateTime(c.created_at)}
                {c.edited_at
                  ? ` · edited${c.edited_by && c.edited_by !== c.author ? ` by ${c.edited_by}` : ""}`
                  : ""}
              </span>
            </div>
            {editing?.id === c.id ? (
              <form
                className="stack"
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (
                    await call(urls.item(c.id), "PATCH", {
                      body: editing.body,
                      day: c.day,
                    })
                  )
                    setEditing(null);
                }}
              >
                <textarea
                  rows={3}
                  maxLength={4000}
                  value={editing.body}
                  onChange={(e) =>
                    setEditing({ ...editing, body: e.target.value })
                  }
                />
                <div className="row">
                  <button className="btn small primary">Save</button>
                  <button
                    type="button"
                    className="btn small"
                    onClick={() => setEditing(null)}
                  >
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
                  <button
                    className="link-btn small"
                    onClick={() => setEditing({ id: c.id, body: c.body })}
                  >
                    Edit
                  </button>
                )}
                {c.can_delete && (
                  <button
                    className="link-btn small"
                    onClick={() =>
                      window.confirm("Delete this comment?") &&
                      call(urls.item(c.id), "DELETE")
                    }
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
          placeholder={
            day
              ? `Comment on ${fmtDay(day)}…`
              : heading
                ? "Comment on the whole plan…"
                : "Add a comment…"
          }
        />
        {error && <div className="error small">{error}</div>}
        <div>
          <button className="btn primary" disabled={!text.trim()}>
            Add comment
          </button>
        </div>
      </form>
    </div>
  );
}
