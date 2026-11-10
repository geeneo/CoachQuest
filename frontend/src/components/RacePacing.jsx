import { Download } from "lucide-react";
import { useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { download } from "../lib/api.js";

const GROUPS = [
  ["team", "In a team, sharing the work"],
  ["bunch", "Sitting in a bunch"],
  ["alone", "Alone"],
];

// The pacing plan on the race's route for its target time, and the course for a Garmin Edge whose
// Virtual Partner rides it (backend pacing.py).
export default function RacePacing({ race }) {
  // The race's own Riding setting (Races page) to start with.
  const [group, setGroup] = useState({ solo: "alone", team: "team", bunch: "bunch" }[race.riding] || "team");
  const [stops, setStops] = useState(0);
  const query = `group=${group}&stops=${stops}`;
  const res = useApi(`/api/races/${race.id}/pacing?${query}`);
  const [error, setError] = useState(null);
  const p = res.data;
  const get = (fmt) => download(`/api/races/${race.id}/pacing.${fmt}?${query}`).catch((e) => setError(e.message));
  return (
    <>
      <div className="row wrap tight">
        <label className="inline">
          Riding{" "}
          <select value={group} onChange={(e) => setGroup(e.target.value)}>
            {GROUPS.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="inline">
          Stops (minutes, in the target time){" "}
          <input
            type="number"
            min={0}
            max={600}
            step={5}
            value={stops}
            onChange={(e) => setStops(Math.max(0, Number(e.target.value) || 0))}
            style={{ width: "5rem" }}
          />
        </label>
      </div>
      {res.loading && <p className="muted">Working out the pacing (heights along the route)…</p>}
      {res.error && <div className="error">{res.error.message}</div>}
      {error && <div className="error">{error}</div>}
      {p && (
        <>
          <div className="stats">
            <div className="stat">
              <div className="stat-label">Target</div>
              <div className="stat-value">{p.target_time}</div>
              <div className="stat-sub">
                {p.start}–{p.finish} · {p.moving_time} riding
              </div>
            </div>
            <div className="stat">
              <div className="stat-label">Average speed</div>
              <div className="stat-value">
                {p.avg_speed_kmh} <span className="muted small">km/h</span>
              </div>
              <div className="stat-sub">
                {p.distance_km} km · {p.climbing_m} m up
              </div>
            </div>
            <div className="stat">
              <div className="stat-label">Power</div>
              <div className="stat-value">
                {p.avg_power_w} <span className="muted small">W</span>
              </div>
              <div className="stat-sub">
                NP {p.norm_power_w} W · {p.w_per_kg} W/kg{p.intensity_factor ? ` · IF ${p.intensity_factor}` : ""}
              </div>
            </div>
          </div>
          {p.warning && <div className="hint bad">{p.warning}</div>}
          <h3>Checkpoints</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>km</th>
                  <th>Time</th>
                  <th>Clock</th>
                  <th>Climbed</th>
                </tr>
              </thead>
              <tbody>
                {p.checkpoints.map((c) => (
                  <tr key={c.km}>
                    <td>{c.km}</td>
                    <td>{c.elapsed}</td>
                    <td>{c.clock}</td>
                    <td>{c.climbed_m} m</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {p.climbs.length > 0 && (
            <>
              <h3>Climbs</h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>From km</th>
                      <th>Length</th>
                      <th>Gradient</th>
                      <th>Target power</th>
                      <th>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.climbs.map((c) => (
                      <tr key={c.start_km}>
                        <td>{c.start_km}</td>
                        <td>
                          {c.length_km} km · {c.gain_m} m
                        </td>
                        <td>{c.grade_pct}%</td>
                        <td>{c.power_w} W</td>
                        <td>{c.time}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <p className="muted small">Assumes {p.notes.join("; ")}.</p>
          <h3>On your Garmin Edge</h3>
          <div className="row tight wrap">
            <button className="btn primary" onClick={() => get("fit")}>
              <Download size={14} /> Pacing course (.fit)
            </button>
            <button className="btn" onClick={() => get("gpx")}>
              <Download size={14} /> GPX
            </button>
          </div>
          <ol className="small">
            <li>
              Plug the Edge into your computer and copy the .fit file into its <strong>Garmin/NewFiles</strong> folder
              (or import the file in Garmin Connect → Training → Courses and sync).
            </li>
            <li>
              On the Edge: <strong>Navigation → Courses</strong>, pick the course and ride it. Every point in the file
              has the time this plan reaches it, so the <strong>Virtual Partner</strong> rides your plan: add the
              "Ahead/Behind" data field (or watch the map) to see if you're up or down on it. Checkpoints show as
              course points with their planned time of day.
            </li>
            <li>
              Turn on <strong>ClimbPro</strong> in the ride profile for each climb's length and gradient, and ride the
              climbs at the target power above.
            </li>
            <li>Test it on a short ride before race day. The stops aren't in the file: the partner keeps riding.</li>
          </ol>
        </>
      )}
    </>
  );
}
