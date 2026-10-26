import { CheckCircle2, KeyRound, XCircle } from "lucide-react";
import { useState } from "react";
import { Stat } from "../components/WellnessPanel.jsx";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { dateTime, formatDate } from "../lib/format.js";
import { AdminSignIns } from "../components/SignInLog.jsx";

const SOURCE = { web: "set here", env: "from .env", unset: "not set" };

export default function Admin() {
  // Bumped when users change, so Storage and Usage show fresh numbers.
  const [rev, setRev] = useState(0);
  const stats = useApi(`/api/admin/stats?rev=${rev}`);
  const version = useApi("/api/admin/version");
  const s = stats.data;
  return (
    <>
      <h1>Admin</h1>
      <p className="muted small">
        API build {version.data?.commit} {version.data?.built} · frontend build {import.meta.env.VITE_BUILD_COMMIT || "dev"}
      </p>
      <Settings />
      <Users onChange={() => setRev((r) => r + 1)} />
      <AiUsage rev={rev} />
      <Storage rev={rev} />
      <AdminSignIns />
      <section className="card">
        <h2>Usage</h2>
        {stats.error && <div className="error">{stats.error.message}</div>}
        {s && (
          <div className="stats">
            <Stat label="Users" value={s.users} />
            <Stat label="Strava links" value={s.connections.strava || 0} />
            <Stat label="Garmin links" value={s.connections.garmin || 0} />
            <Stat label="Sync errors" value={s.connection_errors} />
            <Stat label="AI plans ok" value={s.ai_calls.ok || 0} />
            <Stat label="AI tokens in / out" value={`${s.ai_tokens.input} / ${s.ai_tokens.output}`} />
          </div>
        )}
      </section>
    </>
  );
}

function Settings() {
  const res = useApi("/api/admin/settings");
  const [draft, setDraft] = useState({});
  const [msg, setMsg] = useState(null);
  const [test, setTest] = useState(null);
  const [mailTest, setMailTest] = useState(null);
  const [busy, setBusy] = useState(false);

  if (res.loading) return <section className="card muted">Loading settings…</section>;
  if (res.error) return <div className="error">{res.error.message}</div>;

  const items = res.data.settings;
  const groups = [...new Set(items.map((i) => i.group))];
  const dirty = Object.keys(draft).length > 0;
  const set = (key, value) => setDraft({ ...draft, [key]: value });

  const save = async (values) => {
    setBusy(true);
    setMsg(null);
    try {
      await api("/api/admin/settings", { method: "PUT", body: { values } });
      setDraft({});
      setMsg({ ok: "Saved. Takes effect immediately, no restart needed." });
      res.reload();
    } catch (err) {
      setMsg({ error: err.message });
    } finally {
      setBusy(false);
    }
  };

  const testKey = async () => {
    setTest({ message: "Testing…" });
    try {
      setTest(await api("/api/admin/settings/test-anthropic", { method: "POST" }));
    } catch (err) {
      setTest({ ok: false, message: err.message });
    }
  };

  const testMail = async () => {
    setMailTest({ message: "Sending…" });
    try {
      setMailTest(await api("/api/admin/settings/test-email", { method: "POST", body: {} }));
    } catch (err) {
      setMailTest({ ok: false, message: err.message });
    }
  };

  return (
    <section className="card">
      <h2>
        <KeyRound size={18} /> Settings
      </h2>
      <p className="muted small">
        Values saved here override <code>.env</code> and are stored encrypted. Saved keys are never shown again, only
        their last 4 characters. Clear a value to fall back to <code>.env</code>.
      </p>
      {groups.map((g) => (
        <fieldset key={g} className="settings-group">
          <legend>{g}</legend>
          {items
            .filter((i) => i.group === g)
            .map((i) => (
              <SettingRow key={i.key} item={i} draft={draft[i.key]} onChange={(v) => set(i.key, v)} onClear={() => save({ [i.key]: "" })} />
            ))}
          {g === "AI coach" && (
            <div className="row">
              <button type="button" className="btn" onClick={testKey} disabled={dirty}>
                Test Anthropic key
              </button>
              {test && (
                <span className={`small ${test.ok ? "text-ok" : test.ok === false ? "text-bad" : "muted"}`}>
                  {test.ok ? <CheckCircle2 size={14} /> : test.ok === false ? <XCircle size={14} /> : null} {test.message}
                </span>
              )}
            </div>
          )}
          {g === "Email" && (
            <div className="row">
              <button type="button" className="btn" onClick={testMail} disabled={dirty}>
                Send test email to me
              </button>
              {mailTest && (
                <span className={`small ${mailTest.ok ? "text-ok" : mailTest.ok === false ? "text-bad" : "muted"}`}>
                  {mailTest.ok ? <CheckCircle2 size={14} /> : mailTest.ok === false ? <XCircle size={14} /> : null}{" "}
                  {mailTest.message}
                </span>
              )}
            </div>
          )}
          {g === "Strava" && (
            <p className="hint">
              In your Strava API app, set Authorization Callback Domain to{" "}
              <code>{res.data.env_only.strava_callback_domain}</code>.
            </p>
          )}
        </fieldset>
      ))}
      {msg?.ok && <div className="ok">{msg.ok}</div>}
      {msg?.error && <div className="error">{msg.error}</div>}
      <div className="row">
        <button className="btn primary" disabled={!dirty || busy} onClick={() => save(draft)}>
          Save changes
        </button>
        {dirty && (
          <button className="btn" onClick={() => setDraft({})}>
            Discard
          </button>
        )}
      </div>
      <p className="hint">
        Stay in <code>.env</code> on the server: PUBLIC_BASE_URL ({res.data.env_only.PUBLIC_BASE_URL}),
        PROXY_SHARED_SECRET and TOKEN_ENCRYPTION_KEY.
      </p>
    </section>
  );
}

