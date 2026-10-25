"""Zwift workout files (.zwo) and plan ZIPs, made from CoachQuest workouts.

A .zwo is a small XML file; power is a fraction of FTP, so Zwift scales it to
the rider's own FTP. This is a manual export: the athlete copies the files into
Zwift's workouts folder. Nothing here talks to a Zwift account.
"""

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date

ELEMENT = {
    "warmup": "Warmup",
    "cooldown": "Cooldown",
    "ramp": "Ramp",
    "steady": "SteadyState",
    "recovery": "SteadyState",
    "intervals": "IntervalsT",
    "free": "FreeRide",
}

INSTRUCTIONS = """How to add these workouts to Zwift
==================================

These are files to copy by hand. They are not sent to your Zwift account, so
if your coach changes a workout in CoachQuest, download it again.

Windows
1. Unzip this file (right-click > Extract All).
2. Open File Explorer > Documents > Zwift > Workouts.
3. Open the folder named with a number (your Zwift ID). If there is none,
   start Zwift once and sign in, then look again.
4. Copy the .zwo files into that folder.
5. Start (or restart) Zwift. Choose Workouts and scroll to "Custom Workouts".

Mac
Same steps, using Documents > Zwift > Workouts > (your Zwift ID) in Finder.

Power targets are a percentage of FTP, so Zwift uses the FTP set in your
Zwift profile. Keep it the same as in CoachQuest.
"""


def _num(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".")


def zwo(workout: dict, author: str = "CoachQuest") -> str:
    """The .zwo XML for a workout dict with name, description, instructions and steps."""
    root = ET.Element("workout_file")
    ET.SubElement(root, "author").text = author
    ET.SubElement(root, "name").text = workout["name"]
    notes = "\n\n".join(x for x in (workout.get("description"), workout.get("instructions")) if x)
    ET.SubElement(root, "description").text = notes
    ET.SubElement(root, "sportType").text = "bike"
    tags = ET.SubElement(root, "tags")
    ET.SubElement(tags, "tag", name="CoachQuest")
    body = ET.SubElement(root, "workout")
    for s in workout["steps"]:
        k = s["kind"]
        attrs: dict[str, str] = {}
        if k == "intervals":
            attrs = {
                "Repeat": str(s["repeat"]),
                "OnDuration": str(s["on_s"]),
                "OffDuration": str(s["off_s"]),
                "OnPower": _num(s["on_power"]),
                "OffPower": _num(s["off_power"]),
            }
            if s.get("cadence"):
                attrs["Cadence"] = str(s["cadence"])
            if s.get("off_cadence"):
                attrs["CadenceResting"] = str(s["off_cadence"])
        elif k == "free":
            attrs = {"Duration": str(s["duration_s"]), "FlatRoad": "1"}
        elif k in ("steady", "recovery"):
            attrs = {"Duration": str(s["duration_s"]), "Power": _num(s["power"])}
        else:
            # Zwift reads PowerLow as the start and PowerHigh as the end, also for cool-downs.
            attrs = {
                "Duration": str(s["duration_s"]),
                "PowerLow": _num(s["power_start"]),
                "PowerHigh": _num(s["power_end"]),
            }
        if k != "intervals" and k != "free" and s.get("cadence"):
            attrs["Cadence"] = str(s["cadence"])
        el = ET.SubElement(body, ELEMENT[k], attrs)
        if s.get("text"):
            ET.SubElement(el, "textevent", timeoffset="0", message=s["text"])
    ET.indent(root)
    return ET.tostring(root, encoding="unicode") + "\n"


def filename(name: str, day: date | None = None) -> str:
    safe = re.sub(r"[^A-Za-z0-9 _-]+", "", name.replace("×", "x").replace("/", " ")).strip()
    safe = re.sub(r"\s+", " ", safe)[:60] or "workout"
    return f"{day.isoformat()} {safe}.zwo" if day else f"{safe}.zwo"


def plan_zip(items: list[tuple[date, dict]], author: str = "CoachQuest") -> bytes:
    """A ZIP with one .zwo per scheduled workout plus install instructions."""
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("HOW TO ADD TO ZWIFT.txt", INSTRUCTIONS)
        for day, workout in items:
            name = filename(workout["name"], day)
            n = 2
            while name in used:
                name = filename(f"{workout['name']} {n}", day)
                n += 1
            used.add(name)
            z.writestr(name, zwo(workout, author))
    return buf.getvalue()
