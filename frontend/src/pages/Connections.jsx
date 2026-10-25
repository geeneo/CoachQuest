import { RefreshCw, Unlink } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { dateTime } from "../lib/format.js";

const ERRORS = {
  state: "The Strava link expired or did not match your session. Try again.",
  denied: "Strava access was not granted.",
  strava: "Strava did not accept the link. Try again; if it keeps failing, the server log (api container) has the details.",
  scope:
    "Strava was connected without access to your activities. Click Connect with Strava again and leave " +
    "\"View data about your activities\" ticked.",
  secret:
    "Strava rejected the Client Secret. Copy the Client Secret from strava.com/settings/api again " +
    "(the 40-character value, not the access or refresh token) into the Strava settings here, then reconnect.",
  client_id: "Strava rejected the Client ID. Check it is the short number at the top of strava.com/settings/api.",
  code: "Strava's one-time code had already been used or expired. Click Connect with Strava again (don't reload the return page).",
  network: "The server could not reach strava.com. Check the server's internet access and try again.",
  no_app: "No Strava API app is set up yet. Add one below, then connect.",
  session:
    `Strava sent you back, but you weren't signed in on ${window.location.host} at that moment. ` +
    "Make sure you sign in on this exact address (not the server's IP), then click Connect with Strava again.",
};

