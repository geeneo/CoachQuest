"""News and how-to guides: admins write and publish them, everyone signed in reads the published ones."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import Post, User, get_db, utcnow
from ..deps import admin_user, current_user

router = APIRouter(prefix="/api/posts", tags=["posts"])


class PostIn(BaseModel):
    kind: str = Field(pattern="^(news|guide)$")
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=300)
    body_md: str = Field(default="", max_length=50_000)
    published: bool = False
    position: int = Field(default=0, ge=0, le=1000)


def post_out(p: Post, db: DbSession, full: bool = True) -> dict:
    author = db.get(User, p.author_id) if p.author_id else None
    out = {
        "id": p.id,
        "kind": p.kind,
        "title": p.title,
        "summary": p.summary,
        "published": p.published,
        "published_at": p.published_at,
        "position": p.position,
        "author": author.display_name if author else None,
        "updated_at": p.updated_at,
    }
    if full:
        out["body_md"] = p.body_md
    return out


def _visible(db: DbSession, user: User, post_id: int) -> Post:
    p = db.get(Post, post_id)
    if p is None or (not p.published and not user.is_admin):
        raise HTTPException(status_code=404, detail="Post not found")
    return p


@router.get("")
def list_posts(
    kind: str | None = Query(default=None, pattern="^(news|guide)$"),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Published posts; admins also get drafts. News newest first, guides in their set order."""
    query = select(Post)
    if kind:
        query = query.where(Post.kind == kind)
    if not user.is_admin:
        query = query.where(Post.published.is_(True))
    rows = db.scalars(query).all()
    news = sorted((p for p in rows if p.kind == "news"), key=lambda p: p.published_at or p.created_at, reverse=True)
    guides = sorted((p for p in rows if p.kind == "guide"), key=lambda p: (p.position, p.title.lower()))
    return {
        "news": [post_out(p, db, full=False) for p in news],
        "guides": [post_out(p, db, full=False) for p in guides],
        "can_edit": user.is_admin,
    }


@router.get("/{post_id}")
def get_post(post_id: int, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    return post_out(_visible(db, user, post_id), db)


def _apply(p: Post, body: PostIn) -> None:
    for k, v in body.model_dump().items():
        setattr(p, k, v.strip() if isinstance(v, str) else v)
    if p.published and p.published_at is None:
        p.published_at = utcnow()  # first published; kept when unpublished and published again
    p.updated_at = utcnow()


@router.post("")
def create_post(body: PostIn, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    p = Post(author_id=admin.id)
    _apply(p, body)
    db.add(p)
    db.commit()
    return post_out(p, db)


@router.put("/{post_id}")
def update_post(post_id: int, body: PostIn, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    p = _visible(db, admin, post_id)
    _apply(p, body)
    db.commit()
    return post_out(p, db)


@router.delete("/{post_id}")
def delete_post(post_id: int, admin: User = Depends(admin_user), db: DbSession = Depends(get_db)):
    db.delete(_visible(db, admin, post_id))
    db.commit()
    return {"ok": True}
