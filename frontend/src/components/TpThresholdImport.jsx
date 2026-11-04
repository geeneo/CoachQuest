import { useState } from "react";
import { api } from "../lib/api.js";
import { formatDate } from "../lib/format.js";
import { toBase64 } from "../pages/LoadAudit.jsx";

const LABELS = {
  ftp_watts: ["FTP", "W"],
  run_ftp_watts: ["Run threshold power", "W"],
  lthr_bpm: ["Threshold heart rate", "bpm"],
  max_hr_bpm: ["Max HR", "bpm"],
};

// The thresholds TrainingPeaks used, worked out from its Workout Summary export: tick the ones to take.
export default function TpThresholdImport({ id, onSaved }) {
  const [res, setRes] = useState(null);
  const [take, setTake] = useState({});
  const [correct, setCorrect] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const read = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setMsg(null);
    setRes(null);
    setBusy(true);
    try {
      const zip = /\.zip$/i.test(file.name);
      const body = zip ? { zip_b64: await toBase64(file) } : { csv: await file.text() };
      const out = await api(`/api/athletes/${id}/thresholds/from-trainingpeaks`, { method: "POST", body });
      setRes(out);
      setTake(Object.fromEntries(Object.entries(out.values).map(([k, v]) => [k, v.value !== out.current[k]])));
    } catch (err) {
      setMsg({ error: err.message });
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    const body = Object.fromEntries(Object.keys(take).filter((k) => take[k]).map((k) => [k, res.values[k].value]));
    if (!Object.keys(body).length) return setMsg({ ok: "Nothing ticked." });
    if (correct) body.correct_history = true;
    try {
      const out = await api(`/api/athletes/${id}/thresholds`, { method: "PATCH", body });
      setMsg({ ok: "Saved. Training load was recalculated." });
      setRes(null);
      onSaved?.(out);
    } catch (err) {
      setMsg({ error: err.message });
    }
  };

  return (
    <section className="card">
      <h2>Thresholds from TrainingPeaks</h2>
      <p className="small muted">
        In TrainingPeaks on the web: your name (top right) → <b>Settings</b> → <b>Export Data</b> →{" "}
        <b>Workout Summary</b>, the last 6–12 months, CSV. Upload it here (CSV or ZIP): CoachQuest works out the FTP,
        run threshold power and threshold heart rate TrainingPeaks scored the workouts with. Nothing is saved until you
        choose.
      </p>
      <label className="btn">
        {busy ? "Reading…" : "Choose the TrainingPeaks file"}
        <input type="file" accept=".csv,.zip,text/csv,application/zip" onChange={read} hidden disabled={busy} />
      </label>
      {res && (
        <>
          <p className="small">
            {res.workouts} workouts, {formatDate(res.from)} to {formatDate(res.to)}.
          </p>
          {Object.keys(res.values).length === 0 ? (
            <p className="small warn-text">Not enough workouts with power or heart rate to work anything out.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Take</th>
                    <th>Value</th>
                    <th className="num">TrainingPeaks</th>
                    <th className="num">Now</th>
                    <th>Worked out from</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(res.values).map(([k, v]) => (
                    <tr key={k}>
                      <td>
                        <input
                          type="checkbox"
                          checked={!!take[k]}
                          onChange={(e) => setTake({ ...take, [k]: e.target.checked })}
                          aria-label={`Take ${LABELS[k][0]}`}
                        />
                      </td>
                      <td>{LABELS[k][0]}</td>
                      <td className="num">
                        <b>
                          {v.value} {LABELS[k][1]}
                        </b>
                      </td>
                      <td className="num">{res.current[k] != null ? `${res.current[k]} ${LABELS[k][1]}` : "–"}</td>
                      <td className="small muted" title={v.how}>
                        {v.from ? `${v.sessions} sessions, ${formatDate(v.from)} – ${formatDate(v.to)}` : "all workouts"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {Object.keys(res.values).length > 0 && (
            <>
              <label className="check">
                <input type="checkbox" checked={correct} onChange={(e) => setCorrect(e.target.checked)} />
                Correct earlier workouts too (the values here were wrong, not lower fitness)
              </label>
              <p className="small muted">
                These are worked out from the workouts' scores, so within a few watts or beats: if you can see the exact
                numbers in TrainingPeaks (Settings → Zones), type those in instead.
              </p>
              <button type="button" className="btn primary" onClick={save}>
                Save the ticked values
              </button>
            </>
          )}
        </>
      )}
      {msg?.ok && <div className="ok">{msg.ok}</div>}
      {msg?.error && <div className="error">{msg.error}</div>}
    </section>
  );
}
