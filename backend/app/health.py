"""Health conditions an athlete ticks in Profile, so the AI coach plans around them.

Each condition: {"id", "side" (left|right|both, for joints and tendons), "status" (current|past),
"cleared" (true: a doctor cleared them for training; false; null: not asked), "note"}.
Health data is special personal information (POPIA / GDPR): the athlete opts in, only they and a
coach with the plans scope see it (never friends or the admin view), and nobody else edits it.
CoachQuest isn't medical advice: DISCLAIMER shows wherever conditions or plans do.
"""

from .db import User
from .deps import FRIEND, active_grant

DISCLAIMER = (
    "CoachQuest is not medical advice. Always consult a doctor or other qualified health professional "
    "before starting or changing training, especially with a medical condition or injury. Stop and get "
    "help if you feel chest pain, dizziness, unusual shortness of breath or pain."
)

# (id, label, sided) per group. Heart conditions need the disclaimer accepted first.
GROUPS = {
    "Heart and circulation": [
        ("heart_condition", "Heart condition", False),
        ("high_blood_pressure", "High blood pressure", False),
        ("arrhythmia", "Irregular heartbeat (e.g. atrial fibrillation)", False),
        ("pacemaker", "Pacemaker or ICD", False),
        ("beta_blockers", "On beta blockers", False),
    ],
    "Joints": [
        ("knee", "Knee", True),
        ("hip", "Hip", True),
        ("ankle", "Ankle", True),
        ("shoulder", "Shoulder", True),
        ("lower_back", "Lower back", False),
        ("neck", "Neck", False),
        ("wrist", "Wrist or hand", True),
    ],
    "Muscles and tendons": [
        ("achilles", "Achilles", True),
        ("hamstring", "Hamstring", True),
        ("calf", "Calf", True),
        ("plantar_fasciitis", "Plantar fasciitis (foot)", True),
        ("it_band", "IT band", True),
    ],
    "Other": [
        ("asthma", "Asthma", False),
        ("diabetes_1", "Diabetes type 1", False),
        ("diabetes_2", "Diabetes type 2", False),
        ("osteoporosis", "Osteoporosis or low bone density", False),
        ("pregnancy", "Pregnant or postpartum", False),
        ("surgery", "Recent surgery", False),
        ("concussion", "Concussion", False),
        ("illness", "Recent illness (e.g. COVID)", False),
        ("other", "Other", False),
    ],
}
CONDITIONS = {cid: (label, sided, group) for group, items in GROUPS.items() for cid, label, sided in items}
HEART = {cid for cid, _, _ in GROUPS["Heart and circulation"]}
SIDES = ("left", "right", "both")


def catalog() -> list[dict]:
    return [
        {"group": g, "conditions": [{"id": c, "label": label, "sided": sided} for c, label, sided in items]}
        for g, items in GROUPS.items()
    ]


def clean(raw: list) -> list[dict]:
    """Check conditions from Profile. Raises ValueError."""
    out, seen = [], set()
    for x in raw or []:
        cid = x.get("id") if isinstance(x, dict) else None
        if cid not in CONDITIONS:
            raise ValueError(f"Unknown condition: {cid}")
        if cid in seen:
            continue
        seen.add(cid)
        side = x.get("side") if CONDITIONS[cid][1] and x.get("side") in SIDES else None
        cleared = x.get("cleared")
        out.append(
            {
                "id": cid,
                "side": side,
                "status": "past" if x.get("status") == "past" else "current",
                "cleared": cleared if isinstance(cleared, bool) else None,
                "note": str(x.get("note") or "").strip()[:200],
            }
        )
    if any(c["id"] == "other" and not c["note"] for c in out):
        raise ValueError('Say what "Other" is in its note')
    return out


def can_see(db, viewer: User, athlete_id: int) -> bool:
    """The athlete, or a coach (not a friend) with the plans scope. Not the admin view."""
    if viewer.id == athlete_id:
        return True
    grant = active_grant(db, athlete_id, viewer.id)
    return grant is not None and grant.role != FRIEND and "plans" in (grant.scopes or [])


def out(user: User) -> dict:
    return {
        "conditions": user.health_conditions or [],
        "disclaimer_accepted_at": user.health_disclaimer_at,
        "catalog": catalog(),
        "disclaimer": DISCLAIMER,
    }


def for_ai(user: User) -> list[dict]:
    """The athlete's conditions in words, for the AI coach (plan rules in coach.SYSTEM_PROMPT)."""
    items = []
    for c in user.health_conditions or []:
        label, _, group = CONDITIONS[c["id"]]
        items.append(
            {
                "condition": label + (f" ({c['side']})" if c.get("side") else ""),
                "group": group,
                "status": c["status"],
                "cleared_by_doctor": c["cleared"],
                **({"note": c["note"]} if c.get("note") else {}),
            }
        )
    return items
