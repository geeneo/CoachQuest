import { Stat } from "../components/WellnessPanel.jsx";
import { useApi } from "../hooks/useApi.js";

export default function Admin() {
  const stats = useApi("/api/admin/stats");
  const version = useApi("/api/admin/version");
  const s = stats.data;
  return (
    <>
      <h1>Admin</h1>
      <p className="muted small">
        API build {version.data?.commit} {version.data?.built} · frontend build {import.meta.env.VITE_BUILD_COMMIT || "dev"}
      </p>
      {stats.error && <div className="error">{stats.error.message}</div>}
      {s && (
        <section className="card">
          <div className="stats">
            <Stat label="Users" value={s.users} />
            <Stat label="Strava links" value={s.connections.strava || 0} />
            <Stat label="Garmin links" value={s.connections.garmin || 0} />
            <Stat label="Sync errors" value={s.connection_errors} />
            <Stat label="AI plans ok" value={s.ai_calls.ok || 0} />
            <Stat label="AI tokens in / out" value={`${s.ai_tokens.input} / ${s.ai_tokens.output}`} />
          </div>
          <pre className="facts">{JSON.stringify(s.ai_calls, null, 2)}</pre>
        </section>
      )}
    </>
  );
}
