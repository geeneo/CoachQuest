import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { SCOPE_LABELS, dateTime, duration, formLabel } from "../lib/format.js";

const SORTS = {
  attention: ["Needs attention", (a, b) => b.attention - a.attention || a.name.localeCompare(b.name)],
  name: ["Name", (a, b) => a.name.localeCompare(b.name)],
  compliance: [
    "Compliance (lowest first)",
    (a, b) => (a.week?.compliance_pct ?? 101) - (b.week?.compliance_pct ?? 101) || a.name.localeCompare(b.name),
  ],
  form: ["Form (most tired first)", (a, b) => (a.load?.tsb ?? 999) - (b.load?.tsb ?? 999)],
};
const READINESS = { go: ["Go", "ok"], easy: ["Easy", "warn"], rest: ["Rest", "bad"] };
// Same emoji as the calendar and plan days (TrainingCalendar STATUS, lib/dayStatus.js).
const WORKOUT_STATUS = { done: "✅", partial: "⚠️", missed: "❌", today: "🎯", planned: "•", skipped: "⏭️", cancelled: "🚫" };

// My athletes: every athlete's training week on one page (coach dashboard).
export default function Athletes() {
  const [me, setMe] = useState(false);
  const res = useApi(`/api/coach/dashboard${me ? "?me=true" : ""}`);
  const [sort, setSort] = useState("attention");
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const navigate = useNavigate();
  const rows = [...(res.data || [])]
    .filter((r) => !onlyFlagged || r.flags.length)
    .sort(SORTS[sort][1]);

  return (
    <>
      <h1>My athletes</h1>
      <p className="muted">
        This week for everyone who shares with you, those needing a look first. Each column shows only what that athlete
        shares. Pending invitations are on the <Link to="/sharing">Sharing</Link> page.
      </p>
      <div className="row wrap dash-controls">
        <label className="inline">
          Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            {Object.entries(SORTS).map(([k, [label]]) => (
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
        <label className="check">
          <input type="checkbox" checked={me} onChange={(e) => setMe(e.target.checked)} /> Include me
        </label>
        <button className="btn small" onClick={res.reload}>
          Refresh
        </button>
      </div>
      {res.error && <div className="error">{res.error.message}</div>}
      {res.loading && !res.data && <p className="muted">Loading…</p>}
      {res.data?.length === 0 && <p className="muted">No athletes have you as their coach yet.</p>}
      {rows.length > 0 && (
        <div className="table-wrap card dash">
          <table className="dashboard">
            <thead>
              <tr>
                <th>Athlete</th>
                <th>This week</th>
                <th>Today</th>
                <th>Readiness</th>
                <th>Form</th>
                <th>Volume</th>
                <th>Next race</th>
                <th>Comments</th>
                <th>Flags</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) =>
                r.disabled ? (
                  <tr key={r.id} className="muted">
                    <td>
                      <strong>{r.name}</strong>
                    </td>
                    <td colSpan={8} className="small">
                      Account paused: nothing is shared while it's off.
                    </td>
                  </tr>
                ) : (
                <tr
                  key={r.id}
                  className={`clickable ${r.attention >= 3 ? "attention" : ""}`}
                  onClick={() => navigate(r.is_me ? "/" : `/athletes/${r.id}`)}
                >
                  <td>
                    <strong>{r.name}</strong>
                    {r.is_me && <span className="muted"> (you)</span>}
                    <div className="small muted">
                      {r.last_sync_at ? `synced ${dateTime(r.last_sync_at)}` : "never synced"}
                    </div>
                  </td>
                  <td>{r.week ? <Week w={r.week} /> : <NotShared />}</td>
                  <td className="small">
                    {r.week ? (
                      <>
                        {r.today_plan && <div>{r.today_plan.type === "Rest" ? "Rest day" : r.today_plan.type}</div>}
                        {r.today_workouts.map((w) => (
                          <div key={w.id}>
                            {WORKOUT_STATUS[w.status]} {w.name}
                          </div>
                        ))}
                        {!r.today_plan && !r.today_workouts.length && <span className="muted">Nothing planned</span>}
                      </>
                    ) : (
                      <NotShared />
                    )}
                  </td>
                  <td>
                    {"readiness" in r ? (
                      r.readiness ? (
                        <span className={`badge ${READINESS[r.readiness]?.[1] || ""}`}>
                          {READINESS[r.readiness]?.[0] || r.readiness}
                        </span>
                      ) : (
                        <span className="muted small">No check today</span>
                      )
                    ) : (
                      <NotShared />
                    )}
                  </td>
                  <td className="small">
                    {r.load ? (
                      <>
                        <div>
                          TSB {r.load.tsb} · {formLabel(r.load.tsb)}
                        </div>
                        <div className="muted">
                          CTL {r.load.ctl} ({r.load.ctl_change_7d >= 0 ? "+" : ""}
                          {r.load.ctl_change_7d} in 7 days)
                        </div>
                      </>
                    ) : (
                      <NotShared />
                    )}
                  </td>
                  <td className="small">
                    {r.volume ? (
                      <>
                        {r.volume.minutes ? duration(r.volume.minutes * 60) : "0m"} · {r.volume.km} km
                        <div className="muted">
                          {r.volume.activities} {r.volume.activities === 1 ? "activity" : "activities"}
                        </div>
                      </>
                    ) : (
                      <NotShared />
                    )}
                  </td>
                  <td className="small">
                    {r.next_race ? (
                      <>
                        {r.next_race.name}
                        <div className="muted">in {r.next_race.days_to_go} days</div>
                      </>
                    ) : (
                      <span className="muted">–</span>
                    )}
                  </td>
                  <td className="small">{r.new_comments ? `💬 ${r.new_comments} new` : <span className="muted">–</span>}</td>
                  <td>
                    <div className="chips tight">
                      {r.flags.map((f) => (
                        <span key={f} className="badge bad">
                          {f}
                        </span>
                      ))}
                      {!r.flags.length && <span className="muted small">–</span>}
                    </div>
                  </td>
                </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">
        "New" comments are from the last 7 days, not counting yours. Click a row to open the athlete.
      </p>
      <FriendsSharing />
    </>
  );
}

function Week({ w }) {
  if (!w.scheduled) return <span className="muted small">No workouts scheduled</span>;
  const pct = w.compliance_pct;
  return (
    <div className="small">
      <div>
        <strong>{w.done}</strong>
        {w.partial ? ` + ${w.partial} partly` : ""} of {w.scheduled} done
        {w.upcoming ? <span className="muted"> · {w.upcoming} to come</span> : null}
      </div>
      <div className="muted">
        {w.actual_min ? duration(w.actual_min * 60) : "0m"} of {duration(w.planned_min * 60)}
        {pct != null && (
          <>
            {" · "}
            <span className={pct >= 80 ? "ok-text" : pct >= 50 ? "warn-text" : "error-text"}>{pct}%</span>
          </>
        )}
      </div>
    </div>
  );
}

function NotShared() {
  return <span className="muted small" title="Not shared with you">—</span>;
}

// Friends who let me look at their data (view only), apart from the athletes I coach.
function FriendsSharing() {
  const res = useApi("/api/athletes");
  const friends = (res.data || []).filter((a) => a.role === "friend");
  if (!friends.length) return null;
  return (
    <section className="card">
      <h2>Friends sharing with me (view only)</h2>
      <ul className="list">
        {friends.map((f) => (
          <li key={f.id}>
            {f.disabled ? (
              <span className="muted">{f.display_name} (account paused)</span>
            ) : (
              <Link to={`/athletes/${f.id}`}>{f.display_name}</Link>
            )}
            <span className="muted small">{f.scopes.map((s) => SCOPE_LABELS[s] || s).join(", ")}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
