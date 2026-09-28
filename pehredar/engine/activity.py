"""Suspicious-activity rules computed from ByteTrack track history.

Each finding carries a 0-100 risk score: a per-behaviour base, raised when it happens
inside a restricted/buffer zone, at night, or persists longer."""
import math

BASE_RISK = {"Loitering": 40, "Running": 35, "Wrong-way Movement": 45, "Group Gathering": 40,
             "Crawling Near Fence": 65, "Repeated Fence Passes": 55, "Abandoned Object": 70}


def severity_for(risk):
    if risk >= 75:
        return "critical"
    if risk >= 55:
        return "high"
    if risk >= 35:
        return "medium"
    return "info"


def risk_score(kind, zone_type=None, night=False, duration=0.0):
    r = BASE_RISK.get(kind, 30)
    r += {"restricted": 20, "buffer": 10, "tripwire": 10}.get(zone_type, 0)
    r += 15 if night else 0
    r += min(15, duration / 10)
    return int(max(0, min(100, r)))


class ActivityEngine:
    def __init__(self):
        self.groups = {}  # frozenset(ids) -> first seen
        self.object_alone_since = {}

    @staticmethod
    def _at_edge(tr, wh, m=3):
        x1, y1, x2, y2 = tr.box
        return x1 < m or y1 < m or x2 > wh[0] - m or y2 > wh[1] - m

    def evaluate(self, cam, tracks, zones, wh, night, t, cfg):
        found = []
        persons = [tr for tr in tracks if tr.is_person and tr.height >= 24]
        riders = [tr for tr in tracks if tr.name in ("bicycle", "motorcycle")]

        for tr in persons:
            zone_in = next((z for z in zones.get(cam["id"]) if tr.zone_inside.get(z["id"])
                            and z["type"] in ("restricted", "buffer")), None)
            # 1. loitering — inside a zone longer than N s, or barely moving for N s
            if zone_in:
                dur = t - tr.zone_since.get(zone_in["id"], t)
                if dur >= cfg["loiter_seconds"]:
                    found.append(self._f("Loitering", [tr], f"#{tr.tid} inside {zone_in['name']} for {dur:.0f}s",
                                         zone_in, night, dur))
            else:
                span = tr.span_bh(cfg["loiter_seconds"])
                if span is not None and span < 0.8:
                    found.append(self._f("Loitering", [tr], f"#{tr.tid} stationary ~{cfg['loiter_seconds']}s (moved {span:.1f} body-heights)",
                                         None, night, tr.dwell))
            # 2. running — needs >=1 s of history, a box not clipped by the frame edge
            # (clipping fakes motion), and not a cyclist/motorcyclist
            if tr.dwell >= 1.0 and not self._at_edge(tr, wh) and not any(self._rides(tr, r) for r in riders):
                sp = tr.speed_bh(1.0)
                if sp >= cfg["run_speed_bh_s"]:
                    found.append(self._f("Running", [tr], f"#{tr.tid} moving {sp:.1f} body-heights/s", zone_in, night, 0))
            # 5. crawling / crouching near fence — wide, low box near a fence zone
            x1, y1, x2, y2 = tr.box
            aspect = (x2 - x1) / max(y2 - y1, 1)
            if aspect >= cfg["crawl_aspect"]:
                tr.aspect_since = tr.aspect_since or t
                near = zones.near_fence(cam["id"], tr, wh)
                if near and t - tr.aspect_since >= 1.0:
                    found.append(self._f("Crawling Near Fence", [tr], f"#{tr.tid} low profile (w/h {aspect:.2f}) near {near['name']}",
                                         near, night, t - tr.aspect_since))
            else:
                tr.aspect_since = None
            # 6. repeated passes over the same line
            for zid, ts in tr.crossings.items():
                recent = [x for x in ts if t - x <= 60]
                if len(recent) >= cfg["repeat_passes"]:
                    z = next((z for z in zones.get(cam["id"]) if z["id"] == zid), None)
                    found.append(self._f("Repeated Fence Passes", [tr], f"#{tr.tid} crossed {z['name'] if z else 'line'} {len(recent)}× in 60s",
                                         z, night, 0))

        # 3. wrong-way — vehicles against the flow of a camera configured as one-way
        fx, fy = cam.get("flow", (0, 0))
        for tr in tracks:
            if not cam.get("one_way") or not tr.is_vehicle or len(tr.hist) < 8 or self._at_edge(tr, wh):
                continue
            vx, vy = tr.velocity(1.5)
            v = math.hypot(vx, vy)
            if v / max(tr.height, 1) > 0.4 and (vx * fx + vy * fy) / (v or 1) < -0.7:
                found.append(self._f("Wrong-way Movement", [tr], f"{tr.name} #{tr.tid} travelling against lane flow", None, night, 0))

        # 4. group gathering — >=N people within R body-heights of each other for >=T s
        found += self._groups(persons, night, t, cfg)

        # 7. abandoned object — bag/suitcase stationary with no person nearby
        for tr in tracks:
            if not tr.is_object:
                continue
            fxo, fyo = tr.foot
            near = any(math.hypot(p.foot[0] - fxo, p.foot[1] - fyo) < 2.0 * p.height for p in persons)
            if near or tr.speed_px(2.0) > 0.2 * tr.height:
                self.object_alone_since.pop(tr.tid, None)
                continue
            since = self.object_alone_since.setdefault(tr.tid, t)
            if t - since >= cfg["abandon_seconds"]:
                found.append(self._f("Abandoned Object", [tr], f"{tr.name} #{tr.tid} unattended for {t - since:.0f}s", None, night, t - since))
        return found

    @staticmethod
    def _rides(p, r):
        """Person box substantially overlapping a bicycle/motorcycle box = a rider."""
        ix = max(0, min(p.box[2], r.box[2]) - max(p.box[0], r.box[0]))
        iy = max(0, min(p.box[3], r.box[3]) - max(p.box[1], r.box[1]))
        return ix * iy > 0.25 * (r.box[2] - r.box[0]) * (r.box[3] - r.box[1])

    def _groups(self, persons, night, t, cfg):
        n = len(persons)
        if n < cfg["group_size"]:
            self.groups.clear()
            return []
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(n):
            for j in range(i + 1, n):
                a, b = persons[i], persons[j]
                r = cfg["group_radius_bh"] * (a.height + b.height) / 2
                if math.hypot(a.foot[0] - b.foot[0], a.foot[1] - b.foot[1]) <= r:
                    parent[find(i)] = find(j)
        clusters = {}
        for i in range(n):
            clusters.setdefault(find(i), []).append(persons[i])
        out, live = [], {}
        for members in clusters.values():
            if len(members) < cfg["group_size"]:
                continue
            ids = frozenset(m.tid for m in members)
            # a group keeps its start time while most of its members persist
            start = next((s for g, s in self.groups.items() if len(g & ids) >= max(2, len(ids) // 2)), t)
            live[ids] = start
            if t - start >= cfg["group_seconds"]:
                out.append(self._f("Group Gathering", members, f"{len(members)} people clustered for {t - start:.0f}s",
                                   None, night, t - start))
        self.groups = live
        return out

    @staticmethod
    def _f(kind, members, desc, zone, night, duration):
        risk = risk_score(kind, zone["type"] if zone else None, night, duration)
        return {"kind": kind, "tracks": members, "tids": [m.tid for m in members], "desc": desc, "risk": risk,
                "severity": severity_for(risk), "zone": zone["name"] if zone else None, "duration": round(duration, 1)}
