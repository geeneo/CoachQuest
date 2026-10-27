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
