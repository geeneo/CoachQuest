"""Route geometry: Strava's encoded polylines, distances, bearings and even spacing along a route."""

import math

EARTH_M = 6_371_000

Point = tuple[float, float]  # (lat, lng)


def decode(encoded: str | None) -> list[Point]:
    """Google's encoded polyline format (what Strava's map.polyline / summary_polyline use)."""
    points: list[Point] = []
    if not encoded:
        return points
    i = lat = lng = 0
    try:
        while i < len(encoded):
            for axis in (0, 1):
                shift = result = 0
                while True:
                    b = ord(encoded[i]) - 63
                    i += 1
                    result |= (b & 0x1F) << shift
                    shift += 5
                    if b < 0x20:
                        break
                delta = ~(result >> 1) if result & 1 else result >> 1
                if axis == 0:
                    lat += delta
                else:
                    lng += delta
            points.append((lat / 1e5, lng / 1e5))
    except IndexError:  # a cut-off string: keep what decoded
        pass
    return points


def distance_m(a: Point, b: Point) -> float:
    """Haversine distance in metres."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(min(1.0, h)))


def bearing(a: Point, b: Point) -> float:
    """Direction of travel from a to b, degrees clockwise from north (0-360)."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def length_m(points: list[Point]) -> float:
    return sum(distance_m(points[i], points[i + 1]) for i in range(len(points) - 1))


def resample(points: list[Point], n: int) -> list[Point]:
    """n points spaced evenly by distance along the line (first and last included)."""
    if len(points) < 2 or n < 2:
        return list(points)
    cum = [0.0]
    for i in range(1, len(points)):
        cum.append(cum[-1] + distance_m(points[i - 1], points[i]))
    total = cum[-1]
    if total <= 0:
        return [points[0]] * n
    out, j = [], 0
    for k in range(n):
        target = total * k / (n - 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        seg = cum[j + 1] - cum[j]
        f = 0.0 if seg <= 0 else (target - cum[j]) / seg
        a, b = points[j], points[j + 1]
        out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    return out


def mean_gap_m(a: list[Point], b: list[Point]) -> float:
    """How far apart two routes are: the average distance from each point of `a` to the nearest of `b`
    (direction doesn't matter, so a loop ridden either way round counts as the same route)."""
    if not a or not b:
        return float("inf")
    return sum(min(distance_m(p, q) for q in b) for p in a) / len(a)


def encode(points: list[Point]) -> str:
    """The reverse of decode (used to store lines and in tests)."""
    out, last = [], (0, 0)
    for lat, lng in points:
        cur = (round(lat * 1e5), round(lng * 1e5))
        for v in (cur[0] - last[0], cur[1] - last[1]):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        last = cur
    return "".join(out)
