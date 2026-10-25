import { useEffect, useRef, useState } from "react";
import { KIND_LABEL, fmtDur, pct, watts, zone } from "../lib/workout.js";

// Workout profile: time across, target power up. One hue, darker for harder zones;
// height carries the same information, so colour is never the only cue.
const SHADE = { Z1: 35, Z2: 50, Z3: 65, Z4: 80, Z5: 92, Z6: 100 };
const PAD = { top: 10, right: 8, bottom: 22, left: 34 };

export default function WorkoutChart({ blocks, ftp, height = 140, compact = false }) {
  const ref = useRef(null);
  const [width, setWidth] = useState(600);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(200, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  if (!blocks?.length) return <div ref={ref} className="workout-chart empty muted small">No steps yet</div>;

  const pad = compact ? { top: 4, right: 2, bottom: 2, left: 2 } : PAD;
  const total = blocks.reduce((s, b) => s + b.duration_s, 0);
  const maxP = Math.max(1.2, ...blocks.map((b) => Math.max(b.power_start ?? 0, b.power_end ?? 0))) * 1.05;
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;
  const x = (s) => pad.left + (s / total) * w;
  const y = (p) => pad.top + h - (p / maxP) * h;
  const base = pad.top + h;
  const ticks = minuteTicks(total);

  return (
    <div ref={ref} className="workout-chart" onMouseLeave={() => setHover(null)}>
      <svg width={width} height={height} role="img" aria-label={`Workout profile, ${fmtDur(total)}`}>
        {!compact &&
          [0.5, 1, 1.5].filter((p) => p < maxP).map((p) => (
            <g key={p}>
              <line x1={pad.left} x2={width - pad.right} y1={y(p)} y2={y(p)} className={p === 1 ? "ftp-line" : "grid-line"} />
              <text x={pad.left - 4} y={y(p) + 4} textAnchor="end" className="axis-text">
                {p === 1 ? "FTP" : `${p * 100}%`}
              </text>
            </g>
          ))}
        {blocks.map((b, i) => {
          const x0 = x(b.start_s);
          const x1 = x(b.start_s + b.duration_s);
          const gap = Math.min(2, (x1 - x0) * 0.25);
          const free = b.power_start == null;
          const p0 = free ? 0.5 : b.power_start;
          const p1 = free ? 0.5 : b.power_end;
          const shade = free ? 0 : SHADE[zone((p0 + p1) / 2)];
          const d = shape(x0 + gap / 2, x1 - gap / 2, y(p0), y(p1), base);
          return (
            <g key={i} onMouseEnter={() => setHover({ b, x: (x0 + x1) / 2 })}>
              <path
                d={d}
                className={free ? "block free" : "block"}
                style={free ? undefined : { fill: `color-mix(in srgb, var(--c1) ${shade}%, var(--panel))` }}
                opacity={hover && hover.b !== b ? 0.75 : 1}
              />
              {/* Wider invisible hit area so short intervals are easy to hover. */}
              <rect x={x0} y={pad.top} width={Math.max(6, x1 - x0)} height={h} fill="transparent" />
            </g>
          );
        })}
        <line x1={pad.left} x2={width - pad.right} y1={base} y2={base} className="axis-line" />
        {!compact &&
          ticks.map((t) => (
            <text key={t} x={x(t)} y={height - 6} textAnchor="middle" className="axis-text">
              {Math.round(t / 60)}′
            </text>
          ))}
      </svg>
      {hover && !compact && <Tip hover={hover} ftp={ftp} width={width} />}
    </div>
  );
}

function shape(x0, x1, yStart, yEnd, base) {
  const r = Math.min(3, (x1 - x0) / 2, base - Math.min(yStart, yEnd));
  if (yStart === yEnd) {
    return `M${x0},${base} V${yStart + r} Q${x0},${yStart} ${x0 + r},${yStart} H${x1 - r} Q${x1},${yStart} ${x1},${yStart + r} V${base} Z`;
  }
  return `M${x0},${base} L${x0},${yStart} L${x1},${yEnd} L${x1},${base} Z`;
}

function minuteTicks(total) {
  const step = [300, 600, 900, 1800, 3600].find((s) => total / s <= 8) || 3600;
  const out = [];
  for (let t = step; t < total; t += step) out.push(t);
  return out;
}

function Tip({ hover, ftp, width }) {
  const { b } = hover;
  const label = b.kind === "on" ? "Interval (on)" : b.kind === "off" ? "Interval (off)" : KIND_LABEL[b.kind];
  const power =
    b.power_start == null
      ? "No target"
      : b.power_start === b.power_end
        ? `${pct(b.power_start)}% FTP${ftp ? ` · ${watts(b.power_start, ftp)} W` : ""} · ${zone(b.power_start)}`
        : `${pct(b.power_start)}→${pct(b.power_end)}% FTP${
            ftp ? ` · ${watts(b.power_start, ftp)}→${watts(b.power_end, ftp)} W` : ""
          }`;
  const left = Math.min(Math.max(hover.x, 90), width - 90);
  return (
    <div className="chart-tip" style={{ left }}>
      <strong>{label}</strong> · {fmtDur(b.duration_s)}
      <div>{power}</div>
      {b.cadence && <div>{b.cadence} rpm</div>}
    </div>
  );
}
