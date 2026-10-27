"""CoachQuest's workout library: original structured bike workouts, open to every user.

Written for CoachQuest (no platform's workouts are copied), in the steps format of
workouts.py, so power is a fraction of FTP and every workout fits any athlete.
Users browse it on the Workouts page and can put a workout on a calendar, save a
copy to their own workouts to change it, or download it as a .zwo for Zwift or
MyWhoosh (MyWhoosh: upload the .zwo in its Workout Builder).

The library is code, not data: it is reviewed like code and the same on every
server. `LIBRARY` is checked against the steps format when the module loads.
"""

from . import workouts

COLLECTIONS = [
    ("endurance", "Recovery & endurance", "Easy and aerobic riding (Z1–Z2): the base everything else is built on."),
    ("tempo", "Tempo", "Steady, moderately hard riding (Z3): aerobic strength and fatigue resistance."),
    ("sweetspot", "Sweet spot", "88–94% FTP: a lot of training load for the fatigue it costs."),
    ("threshold", "Threshold", "95–105% FTP: raises the power you can hold for about an hour."),
    ("overunder", "Over-unders & race efforts", "Surges above and recoveries just under FTP, like racing."),
    ("vo2", "VO2 max", "106–120% FTP in 2–8 minute efforts: raises your aerobic ceiling."),
    ("anaerobic", "Anaerobic & sprints", "Short, very hard efforts for attacks, short climbs and sprints."),
    ("short", "Short & sharp (45 min or less)", "Real training for busy days."),
    ("skills", "Cadence & skills", "Pedalling technique, high and low cadence, and smooth power."),
    ("tests", "Tests", "Find your FTP so every workout is set at the right power."),
]
COLLECTION_NAMES = {k: name for k, name, _ in COLLECTIONS}


# ---- Building blocks (minutes in, seconds out) ----


def _m(minutes: float) -> int:
    return round(minutes * 60)


def wu(minutes: float = 10, start: float = 0.45, end: float = 0.7, text: str = "Easy start, build gradually"):
    return {"kind": "warmup", "duration_s": _m(minutes), "power_start": start, "power_end": end, "text": text}


def cd(minutes: float = 8, start: float = 0.65, end: float = 0.4, text: str = "Cool down, spin easy"):
    return {"kind": "cooldown", "duration_s": _m(minutes), "power_start": start, "power_end": end, "text": text}


def ss(minutes: float, power: float, text: str | None = None, cadence: int | None = None):
    step = {"kind": "steady", "duration_s": _m(minutes), "power": power}
    return _extra(step, text, cadence)


def rec(minutes: float, power: float = 0.5, text: str | None = "Recover, easy spin"):
    return _extra({"kind": "recovery", "duration_s": _m(minutes), "power": power}, text, None)


def ramp(minutes: float, start: float, end: float, text: str | None = None):
    return _extra({"kind": "ramp", "duration_s": _m(minutes), "power_start": start, "power_end": end}, text, None)


def iv(repeat: int, on_s: int, on_p: float, off_s: int, off_p: float, text: str | None = None, cadence=None):
    step = {"kind": "intervals", "repeat": repeat, "on_s": on_s, "on_power": on_p, "off_s": off_s, "off_power": off_p}
    return _extra(step, text, cadence)


def free(minutes: float, text: str | None = None):
    return _extra({"kind": "free", "duration_s": _m(minutes)}, text, None)


def _extra(step: dict, text: str | None, cadence: int | None) -> dict:
    if text:
        step["text"] = text
    if cadence:
        step["cadence"] = cadence
    return step


def _sets(sets: int, block: list[dict], between: list[dict]) -> list[dict]:
    """`block` `sets` times, with `between` after each set but the last."""
    out = []
    for i in range(sets):
        out += block
        if i < sets - 1:
            out += between
    return out


LIBRARY: list[dict] = []


def W(slug: str, collection: str, name: str, description: str, instructions: str, steps: list[dict]) -> None:
    LIBRARY.append(
        {
            "slug": slug,
            "collection": collection,
            "name": name,
            "description": description,
            "instructions": instructions,
            "steps": steps,
        }
    )


# ---- Recovery & endurance ----

