"""The shareable information page (welcome.py): public behind its private link, edited by admins."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from .. import runtime, welcome
from ..db import User, get_db
from ..deps import admin_user

public = APIRouter(prefix="/api/welcome", tags=["welcome"])
admin = APIRouter(prefix="/api/admin/welcome", tags=["welcome"])
NOINDEX = {"X-Robots-Tag": "noindex, nofollow, noarchive", "Cache-Control": "private, no-store"}


def _open(db: DbSession, key: str):
    p = welcome.open_page(db, key)
    if p is None:  # off, or a wrong or old link: the same answer, so links can't be guessed
        raise HTTPException(status_code=404, detail="This page isn't available", headers=NOINDEX)
    return p


@public.get("/{key}")
def show(key: str, db: DbSession = Depends(get_db)):
    p = _open(db, key)
    return {
        "title": p.title,
        "body_md": p.body_md,
        "signup": runtime.get("registration_mode") != "closed",
        "approval": runtime.get("signup_approval") == "on",
    }


@public.get("/{key}/img/{name}")
def image(key: str, name: str, db: DbSession = Depends(get_db)):
    _open(db, key)
    path = welcome.image_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="No such image")
    return FileResponse(path, headers=NOINDEX)


def _out(p) -> dict:
    return {
        "enabled": p.enabled,
        "link": welcome.link(p),
        "key": p.key,
        "title": p.title,
        "body_md": p.body_md,
        "images": welcome.images(),
        "updated_at": p.updated_at,
    }


@admin.get("")
def get_page(_: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    return _out(welcome.page(db))


class PageIn(BaseModel):
    enabled: bool | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body_md: str | None = Field(default=None, max_length=50_000)


@admin.put("")
def save_page(body: PageIn, user: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    p = welcome.page(db)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    welcome.touch(p, user.id)
    db.commit()
    return _out(p)


@admin.post("/new-link")
def new_link(user: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    """A new secret link; the old one stops working at once."""
    p = welcome.page(db)
    p.key = welcome.new_key()
    welcome.touch(p, user.id)
    db.commit()
    return _out(p)


class ImageIn(BaseModel):
    data_b64: str = Field(max_length=8 * 1024 * 1024)


@admin.post("/images")
def add_image(body: ImageIn, _: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    try:
        name = welcome.save_image(body.data_b64)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**_out(welcome.page(db)), "added": name}


@admin.delete("/images/{name}")
def delete_image(name: str, _: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    path = welcome.image_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="No such image")
    path.unlink()
    return _out(welcome.page(db))
