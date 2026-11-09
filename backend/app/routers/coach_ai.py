"""AI coach: readiness, weekly reviews, progress and 'Ask the coach'.

Generating anything costs AI calls, so a coach needs the plans scope; the
athlete can always use it for themself. Reading progress needs fitness.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .. import assessments, coach_chat, comments, morning, race_target, week_status
from ..coach import CoachError
from ..db import Assessment, CoachChat, Comment, Race, User, get_db
from ..deps import allowed_scopes, current_user, require_scope, resolve_athlete_id

router = APIRouter(prefix="/api", tags=["ai coach"])


@router.get("/athletes/{athlete}/coach")
def overview(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    scopes = allowed_scopes(db, user, athlete_id)
    rows = db.scalars(
        select(Assessment).where(Assessment.athlete_id == athlete_id).order_by(Assessment.created_at.desc()).limit(40)
    ).all()
    n = comments.counts(db, "assessment", [a.id for a in rows])
    daily = [{**assessments.assessment_out(a), "comments": n.get(a.id, 0)} for a in rows if a.kind == "daily"]
    out = {
        "latest_daily": daily[0] if daily else None,
        "weekly": [{**assessments.assessment_out(a), "comments": n.get(a.id, 0)} for a in rows if a.kind == "weekly"][
            :12
        ],
        "progress": assessments.progress(db, athlete_id) if "fitness" in scopes else None,
    }
    if athlete_id == user.id:
        out["ai_settings"] = {**AiSettings().model_dump(), **(user.ai_settings or {})}
    return out


@router.get("/athletes/{athlete}/coach/week")
def week(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """How the current plan week is going, checked in code (no AI call): null without a current plan."""
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    return week_status.status(db, db.get(User, athlete_id), allowed_scopes(db, user, athlete_id))


class AssessmentRequest(BaseModel):
    kind: str = Field(pattern="^(daily|weekly)$")


@router.post("/athletes/{athlete}/coach/assessments")
async def create_assessment(
    athlete: str, body: AssessmentRequest, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    try:
        a = await assessments.create(db, user, db.get(User, athlete_id), body.kind)
    except CoachError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {**assessments.assessment_out(a), "unchanged": getattr(a, "reused", False)}


@router.post("/races/{race_id}/ctl-advice")
async def target_ctl_advice(race_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The AI coach's target CTL for the race's target time. The athlete's own races only."""
    race = db.get(Race, race_id)
    if race is None or race.user_id != user.id:
        raise HTTPException(status_code=404, detail="Race not found")
    try:
        return await race_target.suggest(db, race, user)
    except CoachError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


class AiSettings(BaseModel):
    daily: bool = False
    weekly: bool = False
    email: bool = False
    # The morning note: when (local time, HH:MM) and how long to wait for last night's sleep (morning.py).
    daily_time: str = Field(default=morning.DEFAULT_TIME, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    sleep_wait_min: int = Field(default=morning.DEFAULT_WAIT_MIN, ge=0, le=morning.MAX_WAIT_MIN)


@router.put("/me/ai-settings")
def set_ai_settings(body: AiSettings, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    user.ai_settings = body.model_dump()
    db.commit()
    return user.ai_settings


def chat_out(chat: CoachChat) -> dict:
    return {"id": chat.id, "updated_at": chat.updated_at, "messages": coach_chat.visible(chat.messages)}


def _chat(db: DbSession, user: User, athlete_id: int, chat_id: int) -> CoachChat:
    chat = db.get(CoachChat, chat_id)
    if chat is None or chat.viewer_id != user.id or chat.athlete_id != athlete_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return chat


@router.get("/athletes/{athlete}/coach/chats")
def list_chats(athlete: str, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    rows = db.scalars(
        select(CoachChat)
        .where(CoachChat.athlete_id == athlete_id, CoachChat.viewer_id == user.id)
        .order_by(CoachChat.updated_at.desc())
        .limit(20)
    ).all()
    return [chat_out(c) for c in rows]


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    chat_id: int | None = None


@router.post("/athletes/{athlete}/coach/chats")
async def ask(athlete: str, body: Question, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Ask a question in a new conversation, or continue one with chat_id."""
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    if body.chat_id:
        chat = _chat(db, user, athlete_id, body.chat_id)
    else:
        chat = CoachChat(athlete_id=athlete_id, viewer_id=user.id, messages=[])
        db.add(chat)
        db.commit()
    try:
        chat = await coach_chat.ask(db, chat, user, db.get(User, athlete_id), body.question.strip())
    except CoachError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return chat_out(chat)


@router.delete("/athletes/{athlete}/coach/assessments/{assessment_id}")
def delete_assessment(
    athlete: str, assessment_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Remove a readiness note or weekly review (e.g. one whose advice is out of date), with its comments."""
    athlete_id = resolve_athlete_id(athlete, user)
    require_scope(db, user, athlete_id, "plans")
    a = db.get(Assessment, assessment_id)
    if a is None or a.athlete_id != athlete_id:
        raise HTTPException(status_code=404, detail="Not found")
    db.execute(delete(Comment).where(Comment.target == "assessment", Comment.target_id == a.id))
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.delete("/athletes/{athlete}/coach/chats/{chat_id}")
def delete_chat(athlete: str, chat_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    db.delete(_chat(db, user, resolve_athlete_id(athlete, user), chat_id))
    db.commit()
    return {"ok": True}
