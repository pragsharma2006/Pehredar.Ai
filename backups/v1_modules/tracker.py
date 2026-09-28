"""
tracker.py
A lightweight centroid-based tracker.

Why not DeepSORT / ByteTrack here?
For an SIH prototype we want zero extra heavyweight model dependencies
(re-ID networks etc). A centroid tracker is enough to give every detected
person a stable ID across frames, which is exactly what we need to measure
dwell time, speed and direction for the suspicious-movement heuristics.
It's a well-known, simple algorithm (nearest-centroid matching with a
"disappeared" grace period) good enough for single/low-density camera feeds
typical of a border check post.
"""
import time
from collections import OrderedDict, deque


class Track:
    """State kept for a single tracked person."""

    def __init__(self, track_id, centroid, bbox, now):
        self.id = track_id
        self.centroid = centroid
        self.bbox = bbox
        self.disappeared = 0
        self.first_seen = now
        self.last_seen = now
        # (x, y, t) history, capped so memory doesn't grow unbounded
        self.history = deque(maxlen=90)
        self.history.append((centroid[0], centroid[1], now))
        # bookkeeping so each suspicious-event type only fires once per
        # cooldown window instead of spamming the log every frame
        self.last_event_time = {}

    def update(self, centroid, bbox, now):
        self.centroid = centroid
        self.bbox = bbox
        self.last_seen = now
        self.disappeared = 0
        self.history.append((centroid[0], centroid[1], now))

    def speed_px_per_s(self, window_s=1.0):
        """Average speed over the last `window_s` seconds of history."""
        if len(self.history) < 2:
            return 0.0
        now = self.history[-1][2]
        pts = [p for p in self.history if now - p[2] <= window_s]
        if len(pts) < 2:
            pts = list(self.history)[-2:]
        (x0, y0, t0), (x1, y1, t1) = pts[0], pts[-1]
        dt = max(t1 - t0, 1e-3)
        dist = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        return dist / dt

    def dwell_radius_px(self, window_s=8.0):
        """
        How far the person has roamed in the last `window_s` seconds.
        A small radius over a long window = loitering in one spot.
        """
        now = self.history[-1][2]
        pts = [(x, y) for x, y, t in self.history if now - t <= window_s]
        if len(pts) < 2:
            return None, None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        duration = now - min(t for x, y, t in self.history if now - t <= window_s)
        return span, duration


class CentroidTracker:
    def __init__(self, max_disappeared=20, max_distance=90):
        self.next_id = 1
        self.tracks = OrderedDict()  # id -> Track
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance

    @staticmethod
    def _centroid(bbox):
        x1, y1, x2, y2 = bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    def update(self, bboxes):
        """
        bboxes: list of (x1, y1, x2, y2) person detections for this frame.
        Returns the current dict of {track_id: Track}.
        """
        now = time.time()

        if len(bboxes) == 0:
            for t in list(self.tracks.values()):
                t.disappeared += 1
                if t.disappeared > self.max_disappeared:
                    del self.tracks[t.id]
            return self.tracks

        input_centroids = [self._centroid(b) for b in bboxes]

        if len(self.tracks) == 0:
            for c, b in zip(input_centroids, bboxes):
                self.tracks[self.next_id] = Track(self.next_id, c, b, now)
                self.next_id += 1
            return self.tracks

        track_ids = list(self.tracks.keys())
        track_centroids = [self.tracks[tid].centroid for tid in track_ids]

        # simple greedy nearest-neighbour matching
        used_rows, used_cols = set(), set()
        pairs = []
        for i, tc in enumerate(track_centroids):
            for j, ic in enumerate(input_centroids):
                d = ((tc[0] - ic[0]) ** 2 + (tc[1] - ic[1]) ** 2) ** 0.5
                pairs.append((d, i, j))
        pairs.sort(key=lambda p: p[0])

        for d, i, j in pairs:
            if i in used_rows or j in used_cols:
                continue
            if d > self.max_distance:
                continue
            tid = track_ids[i]
            self.tracks[tid].update(input_centroids[j], bboxes[j], now)
            used_rows.add(i)
            used_cols.add(j)

        # unmatched existing tracks -> mark disappeared
        for i, tid in enumerate(track_ids):
            if i not in used_rows:
                self.tracks[tid].disappeared += 1
                if self.tracks[tid].disappeared > self.max_disappeared:
                    del self.tracks[tid]

        # unmatched detections -> new tracks
        for j in range(len(input_centroids)):
            if j not in used_cols:
                self.tracks[self.next_id] = Track(
                    self.next_id, input_centroids[j], bboxes[j], now
                )
                self.next_id += 1

        return self.tracks
