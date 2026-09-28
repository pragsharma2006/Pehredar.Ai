"""Tamper-evident event store.

Each event's sha256_hash = SHA-256(snapshot bytes + canonical event JSON + prev_hash),
so editing any stored field, swapping/altering a snapshot file, or deleting/reordering
rows breaks the chain from that point on. Mutable operator-workflow columns (status,
ack time) are deliberately outside the hash; operator actions go into their own
hash-chained `actions` table so they are tamper-evident too.
"""
import csv
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime

import cv2
import numpy as np

from .config import IST, iso_ist

GENESIS = "0" * 64
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "info": 3}
HASHED_FIELDS = ["event_id", "ts_iso", "event_name", "alert_type", "module", "severity", "camera_id",
                 "location", "gps", "model_used", "confidence", "track_id", "description", "extra",
                 "snapshot", "snapshot_sha256", "notification_status", "synthetic"]
ACTION_FIELDS = ["event_id", "action", "operator", "note", "ts_iso"]
ACTIONS = {"acknowledge": "acknowledged", "escalate": "escalated", "false_alarm": "false_alarm", "resolve": "resolved"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT UNIQUE NOT NULL, ts_epoch REAL NOT NULL, ts_iso TEXT NOT NULL,
  event_name TEXT, alert_type TEXT, module TEXT, severity TEXT,
  camera_id TEXT, location TEXT, gps TEXT, model_used TEXT, confidence REAL, track_id INTEGER,
  description TEXT, extra TEXT, snapshot TEXT, snapshot_sha256 TEXT, notification_status TEXT,
  synthetic INTEGER DEFAULT 0, night INTEGER DEFAULT 0,
  prev_hash TEXT, sha256_hash TEXT,
  status TEXT DEFAULT 'new', ack_ts REAL, response_s REAL, operator TEXT);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts_epoch);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT, action TEXT, operator TEXT, note TEXT,
  ts_epoch REAL, ts_iso TEXT, prev_hash TEXT, sha256_hash TEXT);
CREATE TABLE IF NOT EXISTS vehicles (
  plate TEXT PRIMARY KEY, display TEXT, state TEXT, first_seen REAL, last_seen REAL, times_seen INTEGER,
  vehicle_type TEXT, body_type TEXT, colour TEXT, last_camera TEXT, watchlist INTEGER DEFAULT 0,
  watch_reason TEXT, last_event_id TEXT, crop TEXT);
CREATE TABLE IF NOT EXISTS crossings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, plate TEXT, ts_epoch REAL, camera_id TEXT, direction TEXT, event_id TEXT);
CREATE TABLE IF NOT EXISTS vehicle_obs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts_epoch REAL, camera_id TEXT, track_key TEXT, cls TEXT,
  size_class TEXT, colour TEXT, direction TEXT, speed_kmh REAL, crop TEXT, plate TEXT, body_type TEXT);
CREATE INDEX IF NOT EXISTS ix_obs_ts ON vehicle_obs(ts_epoch);
CREATE TABLE IF NOT EXISTS tamper_backup (
  event_id TEXT PRIMARY KEY, kind TEXT, row_json TEXT, snapshot_bytes BLOB);
