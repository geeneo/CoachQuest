import { useApi } from "../hooks/useApi.js";
import { duration } from "../lib/format.js";
import { PlanWeek } from "../pages/PlansPanel.jsx";

// "This week so far" on the AI coach tab: the current plan's week with the same days, details and totals
// as the Current plan card on the Plans tab, and what's still to come. Nothing shows without a current plan.
export default function ThisWeek({ id, openTab }) {
  const res = useApi(`/api/athletes/${id}/plans/current`);
  const status = useApi(`/api/athletes/${id}/coach/week`).data;
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
      {status && <HowItsGoing s={status} />}
      <PlanWeek plan={plan} week={week} />
      {left.length > 0 && (
        <p className="small muted">
          Still to come:{" "}
          {left
            .filter((d) => d.type !== "Rest")
            .map(
              (d) =>
                `${label(d)} ` +
                [d, ...(d.extra_sessions || [])]
                  .map((x) => `${x.type === "Zwift / indoor" ? "indoor" : x.type.toLowerCase()} ${duration((x.duration_min || 0) * 60)}`)
                  .join(" + "), // every session that day, as the day's box adds them up
            )
            .join(" · ") || "rest days only"}
        </p>
      )}
    </section>
  );
}

const MARK = { ok: "✅", warn: "⚠️", bad: "❌" };

// "How is your week going?" (backend week_status.py): a verdict and what's behind it, worked out in code
// each time the tab opens.
function HowItsGoing({ s }) {
  return (
    <div className={`week-status ${s.verdict}`}>
      <strong>How is your week going? {s.headline}</strong>
      <ul>
        {s.points.map((p, i) => (
          <li key={i} className={p.level}>
            <span aria-hidden="true">{MARK[p.level]}</span> {p.text}
          </li>
        ))}
      </ul>
      {s.projection && <p className="small muted">{s.projection}</p>}
    </div>
  );
}

