import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import Activities from "../components/ActivitiesTable.jsx";
import FitnessChart from "../components/FitnessChart.jsx";
import UpcomingRaces from "../components/UpcomingRaces.jsx";
import VolumeStats from "../components/VolumeStats.jsx";
import WellnessPanel, { Stat } from "../components/WellnessPanel.jsx";
import { useApi } from "../hooks/useApi.js";
import { dateTime, formLabel } from "../lib/format.js";
import PlansPanel from "./PlansPanel.jsx";

const TABS = [
  { id: "overview", label: "Overview", needs: ["activities", "fitness", "wellness", "plans"] },
  { id: "activities", label: "Activities", needs: ["activities"] },
  { id: "plans", label: "Plans & AI coach", needs: ["plans"] },
];

export default function AthleteView({ self }) {
  const params = useParams();
  const id = self ? "me" : params.athleteId;
  const summary = useApi(`/api/athletes/${id}`);
  const [tab, setTab] = useState("overview");

  if (summary.loading) return <p className="muted">Loading…</p>;
  if (summary.error) return <div className="error">{summary.error.message}</div>;

  const s = summary.data;
  const scopes = new Set(s.scopes);
  const tabs = TABS.filter((t) => t.needs.some((n) => scopes.has(n)));
  const current = tabs.find((t) => t.id === tab) ? tab : tabs[0]?.id;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{self ? "My training" : s.display_name}</h1>
          <p className="muted small">
            {s.sources.length
              ? s.sources.map((src) => `${src.provider}: synced ${dateTime(src.last_sync_at)}`).join(" · ")
              : "No data sources connected."}{" "}
            {self && !s.sources.length && <Link to="/connections">Connect Strava or Garmin</Link>}
          </p>
          {!self && <p className="small muted">Shared with you: {s.scopes.join(", ")}</p>}
        </div>
      </div>
      <div className="tabs">
        {tabs.map((t) => (
          <button key={t.id} className={current === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      {current === "overview" && <Overview id={id} scopes={scopes} isMe={!!self} />}
      {current === "activities" && <Activities id={id} editable={!!self} />}
      {current === "plans" && <PlansPanel id={id} athlete={s} />}
    </>
  );
}

function Overview({ id, scopes, isMe }) {
  const fitness = useApi(scopes.has("fitness") ? `/api/athletes/${id}/fitness?days=120` : null);
  const wellness = useApi(scopes.has("wellness") ? `/api/athletes/${id}/wellness?days=30` : null);
  const today = fitness.data?.[fitness.data.length - 1];
  return (
    <>
      {scopes.has("plans") && <UpcomingRaces id={id} isMe={isMe} ctl={today?.ctl} />}
      {scopes.has("activities") && <VolumeStats id={id} />}
      {scopes.has("fitness") && (
        <section className="card">
          <h2>Training load</h2>
          <div className="stats">
            <Stat label="Fitness (CTL)" value={today?.ctl} />
            <Stat label="Fatigue (ATL)" value={today?.atl} />
            <Stat label="Form (TSB)" value={today?.tsb} />
            <Stat label="Status" value={formLabel(today?.tsb)} />
          </div>
          {fitness.error ? <div className="error">{fitness.error.message}</div> : <FitnessChart data={fitness.data} />}
        </section>
      )}
      {scopes.has("wellness") && (
        <section className="card">
          <h2>Wellness (last 30 days)</h2>
          {wellness.error ? <div className="error">{wellness.error.message}</div> : <WellnessPanel rows={wellness.data} />}
        </section>
      )}
    </>
  );
}
