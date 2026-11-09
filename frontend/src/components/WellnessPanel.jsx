import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatDate, monthYear, shortDate } from "../lib/format.js";

// The Weight tile: the trend (weigh-ins swing with water), its change over 30 days and the last weigh-in.
function WeightStat({ w }) {
  const change = w.change_30d == null ? "" : `${w.change_30d > 0 ? "+" : ""}${w.change_30d} in 30 days · `;
  const last = w.days_since === 0 ? "weighed today" : `weighed ${shortDate(w.latest_day)} (${w.latest_kg})`;
  return <Stat label="Weight (trend)" unit="kg" value={w.trend_kg} sub={`${change}${last}`} />;
}

export default function WellnessPanel({ rows, weight }) {
  if (!rows?.length) return <p className="muted">No Garmin wellness data yet.</p>;
  // Each tile: the newest day that has that value. Today's row is often still empty (last night's
  // sleep and HRV come with the next Garmin sync), and some watches never send some values.
  const today = rows[rows.length - 1].day;
  const latest = (key) => {
    const r = [...rows].reverse().find((x) => x[key] != null);
    return r ? { value: r[key], sub: r.day === today ? null : shortDate(r.day) } : { value: null, sub: "no data yet" };
  };
  const tile = (label, key, unit) => <Stat label={label} unit={unit} {...latest(key)} />;
  // Weight on its own axis (right): kg and bpm/ms don't share a scale.
  const hasWeight = rows.some((r) => r.weight_kg != null || r.weight_trend != null);
  return (
    <>
      <div className="stats">
        {tile("Resting HR", "resting_hr", "bpm")}
        {tile("HRV (night)", "hrv_ms", "ms")}
        {tile("Sleep", "sleep_h", "h")}
        {tile("Sleep score", "sleep_score")}
        {tile("Body Battery max", "body_battery_max")}
        {weight ? <WeightStat w={weight} /> : hasWeight && tile("Weight", "weight_kg", "kg")}
      </div>
      <div className="chart">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={rows} margin={{ top: 8, right: hasWeight ? -8 : 8, left: -16, bottom: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="day" tickFormatter={rows.length > 370 ? monthYear : shortDate} minTickGap={32} stroke="var(--muted)" fontSize={12} />
            <YAxis yAxisId="left" stroke="var(--muted)" fontSize={12} />
            {hasWeight && (
              <YAxis
                yAxisId="kg"
                orientation="right"
                stroke="var(--muted)"
                fontSize={12}
                domain={[(min) => Math.floor(min - 1), (max) => Math.ceil(max + 1)]}
                allowDecimals={false}
              />
            )}
            <Tooltip
              contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8 }}
              labelFormatter={(v) => formatDate(v)}
            />
            <Legend />
            <Line yAxisId="left" dataKey="hrv_ms" name="HRV (ms)" stroke="var(--c1)" dot={false} connectNulls />
            <Line yAxisId="left" dataKey="resting_hr" name="Resting HR" stroke="var(--c2)" dot={false} connectNulls />
            {hasWeight && (
              <Line
                yAxisId="kg"
                dataKey="weight_kg"
                name="Weigh-ins (kg)"
                stroke="var(--c3)"
                strokeOpacity={0}
                dot={{ r: 2.5, fill: "var(--c3)", strokeOpacity: 1 }}
                activeDot={{ r: 4 }}
                isAnimationActive={false}
              />
            )}
            {hasWeight && (
              <Line
                yAxisId="kg"
                type="monotone"
                dataKey="weight_trend"
                name="Weight trend (kg)"
                stroke="var(--c3)"
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            )}
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
