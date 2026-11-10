import { useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { dateTime } from "../lib/format.js";

// Admin → Errors (backend error_log.py): what the app logged, grouped by kind, and the connections that
// stopped syncing. Super admins also get a daily email when something is new or back.
export default function AdminErrors() {
  const [all, setAll] = useState(false);
  const res = useApi(`/api/admin/errors${all ? "?all=true" : ""}`);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState(null);
  const resolve = (g) =>
    api(`/api/admin/errors/${g.id}/resolve`, { method: "POST" }).then(res.reload, (e) => setError(e.message));
  const d = res.data;
  return (
    <>
      <section className="card">
        <div className="row between">
          <h2>Errors and warnings</h2>
          <label className="check small">
            <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show the fixed ones too
          </label>
        </div>
        <p className="muted small">
          Problems the app logged (failed syncs, crashed requests, jobs that went wrong), one line per kind with how
          often and when. Mark one fixed when you've dealt with it: it comes back if it happens again. Super admins get
          one email a day (06:45) when something is new or back.
        </p>
        {error && <div className="error">{error}</div>}
        {res.error && <div className="error">{res.error.message}</div>}
        {d && d.groups.length === 0 && <p className="ok-text">✓ Nothing open.</p>}
        {d && d.groups.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>What</th>
                  <th>Times</th>
                  <th>Last</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {d.groups.map((g) => (
                  <tr key={g.id} className={g.open ? "" : "muted"}>
                    <td>
                      <span className={g.level === "ERROR" ? "error-text" : "warn-text"}>{g.level}</span>{" "}
                      <span className="muted small">{g.logger}</span>
                      <div>{g.message}</div>
                      {g.traceback && (
                        <button type="button" className="link-btn small" onClick={() => setOpen(open === g.id ? null : g.id)}>
                          {open === g.id ? "Hide details" : "Details"}
                        </button>
                      )}
                      {open === g.id && <pre className="deploy-log">{g.traceback}</pre>}
                    </td>
                    <td>
                      {g.count}
                      <div className="muted small">since {dateTime(g.first_seen)}</div>
                    </td>
                    <td className="small">{dateTime(g.last_seen)}</td>
                    <td>
                      {g.open && (
                        <button type="button" className="btn small" onClick={() => resolve(g)}>
                          Mark fixed
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {d && d.connections.length > 0 && (
        <section className="card">
          <h2>Connections not syncing</h2>
          <ul className="small">
            {d.connections.map((c, i) => (
              <li key={i}>
                <strong>{c.user}</strong>: {c.provider} ({c.why})
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
