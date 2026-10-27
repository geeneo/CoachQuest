import { CalendarPlus, Download, Save } from "lucide-react";
import { useMemo, useState } from "react";
import WorkoutChart from "./WorkoutChart.jsx";
import { useApi } from "../hooks/useApi.js";
import { api, download } from "../lib/api.js";
import { duration } from "../lib/format.js";

const LENGTHS = {
  all: ["Any length", () => true],
  short: ["45 min or less", (s) => s <= 2700],
  mid: ["45–75 min", (s) => s > 2700 && s <= 4500],
  long: ["Over 75 min", (s) => s > 4500],
};

// CoachQuest's own workouts, open to everyone: browse by collection, search, then schedule, save a copy or download.
export default function WorkoutLibrary({ onSchedule, onSaved, onError }) {
  const lib = useApi("/api/library");
  const [collection, setCollection] = useState("all");
  const [length, setLength] = useState("all");
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const shown = useMemo(
    () =>
      (lib.data?.workouts || []).filter(
        (w) =>
          (collection === "all" || w.collection === collection) &&
          LENGTHS[length][1](w.estimate.duration_s) &&
          (!needle || `${w.name} ${w.description} ${w.collection_name}`.toLowerCase().includes(needle)),
      ),
    [lib.data, collection, length, needle],
  );
  if (lib.loading) return <p className="muted">Loading…</p>;
  if (lib.error) return <div className="error">{lib.error.message}</div>;
  const collections = lib.data.collections;
  const groups = collections
    .map((c) => ({ ...c, items: shown.filter((w) => w.collection === c.key) }))
    .filter((g) => g.items.length);

  // Schedule and Save need the steps, which the list leaves out.
  const full = (w) => api(`/api/library/${w.slug}`);
  const save = async (w) => {
    try {
      const d = await full(w);
      const body = { name: d.name, description: d.description, instructions: d.instructions, steps: d.steps };
      await api("/api/workouts", { method: "POST", body });
      onSaved(`"${d.name}" is in My workouts: change it there as you like.`);
    } catch (err) {
      onError(err.message);
    }
  };
  const schedule = async (w) => {
    try {
      onSchedule(await full(w));
    } catch (err) {
      onError(err.message);
    }
  };

  return (
    <>
      <p className="muted small">
        {lib.data.workouts.length} workouts written for CoachQuest, set as a share of FTP so they fit you (the watts,
        TSS and IF use your FTP from Profile). Put one on your calendar, save a copy to change it, or download the .zwo:
        Zwift takes it in its custom workouts folder, MyWhoosh in its Workout Builder (Upload).
      </p>
      <div className="chips">
        <button type="button" className={`chip ${collection === "all" ? "on" : ""}`} onClick={() => setCollection("all")}>
          All
        </button>
        {collections.map((c) => (
          <button
            key={c.key}
            type="button"
            className={`chip ${collection === c.key ? "on" : ""}`}
            onClick={() => setCollection(c.key)}
            title={c.description}
          >
            {c.name}
          </button>
        ))}
      </div>
      <div className="row wrap dash-controls">
        <input type="search" placeholder="Search workouts…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={length} onChange={(e) => setLength(e.target.value)}>
          {Object.entries(LENGTHS).map(([k, [label]]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <span className="muted small">{shown.length} shown</span>
      </div>
      {groups.map((g) => (
        <section key={g.key} className="library-group">
          <h2>{g.name}</h2>
          <p className="muted small">{g.description}</p>
          <div className="workout-grid">
            {g.items.map((w) => (
              <section key={w.slug} className="card workout-card">
                <div className="row between">
                  <h3>{w.name}</h3>
                  <span className="muted small nowrap">
                    {duration(w.estimate.duration_s)} · TSS {w.estimate.tss ?? "–"} · IF{" "}
                    {w.estimate.intensity_factor ?? "–"}
                  </span>
                </div>
                <WorkoutChart blocks={w.blocks} height={70} compact />
                <p className="small">{w.description}</p>
                <details className="small">
                  <summary>How to ride it</summary>
                  <p>{w.instructions}</p>
                </details>
                <div className="row wrap">
                  <button className="btn small primary" onClick={() => schedule(w)}>
                    <CalendarPlus size={14} /> Schedule
                  </button>
                  <button className="btn small" onClick={() => save(w)} title="Copy it to My workouts to change it">
                    <Save size={14} /> Save to my workouts
                  </button>
                  <button
                    className="btn small"
                    onClick={() => download(`/api/library/${w.slug}/zwo`).catch((err) => onError(err.message))}
                  >
                    <Download size={14} /> .zwo
                  </button>
                </div>
              </section>
            ))}
          </div>
        </section>
      ))}
      {!groups.length && <p className="muted">No workouts match.</p>}
    </>
  );
}