W(
    "recovery-spin-30",
    "endurance",
    "Recovery spin 30",
    "30 minutes very easy. Helps the legs recover after a hard day without adding fatigue.",
    "Keep it truly easy: you should be able to chat the whole way. High-ish cadence, no efforts.",
    [wu(5, 0.4, 0.5), ss(20, 0.5, "Easy, relaxed, 90+ rpm", 92), cd(5, 0.5, 0.4)],
)
W(
    "recovery-spin-45",
    "endurance",
    "Recovery spin 45",
    "45 minutes in Z1 with a few light cadence lifts to flush the legs.",
    "Never let it feel like work. The cadence lifts are about leg speed, not power.",
    [
        wu(8, 0.4, 0.55),
        ss(8, 0.52),
        iv(4, 60, 0.55, 120, 0.5, "Spin up to 105 rpm, same easy power", 105),
        ss(10, 0.52),
        cd(7, 0.5, 0.4),
    ],
)
for mins in (45, 60, 75, 90):
    W(
        f"endurance-{mins}",
        "endurance",
        f"Endurance {mins}",
        f"{mins} minutes of steady Z2 riding. The bread and butter of aerobic fitness.",
        "Steady and conversational. Small, even pressure on the pedals; 85–95 rpm. Eat and drink as you would outside.",
        [wu(10), ss(mins - 18, 0.68, "Steady Z2, conversational"), cd(8)],
    )
W(
    "endurance-120",
    "endurance",
    "Long endurance 2 h",
    "Two hours of Z2 with gentle changes of pace to keep it interesting indoors.",
    "Fuel from the start (about 60 g of carbs an hour). Power drifts slightly up and down on purpose.",
    [wu(12)]
    + _sets(4, [ss(12, 0.68), ss(8, 0.73, "A touch firmer, still Z2"), ss(5, 0.62, "Ease off a little")], [])
    + [cd(8)],
)
W(
    "endurance-cadence-pyramid",
    "endurance",
    "Endurance with cadence pyramid",
    "60 minutes in Z2 with a cadence pyramid in the middle: smoother, more efficient pedalling.",
    "Power stays in Z2 throughout. Only the cadence changes: 80, 90, 100, 110, 100, 90, 80 rpm.",
    [wu(10), ss(10, 0.68)]
    + [ss(3, 0.68, f"{c} rpm", c) for c in (80, 90, 100, 110, 100, 90, 80)]
    + [ss(11, 0.68), cd(8)],
)
W(
    "endurance-progressive",
    "endurance",
    "Progressive endurance",
    "75 minutes that start in low Z2 and finish at the top of Z2. Teaches pacing and builds durability.",
    "Each block is a little firmer than the last. The final block should feel steady, not hard.",
    [wu(10), ss(15, 0.62, "Low Z2"), ss(15, 0.67), ss(15, 0.71), ss(12, 0.74, "Top of Z2, steady"), cd(8)],
)
W(
    "endurance-with-bursts",
    "endurance",
    "Endurance with bursts",
    "60 minutes of Z2 with short, punchy 10-second bursts every 5 minutes to wake up the legs.",
    "The bursts are quick and sharp, then straight back to Z2. Don't let the Z2 power sag after them.",
    [wu(10)] + _sets(8, [iv(1, 10, 1.5, 290, 0.68, "10 s punchy burst, then back to Z2")], []) + [ss(2, 0.65), cd(8)],
)
W(
    "endurance-low-cadence",
    "endurance",
    "Endurance with low-cadence blocks",
    "70 minutes of Z2 with seated low-cadence blocks for pedalling strength.",
    "Stay seated in the low-cadence blocks, 55–65 rpm, smooth and controlled. Stop if your knees complain.",
    [wu(10), ss(10, 0.68)]
    + _sets(4, [ss(5, 0.75, "Seated, 60 rpm, smooth", 60), ss(5, 0.66, "Normal cadence", 90)], [])
    + [ss(4, 0.66), cd(6)],
)
W(
    "aerobic-base-builder",
    "endurance",
    "Aerobic base builder",
    "90 minutes split into long Z2 blocks with a short tempo touch in each.",
    "The tempo touches keep the session honest; they should be controlled, not a race.",
    [wu(12)]
    + _sets(3, [ss(18, 0.69), ss(4, 0.8, "Tempo touch, controlled")], [ss(3, 0.6, "Ease off")])
    + [ss(6, 0.66), cd(6)],
)

# ---- Tempo ----

for sets, mins in ((3, 10), (2, 15), (3, 15), (2, 20), (2, 30)):
    W(
        f"tempo-{sets}x{mins}",
        "tempo",
        f"Tempo {sets} × {mins} min",
        f"{sets} blocks of {mins} minutes at 80–85% FTP. Muscular endurance for long climbs and fast group rides.",
        "Tempo is 'comfortably hard': breathing deeper but in control. Stay seated and steady; 85–95 rpm.",
        [wu(10)] + _sets(sets, [ss(mins, 0.83, "Tempo, steady and seated")], [rec(5, 0.55)]) + [cd(8)],
    )
