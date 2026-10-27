import { ArrowLeft, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Markdown from "../components/Markdown.jsx";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { formatDate } from "../lib/format.js";

const TABS = [
  ["guides", "How-to guides"],
  ["news", "News"],
];

// News & guides: everyone reads what's published; admins also see drafts and can write.
export default function News() {
  const res = useApi("/api/posts");
  const [tab, setTab] = useState("guides");
  const d = res.data;
  return (
    <>
      <div className="row between page-head">
        <h1>News &amp; guides</h1>
        {d?.can_edit && (
          <Link className="btn" to={`/news/new?kind=${tab === "news" ? "news" : "guide"}`}>
            <Plus size={16} /> New {tab === "news" ? "news post" : "guide"}
          </Link>
        )}
      </div>
      <div className="tabs">
        {TABS.map(([id, label]) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {res.error && <div className="error">{res.error.message}</div>}
      {d && (
        <div className="post-list">
          {d[tab].map((p) => (
            <Link key={p.id} to={`/news/${p.id}`} className="card post-card">
              <strong>{p.title}</strong>
              {!p.published && <span className="badge"> draft</span>}
              {p.summary && <p className="muted small">{p.summary}</p>}
              {p.kind === "news" && p.published_at && <span className="muted small">{formatDate(p.published_at)}</span>}
            </Link>
          ))}
          {!d[tab].length && (
            <p className="muted">{tab === "news" ? "No news yet." : "No guides yet."}</p>
          )}
        </div>
      )}
    </>
  );
}

export function PostView() {
  const { postId } = useParams();
  const res = useApi(`/api/posts/${postId}`);
  const list = useApi("/api/posts");
  const p = res.data;
  return (
    <>
      <Link to="/news" className="small">
        <ArrowLeft size={14} /> News &amp; guides
      </Link>
      {res.error && <div className="error">{res.error.message}</div>}
      {p && (
        <article className="card post">
          <div className="row between">
            <h1>{p.title}</h1>
            {list.data?.can_edit && (
              <Link className="btn small" to={`/news/${p.id}/edit`}>
                <Pencil size={14} /> Edit
              </Link>
            )}
          </div>
          <p className="muted small">
            {p.published ? (p.kind === "news" && p.published_at ? formatDate(p.published_at) : "") : "Draft: only admins see it."}
            {p.author ? ` · ${p.author}` : ""}
          </p>
          <Markdown>{p.body_md}</Markdown>
        </article>
      )}
    </>
  );
}

export function PostEditor() {
  const { postId } = useParams();
  const isNew = !postId;
  const res = useApi(isNew ? null : `/api/posts/${postId}`);
  if (!isNew && !res.data) return res.error ? <div className="error">{res.error.message}</div> : null;
  return <EditorForm key={postId || "new"} post={res.data} />;
}

function EditorForm({ post }) {
  const navigate = useNavigate();
  const kind = new URLSearchParams(window.location.search).get("kind") === "news" ? "news" : "guide";
  const [form, setForm] = useState(
    post
      ? { kind: post.kind, title: post.title, summary: post.summary, body_md: post.body_md, published: post.published, position: post.position }
      : { kind, title: "", summary: "", body_md: "", published: false, position: 100 },
  );
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = { ...form, position: Number(form.position) || 0 };
      const saved = await api(post ? `/api/posts/${post.id}` : "/api/posts", { method: post ? "PUT" : "POST", body });
      navigate(`/news/${saved.id}`);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!confirm(`Delete "${post.title}"? This can't be undone.`)) return;
    try {
      await api(`/api/posts/${post.id}`, { method: "DELETE" });
      navigate("/news");
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <>
      <Link to={post ? `/news/${post.id}` : "/news"} className="small">
        <ArrowLeft size={14} /> Back
      </Link>
      <h1>{post ? "Edit" : "New"} {form.kind === "news" ? "news post" : "guide"}</h1>
      <form className="card post-editor" onSubmit={save}>
        <div className="row wrap">
          <label className="inline">
            Kind
            <select value={form.kind} onChange={set("kind")}>
              <option value="guide">How-to guide</option>
              <option value="news">News</option>
            </select>
          </label>
          {form.kind === "guide" && (
            <label className="inline" title="Guides are listed from the lowest number up">
              Order
              <input type="number" min={0} max={1000} value={form.position} onChange={set("position")} />
            </label>
          )}
          <label className="check">
            <input type="checkbox" checked={form.published} onChange={set("published")} /> Published (everyone can read
            it)
          </label>
        </div>
        <label>
          Title
          <input value={form.title} onChange={set("title")} maxLength={200} required />
        </label>
        <label>
          Summary (shown in the list)
          <input value={form.summary} onChange={set("summary")} maxLength={300} />
        </label>
        <div className="post-edit-grid">
          <label>
            Text (Markdown: ## heading, **bold**, - list, [link](https://…))
            <textarea rows={22} value={form.body_md} onChange={set("body_md")} maxLength={50000} />
          </label>
          <div>
            <span className="muted small">Preview</span>
            <div className="post-preview">
              <Markdown>{form.body_md || "_Nothing yet._"}</Markdown>
            </div>
          </div>
        </div>
        {error && <div className="error">{error}</div>}
        <div className="row">
          <button className="btn primary" disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
          {post && (
            <button type="button" className="btn danger" onClick={remove}>
              Delete
            </button>
          )}
        </div>
      </form>
    </>
  );
}
