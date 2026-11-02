import { duration } from "../lib/format.js";

// Under a week (Plans strip, Calendar): planned vs done time, distance, climbing, TSS and sessions, and
// fitness (CTL) with its change over the week and form (TSB) at its end. `load` is {date: {ctl, tsb}}.
export default function WeekTotals({ t, dates, load }) {
  const pct = t.planned_min ? Math.round((100 * t.done_min) / t.planned_min) : null;
  const known = (dates || []).filter((d) => load?.[d]);
  const first = known.length ? load[known[0]] : null;
  const last = known.length ? load[known.at(-1)] : null;
  const change = known.length > 1 ? last.ctl - first.ctl : null; // over the week so far
  return (
    <div className="week-totals small">
      <span>
        <span className="muted">Time </span>
        <strong>{t.done_min ? duration(t.done_min * 60) : "0m"}</strong>
        <span className="muted"> of {t.planned_min ? duration(t.planned_min * 60) : "0m"}</span>
        {pct != null && t.done_min > 0 && <span className={pct >= 70 ? "ok-text" : "warn-text"}> ({pct}%)</span>}
      </span>
      {t.sessions_due > 0 && (
        <span>
          <span className="muted">Sessions </span>
          <strong>
            {t.sessions_done}/{t.sessions_due}
          </strong>
        </span>
      )}
      {t.km > 0 && (
        <span>
          <strong>{Math.round(t.km).toLocaleString()} km</strong>
          <span className="muted"> · {Math.round(t.elevation_m).toLocaleString()} m↑</span>
        </span>
      )}
      <span>
        <span className="muted">TSS </span>
        <strong>{t.done_tss || 0}</strong>
        <span className="muted"> of ≈{t.planned_tss || 0}</span>
      </span>
      {last && last.ctl > 0 && (
        <span title="Fitness (CTL, 42-day load) and form (TSB = fitness − fatigue) at the end of the week so far">
          <span className="muted">Fitness </span>
          <strong>{last.ctl}</strong>
          {change != null && (
            <span className={change >= 0 ? "ok-text" : "muted"}>
              {" "}
              ({change >= 0 ? "+" : ""}
              {change})
            </span>
          )}
          <span className="muted"> · Form </span>
          <strong className={last.tsb < -25 ? "bad-text" : last.tsb < -10 ? "warn-text" : ""}>
            {last.tsb > 0 ? "+" : ""}
            {last.tsb}
          </strong>
        </span>
      )}
    </div>
  );
}
