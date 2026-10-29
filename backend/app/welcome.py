"""The shareable information page: what CoachQuest does, screenshots, how it works, and a way in.

Shown to anyone with the private link /welcome/<key> (no sign-in), never linked from the site, and
marked noindex everywhere; an admin edits it (Admin → Information page), switches it on or off, and
can make a new link, which makes the old one stop working. Screenshots that ship with the app are
under /welcome-assets/; ones admins add are stored in DATA_DIR/welcome and served through the link.
"""

import base64
import hmac
import re
import secrets
from pathlib import Path

from sqlalchemy.orm import Session as DbSession

from .config import settings
from .db import WelcomePage, utcnow

IMAGE_TYPES = {"png": b"\x89PNG", "jpg": b"\xff\xd8\xff", "webp": b"RIFF"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
DIAGRAM = "[[how-it-works]]"  # where the page shows the built-in "how it works" diagram

DEFAULT_TITLE = "CoachQuest: your training plan, from your own data"
DEFAULT_BODY = """CoachQuest is a training coach for cyclists and runners. It reads the rides, runs and
wellness you already record, writes a training plan around your goal and your week, and puts the
workouts on your calendar and on Zwift or MyWhoosh. Your human coach can watch, comment and approve.

## What it does

- **AI training plans** for an event (a race, a gran fondo, a stage race) or just to stay fit, built
  from your recent training, fitness and fatigue, your weekday preferences and your races.
- **Day by day:** each day says what to do, why, and for how long. Change a day, swap it, lock it,
  or ask the AI to re-plan just that day or the rest of the plan.
- **Workouts on your trainer:** indoor sessions become structured workouts that go to Zwift and
  MyWhoosh through Intervals.icu, or download as .zwo files.
- **Routes and segments:** your favourite Strava routes and climbs, used to plan outdoor rides and
  hill repeats; share them with other athletes.
- **Strength training** for cyclists and runners, with an exercise library.
- **Health first:** tick health conditions and the plan works around them.
- **Coaches and friends:** share what you choose with a coach (who can comment, edit and approve
  plans) or a friend (view only).
- **Your plan on Strava** (optional): what was planned and how it went, in your activity's
  description.

![Your training week, day by day](/welcome-assets/plan-week.webp)

## How it works

[[how-it-works]]

1. **Connect** Strava, Garmin and/or Intervals.icu. CoachQuest imports your activities and
   wellness (sleep, HRV, resting heart rate) and works out your fitness, fatigue and form.
2. **Set your week and goal:** what you like to do on each weekday, your races, health conditions
   and strength options.
3. **Get a plan:** the AI coach writes it from the data you shared; your coach can approve it first.
4. **Train:** workouts go to your calendar, Zwift and MyWhoosh; outdoor rides name the route.
5. **It keeps up:** done, partly done or missed shows on each day, and you can re-plan any time.

![Indoor workouts with their power profile](/welcome-assets/workout.webp)

![Strength sessions with the muscles they work](/welcome-assets/strength.webp)

## Your data

- You choose what each coach or friend sees, and can stop sharing at any time.
- The AI coach gets only what you shared, and health notes are only for you and your coaches.
- Deleting your account deletes your data and CoachQuest's access to your other apps.

CoachQuest is not medical advice. Always consult a doctor before starting or changing training,
especially with a medical condition or injury.
"""


def page(db: DbSession) -> WelcomePage:
    """The page, created with default content (off) the first time it's needed."""
    p = db.get(WelcomePage, 1)
    if p is None:
        p = WelcomePage(id=1, enabled=False, key=new_key(), title=DEFAULT_TITLE, body_md=DEFAULT_BODY)
        db.add(p)
        db.commit()
    return p


def new_key() -> str:
    return secrets.token_urlsafe(12)


def open_page(db: DbSession, key: str) -> WelcomePage | None:
    """The page if it's on and the key is right (compared in constant time), else None."""
    p = db.get(WelcomePage, 1)
    if p is None or not p.enabled or not hmac.compare_digest(p.key.encode(), (key or "").encode()):
        return None
    return p


def link(p: WelcomePage) -> str:
    return f"{settings.public_base_url}/welcome/{p.key}"


def images_dir() -> Path:
    return Path(settings.data_dir) / "welcome"


def images() -> list[str]:
    d = images_dir()
    return sorted(f.name for f in d.iterdir() if f.is_file()) if d.is_dir() else []


def image_path(name: str) -> Path | None:
    """A stored image by its name; only names we made (no paths)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,40}\.(png|jpg|webp)", name or ""):
        return None
    path = images_dir() / name
    return path if path.is_file() else None


def save_image(data_b64: str) -> str:
    """Store an uploaded screenshot (PNG, JPEG or WebP, checked by its first bytes). Returns its name."""
    try:
        data = base64.b64decode(data_b64, validate=True)
    except ValueError as exc:
        raise ValueError("That isn't an image") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Images up to 5 MB")
    ext = next((e for e, magic in IMAGE_TYPES.items() if data.startswith(magic)), None)
    if ext is None or (ext == "webp" and data[8:12] != b"WEBP"):
        raise ValueError("Use a PNG, JPEG or WebP image")
    images_dir().mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_urlsafe(9)}.{ext}"
    (images_dir() / name).write_bytes(data)
    return name


def touch(p: WelcomePage, admin_id: int) -> None:
    p.updated_by, p.updated_at = admin_id, utcnow()
