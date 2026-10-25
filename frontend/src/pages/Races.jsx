import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";

// Click a field, change it, click away: it saves. Empty number fields clear the value.
const FIELDS = [
  ["name", "Name", "text", "wide-cell"],
  ["short_name", "Short", "text", "short-cell"],
  ["distance_km", "Dist (km)", "number", "num-cell"],
  ["elevation_m", "Elev (m)", "number", "num-cell"],
  ["discipline", "Discipline", "select", ""],
  ["target_date", "Date", "date", ""],
  ["start_time", "Start", "time", ""],
  ["target_ctl", "Target CTL", "number", "num-cell"],
  ["days", "Days", "number", "num-cell"],
];

function toBody(field, raw) {
  if (["distance_km", "elevation_m", "target_ctl", "days"].includes(field)) return raw === "" ? null : Number(raw);
  return raw === "" ? null : raw;
}

export default function Races() {
  const races = useApi("/api/athletes/me/races");
  const disciplines = useApi("/api/races/disciplines");
  const [error, setError] = useState(null);

  const save = (race, field, raw) => {
    const value = toBody(field, raw);
    if ((race[field] ?? null) === value) return;
    setError(null);
    api(`/api/races/${race.id}`, { method: "PATCH", body: { [field]: value } }).then(races.reload, (e) =>
      setError(e.message),
    );
  };
  const remove = (race) =>
    confirm(`Delete ${race.name}?`) &&
    api(`/api/races/${race.id}`, { method: "DELETE" }).then(races.reload, (e) => setError(e.message));

  return (
    <>
      <h1>Races</h1>
      <p className="muted">
        Events you're training for. They show as a countdown on My training, can be linked to activities, and the AI
        coach plans toward the active ones (date and target CTL). Click a field and click away to save.
      </p>
      {error && <div className="error">{error}</div>}
      <section className="card">
        <div className="table-wrap">
          <table className="edit-table">
            <thead>
              <tr>
                <th>Code</th>
                {FIELDS.map(([f, label]) => (
                  <th key={f}>{label}</th>
                ))}
                <th>Active</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {races.data?.map((r) => (
                <tr key={r.id} className={r.days_to_go != null && r.days_to_go < 0 ? "past" : ""}>
                  <td className="muted">{r.code}</td>
                  {FIELDS.map(([f, label, type, cls]) => (
                    <td key={f} className={cls}>
                      <Cell race={r} field={f} label={label} type={type} options={disciplines.data} save={save} />
                    </td>
                  ))}
                  <td>
                    <input
                      type="checkbox"
                      aria-label="Active"
                      checked={r.active}
                      onChange={(e) => save(r, "active", e.target.checked)}
                    />
                  </td>
                  <td>
                    <button className="icon-btn" aria-label={`Delete ${r.name}`} onClick={() => remove(r)}>
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {races.data?.length === 0 && <p className="muted">No races yet. Add your first one below.</p>}
        <AddRace disciplines={disciplines.data || []} onAdded={races.reload} />
      </section>
    </>
  );
}

function Cell({ race, field, label, type, options, save }) {
  const value = race[field] ?? "";
  if (type === "select") {
    return (
      <select aria-label={label} value={value} onChange={(e) => save(race, field, e.target.value)}>
        <option value="">— not set</option>
        {(options || []).map((d) => (
          <option key={d}>{d}</option>
        ))}
      </select>
    );
  }
  return (
    <input
      aria-label={label}
      type={type}
      defaultValue={value}
      key={`${race.id}-${field}-${value}`}
      min={type === "number" ? 0 : undefined}
      onBlur={(e) => save(race, field, e.target.value)}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
    />
  );
}

function AddRace({ disciplines, onAdded }) {
  const empty = { code: "", name: "", short_name: "", distance_km: "", elevation_m: "", discipline: "", target_date: "", start_time: "", target_ctl: "", days: "1" };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    const body = Object.fromEntries(
      Object.entries(form)
        .filter(([, v]) => v !== "")
        .map(([k, v]) => [k, toBody(k, v)]),
    );
    try {
      await api("/api/races", { method: "POST", body });
      setForm(empty);
      onAdded();
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <form className="add-race" onSubmit={submit}>
      <h3>Add a race</h3>
      <div className="row">
        <input placeholder="code (e.g. k2c)" value={form.code} onChange={set("code")} required size={10} />
        <input placeholder="Full name" value={form.name} onChange={set("name")} required />
        <input placeholder="Short (e.g. K2C)" value={form.short_name} onChange={set("short_name")} size={8} />
        <input type="number" min={0} placeholder="Dist km" value={form.distance_km} onChange={set("distance_km")} />
        <input type="number" min={0} placeholder="Elev m" value={form.elevation_m} onChange={set("elevation_m")} />
        <select value={form.discipline} onChange={set("discipline")}>
          <option value="">— discipline</option>
          {disciplines.map((d) => (
            <option key={d}>{d}</option>
          ))}
        </select>
        <input type="date" value={form.target_date} onChange={set("target_date")} aria-label="Date" />
        <input type="time" value={form.start_time} onChange={set("start_time")} aria-label="Start time" />
        <input type="number" min={0} placeholder="Target CTL" value={form.target_ctl} onChange={set("target_ctl")} />
        <input type="number" min={1} placeholder="Days" value={form.days} onChange={set("days")} aria-label="Days" />
        <button className="btn primary">+ Add race</button>
      </div>
      {error && <div className="error">{error}</div>}
    </form>
  );
}
