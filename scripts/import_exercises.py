"""Build backend/app/data/exercises.json from the public-domain Free Exercise DB.

Source: https://github.com/yuhonas/free-exercise-db (Unlicense, public domain),
dist/exercises.json. Usage:

    curl -sSLo /tmp/exercises.json https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json
    python scripts/import_exercises.py /tmp/exercises.json

Keeps the categories useful to cyclists and runners. The photos are imported
separately (scripts/import_exercise_images.py).
"""

import json
import sys
from pathlib import Path

KEEP = {"strength", "plyometrics", "powerlifting", "stretching"}
FIELDS = ("id", "name", "category", "equipment", "level", "force", "mechanic", "primaryMuscles", "secondaryMuscles")


def main(src: str) -> None:
    data = json.loads(Path(src).read_text())
    out = []
    for x in data:
        if x.get("category") not in KEEP:
            continue
        item = {k: x.get(k) for k in FIELDS}
        item["equipment"] = item["equipment"] or "body only"
        item["instructions"] = [s.strip() for s in x.get("instructions") or [] if s.strip()]
        out.append(item)
    out.sort(key=lambda e: e["id"])
    dest = Path(__file__).resolve().parent.parent / "backend" / "app" / "data" / "exercises.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(out)} exercises -> {dest}")


if __name__ == "__main__":
    main(sys.argv[1])
