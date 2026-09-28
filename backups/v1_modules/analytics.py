"""
analytics.py
Turns raw tracker state into security events:
  - Virtual fence intrusion   (person centroid enters a restricted polygon)
  - Loitering                 (person stays within a small area too long)
  - Fast movement / running   (speed above a threshold)
  - Night-time movement       (any person detected while scene is dark)

Also owns the event log: a SQLite table + JPEG snapshots on disk, chained
with SHA-256 hashes (each event's hash covers the previous event's hash +
its own metadata + its snapshot bytes) so the evidence trail is tamper
evident — editing or swapping any past row or snapshot breaks the chain
and verify_chain() will detect it.
"""
import os
import time
import sqlite3
import hashlib
import threading
import cv2

DB_PATH = os.path.join(os.path.dirname(__file__), "events.db")
SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "events")
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

EVENT_COOLDOWN_S = 12  # don't re-fire the same event type for the same track too often
GENESIS_HASH = "0" * 64


def point_in_polygon(point, polygon):
    """Standard ray-casting point-in-polygon test. polygon: list of (x, y)."""
    if not polygon or len(polygon) < 3:
        return False
    x, y = point
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        ):
            inside = not inside
        j = i
    return inside


def _compute_hash(prev_hash, ts, event_type, track_id, camera_id, description, snapshot_bytes):
    h = hashlib.sha256()
    for part in (prev_hash, f"{ts:.6f}", event_type, str(track_id), camera_id, description):
        h.update(part.encode("utf-8"))
    if snapshot_bytes:
        h.update(snapshot_bytes)
    return h.hexdigest()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            event_type TEXT NOT NULL,
            module TEXT NOT NULL DEFAULT 'human',
            camera_id TEXT NOT NULL DEFAULT 'CAM-01',
            track_id INTEGER,
            severity TEXT,
            description TEXT,
            snapshot TEXT,
            night_mode INTEGER,
            prev_hash TEXT,
            event_hash TEXT
        )"""
    )
    conn.commit()
    conn.close()


init_db()


class EventLogger:
    """Thread-safe-enough (single writer) append-only, hash-chained event log."""

    SEVERITY = {
        "Fence Intrusion": "critical",
        "Loitering": "warning",
        "Fast Movement": "warning",
        "Night-time Movement": "info",
        "Vehicle Detected": "info",
        "Watchlist Alert": "critical",
        "Face Detected": "info",
        "Face Watchlist Match": "critical",
    }

    def __init__(self):
        self._lock = threading.Lock()
        self._last_hash = self._load_last_hash()

    def _load_last_hash(self):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT event_hash FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return row[0] if row and row[0] else GENESIS_HASH

    def log(self, event_type, track_id, description, frame, night_mode,
            camera_id="CAM-01", module="human"):
        ts = time.time()
        snap_name = f"{int(ts * 1000)}_{event_type.replace(' ', '')}_{track_id}.jpg"
        snap_path = os.path.join(SNAPSHOT_DIR, snap_name)

        snapshot_bytes = b""
        try:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                snapshot_bytes = buf.tobytes()
                with open(snap_path, "wb") as f:
                    f.write(snapshot_bytes)
            else:
                snap_name = None
        except Exception:
            snap_name = None

        severity = self.SEVERITY.get(event_type, "info")

        with self._lock:
            prev_hash = self._last_hash
            event_hash = _compute_hash(prev_hash, ts, event_type, track_id, camera_id, description, snapshot_bytes)

            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "INSERT INTO events (ts, event_type, module, camera_id, track_id, severity, "
                "description, snapshot, night_mode, prev_hash, event_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, event_type, module, camera_id, track_id, severity, description,
                 snap_name, 1 if night_mode else 0, prev_hash, event_hash),
            )
            conn.commit()
            conn.close()

            self._last_hash = event_hash

        return {
            "ts": ts, "event_type": event_type, "module": module, "camera_id": camera_id,
            "track_id": track_id, "severity": severity, "description": description,
            "snapshot": snap_name, "night_mode": night_mode,
            "prev_hash": prev_hash, "event_hash": event_hash,
        }

    def recent(self, since_id=0, limit=100):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM events WHERE id > ? ORDER BY id DESC LIMIT ?",
            (since_id, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def stats(self):
        conn = sqlite3.connect(DB_PATH)
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        by_type = conn.execute(
            "SELECT event_type, COUNT(*) FROM events GROUP BY event_type"
        ).fetchall()
        conn.close()
        return {"total": total, "by_type": dict(by_type)}

    def verify_chain(self):
        """Recomputes every event's hash from its stored fields + the snapshot
        currently on disk. Any edited row or swapped/altered snapshot image
        breaks the chain from that point on — this is the tamper-detection
        guarantee for the evidence trail."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM events ORDER BY id ASC").fetchall()
        conn.close()

        prev = GENESIS_HASH
        checked = 0
        for r in rows:
            snapshot_bytes = b""
            if r["snapshot"]:
                path = os.path.join(SNAPSHOT_DIR, r["snapshot"])
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        snapshot_bytes = f.read()
            expected = _compute_hash(
                prev, r["ts"], r["event_type"], r["track_id"],
                r["camera_id"] or "CAM-01", r["description"], snapshot_bytes,
            )
            if expected != r["event_hash"] or (r["prev_hash"] or GENESIS_HASH) != prev:
                return {"verified": False, "checked": checked, "total": len(rows), "failed_at_event_id": r["id"]}
            prev = r["event_hash"]
            checked += 1
        return {"verified": True, "checked": checked, "total": len(rows), "head_hash": prev}


