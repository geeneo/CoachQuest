import { CalendarPlus, Download, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import WorkoutBuilder from "../components/WorkoutBuilder.jsx";
import WorkoutChart from "../components/WorkoutChart.jsx";
import { useApi } from "../hooks/useApi.js";
import { api, download } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { duration } from "../lib/format.js";
import { STARTERS, localToday } from "../lib/workout.js";

const BLANK = { name: "", description: "", instructions: "", steps: [] };

export default function Workouts() {
  const { user } = useAuth();
  const library = useApi("/api/workouts");
  const [editing, setEditing] = useState(null); // {id?, name, description, instructions, steps}
  const [scheduling, setScheduling] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const save = async (e) => {
    e.preventDefault();
    setError(null);
    const body = { ...editing };
    delete body.id;
    try {
      const saved = editing.id
        ? await api(`/api/workouts/${editing.id}`, { method: "PUT", body })
        : await api("/api/workouts", { method: "POST", body });
      setEditing(null);
      setNotice(`Saved "${saved.name}".`);
      library.reload();
    } catch (err) {
      setError(err.message);
    }
  };
  const remove = async (w) => {
    if (!window.confirm(`Delete "${w.name}" from your library? Workouts already on a calendar stay there.`)) return;
    await api(`/api/workouts/${w.id}`, { method: "DELETE" }).catch((err) => setError(err.message));
    library.reload();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Workouts</h1>
          <p className="muted small">
            Build structured bike workouts, keep them as templates, and put them on your own or an athlete's calendar.
            Download them as Zwift files (.zwo). Automatic sending to Zwift or MyWhoosh isn't available yet: see{" "}
            <Link to="/connections">Connected platforms</Link>.
          </p>
        </div>
        {!editing && (
          <button className="btn primary" onClick={() => setEditing({ ...BLANK, steps: [] })}>
            <Plus size={16} /> New workout
          </button>
        )}
      </div>
      {notice && <div className="ok small">{notice}</div>}
      {error && <div className="error">{error}</div>}

      {editing && (
        <form className="card" onSubmit={save}>
          <h2>{editing.id ? `Edit ${editing.name}` : "New workout"}</h2>
          {!editing.id && !editing.steps.length && (
            <div className="row wrap">
              <span className="muted small">Start from:</span>
              {STARTERS.map((s) => (
                <button type="button" key={s.name} className="btn small" onClick={() => setEditing({ ...s })}>
                  {s.name}
                </button>
              ))}
            </div>
          )}
          <WorkoutBuilder value={editing} onChange={setEditing} ftp={user.ftp_watts} />
          <div className="row">
            <button className="btn primary" disabled={!editing.name || !editing.steps.length}>
              Save to library
            </button>
            <button type="button" className="btn" onClick={() => setEditing(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {scheduling && (
        <ScheduleForm
          workout={scheduling}
          onDone={(msg) => {
            setScheduling(null);
            if (msg) setNotice(msg);
          }}
        />
      )}

      {library.loading && <p className="muted">Loading…</p>}
      {library.data && !library.data.length && !editing && (
        <div className="card muted">Your library is empty. Click "New workout" to build one, or start from an example.</div>
      )}
      <div className="workout-grid">
        {library.data?.map((w) => (
          <section key={w.id} className="card workout-card">
            <div className="row between">
              <h2>{w.name}</h2>
              <span className="muted small">
                {duration(w.estimate.duration_s)} · TSS {w.estimate.tss ?? "–"} · IF {w.estimate.intensity_factor ?? "–"}
              </span>
            </div>
            <WorkoutChart blocks={w.blocks} height={70} compact />
            {w.description && <p className="small">{w.description}</p>}
            <div className="row wrap">
              <button className="btn small primary" onClick={() => setScheduling(w)}>
                <CalendarPlus size={14} /> Schedule
              </button>
              <button className="btn small" onClick={() => setEditing({ ...w })}>
                Edit
              </button>
              <button
                className="btn small"
                onClick={() => download(`/api/workouts/${w.id}/zwo`).catch((err) => setError(err.message))}
              >
                <Download size={14} /> .zwo
              </button>
              <button className="btn small danger" onClick={() => remove(w)}>
                Delete
              </button>
            </div>
          </section>
        ))}
      </div>
    </>
  );
}

function ScheduleForm({ workout, onDone }) {
  const athletes = useApi("/api/athletes");
  const coachable = (athletes.data || []).filter((a) => a.scopes.includes("plans"));
  const [who, setWho] = useState("me");
  const [day, setDay] = useState(localToday());
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    try {
      await api(`/api/athletes/${who}/workouts`, { method: "POST", body: { day, template_id: workout.id } });
      const name = who === "me" ? "your" : `${coachable.find((a) => String(a.id) === who)?.display_name}'s`;
      onDone(`"${workout.name}" is on ${name} calendar for ${day}.`);
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <form className="card" onSubmit={submit}>
      <h2>Schedule {workout.name}</h2>
      <div className="grid-form">
        <label>
          For
          <select value={who} onChange={(e) => setWho(e.target.value)}>
            <option value="me">Me</option>
            {coachable.map((a) => (
              <option key={a.id} value={String(a.id)}>
                {a.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Day
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} required />
        </label>
      </div>
      <p className="muted small">
        Only athletes who share "Training plans" with you are listed. The athlete gets a copy: editing the template later
        doesn't change it.
      </p>
      {error && <div className="error">{error}</div>}
      <div className="row">
        <button className="btn primary">Schedule</button>
        <button type="button" className="btn" onClick={() => onDone(null)}>
          Cancel
        </button>
      </div>
    </form>
  );
}
