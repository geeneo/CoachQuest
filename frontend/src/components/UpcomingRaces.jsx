import { Link } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { formatDate } from "../lib/format.js";

export default function UpcomingRaces({ id, isMe, ctl }) {
  const races = useApi(`/api/athletes/${id}/races`);
  const upcoming = (races.data || []).filter((r) => r.active && r.days_to_go != null && r.days_to_go >= 0).slice(0, 3);
  if (!upcoming.length) {
    return isMe ? (
      <section className="card">
        <h2>Upcoming races</h2>
        <p className="muted small">
          No races set. <Link to="/races">Add the events you're training for</Link> and the AI coach will plan toward them.
        </p>
      </section>
    ) : null;
  }
  return (
    <section className="card">
      <div className="row between">
        <h2>Upcoming races</h2>
        {isMe && (
          <Link to="/races" className="small">
            Manage races
          </Link>
        )}
      </div>
      <div className="stats race-cards">
        {upcoming.map((r) => (
          <div key={r.id} className="stat">
            <div className="stat-label">
              {r.short_name || r.code} · {r.discipline || "race"}
            </div>
            <div className="stat-value">
              {r.days_to_go === 0 ? "Today" : `${r.days_to_go} days`}
            </div>
            <div className="stat-sub">
              {r.name} · {formatDate(r.target_date)}
              {r.distance_km ? ` · ${r.distance_km} km` : ""}
              {r.target_ctl ? ` · CTL ${ctl ?? "?"} → ${r.target_ctl}` : ""}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