W(
    "tempo-60-continuous",
    "tempo",
    "Tempo hour",
    "40 continuous minutes of tempo in a 1-hour session. Simple, effective, and great for fatigue resistance.",
    "Settle in after the first 5 minutes. Small sips every 10 minutes; keep the power smooth.",
    [wu(10), ss(40, 0.82, "Tempo, settle in"), cd(10)],
)
W(
    "tempo-cadence-changes",
    "tempo",
    "Tempo with cadence changes",
    "3 × 12 minutes at tempo, alternating 3 minutes at 70 rpm and 3 minutes at 100 rpm.",
    "Same power at both cadences. The low cadence is strength, the high cadence is leg speed.",
    [wu(10)]
    + _sets(
        3,
        [
            ss(3, 0.82, "70 rpm", 70),
            ss(3, 0.82, "100 rpm", 100),
            ss(3, 0.82, "70 rpm", 70),
            ss(3, 0.82, "100 rpm", 100),
        ],
        [rec(5, 0.55)],
    )
    + [cd(8)],
)
W(
    "tempo-into-sweetspot",
    "tempo",
    "Tempo into sweet spot",
    "Two 20-minute blocks: 15 minutes at tempo, finishing with 5 minutes of sweet spot.",
    "The finish is the point: holding sweet spot when already tired. Stay seated and smooth.",
    [wu(10)] + _sets(2, [ss(15, 0.82, "Tempo"), ss(5, 0.9, "Lift to sweet spot")], [rec(6, 0.55)]) + [cd(8)],
)
W(
    "tempo-climb-simulation",
    "tempo",
    "Long climb simulation",
    "Three 12-minute 'climbs' at upper tempo with a low-cadence middle third.",
    "Imagine a long alpine climb: seated, steady, rhythmic. Drop to 70 rpm in the middle part of each climb.",
    [wu(10)]
    + _sets(
        3,
        [ss(4, 0.85, "Climb, seated"), ss(4, 0.85, "Steeper: 70 rpm", 70), ss(4, 0.86, "Crest it")],
        [rec(5, 0.55, "Descend, recover")],
    )
    + [cd(8)],
)

# ---- Sweet spot ----

for sets, mins, rest in ((3, 10, 4), (2, 15, 5), (3, 12, 4), (2, 20, 5), (3, 15, 5), (3, 20, 5), (4, 12, 4)):
    W(
        f"sweetspot-{sets}x{mins}",
        "sweetspot",
        f"Sweet spot {sets} × {mins} min",
        f"{sets} × {mins} minutes at 88–93% FTP with {rest} minutes easy between. A classic for raising FTP.",
        "Hard but sustainable. Breathing is deep and rhythmic; you could speak a few words. Seated, 85–95 rpm.",
        [wu(10)] + _sets(sets, [ss(mins, 0.9, "Sweet spot, steady")], [rec(rest, 0.55)]) + [cd(8)],
    )
W(
    "sweetspot-2x30",
    "sweetspot",
    "Sweet spot 2 × 30 min",
    "Two long 30-minute sweet spot blocks. A big aerobic session for experienced riders.",
    "Start at the lower end (88%) and only build if you feel good after 20 minutes. Fuel during the session.",
    [wu(12), ss(30, 0.88, "Sweet spot, settle in"), rec(8, 0.55), ss(30, 0.89, "Second block, steady"), cd(8)],
)
W(
    "sweetspot-progression",
    "sweetspot",
    "Sweet spot progression",
    "3 × 12 minutes, each block a step higher: 88%, 91%, 94% FTP.",
    "Pace the first block so the last one is possible. The final block is right at the top of sweet spot.",
    [
        wu(10),
        ss(12, 0.88, "88% FTP"),
        rec(4, 0.55),
        ss(12, 0.91, "91% FTP"),
        rec(4, 0.55),
        ss(12, 0.94, "94% FTP, hold it"),
        cd(8),
    ],
)
W(
    "sweetspot-with-surges",
    "sweetspot",
    "Sweet spot with surges",
    "3 × 12 minutes of sweet spot with a 20-second surge every 3 minutes, like a hard group ride.",
    "Surge out of the saddle, then settle straight back to sweet spot. Don't drift below 88% after a surge.",
    [wu(10)]
    + _sets(3, _sets(4, [iv(1, 20, 1.3, 160, 0.9, "20 s surge, then sweet spot")], []), [rec(5, 0.55)])
    + [cd(8)],
)
W(
    "sweetspot-ladder",
    "sweetspot",
    "Sweet spot ladder",
    "Ladder of 6, 9, 12, 9, 6 minutes at sweet spot. 42 minutes of quality in a 75-minute session.",
    "Keep every rung at the same power. The 12-minute middle rung is where the session is won.",
    [wu(10)]
    + _sets(
        1,
        [
            ss(6, 0.9),
            rec(3, 0.55),
            ss(9, 0.9),
            rec(3, 0.55),
            ss(12, 0.9),
            rec(3, 0.55),
            ss(9, 0.9),
            rec(3, 0.55),
            ss(6, 0.9),
        ],
        [],
    )
    + [cd(8)],
)

