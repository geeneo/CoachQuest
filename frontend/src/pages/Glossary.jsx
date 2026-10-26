// What the acronyms and metrics in CoachQuest mean, including the exact rules CoachQuest applies.
const TERMS = [
  ["Training load", [
    ["TSS", "Training Stress Score",
      "How much training stress one session caused, scaled so one hour at FTP = 100. CoachQuest works it out from power (NP vs FTP) when there is power, otherwise from heart rate vs LTHR, otherwise Strava's Relative Effort, otherwise 50 per hour. Set FTP and LTHR in Profile for accurate numbers."],
    ["CTL", "Chronic Training Load (\"Fitness\")",
      "A 42-day exponentially weighted average of daily TSS. It moves slowly on purpose: it's the aerobic fitness you've banked from weeks of consistent training."],
    ["ATL", "Acute Training Load (\"Fatigue\")",
      "A 7-day exponentially weighted average of daily TSS. It reacts fast — a few big days spike it. It shows how tired you are from recent training."],
    ["TSB", "Training Stress Balance (\"Form\")",
      "Yesterday's CTL minus ATL. Positive means fresh; around -10 to -30 is a normal building block; below -30 CoachQuest flags high fatigue. Tapering before a race pushes TSB positive on purpose."],
    ["Ramp", "CTL change per week",
      "How fast fitness is rising. CoachQuest flags a rise of more than 7 CTL in 7 days as an injury and illness risk."],
    ["Target CTL", "Fitness you want on race day",
      "Set per race on the Races page, or set a target finish time and let the AI coach suggest one. Progress projects your CTL at the race date from your current ramp and says whether you're on track (within 3)."],
  ]],
  ["Effort and power", [
    ["RE", "Relative Effort",
      "Strava's intensity score for a session, from heart rate zones and duration. A short hard interval session and a long easy ride can score alike. Badges: green under 100, amber 100-180, red over 180."],
    ["FTP", "Functional Threshold Power",
      "The highest average power (watts) you can hold for about an hour. The reference for power zones and power-based TSS."],
    ["NP", "Normalized Power",
      "A weighted average power that counts hard efforts more than easy riding, so it reflects the real cost of a surgy ride. On a steady ride NP ≈ average power."],
    ["IF", "Intensity Factor",
      "NP ÷ FTP. Roughly: under 0.75 endurance (Z2), 0.75-0.85 tempo / sweet spot, 0.85-0.95 threshold, above 0.95 VO2max or a hard race."],
    ["W/kg", "Watts per kilogram",
      "FTP divided by body weight. Compares riders of different sizes and predicts climbing speed better than raw watts."],
    ["Z1-Z5", "Training zones",
      "Z1 recovery, Z2 endurance, Z3 tempo, Z4 threshold, Z5 VO2max. Plans give zones and, when FTP or LTHR is known, watts or bpm ranges."],
    ["Cadence", "Pedal or step rate",
      "Revolutions per minute (rpm) on the bike, steps per minute (spm) for runs and walks."],
  ]],
  ["Heart and recovery", [
    ["LTHR", "Lactate Threshold Heart Rate",
      "The heart rate you can hold for about an hour, the heart-rate counterpart of FTP. Used for heart-rate TSS when a session has no power."],
    ["HRV", "Heart Rate Variability",
      "The variation between heartbeats, measured overnight by Garmin. Higher than your own normal usually means recovered; a sharp drop can flag fatigue, illness or poor sleep before you feel it."],
    ["RHR", "Resting Heart Rate",
      "Measured overnight. A rise of several beats over your personal baseline is one of the earliest signs of fatigue, illness or dehydration."],
    ["Body Battery", "Garmin's energy reserve score",
      "0-100, combining HRV, stress, sleep and activity. Drains during stress and training, refills with rest and good sleep."],
    ["Sleep score", "Garmin's sleep quality score",
      "0-100 from duration, sleep stages and restlessness: whether last night was actually restorative, not just long."],
  ]],
  ["CoachQuest", [
    ["Readiness", "Go / Easy / Rest",
      "Decided in code each morning, then explained by the AI coach. Easy if: HRV under 93% of your 30-day normal, resting HR 4+ above normal, under 5.5 h sleep (or sleep score under 50), Body Battery peak under 40, or TSB under -30. Rest if HRV is under 85% of normal, resting HR is 7+ above normal, or three or more Easy signs show at once."],
    ["Outdoor elevation", "Climbing done outside",
      "Total elevation minus virtual rides and treadmill runs, which report climbing that wasn't real terrain. Shown in brackets after total elevation."],
    ["Calories", "kcal burned",
      "As recorded by Garmin. For Strava rides without a calorie figure, CoachQuest uses the ride's kilojoules of work, which is about equal to kcal burned for cycling."],
    ["Goal met", "Plan vs actual",
      "A planned day counts as goal met when the logged time is at least 70% of the planned time; less is partly done. Past training days with nothing logged show Not logged, where you can pick why from your note tags."],
    ["Note tags", "Why a session was different",
      "Illness, travel, mechanical, weather... set on an activity or a missed day. The AI coach reads them as explained, not as fitness to chase."],
    ["Virtual / Indoor", "Trainer and app sessions",
      "Zwift, MyWhoosh and other trainer rides, or a ride marked as on a trainer. Counted for load and time, but not for outdoor elevation."],
  ]],
];

export default function Glossary() {
  return (
    <>
      <h1>Glossary</h1>
      <p className="muted">What the acronyms and metrics in CoachQuest mean, and the exact rules CoachQuest applies.</p>
      {TERMS.map(([group, items]) => (
        <section key={group}>
          <h2 className="glossary-group">{group}</h2>
          <div className="glossary">
            {items.map(([abbr, name, text]) => (
              <article key={abbr} className="card glossary-card" id={abbr.toLowerCase().replace(/[^a-z0-9]+/g, "-")}>
                <h3>
                  <span className="badge ok">{abbr}</span> {name}
                </h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
