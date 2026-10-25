import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "../hooks/useApi.js";
import { Stat } from "./WellnessPanel.jsx";

const PERIODS = [7, 30, 90];
const tooltipStyle = { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8 };
const number = (n) => (n == null ? null : Math.round(n).toLocaleString());

export default function VolumeStats({ id }) {
  const [days, setDays] = useState(30);
  const res = useApi(`/api/athletes/${id}/summary?days=${days}`);
  const s = res.data;
  return (
    <section className="card">
      <div className="row between">
        <h2>Volume</h2>
        <div className="chips" role="radiogroup" aria-label="Period">
          {PERIODS.map((d) => (
            <button
              key={d}
              type="button"
              role="radio"
              aria-checked={days === d}
              className={`chip ${days === d ? "on" : ""}`}
              onClick={() => setDays(d)}
            >
              {d} days
            </button>
          ))}
        </div>
      </div>
      {res.error && <div className="error">{res.error.message}</div>}
      {s && (
        <>
          <div className="stats">
            <Stat label="Distance" value={number(s.distance_km)} unit="km" sub={`${s.count} activities`} />
            <Stat
              label="Elevation"
              value={number(s.elevation_m)}
              unit="m"
              sub={
                s.outdoor_elevation_m !== s.elevation_m
                  ? `${number(s.outdoor_elevation_m)} m outdoors`
                  : "total climbing"
              }
            />
            <Stat label="Time" value={s.moving_hours} unit="hrs" sub="moving time" />
            <Stat label="Calories" value={number(s.calories)} unit="kcal" sub="burned" />
            <Stat label="Avg effort" value={s.avg_relative_effort} sub="relative effort / ride" />
          </div>
          <div className="chart-pair">
            <figure>
              <figcaption>Activity mix ({days}d)</figcaption>
              {s.mix.length ? (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={s.mix} margin={{ top: 8, right: 4, left: -24, bottom: 0 }}>
                    <CartesianGrid stroke="var(--grid)" vertical={false} />
                    <XAxis dataKey="category" stroke="var(--muted)" fontSize={12} tickLine={false} />
                    <YAxis allowDecimals={false} stroke="var(--muted)" fontSize={12} />
                    <Tooltip
                      contentStyle={tooltipStyle}
                      cursor={{ fill: "var(--panel-2)" }}
                      formatter={(v, _n, p) => [`${v} · ${p.payload.km} km · ${p.payload.hours} h`, "Activities"]}
                    />
                    <Bar dataKey="count" name="Activities" fill="var(--c1)" radius={[4, 4, 0, 0]} maxBarSize={56} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="muted small">No activities in this period.</p>
              )}
            </figure>
            <figure>
              <figcaption>Weekly elevation (12 weeks)</figcaption>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={s.weekly_elevation} margin={{ top: 8, right: 4, left: -16, bottom: 0 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis
                    dataKey="week_start"
                    tickFormatter={(w) => w.slice(5)}
                    stroke="var(--muted)"
                    fontSize={12}
                    tickLine={false}
                    minTickGap={8}
                  />
                  <YAxis stroke="var(--muted)" fontSize={12} tickFormatter={(v) => (v >= 1000 ? `${v / 1000}k` : v)} />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    cursor={{ fill: "var(--panel-2)" }}
                    labelFormatter={(w) => `Week of ${w}`}
                    formatter={(v) => [`${v.toLocaleString()} m`, "Elevation"]}
                  />
                  <Bar dataKey="elevation_m" name="Elevation" fill="var(--c3)" radius={[4, 4, 0, 0]} maxBarSize={40} />
                </BarChart>
              </ResponsiveContainer>
            </figure>
          </div>
        </>
      )}
    </section>
  );
}