# ---- Threshold ----

for sets, mins, rest in ((4, 6, 3), (3, 8, 4), (4, 8, 4), (3, 10, 5), (2, 12, 6), (2, 15, 6), (3, 12, 5), (2, 20, 8)):
    W(
        f"threshold-{sets}x{mins}",
        "threshold",
        f"Threshold {sets} × {mins} min",
        f"{sets} × {mins} minutes at 95–100% FTP. Raises the power you can sustain for about an hour.",
        "Hard and focused: only a few words at a time. Hold it smooth and even; don't start too hard.",
        [wu(12, 0.45, 0.75)] + _sets(sets, [ss(mins, 0.98, "Threshold, even and focused")], [rec(rest, 0.5)]) + [cd(8)],
    )
W(
    "threshold-cruise",
    "threshold",
    "Threshold cruise intervals",
    "5 × 5 minutes at 100% FTP with only 90 seconds between: short rests make it add up.",
    "Each interval should feel the same. If you fade on the fourth, drop the last one to 95%.",
    [wu(12, 0.45, 0.75), iv(5, 300, 1.0, 90, 0.5, "Threshold, then short recovery"), cd(8)],
)
W(
    "threshold-pyramid",
    "threshold",
    "Threshold pyramid",
    "4, 8, 12, 8, 4 minutes at threshold. A tough, well-paced session.",
    "Same power for every block. The middle 12 minutes is the key effort; settle into it.",
    [
        wu(12, 0.45, 0.75),
        ss(4, 0.98),
        rec(2),
        ss(8, 0.98),
        rec(4),
        ss(12, 0.98, "The big one, settle in"),
        rec(4),
        ss(8, 0.98),
        rec(2),
        ss(4, 0.98, "Last one, hold the form"),
        cd(8),
    ],
)
W(
    "threshold-climbing",
    "threshold",
    "Threshold climbing",
    "3 × 10 minutes at threshold with the middle 4 minutes at low cadence, like a steep climb.",
    "Seated throughout. In the low-cadence part, pull through the bottom of the stroke and keep the power steady.",
    [wu(12, 0.45, 0.75)]
    + _sets(
        3,
        [
            ss(3, 0.97, "Threshold, normal cadence"),
            ss(4, 0.97, "Steep: 65 rpm", 65),
            ss(3, 0.97, "Back to normal cadence"),
        ],
        [rec(5)],
    )
    + [cd(8)],
)
W(
    "threshold-ramp-in",
    "threshold",
    "Threshold with ramp-ins",
    "4 × 7 minutes: each starts with a 1-minute ramp from sweet spot into threshold.",
    "The ramp-in teaches you to settle at threshold without overshooting at the start.",
    [wu(12, 0.45, 0.75)]
    + _sets(4, [ramp(1, 0.88, 1.0, "Ramp up into threshold"), ss(6, 1.0, "Threshold")], [rec(4)])
    + [cd(8)],
)

# ---- Over-unders & race efforts ----

