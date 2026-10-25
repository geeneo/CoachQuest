import { ArrowDown, ArrowUp, Copy, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { duration } from "../lib/format.js";
import { KIND_LABEL, STEP_KINDS, fmtDur, newStep, parseDur, pct, watts } from "../lib/workout.js";
import WorkoutChart from "./WorkoutChart.jsx";

// Edits {name, description, instructions, steps}. The chart and TSS / IF come from
// the API's preview, so the numbers match what is saved and exported.
export default function WorkoutBuilder({ value, onChange, ftp }) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const steps = value.steps;

  useEffect(() => {
    if (!steps.length) {
      setPreview(null);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        setPreview(await api("/api/workouts/preview", { method: "POST", body: { steps, ftp: ftp || undefined } }));
        setError(null);
      } catch (err) {
        setError(err.message);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [steps, ftp]);

  const set = (k) => (e) => onChange({ ...value, [k]: e.target.value });
  const setSteps = (next) => onChange({ ...value, steps: next });
  const editStep = (i, changes) => setSteps(steps.map((s, j) => (j === i ? { ...s, ...changes } : s)));
  const move = (i, by) => {
    const next = [...steps];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    setSteps(next);
  };
  const est = preview?.estimate;
  const shownFtp = preview?.ftp;

  return (
    <div className="builder">
      <div className="grid-form">
        <label className="wide">
          Name
          <input value={value.name} maxLength={120} onChange={set("name")} required />
        </label>
        <label className="wide">
          Description
          <textarea rows={2} value={value.description} maxLength={2000} onChange={set("description")} />
        </label>
        <label className="wide">
          Coach instructions
          <textarea
            rows={2}
            value={value.instructions}
            maxLength={2000}
            onChange={set("instructions")}
            placeholder="Cues for the athlete: cadence, position, how it should feel"
          />
        </label>
      </div>

      <WorkoutChart blocks={preview?.blocks} ftp={shownFtp} />
      <div className="stats compact">
        <Mini label="Duration" value={est ? duration(est.duration_s) : "–"} />
        <Mini label="TSS (est.)" value={est?.tss ?? "–"} />
        <Mini label="IF (est.)" value={est?.intensity_factor ?? "–"} />
        <Mini label="Avg power" value={est?.avg_watts ? `${est.avg_watts} W` : est ? `${pct(est.avg_power)}%` : "–"} />
      </div>
      <p className="muted small">
        Power is a percentage of FTP, so the workout fits any rider.
        {shownFtp ? ` Watts are shown for an FTP of ${shownFtp} W.` : " Set your FTP in Profile to see watts."}
        {est?.free_ride_s ? ` Free-ride time (${fmtDur(est.free_ride_s)}) has no target and isn't counted in TSS.` : ""}
      </p>
      {error && <div className="error">{error}</div>}

      <ol className="steps">
        {steps.map((s, i) => (
          <li key={i} className="step-row">
            <span className="step-kind">{KIND_LABEL[s.kind]}</span>
            <StepFields step={s} ftp={shownFtp} onChange={(c) => editStep(i, c)} />
            <span className="step-actions">
              <button type="button" className="icon-btn" title="Move up" disabled={!i} onClick={() => move(i, -1)}>
                <ArrowUp size={15} />
              </button>
              <button
                type="button"
                className="icon-btn"
                title="Move down"
                disabled={i === steps.length - 1}
                onClick={() => move(i, 1)}
              >
                <ArrowDown size={15} />
              </button>
              <button
                type="button"
                className="icon-btn"
                title="Duplicate"
                onClick={() => setSteps([...steps.slice(0, i + 1), { ...s }, ...steps.slice(i + 1)])}
              >
                <Copy size={15} />
              </button>
              <button
                type="button"
                className="icon-btn"
                title="Remove"
                onClick={() => setSteps(steps.filter((_, j) => j !== i))}
              >
                <Trash2 size={15} />
              </button>
            </span>
          </li>
        ))}
      </ol>
      <div className="row wrap">
        <span className="muted small">Add:</span>
        {STEP_KINDS.map(({ kind, label }) => (
          <button type="button" key={kind} className="btn small" onClick={() => setSteps([...steps, newStep(kind)])}>
            + {label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Mini({ label, value }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}

function StepFields({ step, ftp, onChange }) {
  const k = step.kind;
  if (k === "intervals") {
    return (
      <span className="step-fields">
        <Num label="×" value={step.repeat} min={1} max={50} onChange={(v) => onChange({ repeat: v })} />
        <Dur label="on" value={step.on_s} onChange={(v) => onChange({ on_s: v })} />
        <Pct value={step.on_power} ftp={ftp} onChange={(v) => onChange({ on_power: v })} />
        <Dur label="off" value={step.off_s} onChange={(v) => onChange({ off_s: v })} />
        <Pct value={step.off_power} ftp={ftp} onChange={(v) => onChange({ off_power: v })} />
        <Cad value={step.cadence} onChange={(v) => onChange({ cadence: v })} />
      </span>
    );
  }
  return (
    <span className="step-fields">
      <Dur value={step.duration_s} onChange={(v) => onChange({ duration_s: v })} />
      {(k === "steady" || k === "recovery") && (
        <Pct value={step.power} ftp={ftp} onChange={(v) => onChange({ power: v })} />
      )}
      {(k === "warmup" || k === "cooldown" || k === "ramp") && (
        <>
          <Pct label="from" value={step.power_start} ftp={ftp} onChange={(v) => onChange({ power_start: v })} />
          <Pct label="to" value={step.power_end} ftp={ftp} onChange={(v) => onChange({ power_end: v })} />
        </>
      )}
      {k !== "free" && <Cad value={step.cadence} onChange={(v) => onChange({ cadence: v })} />}
      <input
        className="step-text"
        placeholder="On-screen cue (optional)"
        maxLength={200}
        value={step.text || ""}
        onChange={(e) => onChange({ text: e.target.value || undefined })}
      />
    </span>
  );
}

function Dur({ label, value, onChange }) {
  const [text, setText] = useState(fmtDur(value));
  useEffect(() => setText(fmtDur(value)), [value]);
  return (
    <label className="inline">
      {label}
      <input
        className="dur"
        value={text}
        title="Minutes:seconds, e.g. 5:00 or 0:30. A plain number is minutes."
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          const s = parseDur(text);
          if (s) onChange(s);
          else setText(fmtDur(value));
        }}
      />
    </label>
  );
}

function Pct({ label, value, ftp, onChange }) {
  return (
    <label className="inline">
      {label}
      <input
        type="number"
        className="pct"
        min={20}
        max={300}
        value={pct(value)}
        onChange={(e) => e.target.value && onChange(Number(e.target.value) / 100)}
      />
      %{ftp ? <span className="muted"> {watts(value, ftp)} W</span> : null}
    </label>
  );
}

function Num({ label, value, min, max, onChange }) {
  return (
    <label className="inline">
      {label}
      <input
        type="number"
        className="num"
        min={min}
        max={max}
        value={value}
        onChange={(e) => e.target.value && onChange(Number(e.target.value))}
      />
    </label>
  );
}

function Cad({ value, onChange }) {
  return (
    <label className="inline">
      <input
        type="number"
        className="num"
        min={30}
        max={150}
        placeholder="rpm"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : undefined)}
      />
      rpm
    </label>
  );
}
