"""Per-camera track history built on ByteTrack IDs: trails, speed, dwell, direction."""
import math
from collections import Counter, deque

from .detector import OBJECTS, PERSON, VEHICLES


class TrackState:
    def __init__(self, det, t):
        self.tid = det["tid"]
        self.cls = det["cls"]
        self.name = det["name"]
        self.first = t
        self.last = t
        self.conf = det["conf"]
        self.box = det["box"]
        self.hist = deque(maxlen=90)  # (t, foot_x, foot_y, h, w)
        self.fired = {}
        self.zone_inside = {}
        self.zone_since = {}
        self.line_side = {}
        self.crossings = {}
        self.meta = {}
        self.best = None  # (score, frame, box) — best frame for ANPR / face best-shot
        self.aspect_since = None
        self.votes = Counter()
        self.update(det, t)

    @property
    def major_name(self):
        """Class by majority vote over the track's life (YOLO can flicker car/truck)."""
        return self.votes.most_common(1)[0][0] if self.votes else self.name

    @property
    def is_person(self):
        return self.cls == PERSON

    @property
    def is_vehicle(self):
        return self.cls in VEHICLES

    @property
    def is_object(self):
        return self.cls in OBJECTS

    def update(self, det, t):
        self.last = t
        self.conf = det["conf"]
        self.box = det["box"]
        self.cls, self.name = det["cls"], det["name"]
        self.votes[self.name] += 1
        x1, y1, x2, y2 = self.box
        self.hist.append((t, (x1 + x2) / 2, y2, max(1.0, y2 - y1), max(1.0, x2 - x1)))

    @property
    def foot(self):
        return self.hist[-1][1], self.hist[-1][2]

    @property
    def height(self):
        return self.hist[-1][3]

    @property
    def dwell(self):
        return self.last - self.first

    def velocity(self, window=1.0):
        """px/s over the last `window` seconds of foot-point history."""
        if len(self.hist) < 2:
            return 0.0, 0.0
        tn = self.hist[-1][0]
        pts = [p for p in self.hist if tn - p[0] <= window] or list(self.hist)[-2:]
        if len(pts) < 2:
            pts = list(self.hist)[-2:]
        dt = max(pts[-1][0] - pts[0][0], 1e-3)
        return (pts[-1][1] - pts[0][1]) / dt, (pts[-1][2] - pts[0][2]) / dt

    def speed_px(self, window=1.0):
        vx, vy = self.velocity(window)
        return math.hypot(vx, vy)

    def speed_bh(self, window=1.0):
        """Speed in body-heights per second — scale-invariant across camera distances."""
        hs = [p[3] for p in list(self.hist)[-10:]]
        return self.speed_px(window) / max(sorted(hs)[len(hs) // 2], 1.0)

    def span_bh(self, window):
        tn = self.hist[-1][0]
        pts = [p for p in self.hist if tn - p[0] <= window]
        if len(pts) < 2 or tn - pts[0][0] < window * 0.9:
            return None
        xs, ys = [p[1] for p in pts], [p[2] for p in pts]
        return max(max(xs) - min(xs), max(ys) - min(ys)) / max(self.height, 1.0)

    def trail(self, n=30):
        return [(int(p[1]), int(p[2])) for p in list(self.hist)[-n:]]

    def cooldown(self, key, t, seconds):
        if t - self.fired.get(key, -1e9) < seconds:
            return False
        self.fired[key] = t
        return True


class TrackBook:
    def __init__(self, end_after=2.0):
        self.tracks = {}
        self.end_after = end_after
        self.people_seen = 0
        self.vehicles_seen = 0

    def update(self, dets, t):
        seen = set()
        for d in dets:
            tr = self.tracks.get(d["tid"])
            if tr is None:
                tr = self.tracks[d["tid"]] = TrackState(d, t)
                if tr.is_person:
                    self.people_seen += 1
                elif tr.is_vehicle:
                    self.vehicles_seen += 1
            else:
                tr.update(d, t)
            seen.add(d["tid"])
        ended = [tr for tid, tr in self.tracks.items() if tid not in seen and t - tr.last > self.end_after]
        for tr in ended:
            del self.tracks[tr.tid]
        active = [self.tracks[tid] for tid in seen if tid in self.tracks]
        return active, ended

    def flush(self):
        ended = list(self.tracks.values())
        self.tracks.clear()
        return ended
