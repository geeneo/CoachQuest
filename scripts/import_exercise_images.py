"""Build backend/app/data/exercise-images/ from the Free Exercise DB photos.

Source: https://github.com/yuhonas/free-exercise-db (exercises/<id>/0.jpg and 1.jpg,
the start and end of the movement). The dataset is Unlicense, but where the photos
first came from isn't documented, so the super admin can hide them (runtime
setting `exercise_photos`). Each photo is shrunk to 400 px WebP (~8 KB). Usage:

    pip install pillow
    python scripts/import_exercise_images.py

Only exercises in backend/app/data/exercises.json; photos already there are skipped.
"""

import io
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

BASE = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"
DATA = Path(__file__).resolve().parent.parent / "backend" / "app" / "data"
SIZE, QUALITY = 400, 70


def fetch(exercise_id: str, n: int) -> str | None:
    dest = DATA / "exercise-images" / exercise_id / f"{n}.webp"
    if dest.exists():
        return None
    try:
        with urllib.request.urlopen(f"{BASE}{exercise_id}/{n}.jpg", timeout=30) as r:
            im = Image.open(io.BytesIO(r.read())).convert("RGB")
    except OSError as exc:
        return f"{exercise_id}/{n}: {exc}"
    im.thumbnail((SIZE, SIZE))
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "WEBP", quality=QUALITY)
    return None


def main() -> None:
    ids = [e["id"] for e in json.loads((DATA / "exercises.json").read_text())]
    with ThreadPoolExecutor(8) as pool:
        errors = [e for e in pool.map(lambda job: fetch(*job), [(i, n) for i in ids for n in (0, 1)]) if e]
    files = list((DATA / "exercise-images").rglob("*.webp"))
    print(f"{len(files)} photos, {sum(f.stat().st_size for f in files) / 1e6:.1f} MB")
    for e in errors:
        print("missing", e, file=sys.stderr)


if __name__ == "__main__":
    main()
