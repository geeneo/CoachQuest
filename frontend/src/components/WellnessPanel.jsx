import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { shortDate } from "../lib/format.js";

export default function WellnessPanel({ rows }) {
  if (!rows?.length) return <p className="muted">No Garmin wellness data yet.</p>;
  // Each tile: the newest day that has that value. Today's row is often still empty (last night's
  // sleep and HRV come with the next Garmin sync), and some watches never send some values.
  const today = rows[rows.length - 1].day;
  const latest = (key) => {
    const r = [...rows].reverse().find((x) => x[key] != null);
    return r ? { value: r[key], sub: r.day === today ? null : shortDate(r.day) } : { value: null, sub: "no data yet" };
  };
  const tile = (label, key, unit) => <Stat label={label} unit={unit} {...latest(key)} />;
  return (
    <>
      <div className="stats">
        {tile("Resting HR", "resting_hr", "bpm")}
        {tile("HRV (night)", "hrv_ms", "ms")}
        {tile("Sleep", "sleep_h", "h")}
        {tile("Sleep score", "sleep_score")}
        {tile("Body Battery max", "body_battery_max")}
      </div>
      <div className="chart">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={rows} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="day" tickFormatter={shortDate} minTickGap={32} stroke="var(--muted)" fontSize={12} />
            <YAxis stroke="var(--muted)" fontSize={12} />
            <Tooltip
              contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8 }}
              labelFormatter={shortDate}
            />
            <Legend />
            <Line dataKey="hrv_ms" name="HRV (ms)" stroke="var(--c1)" dot={false} connectNulls />
            <Line dataKey="resting_hr" name="Resting HR" stroke="var(--c2)" dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

export function Stat({ label, value, unit, sub }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {value ?? "–"} {value != null && unit ? <span className="muted small">{unit}</span> : null}
      </div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}
