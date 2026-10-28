"""The exercise library (strength.py): search it, and read one exercise's instructions."""

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import strength
from ..db import User
from ..deps import current_user

router = APIRouter(prefix="/api/exercises", tags=["exercises"])


@router.get("")
def search(
    q: str = Query(default="", max_length=60),
    category: str | None = None,
    equipment: str | None = None,
    _: User = Depends(current_user),
):
    """Up to 60 exercises whose name or muscles match `q`."""
    words = q.lower().split()
    out = []
    for e in strength.library().values():
        if category and e["category"] != category or equipment and e["equipment"] != equipment:
            continue
        text = f"{e['name']} {' '.join(e['primaryMuscles'])}".lower()
        if all(w in text for w in words):
            out.append({k: v for k, v in strength.exercise_out(e).items() if k != "instructions"})
        if len(out) >= 60:
            break
    return out


@router.get("/{exercise_id}")
def get_exercise(exercise_id: str, _: User = Depends(current_user)):
    e = strength.library().get(exercise_id)
    if e is None:
        raise HTTPException(status_code=404, detail="Exercise not found")
    return strength.exercise_out(e)
