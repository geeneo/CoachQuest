# Training load audit (CTL / ATL / TSB against TrainingPeaks)

Asked on 4 November 2026: Natalie's CoachQuest fitness / fatigue / form (76.1 / 75.5 / −10.1) against
TrainingPeaks (56 / 59 / −5).

## What the code does (diagnosis)

| Step | Where | What it does | Finding |
|---|---|---|---|
| CTL / ATL / TSB | `backend/app/fitness.py` `pmc()` | CTL 42-day and ATL 7-day exponential averages of daily TSS; **TSB = the previous day's CTL − ATL**; every calendar day, rest days as 0 | Matches the reference formulas. The tiles' TSB is the previous day's, so CTL − ATL of the same day isn't the TSB shown (76.1 − 75.5 ≠ −10.1 is expected) |
| Start | `backend/app/queries.py` `load_curve()` | Starts from 0, 120 days before the period shown (`WARMUP_DAYS`) | Starting at 0 makes CoachQuest lower, not higher |
| Duplicates | `fitness.py` `dedupe()` / `same_session()`, used by `queries.activities_since()` | One session from Strava, Garmin, Intervals.icu (same kind, start within 10 min or half overlapping) counts once; the athlete's main source wins; hidden sources are left out | Correct in the tests; check Natalie's "duplicate" rows in the audit |
| Day of an activity | `fitness.py` `daily_tss()` | Was the **UTC** date (the calendar uses the local date): a session before 02:00 in South Africa counted on the day before | **Fixed**: now the athlete's local date |
| TSS of an activity | `fitness.py` `estimate_tss()`, from `providers/strava.py`, `garmin.py`, `intervals_icu.py` | Power with FTP → else heart rate with LTHR (average HR ÷ LTHR, squared) → else **Strava's Relative Effort used as TSS** → else **50 TSS an hour**; Intervals.icu activities use its training load | **Most likely cause** of a higher CoachQuest load: estimates for sessions TrainingPeaks scores lower or not at all, and Relative Effort running above TSS on long rides |
| FTP changes | `profile_sync.py` `recalculate_tss()` | When FTP or LTHR changes, every past activity is scored again with today's FTP (also replacing Intervals.icu's own load) | Differs from TrainingPeaks, which keeps each workout's TSS from its own FTP. 10% lower FTP ≈ 23% more TSS; ≈15% lower ≈ +38% |

A 36% higher CTL fits an FTP that is about 15% lower in CoachQuest than in TrainingPeaks, or a large
share of estimated TSS. Which one only Natalie's data can show.

## The audit (read only)

My training → Overview → Training load → **"See how it's calculated and compare"**
(`/load-audit/<athlete>`; backend `app/load_audit.py`, `app/routers/load_audit.py`).

- Profile values used (FTP, LTHR, time zone, main and hidden sources) and the calculation, versioned.
- Warnings: no FTP / LTHR, the share of estimated TSS, FTP applied to all history, duplicates, sessions
  near midnight.
- Where the TSS came from: by method (power, heart rate, Relative Effort, duration estimate, Intervals.icu).
- Day by day: activities, TSS, CTL, ATL, TSB (rest days included), identical to the Fitness chart.
- Activities: local start, source, external ID, counted / copy of #id / hidden source, TSS, method, IF.
- CSV downloads of both.
- **Compare with TrainingPeaks**: upload its workouts CSV (WorkoutDay + TSS) or PMC CSV (Date + TSS,
  CTL / Fitness, ATL / Fatigue). Every day in the export's range is compared (a day with no workout there
  counts as 0); it shows the totals, the ratio and the first day that differs by more than 10%.

## Next steps

1. Natalie (or a coach with her fitness and activities shared) opens the audit for 180 days and downloads
   both CSVs.
2. Export the same 180 days from TrainingPeaks (workouts CSV, or the PMC data) and upload it on the audit
   page. Don't use numbers typed from a screenshot: the first differing day needs the real export.
3. Read the first day that differs, and the activity rows that day: method, FTP / IF, duplicates.
4. Then decide the fix with evidence, for example:
   - FTP: set Natalie's FTP to the one TrainingPeaks uses (and decide whether TSS should keep the FTP of
     each workout's own day, instead of recalculating history).
   - Estimates: score walks / strength / yoga without power or HR as 0 or low, and stop using Relative
     Effort as TSS (or cap it).
   - Prefer the provider's own load when it has one (Intervals.icu; Garmin/TrainingPeaks where possible).

No stored data was changed by the audit or the date fix; CTL / ATL / TSB are calculated again from the
activities each time (deterministic, nothing to back fill or undo).

## Findings with real data (4 November 2026, 180 days)

CoachQuest 17,521 TSS against TrainingPeaks 11,183 (×1.57), different from the first day. The audit's
activity rows showed:

1. **Duplicates were fine**: a Zwift ride arrives up to four times (Strava ×2, Garmin ×2) and counted once.
2. **Runs scored with the cycling FTP** (bug): running power against a 212 W cycling FTP gave IF 1.4-1.8,
   e.g. a 30 min run at 161 TSS. Fixed: runs use a separate **Run threshold power** (Profile), and heart
   rate until it's set; power on other sports isn't used.
3. **Walks and strength heavily scored**: ~45-50 TSS an hour from average heart rate, where TrainingPeaks
   gives ~0-15 (e.g. 3 Sep: 63.7 against 0.7). Fixed, as TrainingPeaks does: strength, yoga, workouts and
   climbing 0; walks and hikes light (heart rate, at most 15 an hour; 10 an hour without).
4. **Rides about 1.4× on power and on heart rate**: CoachQuest's FTP (and LTHR) are about 18% lower than
   TrainingPeaks' (24 Oct: IF 0.84 here, about 0.71 there). A setting, not code: copy TrainingPeaks'
   bike power threshold and threshold heart rate into Profile (it scores all past rides again).

`fitness.score()` scores by sport (TSS_VERSION 2); `profile_sync.rescore_all_once()` scores everyone's
stored activities again once after the update (from the stored power and heart rate; Intervals.icu's
own load stays for rides and runs). Run the comparison again after the update and the Profile change.

## Each workout's FTP at its date (4 November 2026)

TrainingPeaks keeps each workout's TSS from the FTP it had then; CoachQuest used today's FTP for all history.
Now `User.threshold_history` holds earlier FTP / run threshold power / LTHR values (`fitness.threshold_at`):
a workout uses the latest value from on or before its date (before the first entry, the first one; without
history, the Profile value). A Profile or Garmin change is recorded from today (`profile_sync.record_change`,
keeping the old value as "before"), so earlier workouts keep their TSS. Athletes add past values in
**Profile → Threshold history** (`PUT /api/me/threshold-history`); everything is scored again.
