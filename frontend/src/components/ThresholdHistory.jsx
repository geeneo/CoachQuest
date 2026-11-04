import { useState } from "react";
import { api } from "../lib/api.js";
import { formatDate } from "../lib/format.js";

export const FIELDS = {
  ftp_watts: ["FTP", "W"],
  run_ftp_watts: ["Run threshold power", "W"],
  lthr_bpm: ["Threshold heart rate", "bpm"],
};

const today = () => new Date().toISOString().slice(0, 10);
const fromHistory = (h) => (h || []).map((e) => ({ field: e.field, from: e.from || "", value: e.value ?? "" }));

// FTP, run threshold power and LTHR over time: each workout's training load uses the value of its date,
// as TrainingPeaks does, so a new FTP doesn't change the TSS of earlier rides.
// `user` is the athlete (the signed-in user, or an athlete a coach sees with the profile share).
export default function ThresholdHistory({ user, onSaved, url = "/api/me/threshold-history", readOnly = false }) {
  const [rows, setRows] = useState(() => fromHistory(user.threshold_history));
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState(null);
  const set = (i, k) => (e) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: e.target.value } : r)));

  const save = async () => {
    setMsg(null);
    const entries = rows
      .filter((r) => r.value !== "" || r.from)
      .map((r) => ({ field: r.field, from: r.from || null, value: r.value === "" ? null : Number(r.value) }));
    try {
      const u = await api(url, { method: "PUT", body: { entries } });
      setRows(fromHistory(u.threshold_history));
      onSaved(u);
      setOpen(false);
      setMsg({ ok: "Saved. Every activity was scored again with the values of its date." });
    } catch (err) {
      setMsg({ error: err.message });
    }
  };

  // Today's Profile values are rows too, so adding an earlier value doesn't replace today's.
  const edit = () => {
    const now = Object.keys(FIELDS)
      .filter((k) => user[k] != null && !rows.some((r) => r.field === k))
      .map((k) => ({ field: k, from: today(), value: user[k] }));
    setRows([...rows, ...now]);
    setOpen(true);
  };

  const sorted = rows.map((r, i) => ({ ...r, i }));
  return (
    <section className="card">
      <h2>Threshold history</h2>
      <p className="small muted">
        Training load scores each workout with the FTP, run threshold power and threshold heart rate you had on its
        date, as TrainingPeaks does. A change in Profile counts from that day. Add earlier values here (TrainingPeaks:
        Settings → Zones, or your past tests) so older workouts score as they did then; the first value also counts before its date.
      </p>
      {!open ? (
        <>
          {rows.length ? (
            <ul className="small">
              {sorted.map((r) => (
                <li key={r.i}>
                  {FIELDS[r.field]?.[0]}: {r.value === "" ? "not set" : `${r.value} ${FIELDS[r.field]?.[1]}`}{" "}
                  {r.from ? `from ${formatDate(r.from)}` : "before that"}
                </li>
              ))}
            </ul>
          ) : (
            <p className="small">No history yet: every workout uses today's values.</p>
          )}
          {!readOnly && (
            <button type="button" className="btn" onClick={edit}>
              Edit history
            </button>
          )}
        </>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Value</th>
                  <th>From</th>
                  <th className="num">Amount</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => (
                  <tr key={r.i}>
                    <td>
                      <select value={r.field} onChange={set(r.i, "field")}>
                        {Object.entries(FIELDS).map(([k, [label]]) => (
                          <option key={k} value={k}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input type="date" value={r.from} max={today()} onChange={set(r.i, "from")} />
                      {!r.from && <span className="hint"> blank: before the first date</span>}
                    </td>
                    <td className="num">
                      <input type="number" value={r.value} onChange={set(r.i, "value")} style={{ width: "6em" }} />{" "}
                      {FIELDS[r.field]?.[1]}
                    </td>
                    <td>
                      <button type="button" className="btn small" onClick={() => setRows(rows.filter((_, j) => j !== r.i))}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row">
            <button
              type="button"
              className="btn"
              onClick={() => setRows([...rows, { field: "ftp_watts", from: today(), value: "" }])}
            >
              Add a value
            </button>
            <button type="button" className="btn primary" onClick={save}>
              Save and score again
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setRows(fromHistory(user.threshold_history));
                setOpen(false);
              }}
            >
              Cancel
            </button>
          </div>
          <p className="small muted">Your Profile values become the ones that apply today.</p>
        </>
      )}
      {msg?.ok && <div className="ok">{msg.ok}</div>}
      {msg?.error && <div className="error">{msg.error}</div>}
    </section>
  );
}
