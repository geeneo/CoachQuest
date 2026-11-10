"""Heart-rate training load from time in zones, as TrainingPeaks scores hrTSS, for sessions without power.

The average heart rate of a ride hides how it was ridden: an hour of hill repeats and an hour steady can
have the same average, but the hard one costs far more. TrainingPeaks' hrTSS therefore scores the time
spent in each heart-rate zone (zones from the lactate threshold heart rate, LTHR) and adds it up, so that
an hour at threshold is 100.

Here every second of heart rate counts by its share of LTHR, through an intensity that follows the zones
(ZONE_IF, piecewise linear) and is squared, like power-based TSS: TSS = Σ seconds/3600 × IF² × 100. An hour
at LTHR is 100, easy riding in zone 1-2 counts less than its average would suggest, and hard efforts more.
TrainingPeaks doesn't publish its zone weights, so the curve is a close reading of its zones, not a copy.

The seconds are kept per heart-rate beat (Activity.hr_histogram, {"142": 315, ...}) rather than per zone,
so a new LTHR, or the LTHR of the workout's own date (threshold history), scores it again without
fetching anything.

Fetching (fill): every few minutes a handful of sessions scored by average heart rate get their heart-rate
stream from where they came from (Strava's activity streams, Garmin's activity details), newest first,
within the providers' limits. A session whose stream can't be had keeps its average-based score.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .db import Activity, Connection, SessionLocal, User, utcnow
from .fitness import rescore
from .security import decrypt_json, encrypt_json

log = logging.getLogger("coachquest.hr_load")

# (share of LTHR, intensity), following the usual TSS-an-hour per heart-rate zone: zone 1 (under 81%)
# up to ~50, zone 2 (81-89%) ~50-60, zone 3 (90-93%) ~60-70, zone 4 (94-99%) ~70-90, an hour at LTHR 100,
# zone 5 above. Calibrate against TrainingPeaks with the compare page (three-way compare on the TODO).
ZONE_IF = [(0.0, 0.0), (0.5, 0.4), (0.7, 0.55), (0.81, 0.71), (0.89, 0.77), (0.93, 0.84), (0.99, 0.95),
           (1.0, 1.0), (1.02, 1.025), (1.06, 1.07), (1.15, 1.18)]  # fmt: skip
MAX_GAP_S = 30  # a longer gap between samples is a pause: it counts as 30 s at most
METHODS = ("hr", "walk hr")  # sessions scored by their average heart rate: candidates for zones
LOOKBACK_DAYS = 400
PER_RUN = {"strava": 15, "garmin": 10}  # Strava: 100 requests a quarter of an hour for everything


def intensity(share: float) -> float:
    """Intensity (like IF) for a heart rate as a share of LTHR."""
    if share >= ZONE_IF[-1][0]:
        return ZONE_IF[-1][1]
    for (x0, y0), (x1, y1) in zip(ZONE_IF, ZONE_IF[1:], strict=False):
        if share <= x1:
            return y0 + (y1 - y0) * (share - x0) / (x1 - x0)
    return ZONE_IF[-1][1]


def histogram(times: list[float], hrs: list[float]) -> dict[str, int]:
    """Seconds at each heart rate (bpm) from a stream of (time, heart rate) samples."""
    out: dict[str, float] = {}
    for i in range(1, min(len(times), len(hrs))):
        dt = min(MAX_GAP_S, max(0.0, float(times[i]) - float(times[i - 1])))
        hr = hrs[i]
        if not dt or not hr or hr < 30 or hr > 240:
            continue
        key = str(round(hr))
        out[key] = out.get(key, 0) + dt
    return {k: round(v) for k, v in out.items() if round(v)}


def tss(hist: dict[str, int] | None, lthr: float | None) -> float | None:
    """TSS from the seconds at each heart rate against LTHR; None without them."""
    if not hist or not lthr:
        return None
    total = sum(secs / 3600 * intensity(int(bpm) / lthr) ** 2 * 100 for bpm, secs in hist.items())
    return round(total, 1)


# ---- fetching the streams ----


async def _strava_stream(db: DbSession, conn: Connection, external_id: str) -> tuple[list, list] | None:
    from .providers import strava

    data = await strava._get(
        db, conn, f"/activities/{external_id}/streams", {"keys": "time,heartrate", "key_by_type": "true"}
    )
    times = ((data or {}).get("time") or {}).get("data") or []
    hrs = ((data or {}).get("heartrate") or {}).get("data") or []
    return (times, hrs) if times and hrs else None


def _garmin_streams(tokens: str, ids: list[str]) -> tuple[str, dict[str, tuple[list, list] | None]]:
    """Blocking: log in once and fetch each activity's heart rate samples (in a thread)."""
    import garminconnect

    api = garminconnect.Garmin()
    api.login(tokenstore=tokens)
    out: dict[str, tuple[list, list] | None] = {}
    for ext in ids:
        try:
            d = api.get_activity_details(ext, maxchart=4000, maxpoly=0)
            keys = {m.get("key"): m.get("metricsIndex") for m in d.get("metricDescriptors") or []}
            hr_i, t_i = keys.get("directHeartRate"), keys.get("sumDuration")
            rows = [r.get("metrics") or [] for r in d.get("activityDetailMetrics") or []]
            if hr_i is None or t_i is None:
                out[ext] = None
                continue
            pairs = [(r[t_i], r[hr_i]) for r in rows if len(r) > max(hr_i, t_i) and r[t_i] is not None]
            out[ext] = ([p[0] for p in pairs], [p[1] for p in pairs]) if pairs else None
        except Exception as exc:  # one activity: keep its average-based score
            log.info("Garmin details for %s failed: %r", ext, exc)
            out[ext] = None
    return api.client.dumps(), out


