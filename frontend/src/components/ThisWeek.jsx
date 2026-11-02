import { useApi } from "../hooks/useApi.js";
import { DAY_STATUS } from "../lib/dayStatus.js";
import { duration } from "../lib/format.js";
import WeekTotals from "./WeekTotals.jsx";

// "This week so far" on the AI coach tab: the current plan's week in one row (each day's mark), and the
// same totals as the Plans strip and the Calendar. Nothing shows without a current plan.
export default function ThisWeek({ id, openTab }) {
  const res = useApi(`/api/athletes/${id}/plans/current`);
  const plan = res.data;
  const week = plan?.weeks?.find((w) => w.is_current);
  if (!week) return null;
  const s = week.summary;
  const label = (d) => d.weekday.slice(0, 1).toUpperCase() + d.weekday.slice(1);
  const left = week.days.filter((d) => d.status === "planned" || d.status === "today");
  return (
    <section className="card this-week">
      <div className="row between wrap">
        <h2>This week so far</h2>
        <span className="row tight small">
          <button type="button" className="link-btn small" onClick={() => openTab("plans")}>
            Plan →
          </button>
          <button type="button" className="link-btn small" onClick={() => openTab("calendar")}>
            Calendar →
          </button>
        </span>
      </div>
      <p className="small muted">
        {plan.title} · {week.phase}
        {week.focus ? ` · ${week.focus}` : ""}
      </p>
      <div className="this-week-days">
        {week.days.map((d) => {
          const st = DAY_STATUS[d.status];
          const mins = (d.duration_min || 0) + (d.extra_sessions || []).reduce((t, e) => t + (e.duration_min || 0), 0);
          return (
            <span
              key={d.date}
              className={`this-week-day ${st?.cls || ""} ${d.is_today ? "today" : ""}`}
              title={`${d.type}${mins ? ` · ${duration(mins * 60)}` : ""}${d.description ? ` — ${d.description}` : ""}`}
            >
              <span className="muted">{label(d)}</span>
              <span aria-label={st?.label || "Planned"}>{d.status === "planned" ? "·" : st?.emoji || "·"}</span>
              <span className="this-week-type">{d.type === "Zwift / indoor" ? "Indoor" : d.type}</span>
            </span>
          );
        })}
      </div>
      <WeekTotals
        t={{
          planned_min: s.planned_minutes,
          done_min: s.logged_minutes,
          planned_tss: s.planned_tss,
          done_tss: s.logged_tss,
          km: s.logged_km,
          elevation_m: s.logged_elevation_m,
          sessions_done: s.sessions_done,
          sessions_due: s.sessions_due,
        }}
        dates={week.days.map((d) => d.date)}
        load={plan.load}
      />
      {left.length > 0 && (
        <p className="small muted">
          Still to come:{" "}
          {left
            .filter((d) => d.type !== "Rest")
            .map((d) => `${label(d)} ${d.type === "Zwift / indoor" ? "indoor" : d.type.toLowerCase()} ${duration((d.duration_min || 0) * 60)}`)
            .join(" · ") || "rest days only"}
        </p>
      )}
    </section>
  );
}
