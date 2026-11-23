import { Trophy } from "lucide-react";
import { Link } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { formatDate } from "../lib/format.js";

const FEELING = { 1: "Terrible", 2: "Hard going", 3: "OK", 4: "Good", 5: "Flying" };

function place(pos, size) {
  if (!pos) return null;
  return size ? `${pos} of ${size}` : String(pos);
}

// An athlete's races for whoever looks at them (coach, admin, the athlete): the upcoming ones with their
// target, the past ones with the post-race update in short and a link to the full race review.
export default function AthleteRaces({ id, isMe }) {
  const races = useApi(`/api/athletes/${id}/races`);
  if (races.loading) return <p className="muted">Loading races…</p>;
  if (races.error) return <div className="error">{races.error.message}</div>;
  const rows = [...(races.data || [])].sort((a, b) => (b.target_date || "").localeCompare(a.target_date || ""));
  const review = (r) => (isMe ? `/races/${r.id}/review` : `/athletes/${id}/races/${r.id}/review`);
  return (
    <section className="card">
      <div className="row between">
        <h2>Races</h2>
        {isMe && (
          <Link to="/races" className="small">
            Manage races
          </Link>
        )}
      </div>
      <p className="muted small">Past races open their review: the ride, the post-race update, earlier years, segments and weather.</p>
      {rows.length === 0 ? (
        <p className="muted small">No races yet.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Race</th>
                <th className="num">km</th>
                <th className="num">Target</th>
                <th className="num">Official time</th>
                <th>Position</th>
                <th>Category</th>
                <th>Felt</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const res = r.result || {};
                const past = r.days_to_go != null && r.days_to_go <= 0;
                return (
                  <tr key={r.id} className={past ? "" : "muted"}>
                    <td className="nowrap">{r.target_date ? formatDate(r.target_date) : "–"}</td>
                    <td>
                      {past ? (
                        <Link to={review(r)} title="Race review: ride, post-race update, earlier years, segments, weather">
                          <Trophy size={13} /> {r.name}
                        </Link>
                      ) : (
                        r.name
                      )}
                      {past && res.has_notes && <span className="muted small"> · notes</span>}
                      {!past && r.days_to_go != null && <span className="muted small"> · in {r.days_to_go} days</span>}
                    </td>
                    <td className="num">{r.distance_km ?? "–"}</td>
                    <td className="num">{r.target_time || "–"}</td>
                    <td className="num">{res.official_time || "–"}</td>
                    <td>{place(res.position, res.field_size) || "–"}</td>
                    <td>
                      {res.category_position
                        ? `${res.category || "Category"}: ${place(res.category_position, res.category_size)}`
                        : res.category || "–"}
                    </td>
                    <td>{res.feeling ? FEELING[res.feeling] : "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