W(
    "overunder-3x9",
    "overunder",
    "Over-unders 3 × 9 min",
    "3 × 9 minutes alternating 2 minutes at 95% and 1 minute at 105% FTP.",
    "The 'overs' build fatigue; the 'unders' teach you to keep going hard while clearing it. Stay seated in unders.",
    [wu(12, 0.45, 0.75)]
    + _sets(3, _sets(3, [ss(2, 0.95, "Under: 95%"), ss(1, 1.05, "Over: 105%")], []), [rec(5)])
    + [cd(8)],
)
W(
    "overunder-4x8",
    "overunder",
    "Over-unders 4 × 8 min",
    "4 × 8 minutes of 1 minute at 92% and 1 minute at 108% FTP.",
    "Smooth changes, no sprinting into the overs. A demanding session; fuel well.",
    [wu(12, 0.45, 0.75)] + _sets(4, [iv(4, 60, 0.92, 60, 1.08, "Under 92% / over 108%")], [rec(5)]) + [cd(8)],
)
W(
    "overunder-surges",
    "overunder",
    "Threshold with surges",
    "3 × 10 minutes at threshold with a 15-second surge to 150% every 2 minutes.",
    "Like holding a wheel in a fast group: the surge, then straight back to threshold. Don't sag after.",
    [wu(12, 0.45, 0.75)]
    + _sets(3, _sets(5, [iv(1, 15, 1.5, 105, 0.97, "Surge, then threshold")], []), [rec(5)])
    + [cd(8)],
)
W(
    "race-simulation-crit",
    "overunder",
    "Criterium simulation",
    "20 minutes of race-like riding: a minute of tempo then 15 seconds hard, again and again. Then a final sprint.",
    "Out of the saddle for the hard bits as you would out of corners. Finish with everything in the sprint.",
    [
        wu(12, 0.45, 0.75),
        ss(2, 0.8),
        iv(16, 15, 1.4, 60, 0.82, "Out of the corner: hard!"),
        ss(1, 0.9, "Last lap"),
        ss(0.33, 1.8, "Sprint for the line!"),
        rec(4),
        cd(8),
    ],
)
W(
    "race-simulation-road",
    "overunder",
    "Road race finale",
    "Steady tempo, a hard climb, a regroup, and a fast finish: the last 30 minutes of a road race.",
    "Pace the climb so you can still respond in the finale. The last minute is all-out.",
    [
        wu(12, 0.45, 0.75),
        ss(10, 0.8, "Bunch riding, tempo"),
        ss(5, 1.03, "The climb: hard and steady"),
        iv(3, 20, 1.3, 40, 0.9, "Attacks near the top"),
        ss(5, 0.75, "Regroup"),
        ss(4, 0.95, "Chase is on"),
        ss(1, 1.2, "Final kilometre"),
        ss(0.25, 1.8, "Sprint!"),
        rec(4),
        cd(8),
    ],
)
W(
    "breakaway",
    "overunder",
    "Breakaway",
    "An attack, then holding it: 1 minute hard followed by 8 minutes just under threshold, 3 times.",
    "The attack opens the gap; the steady part keeps it. Stay low and smooth after the attack.",
    [wu(12, 0.45, 0.75)] + _sets(3, [ss(1, 1.25, "Attack!"), ss(8, 0.94, "Hold the gap")], [rec(6)]) + [cd(8)],
)
W(
    "tempo-with-attacks",
    "overunder",
    "Tempo with attacks",
    "45 minutes of tempo broken up by 30-second attacks every 5 minutes.",
    "Return to tempo straight after each attack. Hard on the legs and the head: a great race-prep session.",
    [wu(10)] + _sets(9, [iv(1, 30, 1.3, 270, 0.82, "Attack 30 s, then tempo")], []) + [cd(8)],
)

# ---- VO2 max ----

for sets, on_min, power, rest in (
    (5, 3, 1.12, 3),
    (6, 3, 1.1, 3),
    (4, 4, 1.1, 4),
    (5, 4, 1.08, 4),
    (3, 5, 1.08, 5),
    (4, 5, 1.06, 5),
    (5, 2, 1.18, 2),
    (3, 6, 1.06, 5),
):
    W(
        f"vo2-{sets}x{on_min}",
        "vo2",
        f"VO2 max {sets} × {on_min} min",
        f"{sets} × {on_min} minutes at {round(power * 100)}% FTP with {rest} minutes easy between.",
        "Very hard: breathing at its limit by the end of each one. Even pacing; the last should match the first.",
        [wu(12, 0.45, 0.75), ss(1, 1.05, "Opener"), rec(3)]
        + [iv(sets, _m(on_min), power, _m(rest), 0.5, "VO2: hard and even")]
        + [cd(8)],
    )
W(
    "vo2-30-30",
    "vo2",
    "VO2 max 30/30s",
    "Three sets of 8 × 30 seconds at 120% with 30 seconds easy. Lots of time at a high heart rate.",
    "Don't go harder than prescribed: the short rests make it accumulate. Spin fast in the easy parts.",
    [wu(12, 0.45, 0.75)] + _sets(3, [iv(8, 30, 1.2, 30, 0.5, "30 s on / 30 s easy")], [rec(5)]) + [cd(8)],
)
W(
    "vo2-40-20",
    "vo2",
    "VO2 max 40/20s",
    "Three sets of 10 × 40 seconds at 115% with 20 seconds easy.",
    "Very short rests: by the end of each set you should be at your limit. Stay seated if you can.",
    [wu(12, 0.45, 0.75)] + _sets(3, [iv(10, 40, 1.15, 20, 0.5, "40 s on / 20 s easy")], [rec(5)]) + [cd(8)],
)
W(
    "vo2-pyramid",
    "vo2",
    "VO2 max pyramid",
    "1, 2, 3, 4, 3, 2, 1 minutes at 110–120% FTP, with equal recovery.",
    "Shorter efforts are harder (120%), longer ones a bit lower (110%). Keep the recoveries truly easy.",
    [wu(12, 0.45, 0.75)]
    + [
        x
        for m, p in ((1, 1.2), (2, 1.15), (3, 1.12), (4, 1.1), (3, 1.12), (2, 1.15), (1, 1.2))
        for x in (ss(m, p, f"{m} min hard"), rec(m))
    ]
    + [cd(8)],
)
W(
    "vo2-hill-repeats",
    "vo2",
    "Hill repeats",
    "6 × 3 minutes at 112% FTP at low cadence, like a short steep climb, with a descent to recover.",
    "Seated or standing as you would outside; 65–75 rpm. Recover fully on the 'descent'.",
    [wu(12, 0.45, 0.75), iv(6, 180, 1.12, 180, 0.48, "Climb! 70 rpm", 70), cd(8)],
)

