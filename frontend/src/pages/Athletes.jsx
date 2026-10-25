import { Link } from "react-router-dom";
import { useApi } from "../hooks/useApi.js";
import { formLabel } from "../lib/format.js";

export default function Athletes() {
  const athletes = useApi("/api/athletes");
  return (
    <>
      <h1>My athletes</h1>
      <p className="muted">
        Athletes who shared their data with you. Pending invitations are on the <Link to="/sharing">Sharing</Link> page.
      </p>
      {athletes.error && <div className="error">{athletes.error.message}</div>}
      {athletes.data?.length === 0 && <p className="muted">Nobody has shared with you yet.</p>}
      <div className="cards">
        {athletes.data?.map((a) => (
          <Link key={a.id} to={`/athletes/${a.id}`} className="card athlete-card">
            <h2>{a.display_name}</h2>
            {a.today ? (
              <p>
                CTL {a.today.ctl} · ATL {a.today.atl} · TSB {a.today.tsb}{" "}
                <span className="badge">{formLabel(a.today.tsb)}</span>
              </p>
            ) : (
              <p className="muted small">Fitness not shared</p>
            )}
            <p className="muted small">Shares: {a.scopes.join(", ")}</p>
          </Link>
        ))}
      </div>
    </>
  );
}