function SettingRow({ item, draft, onChange, onClear }) {
  const status = (
    <span className="muted small">
      {SOURCE[item.source]}
      {item.secret && item.hint ? ` · ${item.hint}` : ""}
    </span>
  );
  let input;
  if (item.choices.length) {
    input = (
      <select value={draft ?? item.value} onChange={(e) => onChange(e.target.value)}>
        {!item.value && <option value="">–</option>}
        {item.choices.map((c) => (
          <option key={c}>{c}</option>
        ))}
      </select>
    );
  } else {
    input = (
      <input
        type={item.secret ? "password" : "text"}
        autoComplete="off"
        placeholder={item.secret ? (item.is_set ? "Enter a new value to replace it" : "Paste the key") : ""}
        value={draft ?? (item.secret ? "" : item.value)}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <div className="setting-row">
      <label>
        <span>
          {item.label} {status}
        </span>
        {input}
        {item.help && <span className="hint">{item.help}</span>}
      </label>
      {item.source === "web" && (
        <button type="button" className="link-btn small" onClick={onClear} title="Use the .env value instead">
          Reset to .env
        </button>
      )}
    </div>
  );
}

const PROVIDERS = [
  ["strava", "Strava"],
  ["garmin", "Garmin"],
  ["intervals_icu", "Intervals.icu"],
];
const USER_SORTS = {
  attention: ["Needs attention", (a, b) => b.attention - a.attention || a.display_name.localeCompare(b.display_name)],
  name: ["Name", (a, b) => a.display_name.localeCompare(b.display_name)],
  seen: ["Last seen", (a, b) => (b.last_seen_at || "").localeCompare(a.last_seen_at || "")],
  activities: ["Activities", (a, b) => b.activities.total - a.activities.total],
  storage: ["Storage", (a, b) => b.storage_bytes - a.storage_bytes],
  joined: ["Joined (newest first)", (a, b) => b.created_at.localeCompare(a.created_at)],
};

function Users({ onChange }) {
  const { user: me } = useAuth();
  const users = useApi("/api/admin/users");
  const [open, setOpen] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("attention");
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const update = (u, body) => {
    setError(null);
    api(`/api/admin/users/${u.id}`, { method: "PATCH", body }).then(users.reload, (e) => setError(e.message));
  };
  const needle = q.trim().toLowerCase();
  const rows = (users.data || [])
    .filter((u) => !needle || `${u.display_name} ${u.email}`.toLowerCase().includes(needle))
    .filter((u) => !onlyFlagged || u.flags.length)
    // People waiting for approval always come first.
    .sort((a, b) => a.approved - b.approved || USER_SORTS[sort][1](a, b));
  return (
    <section className="card">
      <h2>Users</h2>
      <div className="row wrap dash-controls">
        <input type="search" placeholder="Search name or email" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="inline">
          Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            {Object.entries(USER_SORTS).map(([k, [label]]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} /> Only those
          with flags
        </label>
        <button className="btn small" onClick={users.reload}>
          Refresh
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {users.error && <div className="error">{users.error.message}</div>}
      {users.data && (
        <div className="table-wrap">
          <table className="admin-users">
            <thead>
              <tr>
                <th>User</th>
                <th>Last seen</th>
                <th>Activities</th>
                <th>Connections</th>
                <th>Plans &amp; sharing</th>
                <th>AI · storage</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <UserRow
                  key={u.id}
                  u={u}
                  isMe={u.id === me.id}
                  open={open === u.id}
                  toggle={() => setOpen(open === u.id ? null : u.id)}
                  update={update}
                  reload={() => {
                    users.reload();
                    onChange();
                  }}
                />
              ))}
            </tbody>
          </table>
          {!rows.length && <p className="muted small">No users match.</p>}
        </div>
      )}
      <p className="muted small">
        Storage is an estimate (each table's size split by the user's share of its rows). Opening a user's details is
        shown in their "Who looked at my data" log.
      </p>
    </section>
  );
}