# ---- Anaerobic & sprints ----

W(
    "anaerobic-1min",
    "anaerobic",
    "Anaerobic 1-minute efforts",
    "2 sets of 5 × 1 minute at 130% FTP with 2 minutes easy. Builds the power for short climbs and attacks.",
    "Start hard but not all-out; the last 20 seconds will hurt. Recover properly between.",
    [wu(15, 0.45, 0.75)] + _sets(2, [iv(5, 60, 1.3, 120, 0.5, "1 min hard!")], [rec(6)]) + [cd(8)],
)
W(
    "anaerobic-30s",
    "anaerobic",
    "30-second efforts",
    "8 × 30 seconds at 150% FTP with 4 minutes 30 easy. Short, fierce, fully recovered.",
    "Near-maximal for 30 seconds. Seated start, stand if you need to. Full recovery so every effort counts.",
    [wu(15, 0.45, 0.75), iv(8, 30, 1.5, 270, 0.48, "30 s near max!"), cd(8)],
)
W(
    "tabata",
    "anaerobic",
    "Tabata",
    "Two blocks of 8 × 20 seconds all-out, 10 seconds rest. Short and brutal.",
    "Everything you have for 20 seconds, then 10 seconds to breathe. Only do this when fresh.",
    [wu(15, 0.45, 0.75)] + _sets(2, [iv(8, 20, 1.7, 10, 0.4, "20 s all-out")], [rec(8)]) + [cd(8)],
)
W(
    "sprints-standing",
    "anaerobic",
    "Standing sprints",
    "8 × 15-second standing sprints from a rolling start, fully recovered. Peak power and sprint technique.",
    "Jump hard out of the saddle, get on top of the gear, sit for the last 3 seconds. 3–4 minutes easy between.",
    [wu(15, 0.45, 0.75), iv(8, 15, 2.0, 225, 0.48, "Sprint! Out of the saddle"), cd(8)],
)
W(
    "sprints-seated",
    "anaerobic",
    "Seated sprints",
    "6 × 10-second seated sprints at high cadence. Neuromuscular speed without the upper body.",
    "Stay seated, spin as fast as you can with control (120+ rpm). Full recovery between.",
    [wu(15, 0.45, 0.75), iv(6, 10, 1.8, 230, 0.48, "Seated sprint, spin fast!", 120), cd(8)],
)
W(
    "sprint-leadout",
    "anaerobic",
    "Lead-out and sprint",
    "5 × 2-minute build-ups (tempo, threshold, then 20 s sprint), like a lead-out train.",
    "Stay in the 'wheel' during the build, then launch for 20 seconds. Recover fully between.",
    [wu(15, 0.45, 0.75)]
    + _sets(5, [ss(1, 0.85, "In the train"), ss(0.67, 1.05, "Faster"), ss(0.33, 1.9, "Launch the sprint!")], [rec(5)])
    + [cd(8)],
)
W(
    "anaerobic-capacity-2min",
    "anaerobic",
    "2-minute power",
    "5 × 2 minutes at 120% FTP with 4 minutes easy. For the hardest climbs and decisive moments.",
    "Pace it: the first 30 seconds feel easy, the last 30 seconds do not. Recover fully.",
    [wu(15, 0.45, 0.75), iv(5, 120, 1.2, 240, 0.5, "2 min hard, pace it"), cd(8)],
)
W(
    "micro-bursts",
    "anaerobic",
    "Micro-bursts",
    "3 sets of 10 × 15 seconds at 140% with 15 seconds easy. Repeated accelerations.",
    "Quick, snappy accelerations. Don't go all-out: it's the repetition that counts.",
    [wu(12, 0.45, 0.75)] + _sets(3, [iv(10, 15, 1.4, 15, 0.5, "15 s burst / 15 s easy")], [rec(5)]) + [cd(8)],
)

# ---- Short & sharp ----

