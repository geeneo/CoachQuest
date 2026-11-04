import { Download } from "lucide-react";
import { useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { download } from "../lib/api.js";

const TABLES = [
  ["users", "Users"],
  ["activities", "Activities"],
  ["load", "Training load"],
  ["plan_days", "Plan days"],
  ["wellness", "Wellness"],
  ["assessments", "Readiness & reviews"],
];

// Admin → Data (backend data_export.py): the anonymised data for improving CoachQuest's logic, with a
// preview of each table and a ZIP download. Super admins only.
export default function DataExport() {
  const today = new Date().toISOString().slice(0, 10);
  const yearAgo = new Date(Date.now() - 365 * 86400000).toISOString().slice(0, 10);
  const [range, setRange] = useState({ since: yearAgo, until: today });
  const [table, setTable] = useState("activities");
  const q = `since=${range.since}&until=${range.until}`;
  const res = useApi(`/api/admin/data?${q}`);
  const d = res.data;
  const rows = d?.preview[table] || [];
  return (
    <>
      <section className="card">
        <h2>Data</h2>
        <p className="small muted">
          Everyone's training data, anonymised, to study and improve CoachQuest's logic (which plans get followed, what
          predicts a missed session, how readiness and load relate). Users are codes, no names, emails, goals or
          activity names; each user's dates move by a fixed number of whole weeks; weight is rounded and age is a band.
          Users who opted out in their Profile aren't in it. The README in the download explains every column.
        </p>
        <p className="small warn-text">
          Activities from Strava are left out: Strava's API agreement doesn't allow its data in developing or training AI
          applications. Load and plan statuses are worked out from Garmin, Intervals.icu and manual activities only.
          Mention this use in your privacy notice.
        </p>
        <div className="row tight wrap">
          <label className="small">
            From{" "}
            <input type="date" value={range.since} onChange={(e) => setRange({ ...range, since: e.target.value })} />
          </label>
          <label className="small">
            To <input type="date" value={range.until} onChange={(e) => setRange({ ...range, until: e.target.value })} />
          </label>
          <button
            type="button"
            className="btn primary small"
            disabled={!d}
            onClick={() => download(`/api/admin/data/export.zip?${q}`)}
          >
            <Download size={14} /> Download (ZIP of CSVs)
          </button>
        </div>
        {res.error && <div className="error">{res.error.message}</div>}
        {!d && !res.error && <p className="muted">Loading…</p>}
        {d && (
          <>
            <div className="stats">
              {TABLES.map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  className={`stat stat-btn ${table === k ? "on" : ""}`}
                  onClick={() => setTable(k)}
                >
                  <div className="stat-label">{label}</div>
                  <div className="stat-value small-value">{d.counts[k].toLocaleString()}</div>
                </button>
              ))}
            </div>
            <p className="small muted">
              {d.strava_left_out.toLocaleString()} Strava activities left out · {d.users_opted_out} user
              {d.users_opted_out === 1 ? "" : "s"} opted out · {d.version}
            </p>
          </>
        )}
      </section>
      {d && (
        <section className="card">
          <h2>
            {TABLES.find(([k]) => k === table)[1]}: the first {rows.length} of {d.counts[table].toLocaleString()} rows
          </h2>
          {rows.length === 0 ? (
            <p className="muted small">No rows in this range.</p>
          ) : (
            <div className="table-wrap audit-table">
              <table className="small">
                <thead>
                  <tr>
                    {Object.keys(rows[0]).map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i}>
                      {Object.values(r).map((v, j) => (
                        <td key={j}>{v === null || v === "" ? "–" : String(v)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}
