import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { shortDate } from "../lib/format.js";

export default function FitnessChart({ data }) {
  if (!data?.length) return <p className="muted">No training load yet.</p>;
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="day" tickFormatter={shortDate} minTickGap={32} stroke="var(--muted)" fontSize={12} />
          <YAxis stroke="var(--muted)" fontSize={12} />
          <Tooltip
            contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8 }}
            labelFormatter={shortDate}
          />
          <Legend />
          <Area dataKey="tsb" name="Form (TSB)" fill="var(--c3)" stroke="var(--c3)" fillOpacity={0.15} />
          <Line dataKey="ctl" name="Fitness (CTL)" stroke="var(--c1)" dot={false} strokeWidth={2} />
          <Line dataKey="atl" name="Fatigue (ATL)" stroke="var(--c2)" dot={false} strokeWidth={1.5} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
