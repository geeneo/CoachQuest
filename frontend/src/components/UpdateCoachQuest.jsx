import { Download, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { dateTime } from "../lib/format.js";

const TARGETS = [
  ["all", "Everything"],
  ["backend", "Backend only"],
  ["frontend", "Frontend only"],
];

// Admin → Update CoachQuest (super admins). The page only asks; deploy-agent.sh on the server (cron,
// menu.sh option 11) pulls from GitHub and runs deploy.sh, so the web app never gets Docker or root.
export default function UpdateCoachQuest() {
  const [s, setS] = useState(null);
  const [error, setError] = useState(null);
  const [target, setTarget] = useState("all");
  const [password, setPassword] = useState("");
  const [asking, setAsking] = useState(false);
  const load = async () => {
    try {
      setS(await api("/api/admin/update"));
      setError(null);
    } catch (err) {
      // While the API restarts during a deploy, it doesn't answer for a little while.
      setError(s ? "Waiting for the server to come back after the update…" : err.message);
    }
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const busy = s && (s.pending || s.status?.state === "running");
  useEffect(() => {
    if (!busy && !error) return;
    const t = setInterval(load, 4000); // follow a check or deploy as it happens
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, error]);

  const check = async () => {
    try {
      setS(await api("/api/admin/update/check", { method: "POST" }));
    } catch (err) {
      setError(err.message);
    }
  };
  const deploy = async (e) => {
    e.preventDefault();
    try {
      setS(await api("/api/admin/update/deploy", { method: "POST", body: { target, password } }));
      setPassword("");
      setAsking(false);
    } catch (err) {
      setError(err.message);
    }
  };
  if (!s) return error ? <div className="error">{error}</div> : null;
  const v = s.versions;
  const st = s.status;
  const behind = s.new_commits.length;
  return (
    <section className="card update-card">
      <h2>
        <Download size={18} /> Update CoachQuest
      </h2>
      {!s.agent.alive ? (
        <div className="hint">
          The update agent isn't running on the server{s.agent.seen ? ` (last seen ${dateTime(s.agent.seen)})` : ""}.
          Install it once on the server: <code>bash menu.sh</code> → option 11. Until then, deploy there with option 2.
        </div>
      ) : (
        <p className="muted small">
          The server checks GitHub every 30 minutes and deploys when you ask. It pulls the newest code and rebuilds; the
          site is down for a minute or so while the API restarts.
        </p>
      )}
      <div className="row wrap small">
        <span>
          Running <code>{s.running}</code>
        </span>
        {v && (
          <>
            <span>
              · on the server <code>{v.disk}</code>
            </span>
            <span>
              · newest on GitHub ({v.branch}) <code>{v.remote}</code>
            </span>
            <span className="muted">· checked {dateTime(v.checked)}</span>
          </>
        )}
        <button type="button" className="btn small" onClick={check} disabled={!s.agent.alive || busy}>
          <RefreshCw size={14} /> Check now
        </button>
      </div>
      {v && Number(v.dirty) > 0 && (
        <p className="small warn-text">
          The server's copy has {v.dirty} file(s) changed by hand. If an update changes the same file, it stops and the
          log says which (on the server: <code>git status</code>).
        </p>
      )}
      {behind > 0 ? (
        <>
          <p>
            <strong>
              {behind} new change{behind === 1 ? "" : "s"}
            </strong>{" "}
            on GitHub:
          </p>
          <ul className="small commit-list">
            {s.new_commits.map((c) => (
              <li key={c.commit}>
                <code>{c.commit}</code> <span className="muted">{c.date}</span> {c.subject}
              </li>
            ))}
          </ul>
        </>
      ) : (
        v && <p className="small ok-text">✓ Up to date with GitHub.</p>
      )}
      {s.pending && <p className="small">⏳ Waiting for the server to pick it up (within a minute)…</p>}
      {st && (
        <p className={`small ${st.state === "failed" ? "error-text" : st.state === "done" ? "ok-text" : ""}`}>
          {st.state === "running" ? "⏳ Updating" : st.state === "done" ? "✓ Last update done" : "✗ Last update failed"}
          : {st.target} by {st.by}, started {dateTime(st.started)}
          {st.finished && `, finished ${dateTime(st.finished)}`}
          {st.after && st.before !== st.after && ` (${st.before} → ${st.after})`}
        </p>
      )}
      {s.agent.alive &&
        !busy &&
        (asking ? (
          <form className="row wrap" onSubmit={deploy}>
            <select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="What to update">
              {TARGETS.map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
            <input
              type="password"
              autoComplete="current-password"
              placeholder="Your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoFocus
            />
            <button className="btn primary">Update now</button>
            <button type="button" className="link-btn small" onClick={() => setAsking(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <button type="button" className={`btn ${behind ? "primary" : ""}`} onClick={() => setAsking(true)}>
            <Download size={16} /> {behind ? "Update to the newest version" : "Redeploy"}
          </button>
        ))}
      {s.log.length > 0 && (
        <details open={busy || st?.state === "failed"}>
          <summary className="small">Log of the {busy ? "update" : "last update"}</summary>
          <pre className="deploy-log">{s.log.join("\n")}</pre>
        </details>
      )}
      {s.history.length > 0 && (
        <details>
          <summary className="small">Earlier updates</summary>
          <ul className="small">
            {s.history.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        </details>
      )}
      {error && <div className={busy ? "hint" : "error"}>{error}</div>}
    </section>
  );
}