"""


def _canonical(record, fields):
    return json.dumps({k: record.get(k) for k in fields}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def chain_hash(snapshot_bytes, record, prev_hash, fields=HASHED_FIELDS):
    h = hashlib.sha256()
    h.update(snapshot_bytes or b"")
    h.update(_canonical(record, fields))
    h.update(prev_hash.encode("ascii"))
    return h.hexdigest()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _latin1(s):
    s = str(s).replace("—", "-").replace("–", "-").replace("·", "|").replace("✓", "OK").replace("→", "->")
    return s.encode("latin-1", "replace").decode("latin-1")


class EventStore:
    def __init__(self, db_path, snap_dir, bus=None, settings=None, readonly=False):
        self.db_path = db_path
        self.snap_dir = snap_dir
        self.bus = bus
        self.settings = settings
        self.readonly = readonly
        self._lock = threading.RLock()
        self._cool = {}
        os.makedirs(snap_dir, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
        self._last_hash = self._tail_hash("events")
        self._last_action_hash = self._tail_hash("actions")

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _tail_hash(self, table):
        with self._conn() as c:
            key = "seq" if table == "events" else "id"
            r = c.execute(f"SELECT sha256_hash FROM {table} ORDER BY {key} DESC LIMIT 1").fetchone()
        return r[0] if r and r[0] else GENESIS

    # ------------------------------------------------------------------ cooldown
    def cooldown_ok(self, key, seconds):
        now = time.time()
        with self._lock:
            if now - self._cool.get(key, 0) < seconds:
                return False
            self._cool[key] = now
        return True

    # ------------------------------------------------------------------ logging
    def _next_event_id(self, c, ts):
        day = datetime.fromtimestamp(ts, IST).strftime("%Y%m%d")
        r = c.execute("SELECT event_id FROM events WHERE event_id LIKE ? ORDER BY seq DESC LIMIT 1",
                      (f"EVT-{day}-%",)).fetchone()
        n = int(r[0].rsplit("-", 1)[1]) + 1 if r else 1
        return f"EVT-{day}-{n:06d}"

    @staticmethod
    def _footer(img, text):
        out = img.copy()
        h, w = out.shape[:2]
        bar = max(18, h // 26)
        cv2.rectangle(out, (0, h - bar), (w, h), (12, 18, 32), -1)
        cv2.putText(out, text, (6, h - bar // 3), cv2.FONT_HERSHEY_SIMPLEX, max(0.35, bar / 48), (235, 235, 235), 1, cv2.LINE_AA)
        return out

    def log(self, *, event_name, module, severity, camera, frame, description, alert_type=None,
            model_used="", confidence=None, track_id=None, extra=None, ts=None, night=False,
            synthetic=False, crops=None):
        """camera: dict with id/name/location/gps. frame: BGR image with overlays already drawn."""
        ts = ts or time.time()
        extra = dict(extra or {})
        webhook = bool(self.settings and self.settings.get("integrations", "webhook_url"))
        channels = ["log", "toast", "badge"] + (["sound"] if severity in ("critical", "high") else []) \
            + (["banner"] if severity == "critical" else []) + (["webhook"] if webhook else [])
        with self._lock:
            with self._conn() as c:
                event_id = self._next_event_id(c, ts)
                ts_iso = iso_ist(ts)
                snap_name = None
                snap_bytes = b""
                if frame is not None:
                    stamp = f"{event_id} | {camera['id']} | {ts_iso[:23].replace('T', ' ')} IST | {event_name}"
                    ok, buf = cv2.imencode(".jpg", self._footer(frame, stamp), [cv2.IMWRITE_JPEG_QUALITY, 88])
                    if ok:
                        snap_bytes = buf.tobytes()
                        snap_name = f"{event_id}.jpg"
                        with open(os.path.join(self.snap_dir, snap_name), "wb") as f:
                            f.write(snap_bytes)
                for key, img in (crops or {}).items():
                    if img is not None and img.size:
                        name = f"{event_id}_{key}.jpg"
                        cv2.imwrite(os.path.join(self.snap_dir, name), img)
                        extra[f"{key}_img"] = name
                gps = camera.get("gps") or []
                rec = {
                    "event_id": event_id, "ts_iso": ts_iso, "event_name": event_name,
                    "alert_type": alert_type or module.title(), "module": module, "severity": severity,
                    "camera_id": camera["id"], "location": camera.get("location", camera.get("name", "")),
                    "gps": f"{gps[0]:.5f},{gps[1]:.5f}" if len(gps) == 2 else "",
                    "model_used": model_used, "confidence": None if confidence is None else round(float(confidence), 4),
                    "track_id": None if track_id is None else int(track_id), "description": description,
                    "extra": json.dumps(extra, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str),
                    "snapshot": snap_name, "snapshot_sha256": sha256_bytes(snap_bytes) if snap_bytes else None,
                    "notification_status": "dispatched:" + ",".join(channels), "synthetic": 1 if synthetic else 0,
                }
                prev = self._last_hash
                digest = chain_hash(snap_bytes, rec, prev)
                c.execute(
                    "INSERT INTO events (event_id, ts_epoch, ts_iso, event_name, alert_type, module, severity, camera_id,"
                    " location, gps, model_used, confidence, track_id, description, extra, snapshot, snapshot_sha256,"
                    " notification_status, synthetic, night, prev_hash, sha256_hash) VALUES"
                    " (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event_id, ts, ts_iso, rec["event_name"], rec["alert_type"], module, severity, rec["camera_id"],
                     rec["location"], rec["gps"], model_used, rec["confidence"], rec["track_id"], description,
                     rec["extra"], snap_name, rec["snapshot_sha256"], rec["notification_status"], rec["synthetic"],
                     1 if night else 0, prev, digest))
                self._last_hash = digest
                row = dict(c.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone())
        row = self._decorate(row)
        if self.bus:
            self.bus.publish({"type": "event", "event": row})
        return row

    @staticmethod
    def _decorate(row):
        try:
            row["extra"] = json.loads(row.get("extra") or "{}")
        except (TypeError, ValueError):
            row["extra"] = {}
        return row

    # ------------------------------------------------------------------ queries
    def query(self, since_seq=0, limit=200, module=None, camera=None, severity=None, status=None,
              date_from=None, date_to=None, q=None, order="desc"):
        sql = ["SELECT * FROM events WHERE seq > ?"]
        args = [since_seq]
        for col, val in (("module", module), ("camera_id", camera), ("severity", severity), ("status", status)):
            if val and val != "all":
                vals = val.split(",")
                sql.append(f"AND {col} IN ({','.join('?' * len(vals))})")
                args += vals
        if date_from:
            sql.append("AND ts_epoch >= ?"); args.append(float(date_from))
        if date_to:
            sql.append("AND ts_epoch <= ?"); args.append(float(date_to))
        if q:
            sql.append("AND (event_name LIKE ? OR description LIKE ? OR event_id LIKE ? OR extra LIKE ?)")
            args += [f"%{q}%"] * 4
        sql.append(f"ORDER BY seq {'ASC' if order == 'asc' else 'DESC'} LIMIT ?")
        args.append(int(limit))
        with self._conn() as c:
            rows = c.execute(" ".join(sql), args).fetchall()
        return [self._decorate(dict(r)) for r in rows]

    def get(self, event_id):
        with self._conn() as c:
            r = c.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if not r:
                return None
            acts = c.execute("SELECT * FROM actions WHERE event_id=? ORDER BY id", (event_id,)).fetchall()
        row = self._decorate(dict(r))
        row["actions"] = [dict(a) for a in acts]
        return row

    def active_alerts(self, limit=100):
        with self._conn() as c:
            rows = c.execute("SELECT * FROM events WHERE status IN ('new','escalated') AND severity IN ('critical','high')"
                             " ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [self._decorate(dict(r)) for r in rows]

    # ------------------------------------------------------------------ operator workflow
    def action(self, event_id, action, operator, note="", ts=None):
        if action not in ACTIONS:
            raise ValueError("unknown action")
        now = ts or time.time()
        with self._lock:
            with self._conn() as c:
                ev = c.execute("SELECT ts_epoch, ack_ts FROM events WHERE event_id=?", (event_id,)).fetchone()
                if not ev:
                    raise KeyError(event_id)
                rec = {"event_id": event_id, "action": action, "operator": operator, "note": note or "", "ts_iso": iso_ist(now)}
                prev = self._last_action_hash
                digest = chain_hash(b"", rec, prev, ACTION_FIELDS)
                c.execute("INSERT INTO actions (event_id, action, operator, note, ts_epoch, ts_iso, prev_hash, sha256_hash)"
                          " VALUES (?,?,?,?,?,?,?,?)", (event_id, action, operator, rec["note"], now, rec["ts_iso"], prev, digest))
                self._last_action_hash = digest
                if ev["ack_ts"] is None:
                    c.execute("UPDATE events SET ack_ts=?, response_s=? WHERE event_id=?", (now, now - ev["ts_epoch"], event_id))
                c.execute("UPDATE events SET status=?, operator=? WHERE event_id=?", (ACTIONS[action], operator, event_id))
        row = self.get(event_id)
        if self.bus:
            self.bus.publish({"type": "event_update", "event": row})
        return row

    # ------------------------------------------------------------------ integrity
    def verify(self):
        with self._conn() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM events ORDER BY seq ASC").fetchall()]
            acts = [dict(r) for r in c.execute("SELECT * FROM actions ORDER BY id ASC").fetchall()]
        prev = GENESIS
        for i, r in enumerate(rows):
            snap = b""
            if r["snapshot"]:
                p = os.path.join(self.snap_dir, r["snapshot"])
                if os.path.exists(p):
                    with open(p, "rb") as f:
                        snap = f.read()
            if (r["prev_hash"] or GENESIS) != prev:
                return self._fail(r, i, len(rows), "chain link broken (row deleted or reordered)")
            if r["snapshot"] and sha256_bytes(snap) != r["snapshot_sha256"]:
                return self._fail(r, i, len(rows), "snapshot file altered or swapped")
            if chain_hash(snap, r, prev) != r["sha256_hash"]:
                return self._fail(r, i, len(rows), "event record modified")
            prev = r["sha256_hash"]
        aprev = GENESIS
        for a in acts:
            if a["prev_hash"] != aprev or chain_hash(b"", a, aprev, ACTION_FIELDS) != a["sha256_hash"]:
                return {"ok": False, "checked": len(rows), "total": len(rows), "failed_at": f"action #{a['id']}",
                        "reason": "operator action log modified"}
            aprev = a["sha256_hash"]
        return {"ok": True, "checked": len(rows), "total": len(rows), "actions_checked": len(acts), "head": prev}

    @staticmethod
    def _fail(r, i, total, reason):
        return {"ok": False, "checked": i, "total": total, "failed_at": r["event_id"], "reason": reason}

    def tamper(self, kind):
        """Demo only: deliberately corrupt one record or swap one snapshot; restore() undoes it."""
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM events WHERE snapshot IS NOT NULL ORDER BY seq DESC LIMIT 40").fetchall()
            if len(rows) < 2:
                raise ValueError("need at least two events with snapshots")
            target = dict(rows[len(rows) // 2])
            if c.execute("SELECT 1 FROM tamper_backup WHERE event_id=?", (target["event_id"],)).fetchone():
                raise ValueError("that record is already tampered — restore first")
            path = os.path.join(self.snap_dir, target["snapshot"])
            with open(path, "rb") as f:
                original = f.read()
            c.execute("INSERT INTO tamper_backup VALUES (?,?,?,?)", (target["event_id"], kind, json.dumps(target), original))
            if kind == "record":
                c.execute("UPDATE events SET description=? WHERE event_id=?",
                          (target["description"] + " [altered]", target["event_id"]))
            else:
                donor = dict(rows[0] if rows[0]["event_id"] != target["event_id"] else rows[1])
                with open(os.path.join(self.snap_dir, donor["snapshot"]), "rb") as f:
                    swap = f.read()
                with open(path, "wb") as f:
                    f.write(swap)
        return {"tampered": target["event_id"], "kind": kind}

    def restore(self):
        restored = []
        with self._lock, self._conn() as c:
            for b in c.execute("SELECT * FROM tamper_backup").fetchall():
                row = json.loads(b["row_json"])
                c.execute("UPDATE events SET description=? WHERE event_id=?", (row["description"], row["event_id"]))
                with open(os.path.join(self.snap_dir, row["snapshot"]), "wb") as f:
                    f.write(b["snapshot_bytes"])
                restored.append(row["event_id"])
            c.execute("DELETE FROM tamper_backup")
        return {"restored": restored}

    def lookup_hash(self, digest):
        with self._conn() as c:
            rows = c.execute("SELECT event_id, event_name, camera_id, ts_iso, snapshot FROM events"
                             " WHERE snapshot_sha256=? OR sha256_hash=?", (digest, digest)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ exports
    CSV_COLS = ["event_id", "ts_iso", "event_name", "alert_type", "module", "severity", "camera_id", "location", "gps",
                "model_used", "confidence", "track_id", "description", "status", "response_s", "snapshot",
                "snapshot_sha256", "prev_hash", "sha256_hash"]

    def export_csv(self, rows):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(self.CSV_COLS + ["extra"])
        for r in rows:
            w.writerow([r.get(k) for k in self.CSV_COLS] + [json.dumps(r.get("extra"), ensure_ascii=False)])
        return buf.getvalue()

    def _privacy_copy(self, row):
        path = os.path.join(self.snap_dir, row["snapshot"])
        img = cv2.imread(path)
        if img is None:
            return None
        for fbox in (row.get("extra") or {}).get("faces", []):
            if fbox.get("category") == "Watchlist":
                continue
            x1, y1, x2, y2 = [int(v) for v in fbox["box"]]
            x1, y1 = max(0, x1), max(0, y1)
            roi = img[y1:y2, x1:x2]
            if roi.size:
                img[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (0, 0), max(4, (x2 - x1) / 6))
        return img

    def export_pdf(self, rows, privacy=True, operator="", sector=""):
        from fpdf import FPDF
        pdf = FPDF(unit="mm", format="A4")
        pdf.set_auto_page_break(True, 12)
        pdf.add_page()
        pdf.set_fill_color(255, 153, 51); pdf.rect(0, 0, 70, 3, "F")
        pdf.set_fill_color(255, 255, 255); pdf.rect(70, 0, 70, 3, "F")
        pdf.set_fill_color(19, 136, 8); pdf.rect(140, 0, 70, 3, "F")
        pdf.set_font("helvetica", "B", 18)
        pdf.cell(0, 12, "PEHREDAR.AI - Evidence Report", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        integ = self.verify()
        for line in (f"Sector: {sector}", f"Generated: {iso_ist()} by {operator}", f"Events in report: {len(rows)}",
                     f"Chain integrity at export: {'INTACT' if integ['ok'] else 'TAMPERING DETECTED at ' + str(integ.get('failed_at'))}"
                     f" ({integ['checked']}/{integ['total']} events verified)",
                     f"Privacy mode: {'non-watchlist faces blurred in this export (stored evidence unaltered)' if privacy else 'off'}"):
            pdf.cell(0, 6, _latin1(line), new_x="LMARGIN", new_y="NEXT")
        for r in rows:
            pdf.add_page()
            pdf.set_font("helvetica", "B", 13)
            pdf.cell(0, 8, _latin1(f"{r['event_id']}  -  {r['event_name']}"), new_x="LMARGIN", new_y="NEXT")
            if r.get("snapshot"):
                img = self._privacy_copy(r) if privacy else cv2.imread(os.path.join(self.snap_dir, r["snapshot"]))
                if img is not None:
                    tmp = os.path.join(tempfile.gettempdir(), f"pehredar_{r['event_id']}.jpg")
                    cv2.imwrite(tmp, img)
                    pdf.image(tmp, w=180)
                    os.remove(tmp)
            pdf.ln(2)
            pdf.set_font("helvetica", "", 9)
            fields = [("Timestamp (IST)", r["ts_iso"]), ("Severity", r["severity"]), ("Alert type", r["alert_type"]),
                      ("Module", r["module"]), ("Camera", f"{r['camera_id']} - {r['location']} ({r['gps']})"),
                      ("Model", r["model_used"]), ("Confidence", r["confidence"]), ("Track ID", r["track_id"]),
                      ("Description", r["description"]), ("Details", json.dumps(r.get("extra"), ensure_ascii=False)[:600]),
                      ("Status", f"{r['status']} (operator: {r.get('operator') or '-'})"),
                      ("Notification", r["notification_status"]), ("Snapshot SHA-256", r["snapshot_sha256"]),
                      ("Previous hash", r["prev_hash"]), ("Event hash", r["sha256_hash"])]
            for k, v in fields:
                pdf.set_font("helvetica", "B", 9); pdf.cell(38, 5, _latin1(k))
                pdf.set_font("courier" if "hash" in k.lower() or "SHA" in k else "helvetica", "", 8 if "hash" in k.lower() or "SHA" in k else 9)
                pdf.multi_cell(0, 5, _latin1(v), new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())

    # ------------------------------------------------------------------ vehicles
    def upsert_vehicle(self, plate, display, state, vtype, body, colour, camera_id, event_id, watch, reason, crop, direction, ts):
        with self._lock, self._conn() as c:
            r = c.execute("SELECT times_seen FROM vehicles WHERE plate=?", (plate,)).fetchone()
            if r:
                c.execute("UPDATE vehicles SET last_seen=?, times_seen=times_seen+1, vehicle_type=?, body_type=COALESCE(?, body_type),"
                          " colour=?, last_camera=?, watchlist=?, watch_reason=?, last_event_id=?, crop=COALESCE(?, crop) WHERE plate=?",
                          (ts, vtype, body, colour, camera_id, int(watch), reason, event_id, crop, plate))
            else:
                c.execute("INSERT INTO vehicles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (plate, display, state, ts, ts, 1, vtype, body, colour, camera_id, int(watch), reason, event_id, crop))
            c.execute("INSERT INTO crossings (plate, ts_epoch, camera_id, direction, event_id) VALUES (?,?,?,?,?)",
                      (plate, ts, camera_id, direction, event_id))

    def add_observation(self, **kw):
        cols = ["ts_epoch", "camera_id", "track_key", "cls", "size_class", "colour", "direction", "speed_kmh", "crop", "plate", "body_type"]
        with self._conn() as c:
            c.execute(f"INSERT INTO vehicle_obs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [kw.get(k) for k in cols])

    def vehicles(self, q=None, watch_only=False, limit=500):
        sql, args = "SELECT * FROM vehicles WHERE 1=1", []
        if q:
            sql += " AND (plate LIKE ? OR state LIKE ? OR vehicle_type LIKE ? OR colour LIKE ?)"
            args += [f"%{q.replace(' ', '')}%", f"%{q}%", f"%{q}%", f"%{q}%"]
        if watch_only:
            sql += " AND watchlist=1"
        sql += " ORDER BY last_seen DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def vehicle_history(self, plate):
        with self._conn() as c:
            v = c.execute("SELECT * FROM vehicles WHERE plate=?", (plate,)).fetchone()
            h = c.execute("SELECT * FROM crossings WHERE plate=? ORDER BY ts_epoch DESC LIMIT 200", (plate,)).fetchall()
        return {"vehicle": dict(v) if v else None, "crossings": [dict(x) for x in h]}

    def observations(self, since=0, camera=None, limit=200):
        sql, args = "SELECT * FROM vehicle_obs WHERE ts_epoch >= ?", [since]
        if camera:
            sql += " AND camera_id=?"; args.append(camera)
        sql += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    # ------------------------------------------------------------------ stats
    def counts_since(self, ts):
        with self._conn() as c:
            by_name = dict(c.execute("SELECT event_name, COUNT(*) FROM events WHERE ts_epoch>=? GROUP BY event_name", (ts,)).fetchall())
            by_module = dict(c.execute("SELECT module, COUNT(*) FROM events WHERE ts_epoch>=? GROUP BY module", (ts,)).fetchall())
            active = c.execute("SELECT COUNT(*) FROM events WHERE status IN ('new','escalated') AND severity IN ('critical','high')").fetchone()[0]
            resp = c.execute("SELECT AVG(response_s) FROM events WHERE response_s IS NOT NULL AND ts_epoch>=?", (ts,)).fetchone()[0]
            vehicles = c.execute("SELECT COUNT(*) FROM vehicle_obs WHERE ts_epoch>=?", (ts,)).fetchone()[0]
            plates = c.execute("SELECT COUNT(*) FROM crossings WHERE ts_epoch>=?", (ts,)).fetchone()[0]
            total = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return {"by_name": by_name, "by_module": by_module, "active_alerts": active, "avg_response_s": resp,
                "vehicles": vehicles, "plates": plates, "total": total}

    def analytics(self, since):
        with self._conn() as c:
            rows = [dict(r) for r in c.execute("SELECT ts_epoch, module, camera_id, severity, status, response_s, night, extra, event_name"
                                               " FROM events WHERE ts_epoch>=?", (since,)).fetchall()]
            classes = dict(c.execute("SELECT cls, COUNT(*) FROM vehicle_obs WHERE ts_epoch>=? GROUP BY cls", (since,)).fetchall())
            plates = [dict(r) for r in c.execute("SELECT plate, display, state, times_seen, watchlist FROM vehicles"
                                                 " ORDER BY times_seen DESC LIMIT 10").fetchall()]
        return rows, classes, plates