W(
    "short-sweetspot-30",
    "short",
    "Sweet spot 30",
    "Two 8-minute sweet spot efforts in 30 minutes.",
    "Short warm-up, so ease into the first effort. Steady and seated.",
    [wu(6, 0.45, 0.75), ss(8, 0.9, "Sweet spot"), rec(3), ss(8, 0.9, "Sweet spot"), cd(5)],
)
W(
    "short-threshold-35",
    "short",
    "Threshold 35",
    "3 × 5 minutes at threshold in 35 minutes.",
    "Quick but complete: warm up well in the 7 minutes and hold even power in every effort.",
    [wu(7, 0.45, 0.8), iv(3, 300, 0.99, 120, 0.5, "Threshold"), cd(7)],
)
W(
    "short-vo2-30",
    "short",
    "VO2 max 30",
    "10 × 1 minute at 115% with 1 minute easy, in 30 minutes.",
    "Hard and quick. Spin easy between and keep every effort even.",
    [wu(7, 0.45, 0.8), iv(10, 60, 1.15, 60, 0.5, "1 min hard / 1 min easy"), cd(3)],
)
W(
    "short-tempo-40",
    "short",
    "Tempo 40",
    "25 minutes of tempo in a 40-minute session.",
    "Settle into tempo and hold it. Great for a lunchtime ride.",
    [wu(7), ss(25, 0.82, "Tempo, steady"), cd(8)],
)
W(
    "short-endurance-45",
    "short",
    "Endurance 45 with spin-ups",
    "45 minutes of Z2 with short spin-ups to keep the legs fresh.",
    "Easy aerobic riding. The spin-ups are about cadence, not power.",
    [wu(8)] + _sets(5, [ss(5, 0.68), iv(1, 30, 0.7, 30, 0.68, "Spin up to 110 rpm", 110)], []) + [cd(7)],
)
W(
    "short-over-under-40",
    "short",
    "Over-unders 40",
    "2 × 8 minutes of over-unders in 40 minutes.",
    "Alternate 1 minute at 92% and 1 minute at 105%. Smooth changes.",
    [wu(10, 0.45, 0.8)] + _sets(2, [iv(4, 60, 0.92, 60, 1.05, "Under 92% / over 105%")], [rec(4)]) + [cd(10)],
)
W(
    "short-sprints-30",
    "short",
    "Sprints 30",
    "6 short sprints in a 30-minute session. Fun, sharp, and not too tiring.",
    "Everything for 10 seconds, then spin easy. Quality over quantity.",
    [wu(8, 0.45, 0.75), iv(6, 10, 1.9, 170, 0.5, "Sprint!"), cd(4)],
)
W(
    "short-recovery-20",
    "short",
    "Recovery 20",
    "20 minutes of very easy spinning: a leg-loosener on a rest day or after a hard day.",
    "Easy enough to chat. Just turn the legs over.",
    [wu(4, 0.4, 0.5), ss(13, 0.5, "Easy spin"), cd(3, 0.5, 0.4)],
)
W(
    "short-mixed-45",
    "short",
    "Mixed 45",
    "A little of everything in 45 minutes: tempo, threshold and short bursts.",
    "Follow the cues; each block is short. A good session when you don't know what to do.",
    [
        wu(8, 0.45, 0.8),
        ss(8, 0.83, "Tempo"),
        rec(2),
        ss(6, 0.98, "Threshold"),
        rec(3),
        iv(6, 30, 1.25, 60, 0.55, "30 s hard"),
        cd(9),
    ],
)

# ---- Cadence & skills ----

W(
    "skills-high-cadence",
    "skills",
    "High-cadence drills",
    "Spin-ups to 120+ rpm at easy power for a smoother, more efficient pedal stroke.",
    "Increase cadence gradually until just before you bounce on the saddle; hold it there, relaxed.",
    [wu(10), iv(8, 60, 0.6, 120, 0.6, "Spin up to 115–120 rpm", 118), ss(8, 0.65), cd(7)],
)
W(
    "skills-single-leg-focus",
    "skills",
    "Pedal stroke focus",
    "Alternating 1-minute blocks focusing on each part of the pedal stroke, at Z2 power.",
    "Think: push over the top, pull through the bottom, lift on the way up. Smooth, round circles.",
    [wu(10)]
    + [
        ss(1, 0.65, t)
        for t in ("Push over the top", "Pull through the bottom", "Light on the upstroke", "Round, smooth circles")
    ]
    * 4
    + [ss(6, 0.65), cd(8)],
)
W(
    "skills-cadence-ladder",
    "skills",
    "Cadence ladder",
    "Climb the cadence ladder from 70 to 120 rpm at steady Z2 power, three times.",
    "Same power, rising cadence. Relax your upper body as the legs speed up.",
    [wu(10)] + _sets(3, [ss(1.5, 0.68, f"{c} rpm", c) for c in (70, 80, 90, 100, 110, 120)], [rec(3, 0.55)]) + [cd(7)],
)
W(
    "skills-strength-endurance",
    "skills",
    "Strength endurance",
    "5 × 6 minutes at 80–85% FTP at 50–60 rpm. Builds force on the pedals for climbing.",
    "Seated, stable upper body, smooth through the whole stroke. Stop if your knees hurt.",
    [wu(10), iv(5, 360, 0.83, 180, 0.55, "Seated, 55 rpm, strong and smooth", 55), cd(8)],
)
W(
    "skills-smooth-power",
    "skills",
    "Smooth power",
    "Long blocks just under threshold with an eye on the power number: as even as you can make it.",
    "Ignore heart rate, watch the power: aim for a flat line. Gear and cadence steady, no surging.",
    [
        wu(10),
        ss(10, 0.88, "As even as possible"),
        rec(3),
        ss(10, 0.88, "Flat line"),
        rec(3),
        ss(10, 0.88, "Even to the end"),
        cd(8),
    ],
)
W(
    "skills-standing-transitions",
    "skills",
    "Standing transitions",
    "Tempo with 30 seconds out of the saddle every 3 minutes: practise standing without losing speed.",
    "Shift up one gear as you stand, keep the power the same, shift back as you sit.",
    [wu(10)] + _sets(8, [ss(2.5, 0.8, "Seated tempo"), ss(0.5, 0.85, "Stand: one gear up")], []) + [cd(8)],
)