export default function Connections() {
  const conns = useApi("/api/connections");
  const [params] = useSearchParams();
  const byProvider = Object.fromEntries((conns.data?.connections || []).map((c) => [c.provider, c]));
  const firstSyncRunning = (conns.data?.connections || []).some((c) => !c.last_sync_at && c.status === "active");

  // A first sync runs in the background; refresh until it has finished (max ~3 minutes).
  useEffect(() => {
    if (!firstSyncRunning) return;
    let polls = 0;
    const timer = setInterval(() => (++polls > 45 ? clearInterval(timer) : conns.reload()), 4000);
    return () => clearInterval(timer);
  }, [firstSyncRunning, conns.reload]);

  return (
    <>
      <h1>Connections</h1>
      <p className="muted">
        Link your accounts so CoachQuest can import your training. Nothing is shared with anyone until you add them on the{" "}
        <Link to="/sharing">Sharing</Link> page.
      </p>
      {params.get("connected") && <div className="ok">Strava connected. Your first sync is running.</div>}
      {params.get("error") && (
        <div className="error">
          {ERRORS[params.get("error")] || "Linking failed."}
          {params.get("detail") && <div className="small">{params.get("detail")}</div>}
        </div>
      )}
      {conns.error && <div className="error">{conns.error.message}</div>}
      {byProvider.strava?.options.activities && byProvider.garmin?.options.activities && (
        <div className="card flags small">
          Activities come from both Strava and Garmin. CoachQuest hides an activity when both sources have one starting
          within 10 minutes of each other, keeping the Strava copy. To avoid duplicates entirely, untick{" "}
          <strong>Activities</strong> under Garmin and keep Garmin for wellness only.
        </div>
      )}
      <StravaCard
        conn={byProvider.strava}
        configured={conns.data?.strava_configured}
        app={conns.data?.strava_app}
        reload={conns.reload}
      />
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
      reload();
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
        {conn.last_sync_at ? dateTime(conn.last_sync_at) : conn.status === "active" ? "first sync running…" : "never"}
      </p>
      {conn.last_error && <p className="error small">{conn.last_error}</p>}
      <SyncChoices conn={conn} provider={provider} run={run} busy={busy} />
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

const KIND_LABELS = {
  activities: "Activities (rides, runs, swims)",
  wellness: "Wellness (sleep, HRV, resting HR, Body Battery, stress, steps)",
  weight: "Weight → Profile (latest weigh-in from Garmin or a Garmin Index scale)",
};

function SyncChoices({ conn, provider, run, busy }) {
  const name = provider === "strava" ? "Strava" : "Garmin";
  const toggle = (kind, on) =>
    run(async () => {
      await api(`/api/connections/${provider}/options`, { method: "PATCH", body: { [kind]: on } });
      if (!on && kind !== "weight" && confirm(`Stopped importing ${kind} from ${name}, and hid what was already imported.\n\nAlso delete those ${kind} from CoachQuest? Cancel keeps them hidden; switching back on shows them again.`)) {
        await api(`/api/connections/${provider}/data/${kind}`, { method: "DELETE" });
      }
    });
  return (
    <fieldset className="sync-choices">
      <legend>Import from {name}</legend>
      {Object.entries(conn.options).map(([kind, on]) => (
        <label key={kind} className="check">
          <input type="checkbox" checked={on} disabled={busy} onChange={(e) => toggle(kind, e.target.checked)} />
          {KIND_LABELS[kind]}
        </label>
      ))}
    </fieldset>
  );
}

function StravaAppForm({ app, reload }) {
  const [form, setForm] = useState({ client_id: "", client_secret: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/connections/strava/app", { method: "PUT", body: form });
      setForm({ client_id: "", client_secret: "" });
      reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!confirm("Remove your Strava API app from CoachQuest?")) return;
    await api("/api/connections/strava/app", { method: "DELETE" }).catch((err) => setError(err.message));
    reload();
  };

  return (
    <details className="strava-app" open={!app.own && !app.server_available}>
      <summary>
        Your Strava API app{" "}
        <span className="muted small">
          {app.own
            ? `in use · Client ID ${app.client_id} · secret ${app.secret_hint}`
            : app.server_available
              ? "optional · CoachQuest's shared app is used if you don't add one"
              : "needed before you can connect"}
        </span>
      </summary>
      <ol className="small steps">
        <li>
          Open{" "}
          <a href="https://www.strava.com/settings/api" target="_blank" rel="noreferrer">
            strava.com/settings/api
          </a>{" "}
          and create an app (any name, e.g. "My CoachQuest").
        </li>
        <li>
          Set <strong>Authorization Callback Domain</strong> to <code>{app.callback_domain}</code>.
        </li>
        <li>
          Copy <strong>Client ID</strong> (the short number at the top) and <strong>Client Secret</strong> below. Ignore
          "Your Access Token" and "Your Refresh Token".
        </li>
      </ol>
      <form className="stack" onSubmit={save} autoComplete="off">
        <label>
          Client ID
          <input
            name="strava-client-id"
            value={form.client_id}
            onChange={set("client_id")}
            required
            inputMode="numeric"
            pattern="[0-9]{1,12}"
            title="The short number labelled Client ID on strava.com/settings/api"
            autoComplete="off"
            data-1p-ignore
            data-lpignore="true"
            placeholder="e.g. 154321"
          />
        </label>
        <label>
          Client Secret
          <input
            type="password"
            name="strava-client-secret"
            autoComplete="new-password"
            data-1p-ignore
            data-lpignore="true"
            value={form.client_secret}
            onChange={set("client_secret")}
            required
            placeholder={app.own ? "Enter a new secret to replace it" : "40 characters"}
          />
        </label>
        {error && <div className="error">{error}</div>}
        <div className="row">
          <button className="btn primary" disabled={busy}>
            {app.own ? "Replace my Strava app" : "Save my Strava app"}
          </button>
          {app.own && (
            <button type="button" className="btn danger" onClick={remove}>
              Remove
            </button>
          )}
        </div>
        {app.own && (
          <p className="hint">
            If you change apps after connecting, disconnect and connect Strava again: tokens only work with the app that
            issued them.
          </p>
        )}
      </form>
    </details>
  );
}

function StravaCard({ conn, configured, app, reload }) {
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
        <p className="muted small">Add your Strava API app below, then connect.</p>
      )}
      {error && <div className="error">{error}</div>}
      {app && <StravaAppForm app={app} reload={reload} />}
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
