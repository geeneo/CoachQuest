"""Admin page: settings, users, version and usage stats."""

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from .. import mailer, runtime
from ..config import settings
from ..db import AiCall, Connection, Session, User, get_db
from ..deps import admin_user

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/version")
def version(_: User = Depends(admin_user)):
    return {"commit": settings.build_commit, "built": settings.build_time}


@router.get("/stats")
def stats(_: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    return {
        "users": db.scalar(select(func.count(User.id))),
        "connections": dict(db.execute(select(Connection.provider, func.count()).group_by(Connection.provider)).all()),
        "connection_errors": db.scalar(select(func.count()).where(Connection.status == "error")),
        "ai_calls": dict(db.execute(select(AiCall.status, func.count()).group_by(AiCall.status)).all()),
        "ai_tokens": {
            "input": db.scalar(select(func.coalesce(func.sum(AiCall.input_tokens), 0))),
            "output": db.scalar(select(func.coalesce(func.sum(AiCall.output_tokens), 0))),
        },
    }


# ---- settings ----


@router.get("/settings")
def list_settings(_: User = Depends(admin_user)):
    return {
        "settings": runtime.describe(),
        "env_only": {
            "PUBLIC_BASE_URL": settings.public_base_url,
            "strava_callback_domain": settings.public_base_url.split("://")[-1].split("/")[0],
        },
    }


class SettingsUpdate(BaseModel):
    # key -> new value; "" removes the web value and falls back to .env
    values: dict[str, str]


@router.put("/settings")
def update_settings(body: SettingsUpdate, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    try:
        for key, value in body.values.items():
            if value.strip():
                runtime.validate(key, value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    for key, value in body.values.items():
        runtime.save(db, key, value.strip(), admin.id)
    return {"settings": runtime.describe()}


@router.post("/settings/test-anthropic")
async def test_anthropic(_: User = Depends(admin_user)):
    """Checks the key and model with a free models lookup, no tokens spent."""
    key, model = runtime.get("anthropic_api_key"), runtime.get("anthropic_model")
    if not key:
        return {"ok": False, "message": "No API key set."}
    try:
        info = await anthropic.AsyncAnthropic(api_key=key, max_retries=0).models.retrieve(model)
    except anthropic.AuthenticationError:
        return {"ok": False, "message": "Anthropic rejected the API key."}
    except anthropic.NotFoundError:
        return {"ok": False, "message": f"The key works, but model {model!r} was not found."}
    except anthropic.APIStatusError as exc:
        return {"ok": False, "message": f"Anthropic returned an error ({exc.status_code})."}
    except anthropic.APIConnectionError:
        return {"ok": False, "message": "Could not reach api.anthropic.com from the server."}
    return {"ok": True, "message": f"Key works. Model: {info.display_name or info.id}."}


class TestEmail(BaseModel):
    to: EmailStr | None = None


@router.post("/settings/test-email")
async def test_email(body: TestEmail, admin: User = Depends(admin_user)):
    to = body.to or admin.email
    try:
        await mailer.send(
            to,
            "CoachQuest test email",
            f"This is a test from CoachQuest ({settings.public_base_url}).\n\nIf you can read this, email works.",
        )
    except mailer.MailError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": f"Sent to {to}. Check the inbox (and spam folder)."}


# ---- users ----


@router.get("/users")
def list_users(_: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "is_admin": u.is_admin,
            "is_active": u.is_active,
            "created_at": u.created_at,
        }
        for u in users
    ]


class UserUpdate(BaseModel):
    is_admin: bool | None = None
    is_active: bool | None = None


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and (body.is_admin is False or body.is_active is False):
        raise HTTPException(status_code=400, detail="You can't remove your own admin rights or disable yourself")
    if body.is_admin is not None:
        user.is_admin = body.is_admin
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            # Sign the user out everywhere right away.
            db.execute(delete(Session).where(Session.user_id == user.id))
    db.commit()
    return {"ok": True}
