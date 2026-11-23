import { Trophy } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { formatDate } from "../lib/format.js";

const PERIODS = [
  [90, "3 months"],
  [365, "12 months"],
  [3650, "All"],
];
const FEELING = { 1: "Terrible", 2: "Hard going", 3: "OK", 4: "Good", 5: "Flying" };
const NOTES = [
  ["went_well", "Went well"],
  ["went_badly", "Didn't go well"],
  ["nutrition", "Food"],
  ["problems", "Problems"],
  ["next_time", "Next time"],
];

// Admin → Race reviews: every athlete's post-race updates in one list, each opening the full race review.
// Only while admins may view athletes' data; each athlete listed sees it in their access log.
export default function AdminRaceReviews() {
  const [days, setDays] = useState(365);
  const [onlyUpdates, setOnlyUpdates] = useState(true);
  const res = useApi(`/api/admin/race-reviews?days=${days}&only_updates=${onlyUpdates}`);
  const [open, setOpen] = useState(null);
  const rows = res.data || [];
  return (
    <section className="card">
      <h2>Race reviews</h2>
      <p className="muted small">
        Every athlete's races and their post-race update: official time, positions, how it felt and their notes. Open a
        race for the whole review (ride, earlier years, segments, weather, other riders). Each athlete listed sees this
        in their "Who looked at my data" log.
      </p>
      <div className="seg-controls">
        <div className="seg-chips" role="group" aria-label="Period">
          {PERIODS.map(([d, label]) => (
            <button
              key={d}
              className={`btn small ${days === d ? "active" : ""}`}
              aria-pressed={days === d}
              onClick={() => setDays(d)}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="small inline-check">
          <input type="checkbox" checked={onlyUpdates} onChange={(e) => setOnlyUpdates(e.target.checked)} /> Only races
          with a post-race update
        </label>
      </div>
      {res.loading && <p className="muted">Loading…</p>}
      {res.error && <div className="error">{res.error.message}</div>}
      {res.data && rows.length === 0 && <p className="muted small">No race reviews in this period.</p>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Athlete</th>
                <th>Race</th>
                <th className="num">Official</th>
                <th>Position</th>
                <th>Category</th>
                <th>Felt</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const u = r.post_race || {};
                const notes = NOTES.filter(([k]) => u[k]);
                const key = `${r.athlete_id}-${r.race_id}`;
                return (
                  <tr key={key}>
                    <td className="nowrap">{formatDate(r.date)}</td>
                    <td>
                      <Link to={`/athletes/${r.athlete_id}?tab=races`}>{r.athlete}</Link>
                    </td>
                    <td>
                      <Link to={`/athletes/${r.athlete_id}/races/${r.race_id}/review`}>
                        <Trophy size={13} /> {r.race}
                      </Link>
                    </td>
                    <td className="num">{u.official_time || "–"}</td>
                    <td>{u.position ? `${u.position}${u.field_size ? ` of ${u.field_size}` : ""}` : "–"}</td>
                    <td>
                      {u.category_position
                        ? `${u.category || "Category"}: ${u.category_position}${u.category_size ? ` of ${u.category_size}` : ""}`
                        : u.category || "–"}
                    </td>
                    <td>{u.feeling ? FEELING[u.feeling] : "–"}</td>
                    <td className="notes-cell">
                      {notes.length === 0 ? (
                        "–"
                      ) : open === key ? (
                        <>
                          {notes.map(([k, label]) => (
                            <div key={k} className="small">
                              <span className="muted">{label}:</span> {u[k]}
                            </div>
                          ))}
                          <button className="link-btn small" onClick={() => setOpen(null)}>
                            Hide
                          </button>
                        </>
                      ) : (
                        <button className="link-btn small" onClick={() => setOpen(key)}>
                          {notes.map(([, label]) => label).join(", ")}
                        </button>
                      )}
                    </td>
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
