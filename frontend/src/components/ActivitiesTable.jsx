import { duration, shortDate } from "../lib/format.js";

export default function ActivitiesTable({ rows }) {
  if (!rows?.length) return <p className="muted">No activities in this period.</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Activity</th>
            <th>Sport</th>
            <th className="num">Time</th>
            <th className="num">km</th>
            <th className="num">HR</th>
            <th className="num">NP</th>
            <th className="num">TSS</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td>{shortDate(a.start_time)}</td>
              <td>
                {a.name} <span className={`badge ${a.source}`}>{a.source}</span>
              </td>
              <td>{a.sport}</td>
              <td className="num">{duration(a.duration_s)}</td>
              <td className="num">{a.distance_km || "–"}</td>
              <td className="num">{a.avg_hr ? Math.round(a.avg_hr) : "–"}</td>
              <td className="num">{a.norm_power ? Math.round(a.norm_power) : "–"}</td>
              <td className="num" title={`Estimated from ${a.tss_method}`}>
                {Math.round(a.tss)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
