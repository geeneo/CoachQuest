import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Markdown from "../components/Markdown.jsx";
import { PlanApproval, PlanHistory } from "../components/PlanApproval.jsx";
import PlanTracker from "../components/PlanTracker.jsx";
import { useApi } from "../hooks/useApi.js";
import { useAuth } from "../lib/auth.jsx";
import { dateTime, formatDate } from "../lib/format.js";

export default function PlanView() {
  const { athleteId, planId } = useParams();
  const { user } = useAuth();
  const plan = useApi(`/api/athletes/${athleteId}/plans/${planId}`);
  const back = String(user.id) === athleteId ? "/" : `/athletes/${athleteId}`;
  const [p, setP] = useState(null);
  useEffect(() => {
    setP(plan.data);
  }, [plan.data]);

  if (plan.loading && !p) return <p className="muted">Loading…</p>;
  if (plan.error) return <div className="error">{plan.error.message}</div>;
  if (!p) return null;
  return (
    <>
      <Link to={back} className="small">
        <ArrowLeft size={14} /> Back
      </Link>
      <h1>{p.title}</h1>
      <p className="muted small">
        {p.request.goal} · {p.request.weeks} weeks
        {p.start_date ? ` from ${formatDate(p.start_date)}` : ""} · {p.request.hours_per_week} h/week · by {p.author} ·{" "}
        {dateTime(p.created_at)} · {p.model}
      </p>
      <PlanApproval plan={p} athleteId={athleteId} setPlan={setP} />
      <PlanHistory plan={p} />
      {p.facts?.flags?.length > 0 && (
        <div className="card flags">
          <strong>Readiness flags (computed from data)</strong>
          <ul>
            {p.facts.flags.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
      )}
      {p.weeks ? (
        <PlanTracker plan={p} athleteId={athleteId} setPlan={setP} />
      ) : (
        <article className="card">
          <Markdown>{p.content_md}</Markdown>
        </article>
      )}
      <details className="card">
        <summary>Data sent to the AI coach</summary>
        <pre className="facts">{JSON.stringify(p.facts, null, 2)}</pre>
      </details>
    </>
  );
}
