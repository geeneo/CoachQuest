import { useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatDate, monthYear, shortDate } from "../lib/format.js";

// What can be switched on and off below the chart (remembered per browser).
const SERIES = [
  ["ctl", "Fitness (CTL)", "var(--c1)"],
  ["atl", "Fatigue (ATL)", "var(--c2)"],
  ["tsb", "Form (TSB)", "var(--form)"],
  ["tss", "TSS", "var(--danger)"],
  ["plan", "Planned ahead", "var(--muted)"],
];
const STORE = "cq.fitness.hidden";

function loadHidden() {
  try {
    return new Set(JSON.parse(localStorage.getItem(STORE) || "[]"));
  } catch {
    return new Set();
  }
}

// History (from /fitness) and, when given, the projection if the plan is followed (/fitness/projection):
// one row per day, the projection's values under p_* so they draw dashed from today on.
export function mergeRows(data, projection) {
  const rows = (data || []).map((d) => ({ ...d, day: String(d.day), tss: d.tss || null }));
  const byDay = Object.fromEntries(rows.map((r) => [r.day, r]));
  for (const p of projection || []) {
    const row = byDay[p.day] || { day: p.day };
    Object.assign(row, { p_ctl: p.ctl, p_atl: p.atl, p_tsb: p.tsb, p_tss: p.planned_tss || null, race: p.race });
    if (!byDay[p.day]) {
      byDay[p.day] = row;
      rows.push(row);
    }
  }
  return rows;
}

export default function FitnessChart({ data, projection }) {
  const [hidden, setHidden] = useState(loadHidden);
  if (!data?.length) return <p className="muted">No training load yet.</p>;
  const rows = mergeRows(data, projection);
  const race = rows.find((r) => r.race);
  const show = (k) => !hidden.has(k);
  const ahead = show("plan") && projection?.length > 0;
  const toggle = (k) => {
    const next = new Set(hidden);
    next.has(k) ? next.delete(k) : next.add(k);
    setHidden(next);
    try {
      localStorage.setItem(STORE, JSON.stringify([...next]));
    } catch {
      // private window: just don't remember
    }
  };
  const dot = (color, hollow) => ({ r: 3, fill: hollow ? "var(--panel)" : color, stroke: color, strokeWidth: 1.5 });
  return (
    <>
      <div className="chart">
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={rows} margin={{ top: 8, right: show("tss") ? 0 : 8, left: -16, bottom: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis
              dataKey="day"
              tickFormatter={rows.length > 370 ? monthYear : shortDate}
              minTickGap={32}
              stroke="var(--muted)"
              fontSize={12}
            />
            <YAxis yAxisId="load" stroke="var(--muted)" fontSize={12} />
            {show("tss") && <YAxis yAxisId="tss" orientation="right" stroke="var(--muted)" fontSize={11} width={36} />}
            <Tooltip
              contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8 }}
              labelFormatter={(v) => formatDate(v)}
            />
            {ahead && race && (
              <ReferenceLine yAxisId="load" x={race.day} stroke="var(--muted)" strokeDasharray="2 3" label={{ value: `🏁 ${race.race}`, fill: "var(--muted)", fontSize: 11, position: "insideTopRight" }} />
            )}
            {show("tsb") && (
              <Area yAxisId="load" dataKey="tsb" name="Form (TSB)" fill="var(--form)" stroke="var(--form)" fillOpacity={0.15} isAnimationActive={false} />
            )}
            {show("ctl") && <Line yAxisId="load" dataKey="ctl" name="Fitness (CTL)" stroke="var(--c1)" dot={false} strokeWidth={2} isAnimationActive={false} />}
            {show("atl") && <Line yAxisId="load" dataKey="atl" name="Fatigue (ATL)" stroke="var(--c2)" dot={false} strokeWidth={1.5} isAnimationActive={false} />}
            {ahead && show("tsb") && <Line yAxisId="load" dataKey="p_tsb" name="Form, planned" stroke="var(--form)" strokeDasharray="4 3" dot={false} isAnimationActive={false} />}
            {ahead && show("ctl") && <Line yAxisId="load" dataKey="p_ctl" name="Fitness, planned" stroke="var(--c1)" strokeDasharray="4 3" dot={false} strokeWidth={2} isAnimationActive={false} />}
            {ahead && show("atl") && <Line yAxisId="load" dataKey="p_atl" name="Fatigue, planned" stroke="var(--c2)" strokeDasharray="4 3" dot={false} isAnimationActive={false} />}
            {show("tss") && (
              <Line yAxisId="tss" dataKey="tss" name="TSS" stroke="none" dot={dot("var(--danger)")} activeDot={{ r: 4 }} isAnimationActive={false} />
            )}
            {show("tss") && ahead && (
              <Line yAxisId="tss" dataKey="p_tss" name="TSS, planned" stroke="none" dot={dot("var(--danger)", true)} activeDot={{ r: 4 }} isAnimationActive={false} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="chips tight chart-toggles" role="group" aria-label="Show on the chart">
        {SERIES.filter(([k]) => k !== "plan" || projection?.length).map(([k, label, color]) => (
          <button
            key={k}
            type="button"
            aria-pressed={show(k)}
            className={`chip small ${show(k) ? "on" : ""}`}
            onClick={() => toggle(k)}
            title={show(k) ? `Hide ${label}` : `Show ${label}`}
          >
            <span className="swatch" style={{ background: color }} /> {label}
          </button>
        ))}
      </div>
      {ahead && (
        <p className="muted small">
          Dashed: where fitness, fatigue and form go if you follow your plan (planned TSS as hollow dots)
          {race ? `, up to ${race.race}` : ""}.
        </p>
      )}
    </>
  );
}
