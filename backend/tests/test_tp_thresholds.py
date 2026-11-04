"""Thresholds TrainingPeaks used, from its Workout Summary export."""

import base64
import csv
import io
import zipfile

import pytest

from app import tp_thresholds

COLS = [
    "Title",
    "WorkoutType",
    "WorkoutDay",
    "TimeTotalInHours",
    "PowerAverage",
    "HeartRateAverage",
    "HeartRateMax",
    "IF",
    "TSS",
]


def export(rows) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=COLS)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in COLS})
    return "﻿" + out.getvalue()


def sample():
    rows = []
    for i in range(10):
        day = f"2026-06-{i + 10:02d}"
        # Steady indoor rides at FTP 190: average power = normalized power; one variable outdoor ride.
        p = 150 + i
        rows.append(
            {
                "WorkoutType": "Bike",
                "WorkoutDay": day,
                "TimeTotalInHours": 1,
                "PowerAverage": p,
                "IF": p / 190,
                "TSS": (p / 190) ** 2 * 100,
                "HeartRateAverage": 140,
                "HeartRateMax": 170,
            }
        )
        rows.append(
            {
                "WorkoutType": "Run",
                "WorkoutDay": day,
                "TimeTotalInHours": 1,
                "PowerAverage": 240,
                "IF": 240 / 188,
                "TSS": 163,
                "HeartRateAverage": 150,
                "HeartRateMax": 178 + (i % 3),
            }
        )
        hr = 110 + i
        rows.append(
            {
                "WorkoutType": "Strength",
                "WorkoutDay": day,
                "TimeTotalInHours": 0.75,
                "HeartRateAverage": hr,
                "IF": hr / 181,
                "TSS": 0.75 * (hr / 181) ** 2 * 100,
            }
        )
        rows.append(
            {
                "WorkoutType": "Walk",
                "WorkoutDay": day,
                "TimeTotalInHours": 1,
                "HeartRateAverage": 110,
                "TSS": 5,
                "IF": 0.2,
            }
        )  # walks by pace: left out of LTHR
    rows.append(
        {
            "WorkoutType": "Bike",
            "WorkoutDay": "2026-06-30",
            "TimeTotalInHours": 3,
            "PowerAverage": 130,
            "IF": 0.8,
            "TSS": 192,
            "HeartRateMax": 229,
        }
    )  # variable ride, and a glitch spike
    return rows


def test_estimates():
    out = tp_thresholds.estimate(export(sample()))
    v = out["values"]
    assert out["workouts"] == 41
    assert v["ftp_watts"]["value"] == 190
    assert v["run_ftp_watts"]["value"] == 188
    assert v["lthr_bpm"]["value"] == 181
    assert v["max_hr_bpm"]["value"] == 180  # 229 is a single spike


def test_not_a_workout_summary():
    with pytest.raises(ValueError):
        tp_thresholds.estimate("Date,TSS\n2026-01-01,50\n")


def test_too_few_sessions():
    assert tp_thresholds.estimate(export(sample()[:4]))["values"].keys() <= {"max_hr_bpm"}


def test_api_reads_csv_or_zip_and_saves_nothing(make_user):
    athlete = make_user("ath@example.com", "Natalie")
    coach = make_user("c@example.com", "Coach")
    aid = athlete.get("/api/auth/me").json()["id"]
    athlete.patch("/api/me", json={"ftp_watts": 157, "lthr_bpm": 160})
    text = export(sample())
    r = athlete.post("/api/athletes/me/thresholds/from-trainingpeaks", json={"csv": text})
    assert r.status_code == 200, r.text
    assert r.json()["values"]["ftp_watts"]["value"] == 190 and r.json()["current"]["ftp_watts"] == 157
    assert athlete.get("/api/auth/me").json()["ftp_watts"] == 157  # nothing saved
    url = f"/api/athletes/{aid}/thresholds/from-trainingpeaks"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("workouts.csv", text)
    body = {"zip_b64": base64.b64encode(buf.getvalue()).decode()}
    assert coach.post(url, json=body).status_code == 404  # not shared
    g = athlete.post("/api/grants", json={"coach_email": "c@example.com", "scopes": ["profile"]}).json()
    coach.post(f"/api/grants/{g['id']}/accept")
    assert coach.post(url, json=body).json()["values"]["lthr_bpm"]["value"] == 181
    assert coach.post(url, json={"csv": "Date,TSS\n2026-01-01,50\n"}).status_code == 422