function ConnState({ c }) {
  if (!c) return <span className="muted">–</span>;
  if (c.status === "error")
    return (
      <span className="error-text" title={c.last_error || ""}>
        error
      </span>
    );
  return <span className="ok-text">{c.last_sync_at ? formatDate(c.last_sync_at) : "connected"}</span>;
}

function UserRow({ u, isMe, open, toggle, update, reload }) {
  const decide = (user, action) =>
    api(`/api/admin/users/${user.id}/${action}`, { method: "POST" }).then(
      (r) => {
        if (r.emailed) alert(`${user.email} approved. ${r.emailed}`);
        reload();
      },
      (e) => alert(e.message),
    );
  const a = u.activities;
  const d = u.delivery;
  return (
    <>
      <tr className={u.attention >= 3 ? "attention" : ""}>
        <td>
          <strong>{u.display_name}</strong>
          {isMe && <span className="muted"> (you)</span>} {u.is_admin && <span className="badge">admin</span>}{" "}
          {!u.is_active && <span className="badge bad">disabled</span>}
          <div className="small muted">{u.email}</div>
          <div className="small muted">joined {formatDate(u.created_at)}</div>
          {u.flags.length > 0 && (
            <div className="chips tight">
              {u.flags.map((f) => (
                <span key={f} className={`badge ${f === "disabled" || f.startsWith("no sign-in") ? "" : "bad"}`}>
                  {f}
                </span>
              ))}
            </div>
          )}
          {!u.approved ? (
            <span className="row tight">
              <button className="btn primary" onClick={() => decide(u, "approve")}>
                Approve
              </button>
              <button className="btn danger" onClick={() => confirm(`Reject ${u.email}?`) && decide(u, "reject")}>
                Reject
              </button>
            </span>
          ) : (
            <button className="link-btn small" onClick={toggle}>
              {open ? "Close details" : "Details"}
            </button>
          )}
        </td>
        <td className="small">
          {u.last_seen_at ? dateTime(u.last_seen_at) : <span className="muted">never</span>}
          {u.failed_sign_ins_7d > 0 && (
            <div className="error-text">{u.failed_sign_ins_7d} failed sign-ins (7 days)</div>
          )}
        </td>
        <td className="small">
          <strong>{a.total}</strong>
          {a.total > 0 && (
            <>
              <div className="muted">
                {Object.entries(a.by_source)
                  .map(([k, n]) => `${PROVIDERS.find((p) => p[0] === k)?.[1] || k} ${n}`)
                  .join(" · ")}
              </div>
              <div className="muted">latest {formatDate(a.last)}</div>
            </>
          )}
          <div className="muted">{u.wellness_days} wellness days</div>
        </td>
        <td className="small">
          <table className="mini">
            <tbody>
              {PROVIDERS.map(([k, label]) => (
                <tr key={k}>
                  <td className="muted">{label}</td>
                  <td>
                    <ConnState c={u.connections[k]} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(d.failed > 0 || d.blocked > 0 || d.queued > 0) && (
            <div className={d.failed || d.blocked ? "error-text" : "muted"}>
              Workouts: {[d.queued && `${d.queued} queued`, d.failed && `${d.failed} failed`, d.blocked && `${d.blocked} blocked`]
                .filter(Boolean)
                .join(", ")}
            </div>
          )}
        </td>
        <td className="small">
          <div>
            {u.plans} plans · {u.races} races · {u.scheduled_workouts} workouts
          </div>
          <div className="muted">
            {u.coaches} {u.coaches === 1 ? "coach" : "coaches"} · {u.athletes} {u.athletes === 1 ? "athlete" : "athletes"}
          </div>
        </td>
        <td className="small">
          <div>
            {u.ai_disabled ? (
              <span className="badge bad">AI off</span>
            ) : (
              <>
                {u.ai_month.calls}
                {u.ai_limit ? ` / ${u.ai_limit}` : ""} AI calls
              </>
            )}
            {u.ai_month.tokens ? ` · ${Math.round(u.ai_month.tokens / 1000)}k tokens` : ""}
          </div>
          {u.ai_month.for_others > 0 && (
            <div className="muted">{u.ai_month.for_others} for athletes they coach</div>
          )}
          <div className="muted">≈ {bytes(u.storage_bytes)}</div>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={6} className="manage-cell">
            <UserDetail u={u} isMe={isMe} update={update} reload={reload} />
          </td>
        </tr>
      )}
    </>
  );
}

