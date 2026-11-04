import { Download, RefreshCw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { download } from "../lib/api.js";
import { dateTime } from "../lib/format.js";

const MARK = { ok: "✅", warn: "⚠️", bad: "❌" };
const HEADLINE = {
  ok: "Everything looks fine",
  warn: "Mostly fine: a few things to look at",
  bad: "Something needs fixing",
};

// Data health (backend diagnostics.py): connections, activities, the profile values training load
// needs, wellness, and the plan's workout delivery, each with what to do. Read only.
export default function Diagnostics() {
  const { athleteId } = useParams();
  const res = useApi(`/api/athletes/${athleteId}/diagnostics`);
  const d = res.data;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Data health</h1>
          <p className="muted small">
            Is everything CoachQuest needs coming in, and is it sound? Nothing here changes your data. Something odd?
            Download the report and send it to your admin.
          </p>
        </div>
      </div>
      <div className="row tight wrap">
        <button type="button" className="btn small" onClick={res.reload} disabled={res.loading}>
          <RefreshCw size={14} className={res.loading ? "spin" : ""} /> Check again
        </button>
        <button type="button" className="btn small" onClick={() => download(`/api/athletes/${athleteId}/diagnostics/report.json`)}>
          <Download size={14} /> Download diagnostics
        </button>
        <Link className="btn small" to={`/load-audit/${athleteId}`}>
          Training load audit →
        </Link>
      </div>
      {res.error && <div className="error">{res.error.message}</div>}
      {!d && !res.error && <p className="muted">Checking…</p>}
      {d && (
        <>
          <div className={`week-status ${d.status === "ok" ? "on" : d.status === "warn" ? "watch" : "off"}`}>
            <strong>
              {MARK[d.status]} {d.athlete.name}: {HEADLINE[d.status]}
            </strong>
            <p className="small muted">Checked {dateTime(d.checked_at)}</p>
          </div>
          {d.sections.map((s) => (
            <section key={s.id} className="card">
              <h2>
                {MARK[s.status]} {s.title}
              </h2>
              <ul className="diag-list">
                {s.items.map((i, n) => (
                  <li key={n} className={i.level}>
                    <span aria-hidden="true">{MARK[i.level]}</span>
                    <span>
                      {i.text}
                      {i.fix && <span className="muted"> {i.fix}</span>}
                      {i.link && (
                        <>
                          {" "}
                          <Link to={i.link}>Open →</Link>
                        </>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </>
      )}
    </>
  );
}
