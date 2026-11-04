import { Download, Upload } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { api, download } from "../lib/api.js";

// Training load audit (backend load_audit.py): how CTL, ATL and TSB were worked out, day by day and
// activity by activity, with CSV downloads and a comparison with a TrainingPeaks export. Read only.
export default function LoadAudit() {
  const { athleteId } = useParams();
  const [days, setDays] = useState(180);
  const res = useApi(`/api/athletes/${athleteId}/load-audit?days=${days}`);
  const [cmp, setCmp] = useState(null);
  const [error, setError] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const a = res.data;
  const base = `/api/athletes/${athleteId}/load-audit`;
  const compare = async (file) => {
    setError(null);
    setCmp(null);
    try {
      // TrainingPeaks may hand the summary over as a ZIP: send it as it is (base64), the server opens it.
      const zip = /\.zip$/i.test(file.name) || file.type.includes("zip");
      const body = zip ? { zip_b64: await toBase64(file), days } : { csv: await file.text(), days };
      setCmp(await api(`${base}/compare`, { method: "POST", body }));
    } catch (e) {
      setError(e.message);
    }
  };
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Training load audit</h1>
          <p className="muted small">
            How CoachQuest got fitness (CTL), fatigue (ATL) and form (TSB): every day and every activity, with
            the TSS it counted and how that TSS was worked out. Nothing here changes your data.{" "}
            <Link to="/">Back to My training</Link>
          </p>
        </div>
      </div>
      <div className="row tight wrap">
        {[90, 180, 365].map((n) => (
          <button key={n} type="button" className={`chip ${days === n ? "on" : ""}`} onClick={() => setDays(n)}>
            {n} days
          </button>
        ))}
        <button type="button" className="btn small" onClick={() => download(`${base}/days.csv?days=${days}`)}>
          <Download size={14} /> Days (CSV)
        </button>
        <button type="button" className="btn small" onClick={() => download(`${base}/activities.csv?days=${days}`)}>
          <Download size={14} /> Activities (CSV)
        </button>
      </div>
      {res.error && <div className="error">{res.error.message}</div>}
      {!a && !res.error && <p className="muted">Loading…</p>}
      {a && (
        <>
          <section className="card">
            <h2>
              {a.meta.athlete}: {a.meta.from} to {a.meta.to}
            </h2>
            <p className="small muted">
              FTP {a.meta.ftp_watts ? `${a.meta.ftp_watts} W` : "not set"} · LTHR{" "}
              {a.meta.lthr_bpm ? `${a.meta.lthr_bpm} bpm` : "not set"} · time zone {a.meta.timezone} · main source{" "}
              {a.meta.primary_source || "not chosen"}
              {a.meta.hidden_sources.length ? ` · hidden sources: ${a.meta.hidden_sources.join(", ")}` : ""}
              {a.meta.threshold_history?.length
                ? " · each workout scored with the thresholds of its date (Profile → Threshold history)"
                : ""}
            </p>
            <p className="small muted">
              {a.meta.calculation} ({a.meta.version})
            </p>
            {a.warnings.map((w) => (
              <p key={w} className="small warn-text">
                ⚠ {w}
              </p>
            ))}
            <h3>Where the TSS came from</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>How it was worked out</th>
                    <th className="num">Activities</th>
                    <th className="num">TSS</th>
                    <th className="num">Share</th>
                  </tr>
                </thead>
                <tbody>
                  {a.summary.by_method.map((m) => (
                    <tr key={m.method}>
                      <td>{m.label}</td>
                      <td className="num">{m.activities}</td>
                      <td className="num">{m.tss}</td>
                      <td className="num">{m.share}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="small muted">
              {a.summary.counted} activities counted, {a.summary.duplicates} copies of the same session counted once
              {a.summary.hidden_source ? `, ${a.summary.hidden_source} from hidden sources left out` : ""}.
            </p>
          </section>

          <section className="card">
            <h2>Compare with TrainingPeaks</h2>
            <p className="small muted">
              In TrainingPeaks: your name (top right) → Settings → Export Data → <strong>Workout Summary</strong>, the same
              dates as here, Export. Choose that file here (CSV, or the ZIP as it comes). Workouts on one day are added up;
              the first day that differs is usually where the cause is. Guide: News &amp; guides → Compare your training
              load with TrainingPeaks.
            </p>
            <label className="btn small file-btn">
              <Upload size={14} /> Choose the TrainingPeaks file
              <input type="file" accept=".csv,.zip,text/csv,application/zip" hidden onChange={(e) => e.target.files[0] && compare(e.target.files[0])} />
            </label>
            {error && <div className="error">{error}</div>}
            {cmp && (
              <>
                <p>
                  <strong>
                    {cmp.days_compared} days compared: CoachQuest {cmp.cq_tss} TSS, TrainingPeaks {cmp.other_tss}
                    {cmp.ratio ? ` (×${cmp.ratio})` : ""}.
                  </strong>{" "}
                  {cmp.first_difference ? `First day that differs: ${cmp.first_difference}.` : "No day differs by more than 10%."}
                </p>
                <div className="table-wrap audit-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th className="num">CQ TSS</th>
                        <th className="num">TP TSS</th>
                        <th className="num">Diff</th>
                        <th className="num">CQ CTL</th>
                        <th className="num">TP CTL</th>
                        <th className="num">CQ ATL</th>
                        <th className="num">TP ATL</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cmp.days.map((d) => (
                        <tr key={d.date} className={Math.abs(d.tss_diff) > 5 ? "diff" : ""}>
                          <td>{d.date}</td>
                          <td className="num">{d.cq_tss}</td>
                          <td className="num">{d.other_tss}</td>
                          <td className="num">{d.tss_diff > 0 ? `+${d.tss_diff}` : d.tss_diff}</td>
                          <td className="num">{d.cq_ctl ?? "–"}</td>
                          <td className="num">{d.other_ctl ?? "–"}</td>
                          <td className="num">{d.cq_atl ?? "–"}</td>
                          <td className="num">{d.other_atl ?? "–"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>

          <section className="card">
            <h2>Day by day</h2>
            <div className="table-wrap audit-table">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th className="num">Activities</th>
                    <th className="num">TSS</th>
                    <th className="num">CTL</th>
                    <th className="num">ATL</th>
                    <th className="num">TSB</th>
                  </tr>
                </thead>
                <tbody>
                  {[...a.days].reverse().slice(0, showAll ? undefined : 42).map((d) => (
                    <tr key={d.date} className={d.rest ? "muted" : ""}>
                      <td>{d.date}</td>
                      <td className="num">{d.activities || "rest"}</td>
                      <td className="num">{d.tss}</td>
                      <td className="num">{d.ctl}</td>
                      <td className="num">{d.atl}</td>
                      <td className="num">{d.tsb}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!showAll && a.days.length > 42 && (
              <button type="button" className="link-btn small" onClick={() => setShowAll(true)}>
                Show all {a.days.length} days
              </button>
            )}
          </section>

          <section className="card">
            <h2>Activities</h2>
            <div className="table-wrap audit-table">
              <table>
                <thead>
                  <tr>
                    <th>Start (local)</th>
                    <th>Source</th>
                    <th>Activity</th>
                    <th>Sport</th>
                    <th className="num">Min</th>
                    <th className="num">TSS</th>
                    <th>How</th>
                    <th className="num">IF</th>
                    <th>Counted</th>
                  </tr>
                </thead>
                <tbody>
                  {[...a.activities].reverse().map((x) => (
                    <tr key={x.id} className={x.status === "counted" ? "" : "muted"} title={`ID ${x.id} · ${x.source} ${x.external_id}`}>
                      <td>{x.start_local}</td>
                      <td>{x.source}</td>
                      <td className="name-cell">{x.name}</td>
                      <td>{x.sport}</td>
                      <td className="num">{x.minutes}</td>
                      <td className="num">{x.tss}</td>
                      <td className="small">{x.method}</td>
                      <td className="num" title={x.ftp_w ? `FTP ${x.ftp_w} W on that date` : undefined}>
                        {x.intensity ?? "–"}
                      </td>
                      <td className="small">
                        {x.status === "duplicate" ? `copy of #${x.canonical_id}` : x.status}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  );
}

export async function toBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