function UserDetail({ u, isMe, update, reload }) {
  const d = useApi(`/api/admin/users/${u.id}/detail`);
  const [msg, setMsg] = useState(null);
  const syncNow = (provider) => {
    setMsg(null);
    api(`/api/admin/users/${u.id}/sync/${provider}`, { method: "POST" }).then(
      (r) => {
        setMsg({ ok: `Synced: ${r.fetched} new item${r.fetched === 1 ? "" : "s"}.` });
        reload();
      },
      (e) => setMsg({ error: e.message }),
    );
  };
  return (
    <div className="manage">
      <div className="user-detail">
        <div>
          <h3>Connections</h3>
          <table className="mini">
            <tbody>
              {PROVIDERS.map(([k, label]) => {
                const c = u.connections[k];
                return (
                  <tr key={k}>
                    <td>{label}</td>
                    <td>
                      {c ? (
                        <>
                          <span className={c.status === "error" ? "error-text" : "ok-text"}>{c.status}</span>
                          <span className="muted"> · last sync {c.last_sync_at ? dateTime(c.last_sync_at) : "never"}</span>
                          {c.last_error && <div className="error-text">{c.last_error}</div>}
                        </>
                      ) : (
                        <span className="muted">not connected</span>
                      )}
                    </td>
                    <td>
                      {c && (
                        <button className="btn small" onClick={() => syncNow(k)}>
                          Sync now
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {msg?.ok && <div className="ok small">{msg.ok}</div>}
          {msg?.error && <div className="error small">{msg.error}</div>}
          {d.data && (
            <>
              <h3>Activities by sport</h3>
              <p className="small">
                {d.data.sports.length ? d.data.sports.map((s) => `${s.sport} ${s.count}`).join(" · ") : "None yet."}
                {u.activities.first && (
                  <span className="muted">
                    {" "}
                    ({formatDate(u.activities.first)} to {formatDate(u.activities.last)})
                  </span>
                )}
              </p>
              <h3>Sharing</h3>
              <p className="small">
                Coaches: {d.data.coaches.map((g) => g.name).join(", ") || "none"}
                <br />
                Athletes: {d.data.athletes.map((g) => g.name).join(", ") || "none"}
              </p>
            </>
          )}
        </div>
        {d.error && <div className="error small">{d.error.message}</div>}
        {d.data && (
          <div>
            <h3>Recent sign-ins</h3>
            <ul className="plain small">
              {d.data.sign_ins.map((e) => (
                <li key={e.id} className={e.failed ? "error-text" : ""}>
                  {dateTime(e.at)} · {e.label}
                  {e.ip && <span className="muted"> · {e.ip}</span>}
                </li>
              ))}
              {!d.data.sign_ins.length && <li className="muted">None logged.</li>}
            </ul>
            <h3>Recent workout deliveries</h3>
            <ul className="plain small">
              {d.data.deliveries.map((r, i) => (
                <li key={i} className={["failed", "blocked"].includes(r.outcome) ? "error-text" : ""}>
                  {dateTime(r.at)} · {r.workout || "workout"} → {r.provider}: {r.outcome}
                  {r.message && <span className="muted"> · {r.message}</span>}
                </li>
              ))}
              {!d.data.deliveries.length && <li className="muted">None.</li>}
            </ul>
          </div>
        )}
      </div>
      {d.data && <AiUse u={u} ai={d.data.ai} update={update} />}
      {!isMe && (
        <>
          <div className="row wrap">
            <label className="check">
              <input type="checkbox" checked={u.is_admin} onChange={(e) => update(u, { is_admin: e.target.checked })} /> Admin
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={u.is_active}
                onChange={(e) =>
                  (e.target.checked || confirm(`Disable ${u.display_name}? They are signed out at once.`)) &&
                  update(u, { is_active: e.target.checked })
                }
              />{" "}
              Active (can sign in)
            </label>
          </div>
          <ManageUser u={u} reload={reload} />
        </>
      )}
    </div>
  );
}

const AI_KINDS = { plan: "Plans", replan: "Re-plans", readiness: "Readiness notes", weekly: "Weekly reviews", chat: "Chat" };

// This month's AI use for one user, and the admin's switch and limit for it.
function AiUse({ u, ai, update }) {
  const [limit, setLimit] = useState(u.ai_monthly_limit ?? "");
  const k = (n) => (n >= 1000 ? `${Math.round(n / 1000)}k` : n);
  const rows = (obj, label) =>
    Object.entries(obj).map(([key, b]) => (
      <tr key={key}>
        <td>{label(key)}</td>
        <td className="num">
          {b.calls}
          {b.failed ? <span className="error-text"> ({b.failed} failed)</span> : null}
        </td>
        <td className="num">{k(b.input)}</td>
        <td className="num">{k(b.cache_read)}</td>
        <td className="num">{k(b.output)}</td>
      </tr>
    ));
  const head = (first) => (
    <thead>
      <tr>
        <th>{first}</th>
        <th className="num">Calls</th>
        <th className="num">Input</th>
        <th className="num">From cache</th>
        <th className="num">Output</th>
      </tr>
    </thead>
  );
  const empty = !Object.keys(ai.by_kind).length;
  return (
    <div className="ai-use">
      <h3>AI coach this month</h3>
      {empty ? (
        <p className="small muted">No AI calls this month.</p>
      ) : (
        <div className="user-detail">
          <table className="small">
            {head("What for")}
            <tbody>{rows(ai.by_kind, (key) => AI_KINDS[key] || "Earlier calls (type not recorded)")}</tbody>
          </table>
          <table className="small">
            {head("Whose data")}
            <tbody>{rows(ai.by_athlete, (key) => (key === "themselves" ? "Their own" : key))}</tbody>
          </table>
        </div>
      )}
      {!empty && (
        <p className="small muted">
          Rough cost: ${ai.cost_usd.toFixed(2)}
          {ai.cost_complete ? "" : " (some calls used a model without a price here)"}. Calls count against the person
          who asked, also when it's for an athlete they coach. Cached input costs about a tenth.
        </p>
      )}
      <div className="row wrap">
        <label className="check">
          <input
            type="checkbox"
            checked={!u.ai_disabled}
            onChange={(e) =>
              (e.target.checked || confirm(`Turn the AI coach off for ${u.display_name}? Their AI requests stop at once.`)) &&
              update(u, { ai_disabled: !e.target.checked })
            }
          />{" "}
          AI coach on
        </label>
        <form
          className="row tight"
          onSubmit={(e) => {
            e.preventDefault();
            update(u, { ai_monthly_limit: limit === "" ? null : Number(limit) });
          }}
        >
          <label className="inline small">
            Monthly limit
            <input
              type="number"
              min={0}
              max={100000}
              style={{ width: "7rem" }}
              placeholder="site's limit"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
            />
          </label>
          <button className="btn small">Save</button>
        </form>
        <span className="small muted">
          Now: {u.ai_limit ? `${u.ai_limit} calls` : "no limit"}
          {u.ai_monthly_limit == null ? " (the site's)" : " (set for this user)"}. Empty: the site's limit; 0: no limit.
        </span>
      </div>
    </div>
  );
}

function ManageUser({ u, reload }) {
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState(null);
  const [link, setLink] = useState(null);
  const [confirmEmail, setConfirmEmail] = useState("");
  const done = (ok) => setMsg({ ok });
  const fail = (err) => setMsg({ error: err.message });

  const setPw = (e) => {
    e.preventDefault();
    api(`/api/admin/users/${u.id}/password`, { method: "POST", body: { new_password: password } }).then(() => {
      setPassword("");
      done(`Password set. ${u.display_name} has been signed out everywhere; give them the new password.`);
    }, fail);
  };
  const makeLink = () =>
    api(`/api/admin/users/${u.id}/reset-link`, { method: "POST" }).then((r) => {
      setLink(r.link);
      done(`Reset link created (valid 24 hours, works once). ${r.emailed}`);
    }, fail);
  const remove = (e) => {
    e.preventDefault();
    if (!confirm(`Delete ${u.display_name} and all their data? This cannot be undone.`)) return;
    api(`/api/admin/users/${u.id}`, { method: "DELETE", body: { confirm_email: confirmEmail } }).then(reload, fail);
  };

  return (
    <div className="manage">
      <form className="row" onSubmit={setPw}>
        <input
          type="password"
          autoComplete="new-password"
          minLength={12}
          placeholder="New password (12+ characters)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <button className="btn">Set password</button>
        <button type="button" className="btn" onClick={makeLink}>
          Create reset link
        </button>
      </form>
      {link && (
        <div className="row">
          <input readOnly value={link} onFocus={(e) => e.target.select()} />
          <button type="button" className="btn" onClick={() => navigator.clipboard?.writeText(link)}>
            Copy
          </button>
        </div>
      )}
      <form className="row" onSubmit={remove}>
        <input
          placeholder={`Type ${u.email} to delete`}
          value={confirmEmail}
          onChange={(e) => setConfirmEmail(e.target.value)}
          autoComplete="off"
        />
        <button className="btn danger" disabled={confirmEmail.trim().toLowerCase() !== u.email}>
          Delete user and all data
        </button>
      </form>
      {msg?.ok && <div className="ok small">{msg.ok}</div>}
      {msg?.error && <div className="error small">{msg.error}</div>}
    </div>
  );
}

function bytes(n) {
  if (n == null) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function Storage({ rev }) {
  const s = useApi(`/api/admin/storage?rev=${rev}`);
  if (s.error) return <div className="error">{s.error.message}</div>;
  if (!s.data) return null;
  const { disk } = s.data;
  return (
    <section className="card">
      <h2>Storage</h2>
      <div className="stats">
        <Stat label="Database" value={bytes(s.data.database_bytes)} />
        <Stat label="Disk free" value={bytes(disk.free)} />
        <Stat label="Disk used" value={`${Math.round((disk.used / disk.total) * 100)}%`} />
      </div>
      <div className="table-wrap">
        <table>
          <tbody>
            {Object.entries(s.data.tables).map(([name, count]) => (
              <tr key={name}>
                <td>{name}</td>
                <td className="num">{count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">
        Files: {Object.entries(s.data.files).map(([f, n]) => `${f} ${bytes(n)}`).join(" · ")} · in {disk.path}
      </p>
    </section>
  );
}

function AiUsage({ rev }) {
  const u = useApi(`/api/admin/ai-usage?rev=${rev}`);
  if (!u.data) return null;
  return (
    <section className="card">
      <h2>AI use this month</h2>
      <p className="muted small">
        Limit: {u.data.limit ? `${u.data.limit} requests per user` : "none"} (change it under Settings → AI coach).
      </p>
      {u.data.users.length === 0 ? (
        <p className="muted">No AI requests yet this month.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th className="num">Requests</th>
                <th className="num">Tokens in</th>
                <th className="num">Tokens out</th>
              </tr>
            </thead>
            <tbody>
              {u.data.users.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td className="num">
                    {r.calls}
                    {u.data.limit ? ` / ${u.data.limit}` : ""}
                  </td>
                  <td className="num">{r.input_tokens.toLocaleString()}</td>
                  <td className="num">{r.output_tokens.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
