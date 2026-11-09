import { useState } from "react";
import { api } from "../lib/api.js";

// Pick one of the athlete's routes: their saved routes (Routes page), and their Strava routes and starred
// segments that aren't saved yet (loaded when the list is opened). A Strava one is saved first
// (POST /segments/from-strava), then picked. onPick gets the saved route's id, or null for none.
export default function RoutePicker({
  athleteId = "me",
  saved,
  value,
  onPick,
  onSaved,
  stravaLinked,
  routesOnly = false,
  label = "Route",
  autoFocus = false,
}) {
  const base = `/api/athletes/${athleteId}/segments`;
  const [strava, setStrava] = useState(null); // null = not loaded, "loading", or the list
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const keep = (x) => !routesOnly || x.kind !== "segment"; // routes and rides saved as routes
  // Routes tagged "race" (Routes page) first: they're the likely race courses.
  const raceFirst = (x) => (routesOnly && x.uses?.includes("race") ? 0 : 1);
  const mine = saved.filter(keep).sort((a, b) => raceFirst(a) - raceFirst(b));

  const loadStrava = async () => {
    if (!stravaLinked || strava !== null) return;
    setStrava("loading");
    try {
      setStrava((await api(`${base}/strava`)).found.filter(keep));
    } catch (e) {
      setStrava([]);
      setError(e.message);
    }
  };

  const pick = async (raw) => {
    setError(null);
    if (!raw) return onPick(null);
    if (!raw.startsWith("strava:")) return onPick(Number(raw));
    const [, kind, id] = raw.split(":");
    setBusy(true);
    try {
      const { added } = await api(`${base}/from-strava`, {
        method: "POST",
        body: { items: [{ kind, strava_id: id }], uses: kind === "route" ? ["endurance"] : [] },
      });
      if (!added.length) throw new Error("Strava didn't return that route; try again");
      setStrava((list) => (Array.isArray(list) ? list.filter((f) => f.strava_id !== id) : list));
      await onSaved?.();
      onPick(added[0].id);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const km = (m) => (m ? ` · ${Math.round(m / 1000)} km` : "");
  return (
    <>
      <select
        aria-label={label}
        autoFocus={autoFocus}
        disabled={busy}
        value={value ? String(value) : ""}
        onFocus={loadStrava}
        onMouseDown={loadStrava}
        onChange={(e) => pick(e.target.value)}
      >
        <option value="">– no route –</option>
        {mine.length > 0 && (
          <optgroup label="My saved routes">
            {mine.map((s) => (
              <option key={s.id} value={s.id}>
                {s.uses?.includes("race") ? "🏁" : s.kind === "segment" ? "⛰" : "🗺"} {s.name}
                {km(s.distance_m)}
              </option>
            ))}
          </optgroup>
        )}
        {stravaLinked && (
          <optgroup label="My Strava routes (saved when picked)">
            {strava === null || strava === "loading" ? (
              <option disabled value="loading">
                Loading from Strava…
              </option>
            ) : strava.length === 0 ? (
              <option disabled value="none">
                None that aren't saved already
              </option>
            ) : (
              strava.map((f) => (
                <option key={`${f.kind}${f.strava_id}`} value={`strava:${f.kind}:${f.strava_id}`}>
                  {f.kind === "segment" ? "⛰" : "🗺"} {f.name}
                  {km(f.distance_m)}
                </option>
              ))
            )}
          </optgroup>
        )}
      </select>
      {busy && <span className="muted small"> Saving the route…</span>}
      {error && <span className="error small"> {error}</span>}
    </>
  );
}
