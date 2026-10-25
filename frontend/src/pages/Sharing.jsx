import { Check, X } from "lucide-react";
import { useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { SCOPE_LABELS, dateTime } from "../lib/format.js";

export default function Sharing() {
  const grants = useApi("/api/grants");
  const log = useApi("/api/grants/access-log");
  const scopes = grants.data?.scopes || Object.keys(SCOPE_LABELS);

  return (
    <>
      <h1>Sharing</h1>
      <p className="muted">
        You decide which coach sees what. Changes and revocations take effect on their next page load.
      </p>
      {grants.error && <div className="error">{grants.error.message}</div>}
      <AddCoach scopes={scopes} onDone={grants.reload} />
      <section className="card">
        <h2>My coaches</h2>
        {grants.data?.given.length ? (
          grants.data.given.map((g) => <GivenGrant key={g.id} grant={g} scopes={scopes} reload={grants.reload} />)
        ) : (
          <p className="muted">You are not sharing with anyone.</p>
        )}
      </section>
      <section className="card">
        <h2>Athletes who invited me as coach</h2>
        {grants.data?.received.length ? (
          <ul className="list">
            {grants.data.received.map((g) => (
              <ReceivedGrant key={g.id} grant={g} reload={grants.reload} />
            ))}
          </ul>
        ) : (
          <p className="muted">No invitations.</p>
        )}
      </section>
      <section className="card">
        <h2>Who looked at my data</h2>
        {log.data?.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Who</th>
                  <th>What</th>
                </tr>
              </thead>
              <tbody>
                {log.data.map((r, i) => (
                  <tr key={i}>
                    <td>{dateTime(r.at)}</td>
                    <td>{r.viewer}</td>
                    <td>{r.resource}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">Nobody else has opened your data.</p>
        )}
      </section>
    </>
  );
}

function ScopePicker({ scopes, value, onChange }) {
  const toggle = (s) => onChange(value.includes(s) ? value.filter((x) => x !== s) : [...value, s]);
  return (
    <div className="stack tight">
      {scopes.map((s) => (
        <label key={s} className="check">
          <input type="checkbox" checked={value.includes(s)} onChange={() => toggle(s)} /> {SCOPE_LABELS[s] || s}
        </label>
      ))}
    </div>
  );
}

function AddCoach({ scopes, onDone }) {
  const [email, setEmail] = useState("");
  const [picked, setPicked] = useState(["activities", "fitness"]);
  const [error, setError] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      await api("/api/grants", { method: "POST", body: { coach_email: email, scopes: picked } });
      setEmail("");
      onDone();
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <section className="card">
      <h2>Share with a coach</h2>
      <form className="stack" onSubmit={submit}>
        <label>
          Coach's email (they need a CoachQuest account; we email them the invitation)
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <ScopePicker scopes={scopes} value={picked} onChange={setPicked} />
        {error && <div className="error">{error}</div>}
        <button className="btn primary" disabled={!picked.length}>
          Send invitation
        </button>
      </form>
    </section>
  );
}

function GivenGrant({ grant, scopes, reload }) {
  const [picked, setPicked] = useState(grant.scopes);
  const [error, setError] = useState(null);
  const dirty = picked.slice().sort().join() !== grant.scopes.slice().sort().join();
  const save = () =>
    api(`/api/grants/${grant.id}`, { method: "PATCH", body: { scopes: picked } }).then(reload, (e) => setError(e.message));
  const revoke = () => {
    if (confirm(`Stop sharing with ${grant.coach.display_name}?`))
      api(`/api/grants/${grant.id}`, { method: "DELETE" }).then(reload, (e) => setError(e.message));
  };
  return (
    <div className="grant">
      <div className="row between">
        <div>
          <strong>{grant.coach.display_name}</strong> <span className="muted small">{grant.coach.email}</span>{" "}
          <span className={`badge ${grant.status === "active" ? "ok" : ""}`}>
            {grant.status === "pending" ? "waiting for coach" : grant.status}
          </span>
        </div>
        <button className="btn danger" onClick={revoke}>
          Stop sharing
        </button>
      </div>
      <ScopePicker scopes={scopes} value={picked} onChange={setPicked} />
      {dirty && (
        <button className="btn" disabled={!picked.length} onClick={save}>
          Save changes
        </button>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  );
}

function ReceivedGrant({ grant, reload }) {
  const act = (method, path = "") => api(`/api/grants/${grant.id}${path}`, { method }).then(reload, (e) => alert(e.message));
  return (
    <li>
      <span>
        <strong>{grant.athlete.display_name}</strong> shares {grant.scopes.join(", ")}
      </span>
      {grant.status === "pending" ? (
        <span className="row">
          <button className="btn primary" onClick={() => act("POST", "/accept")}>
            <Check size={16} /> Accept
          </button>
          <button className="btn" onClick={() => act("DELETE")}>
            <X size={16} /> Decline
          </button>
        </span>
      ) : (
        <button className="btn" onClick={() => confirm("Stop coaching this athlete?") && act("DELETE")}>
          Leave
        </button>
      )}
    </li>
  );
}
