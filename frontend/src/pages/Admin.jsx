import { CheckCircle2, KeyRound, XCircle } from "lucide-react";
import { useState } from "react";
import { Stat } from "../components/WellnessPanel.jsx";
import { useApi } from "../hooks/useApi.js";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { dateTime } from "../lib/format.js";

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
      <Storage rev={rev} />
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

function Users({ onChange }) {
  const { user: me } = useAuth();
  const users = useApi("/api/admin/users");
  const [open, setOpen] = useState(null);
  const [error, setError] = useState(null);
  const update = (u, body) => {
    setError(null);
    api(`/api/admin/users/${u.id}`, { method: "PATCH", body }).then(users.reload, (e) => setError(e.message));
  };
  return (
    <section className="card">
      <h2>Users</h2>
      {error && <div className="error">{error}</div>}
      {users.data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Joined</th>
                <th>Admin</th>
                <th>Active</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.data.map((u) => (
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
        </div>
      )}
    </section>
  );
}

function UserRow({ u, isMe, open, toggle, update, reload }) {
  return (
    <>
      <tr>
        <td>{u.display_name}</td>
        <td>{u.email}</td>
        <td>{dateTime(u.created_at)}</td>
        <td>
          <input type="checkbox" checked={u.is_admin} disabled={isMe} onChange={(e) => update(u, { is_admin: e.target.checked })} />
        </td>
        <td>
          <input
            type="checkbox"
            checked={u.is_active}
            disabled={isMe}
            onChange={(e) =>
              (e.target.checked || confirm(`Disable ${u.display_name}? They are signed out at once.`)) &&
              update(u, { is_active: e.target.checked })
            }
          />
        </td>
        <td>
          {!isMe && (
            <button className="link-btn small" onClick={toggle}>
              {open ? "Close" : "Manage"}
            </button>
          )}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={6} className="manage-cell">
            <ManageUser u={u} reload={reload} />
          </td>
        </tr>
      )}
    </>
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
