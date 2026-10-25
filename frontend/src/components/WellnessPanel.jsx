import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { shortDate } from "../lib/format.js";

export default function WellnessPanel({ rows }) {
  if (!rows?.length) return <p className="muted">No Garmin wellness data yet.</p>;
  const last = rows[rows.length - 1];
  return (
    <>
      <div className="stats">
        <Stat label="Resting HR" value={last.resting_hr} unit="bpm" />
        <Stat label="HRV (night)" value={last.hrv_ms} unit="ms" />
        <Stat label="Sleep" value={last.sleep_h} unit="h" />
        <Stat label="Sleep score" value={last.sleep_score} />
        <Stat label="Body Battery max" value={last.body_battery_max} />
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

export function Stat({ label, value, unit }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {value ?? "–"} {value != null && unit ? <span className="muted small">{unit}</span> : null}
      </div>
    </div>
  );
}
