"""Virtual fence zones. Points are stored normalised (0..1) so zones survive resolution
changes; all checks use the object's foot point (bottom-centre of its box)."""
import threading
import uuid

from ..config import ZONES_PATH, load_json, now_ist, save_json

ZONE_TYPES = ("restricted", "buffer", "count", "tripwire")
POLY_TYPES = ("restricted", "buffer")


def point_in_poly(pt, poly):
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def side(pt, a, b):
    return (b[0] - a[0]) * (pt[1] - a[1]) - (b[1] - a[1]) * (pt[0] - a[0])


def segments_intersect(p1, p2, a, b):
    d1, d2 = side(p1, a, b), side(p2, a, b)
    d3, d4 = side(a, p1, p2), side(b, p1, p2)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def dist_to_poly(pt, poly):
    best = 1e9
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = dx * dx + dy * dy or 1e-9
        u = max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / L))
        best = min(best, ((a[0] + u * dx - pt[0]) ** 2 + (a[1] + u * dy - pt[1]) ** 2) ** 0.5)
    return best


def _hhmm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


class ZoneEngine:
    def __init__(self, defaults=None):
        self._lock = threading.Lock()
        raw = load_json(ZONES_PATH, defaults or {})
        self.zones = {cid: self._clean(zs) for cid, zs in raw.items()}

    def get(self, cam_id):
        return self.zones.get(cam_id, [])

    def set(self, cam_id, zones):
        clean = self._clean(zones)
        with self._lock:
            self.zones[cam_id] = clean
            save_json(ZONES_PATH, self.zones)
        return clean

    def reset(self, defaults):
        with self._lock:
            self.zones = {cid: self._clean(zs) for cid, zs in defaults.items()}
            save_json(ZONES_PATH, self.zones)

    @staticmethod
    def _clean(zones):
        clean = []
        for z in zones:
            if z.get("type") not in ZONE_TYPES:
                continue
            pts = [[min(1.0, max(0.0, float(x))), min(1.0, max(0.0, float(y)))] for x, y in z.get("points", [])]
            if (z["type"] in POLY_TYPES and len(pts) < 3) or (z["type"] not in POLY_TYPES and len(pts) != 2):
                continue
            clean.append({"id": z.get("id") or uuid.uuid4().hex[:8], "name": z.get("name") or z["type"].title(),
                          "type": z["type"], "points": pts, "objects": z.get("objects", "both"),
                          "schedule": z.get("schedule", "always"), "from": z.get("from", "20:00"),
                          "to": z.get("to", "06:00"), "direction": z.get("direction", "any"),
                          "armed": bool(z.get("armed", True))})
        return clean

    @staticmethod
    def armed(z, is_night):
        if not z.get("armed", True):
            return False
        if z["schedule"] == "night":
            return is_night
        if z["schedule"] == "custom":
            now = now_ist()
            m = now.hour * 60 + now.minute
            a, b = _hhmm(z["from"]), _hhmm(z["to"])
            return a <= m < b if a <= b else (m >= a or m < b)
        return True

    @staticmethod
    def accepts(z, track):
        o = z.get("objects", "both")
        return (o == "both" and (track.is_person or track.is_vehicle)) or (o == "person" and track.is_person) \
            or (o == "vehicle" and track.is_vehicle)

    def check(self, cam_id, track, wh, is_night, t):
        """Returns zone hits for this track: kind in {'enter','inside','cross'}."""
        w, h = wh
        fx, fy = track.foot
        pt = (fx / w, fy / h)
        prev = None
        if len(track.hist) >= 2:
            p = track.hist[-2]
            prev = (p[1] / w, p[2] / h)
        hits = []
        for z in self.get(cam_id):
            if not self.accepts(z, track):
                continue
            armed = self.armed(z, is_night)
            if z["type"] in POLY_TYPES:
                inside = point_in_poly(pt, z["points"])
                was = track.zone_inside.get(z["id"], False)
                track.zone_inside[z["id"]] = inside
                if inside and not was:
                    track.zone_since[z["id"]] = t
                if inside and armed:
                    hits.append({"zone": z, "kind": "enter" if not was else "inside",
                                 "since": track.zone_since.get(z["id"], t)})
            elif prev is not None:
                a, b = z["points"]
                if segments_intersect(prev, pt, a, b):
                    # forward = crossing to the left-hand side of the line drawn from point A to point B
                    direction = "forward" if side(pt, a, b) < 0 else "reverse"
                    track.crossings.setdefault(z["id"], []).append(t)
                    if armed and (z["direction"] == "any" or z["direction"] == direction):
                        hits.append({"zone": z, "kind": "cross", "direction": direction})
                    elif z["type"] == "count":
                        hits.append({"zone": z, "kind": "cross", "direction": direction})
        return hits

    def near_fence(self, cam_id, track, wh, margin=0.08):
        w, h = wh
        fx, fy = track.foot
        pt = (fx / w, fy / h)
        for z in self.get(cam_id):
            if z["type"] in ("restricted", "buffer"):
                if point_in_poly(pt, z["points"]) or dist_to_poly(pt, z["points"]) < margin:
                    return z
            elif z["type"] == "tripwire" and dist_to_poly(pt, z["points"]) < margin:
                return z
        return None