# ---- Tests ----

W(
    "test-ftp-20",
    "tests",
    "FTP test (20 minutes)",
    "The classic 20-minute test: your FTP is about 95% of the average power for the 20 minutes.",
    "Be rested. Pace the first 5 minutes slightly below what you think you can hold, then build. "
    "The target power shown is only a guide: ride the 20 minutes at your best even effort. FTP = 0.95 × average.",
    [
        wu(10, 0.45, 0.75),
        iv(3, 60, 1.05, 60, 0.55, "Openers"),
        rec(5),
        ss(5, 1.1, "Blow-out effort, hard"),
        rec(10, 0.5, "Recover fully"),
        ss(20, 1.03, "Test! Your best even effort"),
        cd(10),
    ],
)
W(
    "test-ramp",
    "tests",
    "Ramp test",
    "Power rises every minute until you can't hold it. FTP is about 75% of your best 1-minute power.",
    "Go until you can no longer hold the target. Keep cadence high near the end. FTP = 0.75 × best 1-minute power.",
    [wu(5, 0.4, 0.5)] + [ss(1, round(0.5 + 0.06 * i, 2), f"Step {i + 1}") for i in range(20)] + [cd(5, 0.5, 0.35)],
)
W(
    "test-8min",
    "tests",
    "8-minute test",
    "Two 8-minute efforts. FTP is about 90% of the higher average of the two.",
    "Ride each 8 minutes as hard as you can evenly. Recover well between. FTP = 0.90 × higher average.",
    [
        wu(15, 0.45, 0.8),
        ss(8, 1.1, "Test 1: best even effort"),
        rec(10, 0.5, "Recover fully"),
        ss(8, 1.1, "Test 2: best even effort"),
        cd(10),
    ],
)
W(
    "test-openers",
    "tests",
    "Pre-test openers",
    "Short session for the day before a test or race: a few short efforts to feel sharp.",
    "Keep it short and easy apart from the efforts. You should finish feeling fresh, not tired.",
    [
        wu(10),
        ss(5, 0.7),
        iv(3, 60, 1.05, 120, 0.5, "1 min at threshold+"),
        iv(3, 15, 1.6, 105, 0.5, "15 s quick"),
        cd(8),
    ],
)


# ---- Access ----

BY_SLUG: dict[str, dict] = {}


def _check() -> None:
    names = set()
    for w in LIBRARY:
        assert w["collection"] in COLLECTION_NAMES, w["slug"]
        assert w["slug"] not in BY_SLUG, f"duplicate slug {w['slug']}"
        assert w["name"] not in names, f"duplicate name {w['name']}"
        w["steps"] = workouts.validate_steps(w["steps"])
        names.add(w["name"])
        BY_SLUG[w["slug"]] = w


_check()


def get(slug: str) -> dict | None:
    return BY_SLUG.get(slug)


def out(w: dict, ftp: int | None = None, with_steps: bool = False) -> dict:
    """A library workout for the page: the timeline, an estimate for the athlete's FTP, and its collection."""
    return {
        "slug": w["slug"],
        "name": w["name"],
        "collection": w["collection"],
        "collection_name": COLLECTION_NAMES[w["collection"]],
        "description": w["description"],
        "instructions": w["instructions"],
        "estimate": workouts.estimate(w["steps"], ftp),
        "blocks": workouts.blocks(w["steps"]),
        **({"steps": w["steps"]} if with_steps else {}),
    }
