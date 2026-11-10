// What the acronyms and metrics in CoachQuest mean, including the exact rules CoachQuest applies.
const TERMS = [
  ["Training load", [
    ["TSS", "Training Stress Score",
      "How much training stress one session caused, scaled so one hour at FTP = 100. Rides: power (NP vs FTP) when there is power, else heart rate (hrTSS), else Strava's Relative Effort, else 50 an hour. Runs: power vs your run threshold power, else heart rate. Strength, yoga and other workouts: heart rate, 0 without it. Walks and hikes: heart rate × 0.65. Each workout uses the FTP and LTHR of its own date (Threshold history). Set FTP and LTHR in Profile for accurate numbers."],
    ["hrTSS", "Heart-rate TSS (time in zones)",
      "For sessions without power, as TrainingPeaks scores them: every second counts by its share of your LTHR (zone 1 about 30-50 an hour, zone 2 about 50-60, zone 3 about 60-70, zone 4 about 70-90, an hour at LTHR 100, zone 5 more). Hard efforts count more than an easy hour with the same average. Until a session's heart-rate stream is fetched (within hours of syncing), it's scored from its average heart rate."],
    ["Daily TSS", "The red dots on the chart",
      "The day's total TSS, on its own scale on the right of the Training Load & Fitness Metrics chart. Hollow dots are planned sessions."],
    ["CTL", "Chronic Training Load (\"Fitness\")",
      "A 42-day exponentially weighted average of daily TSS, counted from your first training day as TrainingPeaks does, so every period shows the same value. It moves slowly on purpose: it's the aerobic fitness you've banked from weeks of consistent training. Until you've trained today, the tiles show the value at the end of yesterday."],
    ["ATL", "Acute Training Load (\"Fatigue\")",
      "A 7-day exponentially weighted average of daily TSS. It reacts fast — a few big days spike it. It shows how tired you are from recent training."],
    ["TSB", "Training Stress Balance (\"Form\")",
      "Yesterday's CTL minus ATL, as TrainingPeaks defines it (Intervals.icu uses today's, so its form can differ by a point or two). Shown in yellow. Positive means fresh; around -10 to -30 is a normal building block; below -30 CoachQuest flags high fatigue. Tapering before a race pushes TSB positive on purpose: a race wants about +5 to +15."],
    ["Status", "What your form means",
      "Very fresh above +15, Fresh +5 to +15, Neutral -10 to +5 (adapted to your training), Building -30 to -10 (training stress you're adapting to), Overreaching below -30."],
    ["Projection", "Planned ahead (dashed lines)",
      "Where fitness, fatigue and form go if you follow your plan, from the planned sessions' TSS: up to your next race when it's within 8 weeks (🏁), otherwise two weeks. Like TrainingPeaks' projected chart."],
    ["Ramp", "CTL change per week",
      "How fast fitness is rising. CoachQuest flags a rise of more than 7 CTL in 7 days as an injury and illness risk."],
    ["Target CTL", "Fitness you want on race day",
      "Set per race on the Races page, or set a target finish time and let the AI coach suggest one. Progress projects your CTL at the race date from your current ramp and says whether you're on track (within 3)."],
  ]],
  ["Racing", [
    ["Taper", "The last 14 days before a race",
      "The morning note lists every day to the race from your plan, flags what breaks the taper rules (no strength in the last 10 days, at most 90 minutes a session in race week, race week at most 60% and the week before 85% of a usual week) and works out your race-morning form. AI coach → Taper for <race> → Make these changes puts the changes in your plan; locked days stay as they are."],
    ["Race-morning form", "TSB on race day",
      "Your form the morning of the race if you follow the plan as it is, and with the taper changes. Aim for about +5 to +15 for a one-day race."],
    ["Go / no-go", "When to make a session easy",
      "From your own 30-day baselines: easy if HRV is under 93% of normal or resting HR 4+ bpm above; rest if HRV under 85% or resting HR 7+ above. Don't make up a session you made easy."],
    ["Race day", "A plan day linked to a race",
      "Set a day's type to Race and pick the race: it's locked, shows the race and rides its route. A race after your plan ends: Add race day to the plan."],
    ["Race route", "The course a race is ridden on",
      "Set on the Races page (Route) or Routes → Race routes, from your saved routes or your Strava routes. Its heights feed the pacing; it's tagged race on the Routes page with a 🏁 badge."],
    ["Riding", "Solo, team or bunch",
      "How a race is ridden. A team sharing the work (e.g. the DC) has about 25% less drag than alone, a bunch about 35%. The target-time estimate and the pacing use it."],
    ["Pacing plan", "Your target time on the race route",
      "Races → gauge button: average speed and power, checkpoints every 25 km with the time of day, and each climb with a target power (up to 15% more on climbs, less on descents)."],
    ["Virtual Partner", "Garmin Edge: ahead or behind your plan",
      "The pacing course (.fit) has the planned time at every point; copied to your Edge (Garmin/NewFiles) its Virtual Partner rides your plan. ClimbPro on the Edge shows each climb's length and gradient."],
  ]],
  ["Effort and power", [
    ["RE", "Relative Effort",
      "Strava's intensity score for a session, from heart rate zones and duration. A short hard interval session and a long easy ride can score alike. Badges: green under 100, amber 100-180, red over 180."],
    ["FTP", "Functional Threshold Power",
      "The highest average power (watts) you can hold for about an hour. The reference for power zones and power-based TSS."],
    ["Run threshold power", "FTP for running",
      "Running power (watch or footpod) you can hold for about an hour. Runs with power are scored against it, not your cycling FTP; runs use heart rate until it's set."],
    ["Threshold history", "Each workout keeps its FTP",
      "Earlier FTP, run threshold power and LTHR values with their dates (Profile). A change counts from today, as on TrainingPeaks; tick Correct earlier workouts too when the old value was simply wrong."],
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
    ["Weight trend", "Weight from occasional weigh-ins",
      "A smoothed line through your weigh-ins (Garmin, Intervals.icu, or typed in Profile) that ignores the day-to-day swings of water and food; a weigh-in after a gap counts for more. The tile shows the trend and its change over 30 days."],
  ]],
  ["CoachQuest", [
    ["Readiness", "Go / Easy / Rest",
      "Decided in code each morning, then explained by the AI coach. Easy if: HRV under 93% of your 30-day normal, resting HR 4+ above normal, under 5.5 h sleep (or sleep score under 50), Body Battery peak under 40, or TSB under -30 (under -15 in the two weeks before a race). Rest if HRV is under 85% of normal, resting HR is 7+ above normal, or three or more Easy signs show at once."],
    ["Morning note", "Readiness at your own time",
      "AI coach → Automatic notes: sent at the time you pick, once last night's sleep or HRV is in (CoachQuest syncs your Garmin for it and waits up to the time you set), else on training load alone. If the sleep comes in later and changes the verdict, a short update follows."],
    ["Evening preview", "Tomorrow, the night before",
      "An email at the time you pick: tomorrow's session and a verdict on training load alone. Worked out in code, so it doesn't count toward your AI allowance."],
    ["Weigh-in reminder", "A weekly nudge",
      "Pick a day: that morning's note (and the evening preview the night before) reminds you to weigh in, and the next morning if you missed it."],
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
    ["Duplicates", "One session from several apps",
      "A ride that arrives from Strava, Garmin and Intervals.icu counts once (same sport, starting within 10 minutes or overlapping by half); your main activity source's copy is kept. TrainingPeaks doesn't do this for Zwift + Garmin uploads, which can double a day's TSS there."],
    ["Weekday preferences", "What you do each day",
      "Profile: up to 3 session types a day (e.g. Zwift / indoor + Strength), each planned as its own session; Rest keeps the day free. Plans and re-plans follow them; Apply weekday preferences to future days brings an existing plan in line."],
    ["Pace (min/km)", "Walks and runs",
      "Walks and runs in the Calendar show pace from your own recent walks or runs (12:00 and 6:00 per km when there are none), rides speed in km/h."],
    ["Data health", "Is your data sound?",
      "A tab on My training: connections, activities, the profile values training load needs, wellness and workout delivery, each with what to do."],
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