def candidates(db: DbSession, source: str, limit: int) -> list[Activity]:
    since = utcnow() - timedelta(days=LOOKBACK_DAYS)
    return list(
        db.scalars(
            select(Activity)
            .where(
                Activity.source == source,
                Activity.tss_method.in_(METHODS),
                Activity.avg_hr.is_not(None),
                Activity.hr_tried_at.is_(None),
                Activity.start_time >= since,
            )
            .order_by(Activity.start_time.desc())
            .limit(limit)
        )
    )


def _apply(db: DbSession, a: Activity, stream: tuple[list, list] | None) -> bool:
    a.hr_tried_at = utcnow()
    if stream is None:
        return False
    hist = histogram(*stream)
    if not hist:
        return False
    a.hr_histogram = hist
    rescore(a, db.get(User, a.user_id))
    return True


async def fill() -> int:
    """Scheduler job: heart-rate zones for the newest sessions still scored by their average. Returns how
    many were scored by zones."""
    done = 0
    with SessionLocal() as db:
        # Strava, one request each.
        for a in candidates(db, "strava", PER_RUN["strava"]):
            conn = db.scalar(
                select(Connection).where(
                    Connection.user_id == a.user_id, Connection.provider == "strava", Connection.status == "active"
                )
            )
            if conn is None:
                a.hr_tried_at = utcnow()
                continue
            try:
                stream = await _strava_stream(db, conn, a.external_id)
            except Exception as exc:
                if "429" in str(exc):  # Strava's limit: try again next time
                    log.info("Strava rate limit while fetching heart rate streams")
                    break
                log.info("Strava stream for activity %s failed: %r", a.id, exc)
                stream = None
            done += _apply(db, a, stream)
            db.commit()
        # Garmin, one sign-in per athlete.
        by_user: dict[int, list[Activity]] = {}
        for a in candidates(db, "garmin", PER_RUN["garmin"] * 5):
            by_user.setdefault(a.user_id, []).append(a)
        for uid, acts in list(by_user.items())[:5]:
            acts = acts[: PER_RUN["garmin"]]
            conn = db.scalar(select(Connection).where(Connection.user_id == uid, Connection.provider == "garmin"))
            if conn is None or not conn.token_enc:
                for a in acts:
                    a.hr_tried_at = utcnow()
                db.commit()
                continue
            try:
                tokens = decrypt_json(conn.token_enc)["tokens"]
                new_tokens, streams = await asyncio.to_thread(_garmin_streams, tokens, [a.external_id for a in acts])
                conn.token_enc = encrypt_json({"tokens": new_tokens})
            except Exception as exc:  # signed out, or Garmin down: next time
                log.info("Garmin heart rate streams for user %s failed: %r", uid, exc)
                continue
            for a in acts:
                done += _apply(db, a, streams.get(a.external_id))
            db.commit()
    if done:
        log.info("Training load from heart-rate zones for %d sessions", done)
    return done
