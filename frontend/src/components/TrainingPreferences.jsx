import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";

const DAYS = [
  ["mon", "Mon"],
  ["tue", "Tue"],
  ["wed", "Wed"],
  ["thu", "Thu"],
  ["fri", "Fri"],
  ["sat", "Sat"],
  ["sun", "Sun"],
];

export default function TrainingPreferences() {
  const res = useApi("/api/athletes/me/preferences");
  const [prefs, setPrefs] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    setPrefs(res.data);
  }, [res.data]);

  const save = async (body) => {
    setError(null);
    try {
      setPrefs(await api("/api/me/preferences", { method: "PUT", body }));
    } catch (err) {
      setError(err.message);
      res.reload();
    }
  };
  if (!prefs) return null;
  return (
    <>
      <WeekdayPrefs prefs={prefs} setPrefs={setPrefs} save={save} />
      <StrengthOptions prefs={prefs} save={save} />
      <NoteTags prefs={prefs} setPrefs={setPrefs} save={save} setError={setError} />
      {error && <div className="error">{error}</div>}
    </>
  );
}

function WeekdayPrefs({ prefs, setPrefs, save }) {
  const weekStart = useAuth().user.week_start || 0; // follows Profile at once, before prefs reload
  const max = prefs.max_per_day || 1;
  const [full, setFull] = useState(null); // the day that hit the limit, for the hint
  const toggle = (day, type) => {
    // Every type picked is a session that day; clicking a chosen type removes it.
    // Rest stands alone: picking it clears the others, picking another type clears Rest.
    const current = prefs.weekday_prefs[day];
    const others = current.filter((t) => t !== "Rest");
    let next;
    if (current.includes(type)) next = current.filter((t) => t !== type);
    else if (type === "Rest") next = ["Rest"];
    else if (max === 1) next = [type];
    else if (others.length >= max) return setFull(day);
    else next = [...others, type];
    setFull(null);
    const weekday_prefs = { ...prefs.weekday_prefs, [day]: next };
    setPrefs({ ...prefs, weekday_prefs });
    save({ weekday_prefs });
  };
  return (
    <section className="card">
      <h2>Weekday preferences</h2>
      <p className="muted small">
        {max > 1
          ? `What you do on each day of the week: pick up to ${max} types a day, e.g. Zwift / indoor + Strength. The AI coach plans every one of them that day, as separate sessions. `
          : "What you do on each day of the week: pick one type per day. The AI coach plans that type on that day. "}
        Click a type again to remove it. Rest clears the day's other types and stays free. Saved as you click.
      </p>
      <div className="weekday-grid">
        {[...DAYS.slice(weekStart), ...DAYS.slice(0, weekStart)].map(([day, label]) => (
          <div key={day} className="weekday-row">
            <span className="weekday-label">{label}</span>
            <div className="chips" role="group" aria-label={label}>
              {prefs.session_types.map((type) => {
                const on = prefs.weekday_prefs[day].includes(type);
                return (
                  <button
                    key={type}
                    type="button"
                    aria-pressed={on}
                    className={`chip ${on ? "on" : ""}`}
                    onClick={() => toggle(day, type)}
                  >
                    {type}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      {full && (
        <p className="hint">
          {full.charAt(0).toUpperCase() + full.slice(1)} already has {max} sessions, the most a day can have. Remove one
          first.
        </p>
      )}
    </section>
  );
}

function NoteTags({ prefs, setPrefs, save, setError }) {
  const [newTag, setNewTag] = useState("");
  const [editing, setEditing] = useState(null);
  const add = (e) => {
    e.preventDefault();
    if (!newTag.trim()) return;
    save({ note_tags: [...prefs.note_tags, newTag] });
    setNewTag("");
  };
  const remove = (tag) => save({ note_tags: prefs.note_tags.filter((t) => t !== tag) });
  const rename = async (old, value) => {
    setEditing(null);
    if (!value.trim() || value.trim().toLowerCase() === old) return;
    try {
      setPrefs(await api("/api/me/note-tags/rename", { method: "POST", body: { old, new: value } }));
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <section className="card">
      <h2>Activity note tags</h2>
      <p className="muted small">
        Reasons you can put on an activity (illness, mechanical, travel, group ride…). The AI coach reads a light week
        marked "illness" as explained, not as a gap to make up. Click a tag to rename it; renaming updates activities
        already tagged.
      </p>
      <div className="chips">
        {prefs.note_tags.map((tag) =>
          editing === tag ? (
            <input
              key={tag}
              className="tag-edit"
              defaultValue={tag}
              autoFocus
              onBlur={(e) => rename(tag, e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
                if (e.key === "Escape") setEditing(null);
              }}
            />
          ) : (
            <span key={tag} className="chip on tag">
              <button type="button" className="tag-name" onClick={() => setEditing(tag)} title="Rename">
                {tag}
              </button>
              <button type="button" className="tag-x" aria-label={`Remove ${tag}`} onClick={() => remove(tag)}>
                <X size={12} />
              </button>
            </span>
          ),
        )}
      </div>
      <form className="row" onSubmit={add} style={{ marginTop: "0.75rem" }}>
        <input
          placeholder="add new tag (e.g. work-trip)"
          value={newTag}
          onChange={(e) => setNewTag(e.target.value)}
          maxLength={30}
          style={{ maxWidth: 240 }}
        />
        <button className="btn primary">+ Add</button>
      </form>
    </section>
  );
}

// Strength options for the AI coach (backend strength.py): equipment, level, sports, how much.
function StrengthOptions({ prefs, save }) {
  const [form, setForm] = useState(prefs.strength);
  const [saved, setSaved] = useState(false);
  const opts = prefs.strength_options;
  const toggle = (key, value) =>
    setForm({
      ...form,
      [key]: form[key].includes(value) ? form[key].filter((x) => x !== value) : [...form[key], value],
    });
  const submit = async (e) => {
    e.preventDefault();
    await save({ strength: { ...form, sessions_per_week: Number(form.sessions_per_week), minutes: Number(form.minutes) } });
    setSaved(true);
  };
  const chips = (key, values) => (
    <div className="chips">
      {values.map((v) => (
        <button
          key={v}
          type="button"
          aria-pressed={form[key].includes(v)}
          className={`chip ${form[key].includes(v) ? "on" : ""}`}
          onClick={() => (toggle(key, v), setSaved(false))}
        >
          {v}
        </button>
      ))}
    </div>
  );
  return (
    <section className="card">
      <h2>Strength training</h2>
      <p className="muted small">
        On your Strength days the AI coach writes a strength session for cycling and running: exercises with sets,
        reps, effort and rest, heavier in base and build, lighter in race season. It only picks exercises you can do
        with this equipment.
      </p>
      <form className="stack" onSubmit={submit} onChange={() => setSaved(false)}>
        <div>
          <span className="small strong-label">Equipment I have</span>
          {chips("equipment", opts.equipment)}
        </div>
        <div>
          <span className="small strong-label">For</span>
          {chips("sports", opts.sports)}
        </div>
        <div className="row wrap">
          <label className="inline">
            Level
            <select value={form.level} onChange={(e) => setForm({ ...form, level: e.target.value })}>
              {opts.levels.map((l) => (
                <option key={l}>{l}</option>
              ))}
            </select>
          </label>
          <label className="inline">
            Sessions a week
            <select
              value={form.sessions_per_week}
              onChange={(e) => setForm({ ...form, sessions_per_week: e.target.value })}
            >
              {[0, 1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>
                  {n === 0 ? "coach decides" : n}
                </option>
              ))}
            </select>
          </label>
          <label className="inline">
            Minutes each
            <input
              type="number"
              min={15}
              max={120}
              step={5}
              value={form.minutes}
              onChange={(e) => setForm({ ...form, minutes: e.target.value })}
            />
          </label>
        </div>
        <label>
          Limits (injuries, exercises to avoid)
          <input
            value={form.limits}
            maxLength={300}
            placeholder="e.g. left knee: no deep squats or jumps"
            onChange={(e) => setForm({ ...form, limits: e.target.value })}
          />
        </label>
        <div className="row">
          <button className="btn primary">Save strength options</button>
          {saved && <span className="ok-text small">Saved. Used the next time the AI coach plans.</span>}
        </div>
      </form>
    </section>
  );
}
