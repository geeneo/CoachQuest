import { RefreshCw, Unlink } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { dateTime } from "../lib/format.js";

const ERRORS = {
  state: "The Strava link expired or did not match your session. Try again.",
  denied: "Strava access was not granted.",
  strava: "Strava did not accept the link. Check that activity access is ticked.",
};

export default function Connections() {
  const conns = useApi("/api/connections");
  const [params] = useSearchParams();
  const byProvider = Object.fromEntries((conns.data?.connections || []).map((c) => [c.provider, c]));

  return (
    <>
      <h1>Connections</h1>
      <p className="muted">
        Link your accounts so CoachQuest can import your training. Nothing is shared with anyone until you add them on the{" "}
        <Link to="/sharing">Sharing</Link> page.
      </p>
      {params.get("connected") && <div className="ok">Strava connected. Your first sync is running.</div>}
      {params.get("error") && <div className="error">{ERRORS[params.get("error")] || "Linking failed."}</div>}
      {conns.error && <div className="error">{conns.error.message}</div>}
      <StravaCard conn={byProvider.strava} configured={conns.data?.strava_configured} reload={conns.reload} />
      <GarminCard conn={byProvider.garmin} reload={conns.reload} />
    </>
  );
}

function Status({ conn, provider, reload }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const run = async (fn) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      reload();
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy(false);
    }
  };
  const sync = () => run(() => api(`/api/connections/${provider}/sync`, { method: "POST" }));
  const unlink = () => {
    if (!confirm(`Disconnect ${provider}?`)) return;
    const purge =
      provider === "strava" || confirm("Also delete the Garmin data already imported? Cancel keeps it.");
    run(() => api(`/api/connections/${provider}?purge=${purge}`, { method: "DELETE" }));
  };
  return (
    <>
      <p className="small">
        <span className={`badge ${conn.status === "active" ? "ok" : "bad"}`}>{conn.status}</span> Last sync:{" "}
        {dateTime(conn.last_sync_at)}
      </p>
      {conn.last_error && <p className="error small">{conn.last_error}</p>}
      {msg && <p className="error small">{msg}</p>}
      <div className="row">
        <button className="btn" disabled={busy} onClick={sync}>
          <RefreshCw size={16} /> Sync now
        </button>
        <button className="btn danger" disabled={busy} onClick={unlink}>
          <Unlink size={16} /> Disconnect
        </button>
      </div>
      {provider === "strava" && (
        <p className="hint">Disconnecting Strava also deletes the Strava activities imported here.</p>
      )}
    </>
  );
}

function StravaCard({ conn, configured, reload }) {
  const [error, setError] = useState(null);
  const connect = async () => {
    try {
      const { url } = await api("/api/connections/strava/authorize", { method: "POST" });
      window.location.assign(url);
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <section className="card">
      <h2>Strava</h2>
      <p className="muted small">Activities: rides, runs, swims, with power and heart rate. Synced every 6 hours.</p>
      {conn ? (
        <Status conn={conn} provider="strava" reload={reload} />
      ) : configured ? (
        <button className="btn strava" onClick={connect}>
          Connect with Strava
        </button>
      ) : (
        <p className="muted">Strava is not configured on this server yet.</p>
      )}
      {error && <div className="error">{error}</div>}
    </section>
  );
}

function GarminCard({ conn, reload }) {
  const [form, setForm] = useState({ email: "", password: "", code: "" });
  const [step, setStep] = useState("login");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res =
        step === "login"
          ? await api("/api/connections/garmin", { method: "POST", body: { email: form.email, password: form.password } })
          : await api("/api/connections/garmin/mfa", { method: "POST", body: { code: form.code } });
      setForm({ email: "", password: "", code: "" });
      if (res.status === "needs_mfa") setStep("mfa");
      else {
        setStep("login");
        reload();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2>Garmin Connect</h2>
      <p className="muted small">
        Wellness (sleep, HRV, resting HR, Body Battery, stress) and activities. Synced twice a day.
      </p>
      {conn ? (
        <Status conn={conn} provider="garmin" reload={reload} />
      ) : (
        <form className="stack" onSubmit={submit}>
          {step === "login" ? (
            <>
              <label>
                Garmin email
                <input type="email" value={form.email} onChange={set("email")} required autoComplete="off" />
              </label>
              <label>
                Garmin password
                <input type="password" value={form.password} onChange={set("password")} required autoComplete="off" />
              </label>
              <p className="hint">
                Your password is used once to sign in to Garmin and is not stored. CoachQuest keeps only the encrypted
                Garmin session.
              </p>
            </>
          ) : (
            <label>
              Code Garmin sent you
              <input value={form.code} onChange={set("code")} required inputMode="numeric" autoComplete="one-time-code" />
            </label>
          )}
          {error && <div className="error">{error}</div>}
          <button className="btn primary" disabled={busy}>
            {busy ? "…" : step === "login" ? "Connect Garmin" : "Verify code"}
          </button>
        </form>
      )}
    </section>
  );
}
