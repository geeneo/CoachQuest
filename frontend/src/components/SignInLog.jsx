import { useState } from "react";
import { useApi } from "../hooks/useApi.js";
import { dateTime } from "../lib/format.js";

// "Firefox on Windows" from a user-agent string; good enough to recognise your own devices.
export function browser(ua) {
  if (!ua) return "–";
  const name = /Edg\//.test(ua)
    ? "Edge"
    : /Firefox\//.test(ua)
      ? "Firefox"
      : /Chrome\//.test(ua)
        ? "Chrome"
        : /Safari\//.test(ua)
          ? "Safari"
          : ua.split(/[ /]/)[0];
  const os = /Windows/.test(ua)
    ? "Windows"
    : /iPhone|iPad/.test(ua)
      ? "iOS"
      : /Android/.test(ua)
        ? "Android"
        : /Mac OS/.test(ua)
          ? "Mac"
          : /Linux/.test(ua)
            ? "Linux"
            : "";
  return os ? `${name} on ${os}` : name;
}

function Rows({ events, showWho }) {
  return (
    <div className="table-wrap">
      <table className="compact sign-ins">
        <thead>
          <tr>
            <th>When</th>
            <th>What</th>
            {showWho && <th>Account</th>}
            <th>IP address</th>
            <th>Browser</th>
            {showWho && <th></th>}
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id} className={e.failed ? "failed" : ""}>
              <td className="small">{dateTime(e.at)}</td>
              <td className={e.failed ? "error-text" : ""}>{e.label}</td>
              {showWho && <td className="small">{e.email || "–"}</td>}
              <td className="small">{e.ip || "–"}</td>
              <td className="small" title={e.user_agent}>
                {browser(e.user_agent)}
              </td>
              {showWho && <td className="small muted">{e.detail}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Admin > Sign-ins: everyone's sign-ins, failed attempts and account events.
export function AdminSignIns() {
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [failed, setFailed] = useState(false);
  const [days, setDays] = useState(30);
  const res = useApi(`/api/admin/sign-ins?q=${encodeURIComponent(search)}&failed=${failed}&days=${days}`);
  const keep = res.data?.keep_days;
  return (
    <section className="card">
      <h2>Sign-ins</h2>
      <p className="muted small">
        Sign-ins, failed attempts, sign-outs, password changes and admin actions on accounts.{" "}
        {keep && keep !== "0" ? `Kept for ${keep} days, then deleted` : "Kept until deleted by hand"} (Settings →
        Accounts). Attempts blocked by the rate limit don't reach CoachQuest, so they aren't listed.
      </p>
      <form
        className="row wrap"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(q);
        }}
      >
        <input placeholder="Email or IP address" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[1, 7, 30, 90, 365].map((d) => (
            <option key={d} value={d}>
              Last {d === 1 ? "day" : `${d} days`}
            </option>
          ))}
        </select>
        <label className="check">
          <input type="checkbox" checked={failed} onChange={(e) => setFailed(e.target.checked)} /> Failed only
        </label>
        <button className="btn small">Search</button>
      </form>
      {res.error && <div className="error">{res.error.message}</div>}
      {res.data && (res.data.events.length ? <Rows events={res.data.events} showWho /> : <p className="muted">Nothing here.</p>)}
    </section>
  );
}

// Profile > Security: your own recent sign-ins.
export function MySignIns() {
  const res = useApi("/api/auth/sign-ins");
  if (!res.data?.length) return null;
  return (
    <>
      <h3>Recent sign-ins</h3>
      <p className="muted small">
        If one wasn't you, change your password and use "Sign out everywhere".
      </p>
      <Rows events={res.data.slice(0, 10)} />
    </>
  );
}
