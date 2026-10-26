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
  intervals: "Intervals.icu didn't link.",
  intervals_denied: "Intervals.icu access was not granted.",
  session:
    `Strava sent you back, but you weren't signed in on ${window.location.host} at that moment. ` +
    "Make sure you sign in on this exact address (not the server's IP), then click Connect with Strava again.",
};

export default function Connections() {
  const conns = useApi("/api/connections");
  const platforms = useApi("/api/athletes/me/platforms");
  const reloadAll = () => {
    conns.reload();
    platforms.reload();
  };
  const [params] = useSearchParams();
  const byProvider = Object.fromEntries((conns.data?.connections || []).map((c) => [c.provider, c]));
  const firstSyncRunning = (conns.data?.connections || []).some(
    (c) => (!c.last_sync_at && c.status === "active") || c.backfill?.status === "running",
  );

  // A first sync runs in the background; refresh until it has finished (max ~3 minutes).
  useEffect(() => {
    if (!firstSyncRunning) return;
    let polls = 0;
    const timer = setInterval(() => (++polls > 450 ? clearInterval(timer) : conns.reload()), 4000);
    return () => clearInterval(timer);
  }, [firstSyncRunning, conns.reload]);

  return (
    <>
      <h1>Connections</h1>
      <p className="muted">
        Link your accounts so CoachQuest can import your training. Nothing is shared with anyone until you add them on the{" "}
        <Link to="/sharing">Sharing</Link> page.
      </p>
      {params.get("connected") === "strava" && <div className="ok">Strava connected. Your first sync is running.</div>}
      {params.get("connected") === "intervals" && (
        <div className="ok">
          Intervals.icu connected. Tick "Auto-send workouts" for Intervals.icu below to send your scheduled workouts there.
        </div>
      )}
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
      <IntervalsCard
        conn={byProvider.intervals_icu}
        platform={platforms.data?.find((p) => p.id === "intervals_icu")}
        platforms={platforms.data}
        reload={reloadAll}
      />
      <ConnectedPlatforms platforms={platforms} />
    </>
  );
}

const PLATFORM_STATUS = {
  connected: { label: "Connected", cls: "ok" },
  error: { label: "Needs attention", cls: "bad" },
  not_connected: { label: "Not connected", cls: "" },
  export_only: { label: "File download only", cls: "" },
  not_available: { label: "Not available yet", cls: "" },
  not_configured: { label: "Not set up on this server", cls: "" },
};

// Settings > Connected platforms: every training platform, what CoachQuest can do with it
// today, and the athlete's choices. Automatic delivery is only offered where it really works.
// PUT /api/me/platforms needs the whole choice; `changes` gets the current lists and returns what differs.
async function savePlatformPrefs(list, changes) {
  const preferred = list.filter((p) => p.preferred).map((p) => p.id);
  const auto = Object.fromEntries(list.filter((p) => p.auto_sync).map((p) => [p.id, true]));
  await api("/api/me/platforms", { method: "PUT", body: { preferred, auto, ...changes(preferred, auto) } });
}