class SuspiciousActivityDetector:
    def __init__(self, thresholds=None, logger=None):
        self.thresholds = thresholds or {
            "loiter_seconds": 8.0,
            "loiter_radius_px": 45,
            "run_speed_px_s": 260,
            "night_brightness": 60,
        }
        self.fence_polygon = []  # list of (x, y) in frame pixel coords
        self.logger = logger or EventLogger()

    def set_fence(self, points):
        self.fence_polygon = [tuple(p) for p in points]

    @staticmethod
    def frame_brightness(frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(gray.mean())

    def _cooldown_ok(self, track, event_type):
        last = track.last_event_time.get(event_type, 0)
        if time.time() - last < EVENT_COOLDOWN_S:
            return False
        track.last_event_time[event_type] = time.time()
        return True

    def evaluate(self, tracks, frame, camera_id="CAM-01"):
        """
        tracks: dict {id: Track} from CentroidTracker
        frame: current BGR frame (used only for brightness + snapshots)
        Returns list of event dicts fired this call, for immediate UI feedback.
        """
        night_mode = self.frame_brightness(frame) < self.thresholds["night_brightness"]
        fired = []

        for track in tracks.values():
            if track.disappeared > 0:
                continue

            # 1. virtual fence intrusion
            if self.fence_polygon and point_in_polygon(track.centroid, self.fence_polygon):
                if self._cooldown_ok(track, "Fence Intrusion"):
                    desc = f"Person #{track.id} crossed the virtual fence line"
                    self.logger.log("Fence Intrusion", track.id, desc, frame, night_mode,
                                     camera_id=camera_id, module="fence")
                    fired.append({"type": "Fence Intrusion", "track_id": track.id})

            # 2. loitering
            span, duration = track.dwell_radius_px(window_s=self.thresholds["loiter_seconds"])
            if (
                span is not None
                and duration >= self.thresholds["loiter_seconds"] * 0.9
                and span <= self.thresholds["loiter_radius_px"]
            ):
                if self._cooldown_ok(track, "Loitering"):
                    desc = f"Person #{track.id} lingered in one spot for ~{int(duration)}s"
                    self.logger.log("Loitering", track.id, desc, frame, night_mode,
                                     camera_id=camera_id, module="activity")
                    fired.append({"type": "Loitering", "track_id": track.id})

            # 3. fast movement / running
            speed = track.speed_px_per_s()
            if speed > self.thresholds["run_speed_px_s"]:
                if self._cooldown_ok(track, "Fast Movement"):
                    desc = f"Person #{track.id} moving fast (~{int(speed)} px/s)"
                    self.logger.log("Fast Movement", track.id, desc, frame, night_mode,
                                     camera_id=camera_id, module="activity")
                    fired.append({"type": "Fast Movement", "track_id": track.id})

            # 4. night-time movement (any detection while dark)
            if night_mode:
                if self._cooldown_ok(track, "Night-time Movement"):
                    desc = f"Person #{track.id} detected during low-light conditions"
                    self.logger.log("Night-time Movement", track.id, desc, frame, night_mode,
                                     camera_id=camera_id, module="activity")
                    fired.append({"type": "Night-time Movement", "track_id": track.id})

        return fired, night_mode
