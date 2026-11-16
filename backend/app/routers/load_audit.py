"""Training load audit (load_audit.py): read only, for the athlete and anyone with their fitness and
activities shared."""

import base64
import binascii
import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from .. import load_audit
from ..db import User, get_db
from ..deps import current_user, require_scope, resolve_athlete_id

router = APIRouter(prefix="/api/athletes/{athlete}/load-audit", tags=["load audit"])


def _athlete(db: DbSession, user: User, athlete: str) -> User:
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "fitness")
    require_scope(db, user, athlete_id, "activities")
    return db.get(User, athlete_id)


@router.get("")
def audit(
    athlete: str,
    days: int = Query(default=180, ge=7, le=730),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    return load_audit.audit(db, _athlete(db, user, athlete), days)


@router.get("/{part}.csv")
def audit_csv(
    athlete: str,
    part: str,
    days: int = Query(default=180, ge=7, le=730),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """The days (date, TSS, CTL, ATL, TSB) or the activities (source, IDs, status, TSS and method) as CSV."""
    if part not in ("days", "activities"):
        raise HTTPException(status_code=404, detail="Not found")
    a = _athlete(db, user, athlete)
    data = load_audit.audit(db, a, days)
    name = f"coachquest-load-{part}-{data['meta']['to']}.csv"
    return Response(
        load_audit.csv_text(data[part]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# Uploads to compare with (nginx allows 45 MB for this route; the page checks the same sizes first).
MAX_CSV_CHARS = 30_000_000
MAX_ZIP_B64 = 40_000_000  # a 30 MB ZIP once base64
# A CSV inside a ZIP is read as a stream, never whole; this only stops a ZIP bomb.
MAX_UNZIPPED_CSV = 300_000_000


class Other(BaseModel):
    csv: str = Field(default="", max_length=MAX_CSV_CHARS)
    # TrainingPeaks' Export Data can hand the summary over as a ZIP: its bytes, base64.
    zip_b64: str = Field(default="", max_length=MAX_ZIP_B64)
    days: int = Field(default=180, ge=7, le=730)


def _csv_from_zip(b64: str) -> str:
    """The first CSV in a ZIP, whole (athletes.py: TrainingPeaks thresholds, small files)."""
    try:
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(b64))) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
            if name is None:
                raise ValueError("No CSV file in that ZIP")
            return z.read(name).decode("utf-8-sig", errors="replace")
    except (zipfile.BadZipFile, ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail=f"Couldn't read that ZIP: {exc}") from exc


# Session recordings: TrainingPeaks' "workout files" export (WorkoutFileExport-*.zip), often gzipped.
_WORKOUT_FILE = (".fit", ".tcx", ".gpx", ".pwx", ".fit.gz", ".tcx.gz", ".gpx.gz", ".pwx.gz", ".gz")


def _no_csv_message(names: list[str]) -> str:
    """Why a ZIP has nothing to compare: most often the workout files export instead of the summary."""
    files = [n for n in names if not n.endswith("/")]
    if files and sum(n.lower().endswith(_WORKOUT_FILE) for n in files) * 2 >= len(files):
        return (
            f"That ZIP holds {len(files)} workout files (one recording per session), TrainingPeaks' workout "
            "files export. The comparison needs the Workout Summary instead: in TrainingPeaks, your name "
            "(top right) → Settings → Export Data → Workout Summary, the same dates as here."
        )
    shown = ", ".join(files[:5]) + (f" and {len(files) - 5} more" if len(files) > 5 else "")
    return (
        f"Couldn't read that ZIP: no CSV file in it ({shown or 'it is empty'}). Use TrainingPeaks' "
        "Workout Summary export (Settings → Export Data → Workout Summary)."
    )


def _parse_zip(b64: str) -> dict[str, dict]:
    """The first CSV in a ZIP (TrainingPeaks' Workout Summary export), read row by row."""
    try:
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(b64))) as z:
            info = next((i for i in z.infolist() if i.filename.lower().endswith(".csv")), None)
            if info is None:
                raise HTTPException(status_code=422, detail=_no_csv_message(z.namelist()))
            if info.file_size > MAX_UNZIPPED_CSV:
                raise ValueError(f"the CSV in it is {info.file_size // 1_000_000} MB unzipped; export a shorter range")
            with z.open(info) as raw:
                return load_audit.parse_other(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace"))
    except (zipfile.BadZipFile, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail=f"Couldn't read that ZIP: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Couldn't read that ZIP: {exc}") from exc


@router.post("/compare")
def compare(athlete: str, body: Other, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Day by day against another platform's export (TrainingPeaks workouts or PMC CSV)."""
    a = _athlete(db, user, athlete)
    if body.zip_b64:
        other = _parse_zip(body.zip_b64)
    else:
        if len(body.csv.strip()) < 10:
            raise HTTPException(status_code=422, detail="That file is empty")
        try:
            other = load_audit.parse_other(body.csv)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return load_audit.compare(load_audit.audit(db, a, body.days)["days"], other)
