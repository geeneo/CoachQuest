import { useApi } from "../hooks/useApi.js";
import { duration } from "../lib/format.js";
import { PlanWeek } from "../pages/PlansPanel.jsx";

// "This week so far" on the AI coach tab: the current plan's week with the same days, details and totals
// as the Current plan card on the Plans tab, and what's still to come. Nothing shows without a current plan.
export default function ThisWeek({ id, openTab }) {
  const res = useApi(`/api/athletes/${id}/plans/current`);
  const plan = res.data;
  const week = plan?.weeks?.find((w) => w.is_current);
  if (!week) return null;
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
      <PlanWeek plan={plan} week={week} />
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