function ConnectedPlatforms({ platforms }) {
  const [error, setError] = useState(null);
  const list = platforms.data || [];

  const savePrefs = async (changes) => {
    setError(null);
    try {
      await savePlatformPrefs(list, changes);
      platforms.reload();
    } catch (err) {
      setError(err.message);
    }
  };
  const togglePreferred = (id, on) =>
    savePrefs((preferred) => ({ preferred: on ? [...preferred, id] : preferred.filter((x) => x !== id) }));
  const toggleAuto = (id, on) => savePrefs((_, auto) => ({ auto: { ...auto, [id]: on } }));
  return (
    <section className="card" id="platforms">
      <h2>Connected platforms</h2>
      <p className="muted small">
        Where your workouts go and where your rides come from. Every scheduled workout can be downloaded as a Zwift file
        (.zwo) from the calendar. Automatic delivery is only offered through an official, authorised integration: today
        that is Intervals.icu, which passes workouts on to Zwift when you link Zwift there.
      </p>
      {error && <div className="error">{error}</div>}
      {platforms.error && <div className="error">{platforms.error.message}</div>}
      <div className="table-wrap">
        <table className="platforms">
          <thead>
            <tr>
              <th>Platform</th>
              <th>Status</th>
              <th>Account</th>
              <th>Last sync</th>
              <th>Can do</th>
              <th>I use it</th>
              <th>Auto-send workouts</th>
            </tr>
          </thead>
          <tbody>
            {list.map((p) => (
              <tr key={p.id}>
                <td>
                  <strong>{p.name}</strong>
                  {p.experimental && <span className="badge"> Experimental</span>}
                  <div className="small muted">{p.note}</div>
                </td>
                <td>
                  <span className={`badge ${PLATFORM_STATUS[p.status].cls}`}>{PLATFORM_STATUS[p.status].label}</span>
                  {p.last_error && <div className="small error-text">{p.last_error}</div>}
                  {p.id === "intervals_icu" && p.status !== "not_configured" && (
                    <div className="small muted">Connect and choose what syncs on the Intervals.icu card above.</div>
                  )}
                  {p.status === "not_configured" && (
                    <div className="small muted">An admin adds the Intervals.icu app keys in Admin → Settings.</div>
                  )}
                </td>
                <td className="small">{p.account || "–"}</td>
                <td className="small">{p.last_sync_at ? dateTime(p.last_sync_at) : "–"}</td>
                <td className="small">{p.capabilities.map((c) => c.label).join("; ") || "–"}</td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`I train on ${p.name}`}
                    checked={p.preferred}
                    onChange={(e) => togglePreferred(p.id, e.target.checked)}
                  />
                </td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Send workouts to ${p.name} automatically`}
                    checked={p.auto_sync}
                    disabled={!p.auto_sync_available && !p.auto_sync}
                    title={p.auto_sync_available ? "" : "Not available for this platform yet"}
                    onChange={(e) => toggleAuto(p.id, e.target.checked)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small muted">
        Strava and Garmin are connected and disconnected with their cards above. Intervals.icu uses its own sign-in
        (OAuth): CoachQuest never asks for your password on another platform.
      </p>
      <SyncHistory />
    </section>
  );
}

const OUTCOME = {
  sent: "✓ Sent",
  deleted: "✓ Removed",
  unchanged: "Up to date",
  skipped: "Nothing to remove",
  retrying: "↻ Will retry",
  rate_limited: "↻ Waiting (rate limit)",
  failed: "✗ Failed",
  blocked: "⚠ Blocked",
  unavailable: "✗ Not available",
  disconnected: "Disconnected",
};
const JOB_STATUS = { queued: "Queued", running: "Sending", failed: "Failed", blocked: "Needs reconnect" };
const PLATFORM_NAME = { intervals_icu: "Intervals.icu", zwift: "Zwift", mywhoosh: "MyWhoosh" };

// What was sent where, what is waiting, and what failed (with Retry).
export function SyncHistory({ id = "me" }) {
  const hist = useApi(`/api/athletes/${id}/sync?limit=30`);
  const [error, setError] = useState(null);
  const retry = async (job) => {
    setError(null);
    try {
      await api(`/api/athletes/${id}/sync/${job.id}/retry`, { method: "POST" });
      hist.reload();
    } catch (err) {
      setError(err.message);
    }
  };
  const data = hist.data;
  if (!data || (!data.open.length && !data.log.length)) return null;
  return (
    <div className="sync-history">
      <div className="row between">
        <h3>Workout delivery</h3>
        <button className="btn small" onClick={hist.reload}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {data.open.length > 0 && (
        <ul className="sync-open">
          {data.open.map((j) => (
            <li key={j.id} className={`sync-job ${j.status}`}>
              <strong>{j.workout || "Workout"}</strong> → {PLATFORM_NAME[j.provider] || j.provider}:{" "}
              {j.attempts && j.status === "queued" ? "Retrying" : JOB_STATUS[j.status]}
              {j.action === "delete" ? " (remove)" : ""}
              {j.error && <span className="small muted"> — {j.error}</span>}
              {j.status === "failed" && (
                <button className="btn small" onClick={() => retry(j)}>
                  Retry
                </button>
              )}
              {j.status === "blocked" && <span className="small"> Reconnect above; it is sent again then.</span>}
            </li>
          ))}
        </ul>
      )}
      {data.log.length > 0 && (
        <details>
          <summary className="small">History ({data.log.length} latest)</summary>
          <div className="table-wrap">
            <table className="compact">
              <tbody>
                {data.log.map((e, i) => (
                  <tr key={i}>
                    <td className="small muted">{dateTime(e.at)}</td>
                    <td className="small">{PLATFORM_NAME[e.provider] || e.provider}</td>
                    <td className="small">{e.workout}</td>
                    <td className="small">{OUTCOME[e.outcome] || e.outcome}</td>
                    <td className="small muted">{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
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
      <Backfill conn={conn} provider={provider} run={run} busy={busy} />
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
  thresholds: "Thresholds → Profile (cycling FTP, lactate threshold HR, max HR from your Garmin zones)",
  birth_date: "Birth date → Profile (your age, for the AI coach and age-based estimates)",
};

const BACKFILL_CHOICES = [
  ["1y", "1 year", 365],
  ["2y", "2 years", 730],
  ["5y", "5 years", 1826],
  ["all", "Everything", null],
];

function isoDaysAgo(days) {
  return days == null ? "2009-01-01" : new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
}

function Backfill({ conn, provider, run, busy }) {
  const [choice, setChoice] = useState("1y");
  const bf = conn.backfill;
  const active = bf && (bf.status === "running" || bf.status === "waiting");
  const start = () => {
    const days = BACKFILL_CHOICES.find((c) => c[0] === choice)[2];
    run(() => api(`/api/connections/${provider}/backfill`, { method: "POST", body: { since: isoDaysAgo(days) } }));
  };
  const cancel = () => run(() => api(`/api/connections/${provider}/backfill`, { method: "DELETE" }));
  const refresh = () => run(() => api(`/api/connections/${provider}/refresh`, { method: "POST" }));
  const refreshing = bf?.mode === "refresh";
  const reached = bf?.cursor ? bf.cursor.slice(0, 10) : null;

  return (
    <fieldset className="sync-choices">
      <legend>Import older data</legend>
      {bf && (
        <p className="small">
          {
            {
              running: refreshing
                ? `Refreshing stored activities… back to ${reached} so far, ${bf.stored} updated.`
                : `Importing… back to ${reached} so far, ${bf.stored} items. Target ${bf.target}.`,
              waiting: `Paused at ${reached} (${bf.stored} items) to stay inside the rate limit. Resumes around ${bf.resume_at?.slice(11, 16)} UTC.`,
              done: refreshing
                ? `Stored activities refreshed (${bf.stored} updated) back to ${bf.target}.`
                : `Done: imported ${bf.stored} items back to ${bf.target}.`,
              cancelled: `Stopped at ${reached} after ${bf.stored} items.`,
              error: `Stopped with an error at ${reached}: ${bf.message}`,
            }[bf.status]
          }
        </p>
      )}
      {active ? (
        <button type="button" className="btn" disabled={busy} onClick={cancel}>
          Stop import
        </button>
      ) : (
        <div className="row">
          <select value={choice} onChange={(e) => setChoice(e.target.value)} disabled={busy}>
            {BACKFILL_CHOICES.map(([value, label]) => (
              <option key={value} value={value}>
                Back {label === "Everything" ? "to the start" : label}
              </option>
            ))}
          </select>
          <button type="button" className="btn" disabled={busy} onClick={start}>
            Import
          </button>
          {conn.options.activities && (
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={refresh}
              title="Re-download activities you already have, to fill in speed, cadence and calories"
            >
              Refresh imported activities
            </button>
          )}
        </div>
      )}
      <p className="hint">
        {provider === "strava"
          ? "Pauses on its own near Strava's rate limits (shared with other apps using the same Strava app) and resumes later."
          : "Goes back two weeks at a time. Wellness is imported for the last year only; activities go back as far as you choose."}
      </p>
    </fieldset>
  );
}

function SyncChoices({ conn, provider, run, busy }) {
  const name = provider === "strava" ? "Strava" : "Garmin";
  const toggle = (kind, on) =>
    run(async () => {
      await api(`/api/connections/${provider}/options`, { method: "PATCH", body: { [kind]: on } });
      if (!on && ["activities", "wellness"].includes(kind) && confirm(`Stopped importing ${kind} from ${name}, and hid what was already imported.\n\nAlso delete those ${kind} from CoachQuest? Cancel keeps them hidden; switching back on shows them again.`)) {
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

const ICU_CHOICES = {
  activities: [
    "ACTIVITY:READ",
    "Import activities",
    "Leave off if Strava or Garmin already brings your rides in; the same ride is only shown once either way.",
  ],
  wellness: [
    "WELLNESS:READ",
    "Import wellness (sleep, HRV, resting HR, steps)",
    "Fills what Garmin leaves empty, or replaces Garmin if you stop that connection.",
  ],
};

// Intervals.icu: send workouts to it (and on to Zwift / MyWhoosh), and optionally import from it.
function IntervalsCard({ conn, platform, platforms, reload }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const run = async (fn) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy(false);
      reload();
    }
  };
  const connect = () =>
    run(async () => {
      window.location.href = (await api("/api/connections/intervals/authorize", { method: "POST" })).url;
    });
  const disconnect = () => {
    if (!confirm("Disconnect Intervals.icu? Workouts already on your Intervals.icu calendar stay there.")) return;
    const purge = confirm("Also delete activities and wellness imported from Intervals.icu? Cancel keeps them.");
    run(() => api(`/api/connections/intervals?purge=${purge}`, { method: "DELETE" }));
  };
  const setSend = (on) =>
    run(() => savePlatformPrefs(platforms, (_, auto) => ({ auto: { ...auto, intervals_icu: on } })));
  const setImport = (kind, on) =>
    run(async () => {
      await api("/api/connections/intervals_icu/options", { method: "PATCH", body: { [kind]: on } });
      if (!on && confirm(`Stopped importing ${kind} from Intervals.icu, and hid what was imported.\n\nAlso delete it? Cancel keeps it hidden.`)) {
        await api(`/api/connections/intervals_icu/data/${kind}`, { method: "DELETE" });
      }
    });
  const sync = () => run(() => api("/api/connections/intervals_icu/sync", { method: "POST" }));
  const scopes = new Set(conn?.scopes || []);

  return (
    <section className="card">
      <h2>Intervals.icu</h2>
      <p className="muted small">
        Sends your scheduled workouts to Intervals.icu, which passes them on to Zwift (and MyWhoosh) when you link those in
        Intervals.icu. Can also import activities and wellness. Imports run every 6 hours.
      </p>
      {platform?.status === "not_configured" ? (
        <p className="small">Not set up on this server yet: an admin adds the Intervals.icu app keys in Admin → Settings.</p>
      ) : !conn ? (
        <button className="btn primary" disabled={busy} onClick={connect}>
          Connect Intervals.icu
        </button>
      ) : (
        <>
          <p className="small">
            <span className={`badge ${conn.status === "active" ? "ok" : "bad"}`}>{conn.status}</span> Last sync:{" "}
            {conn.last_sync_at ? dateTime(conn.last_sync_at) : "never"}
            {conn.external_id && <span className="muted"> · athlete {conn.external_id}</span>}
          </p>
          {conn.last_error && <p className="error small">{conn.last_error}</p>}
          <fieldset className="sync-choices">
            <legend>Sync with Intervals.icu</legend>
            <label className="check">
              <input
                type="checkbox"
                checked={!!platform?.auto_sync}
                disabled={busy || (!platform?.auto_sync_available && !platform?.auto_sync)}
                onChange={(e) => setSend(e.target.checked)}
              />
              Send scheduled workouts (from today on; they go on to Zwift and MyWhoosh when linked in Intervals.icu)
            </label>
            {!scopes.has("CALENDAR:WRITE") && (
              <p className="hint">Calendar access wasn't allowed. Reconnect and allow it to send workouts.</p>
            )}
            {Object.entries(ICU_CHOICES).map(([kind, [scope, label, hint]]) => (
              <label key={kind} className="check">
                <input
                  type="checkbox"
                  checked={!!conn.options[kind]}
                  disabled={busy || !scopes.has(scope)}
                  onChange={(e) => setImport(kind, e.target.checked)}
                />
                <span>
                  {label}
                  <span className="hint">
                    {" "}
                    {scopes.has(scope) ? hint : "Not allowed when you connected: reconnect to allow it."}
                  </span>
                </span>
              </label>
            ))}
          </fieldset>
          {msg && <p className="error small">{msg}</p>}
          <div className="row">
            {(conn.options.activities || conn.options.wellness) && (
              <button className="btn" disabled={busy} onClick={sync}>
                <RefreshCw size={16} /> Import now
              </button>
            )}
            {(conn.status === "error" || scopes.size < 3) && (
              <button className="btn primary" disabled={busy} onClick={connect}>
                Reconnect
              </button>
            )}
            <button className="btn danger" disabled={busy} onClick={disconnect}>
              <Unlink size={16} /> Disconnect
            </button>
          </div>
        </>
      )}
    </section>
  );
}
