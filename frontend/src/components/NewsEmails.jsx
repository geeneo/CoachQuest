import { Mail, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { dateTime } from "../lib/format.js";

// Admin → Email users (backend news_email.py): write to users about new features. Write, pick who gets
// it, send a test to yourself, then send; the history shows how many went out.
export default function NewsEmails() {
  const info = useApi("/api/admin/news-emails");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [audience, setAudience] = useState("all");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const sending = info.data?.history.some((h) => h.status === "sending");
  // While one goes out, look again every few seconds for its progress.
  useEffect(() => {
    if (!sending) return;
    const t = setTimeout(info.reload, 4000);
    return () => clearTimeout(t);
  }, [sending, info.data, info.reload]);
  if (info.error) return <div className="error">{info.error.message}</div>;
  if (!info.data) return <p className="muted">Loading…</p>;
  const d = info.data;
  const count = d.audiences.find((a) => a.id === audience)?.count ?? 0;
  const ready = subject.trim().length >= 3 && body.trim().length >= 10;
  const fromPost = (id) => {
    const p = d.posts.find((x) => String(x.id) === id);
    if (!p) return;
    setSubject(p.title);
    setBody(`${p.summary ? `${p.summary}\n\n` : ""}${p.body_md}\n\nRead it on CoachQuest: ${d.base_url}/news/${p.id}`);
  };
  const run = async (fn) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg({ error: e.message });
    }
    setBusy(false);
  };
  const test = () =>
    run(async () => {
      const r = await api("/api/admin/news-emails/test", { method: "POST", body: { subject, body } });
      setMsg({ ok: `Test sent to ${r.to}. Check how it looks before sending it to users.` });
    });
  const send = () =>
    confirm(`Send "${subject}" to ${count} user${count === 1 ? "" : "s"}? This can't be undone.`) &&
    run(async () => {
      await api("/api/admin/news-emails", { method: "POST", body: { subject, body, audience } });
      setMsg({ ok: "Sending: progress shows below." });
      setSubject("");
      setBody("");
      info.reload();
    });
  return (
    <>
      <section className="card">
        <h2>
          <Mail size={18} /> Email users
        </h2>
        <p className="small muted">
          Tell users about new features and changes. Plain text (Markdown like **bold** and lists read fine). Every
          email starts "Hi &lt;name&gt;", ends with a link to CoachQuest and says how to stop news emails (Profile).
          Users who switched news off, and users whose emails an admin stopped, don't get it.
        </p>
        {!d.mail_ready && <div className="error">Email isn't set up yet: Admin → Settings → Email.</div>}
        <div className="news-form">
          {d.posts.length > 0 && (
            <label>
              Start from a News &amp; guides post (optional)
              <select defaultValue="" onChange={(e) => fromPost(e.target.value)}>
                <option value="">—</option>
                {d.posts.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            Subject
            <input value={subject} maxLength={200} onChange={(e) => setSubject(e.target.value)} placeholder="New: the weather on your routes" />
          </label>
          <label>
            Text
            <textarea
              rows={10}
              value={body}
              maxLength={20000}
              onChange={(e) => setBody(e.target.value)}
              placeholder={"What's new, in a few short paragraphs.\n\n- A list works\n- Link to a page: " + d.base_url + "/weather"}
            />
          </label>
          <label>
            Who gets it
            <select value={audience} onChange={(e) => setAudience(e.target.value)}>
              {d.audiences.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label} ({a.count})
                </option>
              ))}
            </select>
          </label>
          <div className="row tight">
            <button type="button" className="btn" disabled={!ready || busy || !d.mail_ready} onClick={test}>
              Send a test to me
            </button>
            <button type="button" className="btn primary" disabled={!ready || busy || !d.mail_ready || sending || !count} onClick={send}>
              <Send size={14} /> Send to {count} user{count === 1 ? "" : "s"}
            </button>
          </div>
          {msg?.ok && <div className="ok">{msg.ok}</div>}
          {msg?.error && <div className="error">{msg.error}</div>}
        </div>
      </section>
      <section className="card">
        <h2>Sent</h2>
        {d.history.length === 0 ? (
          <p className="muted small">Nothing sent yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Subject</th>
                  <th>To</th>
                  <th className="num">Sent</th>
                  <th>By</th>
                </tr>
              </thead>
              <tbody>
                {d.history.map((h) => (
                  <tr key={h.id} title={h.body}>
                    <td>{dateTime(h.created_at)}</td>
                    <td>{h.subject}</td>
                    <td className="small muted">{h.audience_label}</td>
                    <td className="num">
                      {h.status === "sending" ? `sending… ${h.sent} of ${h.recipients || "?"}` : `${h.sent} of ${h.recipients}`}
                      {h.failed > 0 && <span className="bad-text"> · {h.failed} failed</span>}
                    </td>
                    <td className="small muted">{h.by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
