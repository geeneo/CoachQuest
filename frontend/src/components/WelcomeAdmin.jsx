import { Copy, ExternalLink, Image, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";
import { dateTime } from "../lib/format.js";

// Admin → Information page: the shareable page at its private link (backend welcome.py).
export default function WelcomeAdmin() {
  const [p, setP] = useState(null);
  const [draft, setDraft] = useState(null);
  const [msg, setMsg] = useState(null);
  const body = useRef(null);
  const load = (data) => {
    setP(data);
    setDraft((d) => d ?? { title: data.title, body_md: data.body_md });
  };
  useEffect(() => {
    api("/api/admin/welcome").then(load, (e) => setMsg({ error: e.message }));
  }, []);
  if (!p || !draft) return msg?.error ? <div className="error">{msg.error}</div> : null;

  const call = async (path, method, payload, ok) => {
    setMsg(null);
    try {
      const r = await api(`/api/admin/welcome${path}`, { method, body: payload });
      setP(r);
      if (ok) setMsg({ ok });
      return r;
    } catch (e) {
      setMsg({ error: e.message });
      return null;
    }
  };
  const changed = draft.title !== p.title || draft.body_md !== p.body_md;
  const insert = (text) => {
    // At the cursor in the text box, or at the end.
    const el = body.current;
    const at = el ? el.selectionStart : draft.body_md.length;
    setDraft({ ...draft, body_md: `${draft.body_md.slice(0, at)}${text}${draft.body_md.slice(at)}` });
  };
  const upload = (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      const r = await call("/images", "POST", { data_b64: String(reader.result).split(",")[1] });
      if (r) insert(`\n\n![${file.name.replace(/\.[^.]+$/, "")}](welcome-img/${r.added})\n\n`);
    };
    reader.readAsDataURL(file);
  };
  return (
    <section className="card">
      <h2>Information page</h2>
      <p className="muted small">
        A page about CoachQuest to send to people before they sign up: what it does, screenshots and how it works. Only
        people with the link see it; it isn't linked from the site, and search engines and AI crawlers are told to stay
        away. A new link makes the old one stop working.
      </p>
      <label className="check">
        <input type="checkbox" checked={p.enabled} onChange={(e) => call("", "PUT", { enabled: e.target.checked })} /> Page
        is on
      </label>
      <div className="row wrap">
        <input className="grow" readOnly value={p.link} onFocus={(e) => e.target.select()} aria-label="Link" />
        <button type="button" className="btn small" onClick={() => navigator.clipboard?.writeText(p.link)}>
          <Copy size={14} /> Copy
        </button>
        <a className="btn small" href={`/welcome/${p.key}`} target="_blank" rel="noreferrer">
          <ExternalLink size={14} /> Open
        </a>
        <button
          type="button"
          className="btn small"
          onClick={() =>
            confirm("Make a new link? The current one stops working for everyone you sent it to.") &&
            call("/new-link", "POST", undefined, "New link made; the old one no longer works.")
          }
        >
          <RefreshCw size={14} /> New link
        </button>
      </div>
      {!p.enabled && <p className="small warn-text">The page is off: the link shows "This page isn't available".</p>}
      <label>
        Title
        <input value={draft.title} maxLength={200} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
      </label>
      <label>
        Text (Markdown: ## heading, **bold**, - list, ![caption](image)); [[how-it-works]] shows the diagram
        <textarea
          ref={body}
          rows={16}
          value={draft.body_md}
          onChange={(e) => setDraft({ ...draft, body_md: e.target.value })}
          className="mono"
        />
      </label>
      <div className="row wrap">
        <button
          type="button"
          className="btn primary"
          disabled={!changed}
          onClick={() => call("", "PUT", draft, "Saved.")}
        >
          Save
        </button>
        {changed && (
          <button
            type="button"
            className="link-btn small"
            onClick={() => setDraft({ title: p.title, body_md: p.body_md })}
          >
            Undo changes
          </button>
        )}
        <label className="btn small file-btn">
          <Image size={14} /> Add a screenshot
          <input type="file" accept="image/png,image/jpeg,image/webp" onChange={upload} hidden />
        </label>
        <span className="muted small">Updated {dateTime(p.updated_at)}</span>
      </div>
      {p.images.length > 0 && (
        <div className="small">
          Screenshots added:{" "}
          {p.images.map((name) => (
            <span key={name} className="chip small static">
              <button type="button" className="link-btn small" onClick={() => insert(`![](welcome-img/${name})`)}>
                {name}
              </button>
              <button
                type="button"
                className="icon-btn"
                aria-label={`Delete ${name}`}
                onClick={() => confirm(`Delete ${name}?`) && call(`/images/${name}`, "DELETE")}
              >
                <Trash2 size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      {msg?.ok && <div className="ok small">{msg.ok}</div>}
      {msg?.error && <div className="error small">{msg.error}</div>}
    </section>
  );
}
