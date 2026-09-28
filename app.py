"""Pehredar.ai — IBVAP server.

    python app.py            ->  http://localhost:5000

Video for all tiles is multiplexed over one WebSocket (/ws): browsers allow only ~6
HTTP connections per host, so 8 MJPEG streams would stall. /video/<cam> MJPEG and the
REST + /ws/alerts endpoints remain for integration with command-and-control systems.
"""
import hashlib
import json
import os
import queue
import re
import struct
import threading
import time
from datetime import datetime

import traceback

import requests
from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory
from flask_sock import ConnectionClosed, Sock

from pehredar.config import DATA, EVENTS_DIR, GEN, IST, MODULES, UPLOADS, VIDEOS, WATCHLIST_PATH, iso_ist, load_json, save_json

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024
sock = Sock(app)
M = None  # Manager, created under __main__ (the ANPR body-type worker uses a spawned process)


def ctx():
    return M.ctx


def worker(cam_id):
    w = M.workers.get(cam_id)
    if w is None:
        abort(404, "unknown camera")
    return w


def operator():
    return ctx().settings.get("operator")


# ============================================================================ pages & files
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/events/<path:name>")
def snapshot(name):
    return send_from_directory(EVENTS_DIR, name)


@app.route("/history_snaps/<path:name>")
def history_snapshot(name):
    return send_from_directory(os.path.join(GEN, "history_snaps"), name)


@app.route("/data/<path:p>")
def data_file(p):
    if not p.startswith(("faces/", "generated/avatars/", "generated/plates/", "generated/sprites/")):
        abort(404)
    return send_from_directory(DATA, p)


# ============================================================================ status
_integ = {"t": 0, "v": None}


def integrity_cached(max_age=None):
    """Never blocks a request: the full chain is re-verified by integrity_loop()."""
    return _integ["v"] or {"ok": True, "checked": 0, "total": 0, "pending": True}


def integrity_now():
    _integ["v"], _integ["t"] = ctx().store.verify(), time.time()
    return _integ["v"]


def integrity_loop():
    while True:
        try:
            integrity_now()
        except Exception:
            traceback.print_exc()
        time.sleep(30)


def system_status(kpis, net):
    crit = ctx().store.query(limit=1, severity="critical", status="new")
    if crit and time.time() - crit[0]["ts_epoch"] < 120:
        return "critical"
    if kpis["cameras_online"] < kpis["cameras_total"] or any(n["tier"] in ("KEYFRAMES", "METADATA", "OFFLINE") for n in net.values()):
        return "degraded"
    return "all green"


@app.route("/api/status")
def status():
    k = M.kpis()
    net = ctx().network.snapshot()
    return jsonify({"kpis": k, "system": system_status(k, net), "device": ctx().device_label, "sector": ctx().settings.get("sector"),
                    "operator": operator(), "sound": ctx().settings.get("sound"), "server_time": iso_ist(),
                    "integrity": integrity_cached()})


@app.route("/api/cameras", methods=["GET", "POST"])
def cameras():
    if request.method == "POST":
        b = request.get_json(force=True)
        url = (b.get("rtsp") or "").strip()
        if not re.match(r"^(rtsp|rtsps|http|https)://", url):
            return jsonify({"ok": False, "error": "enter an rtsp:// or http(s):// stream URL"}), 400
        n = 1 + max(int(c["id"].split("-")[1]) for c in M.cams)
        cfg = {"id": f"CAM-{n:02d}", "name": b.get("name") or f"IP Camera {n}", "location": b.get("location") or "Onboarded camera",
               "gps": [float(b.get("lat") or 31.6), float(b.get("lon") or 74.55)], "link": b.get("link") or "Fibre", "kind": "live",
               "source": url, "modules": ["human", "fence", "activity", "night", "vehicle", "face"], "restricted_post": True,
               "in_vector": [0, 1], "onboarded": iso_ist(), "protocol": b.get("protocol", "RTSP")}
        w = M.add_camera(cfg)
        return jsonify({"ok": True, "camera": w.info()})
    net = ctx().network.snapshot()
    return jsonify([{**w.info(), "net": net.get(w.id)} for w in M.workers.values()])


@app.route("/api/cameras/<cam_id>")
def camera(cam_id):
    w = worker(cam_id)
    return jsonify({**w.info(), "net": ctx().network.snapshot().get(cam_id), "history": ctx().network.history(cam_id)[-120:]})


@app.route("/api/cameras/<cam_id>/tracks")
def camera_tracks(cam_id):
    return jsonify(worker(cam_id).tracks_info())


@app.route("/api/cameras/<cam_id>/source", methods=["POST"])
def camera_source(cam_id):
    w = worker(cam_id)
    if w.kind != "live":
        return jsonify({"ok": False, "error": "only live cameras accept a new source"}), 400
    src = (request.get_json(force=True).get("source") or "").strip()
    if not (src.startswith(("webcam:", "sample:", "rtsp://", "rtsps://", "http://", "https://")) or src == "auto"):
        return jsonify({"ok": False, "error": "unsupported source"}), 400
    ok = w.set_source(src)
    return jsonify({"ok": ok, "source": w.source_label, "status": w.stats["status"]})


@app.route("/api/cameras/<cam_id>/upload", methods=["POST"])
def camera_upload(cam_id):
    w = worker(cam_id)
    f = request.files.get("video")
    if not f or w.kind != "live":
        return jsonify({"ok": False, "error": "no file / not a live camera"}), 400
    name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(f.filename or "upload.mp4"))
    f.save(os.path.join(UPLOADS, name))
    ok = w.set_source(f"sample:{name}")
    return jsonify({"ok": ok, "source": w.source_label})


@app.route("/api/samples")
def samples():
    names = sorted({n for d in (UPLOADS, VIDEOS) if os.path.isdir(d) for n in os.listdir(d)
                    if n.lower().endswith((".mp4", ".avi", ".mov", ".mkv"))})
    return jsonify(names)


@app.route("/api/cameras/<cam_id>/capture", methods=["POST"])
def camera_capture(cam_id):
    return jsonify(worker(cam_id).capture_scan())


@app.route("/api/cameras/<cam_id>/display", methods=["POST"])
def camera_display(cam_id):
    w = worker(cam_id)
    b = request.get_json(force=True)
    if b.get("mode") in ("normal", "enhanced", "thermal"):
        w.display = b["mode"]
    if "heatmap" in b:
        w.show_heat = bool(b["heatmap"])
    if "variant" in b:
        try:
            M.set_variant(cam_id, b["variant"])
        except (ValueError, KeyError) as e:
            return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "display": w.display, "heatmap": w.show_heat})


@app.route("/api/cameras/<cam_id>/frame")
def camera_frame(cam_id):
    data = worker(cam_id).raw_jpeg(request.args.get("mode", "raw"))
    if data is None:
        abort(404)
    return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


@app.route("/video/<cam_id>")
def mjpeg(cam_id):
    w = worker(cam_id)

    def gen():
        last = -1
        while True:
            if w.seq == last:
                time.sleep(0.02)
                continue
            last = w.seq
            data = w.jpeg(max_w=1280, quality=80)
            if data:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ============================================================================ zones / settings / models
@app.route("/api/zones/<cam_id>", methods=["GET", "POST"])
def zones(cam_id):
    worker(cam_id)
    if request.method == "POST":
        return jsonify({"ok": True, "zones": ctx().zones.set(cam_id, request.get_json(force=True).get("zones", []))})
    return jsonify(ctx().zones.get(cam_id))


@app.route("/api/zones/reset", methods=["POST"])
def zones_reset():
    from pehredar.config import DEFAULT_ZONES
    ctx().zones.reset(DEFAULT_ZONES)
    return jsonify({"ok": True})


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        patch = request.get_json(force=True)
        return jsonify(ctx().settings.update({k: v for k, v in patch.items() if k in ctx().settings.data}))
    return jsonify(ctx().settings.data)


@app.route("/api/models")
def models():
    return jsonify(M.models())


@app.route("/api/models/<key>/toggle", methods=["POST"])
def model_toggle(key):
    b = request.get_json(force=True)
    for k in (list(MODULES) if key == "all" else [key]):
        if k in ctx().toggles:
            ctx().toggles[k] = bool(b.get("enabled", True))
    return jsonify(ctx().toggles)


# ============================================================================ events & alerts
def _filters():
    a = request.args
    return dict(since_seq=int(a.get("since", 0)), limit=min(int(a.get("limit", 200)), 5000), module=a.get("module"),
                camera=a.get("camera"), severity=a.get("severity"), status=a.get("status"), date_from=a.get("from"),
                date_to=a.get("to"), q=a.get("q"))


@app.route("/api/events")
def events():
    return jsonify(ctx().store.query(**_filters()))


@app.route("/api/events/<event_id>")
def event(event_id):
    ev = ctx().store.get(event_id)
    if not ev:
        abort(404)
    return jsonify(ev)


@app.route("/api/events/<event_id>/action", methods=["POST"])
def event_action(event_id):
    b = request.get_json(force=True)
    op = operator()
    try:
        ev = ctx().store.action(event_id, b.get("action"), f"{op['name']} ({op['id']})", b.get("note", ""))
    except (ValueError, KeyError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "event": ev})


@app.route("/api/alerts")
def alerts():
    return jsonify(ctx().store.active_alerts())


@app.route("/api/integrity")
def integrity():
    return jsonify(integrity_now())


@app.route("/api/integrity/tamper", methods=["POST"])
def integrity_tamper():
    try:
        r = ctx().store.tamper(request.get_json(force=True).get("kind", "record"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, **r, "verify": integrity_now()})


@app.route("/api/integrity/restore", methods=["POST"])
def integrity_restore():
    r = ctx().store.restore()
    return jsonify({"ok": True, **r, "verify": integrity_now()})


@app.route("/api/hash", methods=["POST"])
def hash_tool():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "no file"}), 400
    data = f.read()
    digest = hashlib.sha256(data).hexdigest()
    return jsonify({"ok": True, "name": f.filename, "bytes": len(data), "sha256": digest, "matches": ctx().store.lookup_hash(digest)})


@app.route("/api/export")
def export():
    fmt = request.args.get("fmt", "csv")
    rows = ctx().store.query(**_filters())
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if fmt == "json":
        return Response(json.dumps(rows, indent=2, ensure_ascii=False), mimetype="application/json",
                        headers={"Content-Disposition": f"attachment; filename=pehredar_events_{stamp}.json"})
    if fmt == "pdf":
        op = operator()
        pdf = ctx().store.export_pdf(rows[:200], privacy=request.args.get("privacy", "1") == "1",
                                     operator=f"{op['name']} ({op['id']})", sector=ctx().settings.get("sector"))
        return Response(pdf, mimetype="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename=pehredar_evidence_{stamp}.pdf"})
    return Response(ctx().store.export_csv(rows), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=pehredar_events_{stamp}.csv"})


# ============================================================================ vehicles / ANPR / faces
@app.route("/api/vehicles")
def vehicles():
    return jsonify(ctx().store.vehicles(request.args.get("q"), request.args.get("watch") == "1"))


@app.route("/api/vehicles/<plate>")
def vehicle(plate):
    return jsonify(ctx().store.vehicle_history(plate.replace(" ", "").upper()))


@app.route("/api/vehicles.csv")
def vehicles_csv():
    import csv
    import io
    rows = ctx().store.vehicles(request.args.get("q"), request.args.get("watch") == "1", limit=5000)
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["plate", "display", "state", "vehicle_type", "body_type", "colour", "times_seen", "first_seen", "last_seen",
            "last_camera", "watchlist", "watch_reason", "last_event_id"]
    w.writerow(cols)
    for r in rows:
        w.writerow([iso_ist(r[c]) if c in ("first_seen", "last_seen") else r[c] for c in cols])
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=vehicle_registry.csv"})


@app.route("/api/vehicles/feed")
def vehicle_feed():
    return jsonify(list(ctx().vehicle_feed)[:40])


@app.route("/api/vehicles/stats")
def vehicle_stats():
    since = M.midnight()
    obs = ctx().store.observations(since=since, limit=20000)
    by_cls, timeline = {}, {}
    for o in obs:
        by_cls[o["cls"]] = by_cls.get(o["cls"], 0) + 1
        slot = int((o["ts_epoch"] - since) // 600)
        timeline.setdefault(o["camera_id"], {}).setdefault(slot, 0)
        timeline[o["camera_id"]][slot] += 1
    return jsonify({"by_class": by_cls, "timeline": timeline, "total": len(obs)})


@app.route("/api/anpr/recent")
def anpr_recent():
    return jsonify(list(ctx().anpr.recent))


@app.route("/api/watchlist", methods=["GET", "POST", "DELETE"])
def watchlist():
    wl = load_json(WATCHLIST_PATH, [])
    if request.method == "POST":
        from pehredar.engine.anpr import display_plate, normalise_plate
        b = request.get_json(force=True)
        p, valid = normalise_plate(b.get("plate", ""))
        if not valid:
            return jsonify({"ok": False, "error": "not a valid Indian plate"}), 400
        wl = [w for w in wl if w["plate"] != p] + [{"plate": p, "display": display_plate(p), "reason": b.get("reason") or "added by operator",
                                                   "since": iso_ist()[:10], "severity": "critical", "added_by": operator()["id"]}]
    elif request.method == "DELETE":
        p = request.args.get("plate", "").replace(" ", "").upper()
        wl = [w for w in wl if w["plate"] != p]
    if request.method != "GET":
        save_json(WATCHLIST_PATH, wl)
        ctx().anpr.reload_watchlist()
    return jsonify(wl)


@app.route("/api/faces")
def faces():
    return jsonify(ctx().faces.entries())


@app.route("/api/faces/enroll", methods=["POST"])
def faces_enroll():
    import cv2
    import numpy as np
    from pehredar.engine.faces import CATEGORIES
    fe = ctx().faces
    if not fe.available:
        return jsonify({"ok": False, "error": "face models missing — run fetch_assets.py"}), 400
    if request.files.get("image"):
        frame = cv2.imdecode(np.frombuffer(request.files["image"].read(), np.uint8), cv2.IMREAD_COLOR)
        name, cat = request.form.get("name", ""), request.form.get("category", "Authorised Personnel")
    else:
        b = request.get_json(force=True)
        w = worker(b.get("camera", "CAM-01"))
        with w.lock:
            frame = None if w.frame is None else w.frame.copy()
        name, cat = b.get("name", ""), b.get("category", "Authorised Personnel")
    if frame is None:
        return jsonify({"ok": False, "error": "no image"}), 400
    if cat not in CATEGORIES:
        return jsonify({"ok": False, "error": "unknown category"}), 400
    fs = fe.detect(frame)
    if not fs:
        return jsonify({"ok": False, "error": "no face found — face the camera in good light"}), 400
    f = max(fs, key=lambda x: (x["box"][2] - x["box"][0]) * x["score"])
    return jsonify({"ok": True, "entry": fe.enroll(frame, f, name.strip() or "Unnamed", cat)})


@app.route("/api/faces/<eid>", methods=["DELETE"])
def faces_delete(eid):
    ctx().faces.remove(eid)
    return jsonify({"ok": True})


# ============================================================================ network / analytics / system / integrations
@app.route("/api/network")
def network():
    net = ctx().network
    return jsonify({"links": net.snapshot(), "history": {cid: net.history(cid)[-300:] for cid in net.links}})


@app.route("/api/network/<cam_id>/simulate", methods=["POST"])
def network_sim(cam_id):
    kind = request.get_json(force=True).get("kind", "degrade")
    if kind not in ("degrade", "outage", "congest"):
        abort(400)
    ctx().network.trigger(cam_id, kind, 30 if kind == "outage" else 45)
    return jsonify({"ok": True})


@app.route("/api/analytics")
def analytics():
    days = max(1, int(request.args.get("days", 1)))
    since = M.midnight() - (days - 1) * 86400
    rows, classes, plates = ctx().store.analytics(since)
    include = request.args.get("history") == "1" and ctx().history is not None
    if include:
        h_rows, h_classes, h_plates = ctx().history.analytics(since)
        rows = rows + h_rows
        for k, v in h_classes.items():
            classes[k] = classes.get(k, 0) + v
        plates = plates + [dict(p, sample=True) for p in h_plates]
    per_hour = [0] * 24
    by_mod, by_cam, sev, zones_c = {}, {}, {}, {}
    fa = acted = 0
    resp = []
    daynight = {"day": 0, "night": 0}
    for r in rows:
        per_hour[datetime.fromtimestamp(r["ts_epoch"], IST).hour] += 1
        by_mod[r["module"]] = by_mod.get(r["module"], 0) + 1
        by_cam[r["camera_id"]] = by_cam.get(r["camera_id"], 0) + 1
        sev[r["severity"]] = sev.get(r["severity"], 0) + 1
        daynight["night" if r["night"] else "day"] += 1
        if r["status"] != "new":
            acted += 1
            fa += r["status"] == "false_alarm"
        if r["response_s"]:
            resp.append(r["response_s"])
        if r["module"] == "fence":
            try:
                z = json.loads(r["extra"] or "{}").get("zone")
            except ValueError:
                z = None
            if z:
                zones_c[z] = zones_c.get(z, 0) + 1
    return jsonify({"total": len(rows), "per_hour": per_hour, "by_module": by_mod, "by_camera": by_cam, "severity": sev,
                    "vehicle_classes": classes, "top_plates": sorted(plates, key=lambda p: -p["times_seen"])[:10],
                    "intrusions_by_zone": zones_c, "false_alarm_rate": round(fa / acted, 3) if acted else None,
                    "avg_response_s": round(sum(resp) / len(resp), 1) if resp else None, "day_night": daynight,
                    "includes_sample_history": include, "days": days})


@app.route("/api/system")
def system():
    return jsonify(M.system_info())


@app.route("/api/integrations/sample")
def integration_sample():
    ev = ctx().store.query(limit=1)
    return jsonify(ev[0] if ev else {})


_webhook = {"last": None}


@app.route("/api/webhook/test", methods=["POST"])
def webhook_test():
    url = ctx().settings.get("integrations", "webhook_url")
    if not url:
        return jsonify({"ok": False, "error": "no webhook URL configured"}), 400
    try:
        r = requests.post(url, json={"type": "test", "source": "pehredar.ai", "ts": iso_ist()}, timeout=4)
        return jsonify({"ok": r.ok, "status": r.status_code})
    except requests.RequestException as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@app.route("/api/webhook/status")
def webhook_status():
    return jsonify(_webhook["last"] or {})


def webhook_dispatcher():
    q = ctx().bus.subscribe(1000)
    while True:
        msg = q.get()
        url = ctx().settings.get("integrations", "webhook_url")
        if not url or msg.get("type") != "event" or msg["event"]["severity"] not in ("critical", "high"):
            continue
        try:
            r = requests.post(url, json={"type": "alert", "event": msg["event"]}, timeout=4)
            _webhook["last"] = {"ok": r.ok, "status": r.status_code, "ts": iso_ist(), "event_id": msg["event"]["event_id"]}
        except requests.RequestException as e:
            _webhook["last"] = {"ok": False, "error": str(e)[:200], "ts": iso_ist()}


# ============================================================================ websockets
class _SendAllSocket:
    """simple-websocket writes frames with socket.send(), which may write only part of a
    large (JPEG) frame and silently drop the rest — the browser then sees a corrupt
    stream ('Invalid frame header'). Force complete, serialised writes."""

    def __init__(self, s):
        self._s = s
        self._lock = threading.Lock()

    def send(self, data):
        with self._lock:
            self._s.sendall(data)
        return len(data)

    def __getattr__(self, name):
        return getattr(self._s, name)


import simple_websocket.ws as _sws
from wsproto.extensions import PerMessageDeflate as _PMD


class _NoDeflate(_PMD):
    """Decline permessage-deflate: its shared compressor state is not thread-safe with
    simple-websocket's reader thread and corrupted frames in Chrome. JPEGs don't compress anyway."""

    def accept(self, offer):
        return None


_sws.PerMessageDeflate = _NoDeflate


class _LockedConn:
    """wsproto's Connection is not thread-safe; simple-websocket parses incoming frames on a
    reader thread while our handler thread sends. Serialise both on one lock."""

    def __init__(self, c):
        self._c = c
        self._l = threading.RLock()

    def send(self, ev):
        with self._l:
            return self._c.send(ev)

    def receive_data(self, d):
        with self._l:
            return self._c.receive_data(d)

    def events(self):
        with self._l:
            return iter(list(self._c.events()))

    def __getattr__(self, n):
        return getattr(self._c, n)


def _harden(ws):
    if not isinstance(ws.sock, _SendAllSocket):
        ws.sock = _SendAllSocket(ws.sock)
    if not isinstance(ws.ws, _LockedConn):
        ws.ws = _LockedConn(ws.ws)
    return ws


@sock.route("/ws")
def ws_main(ws):
    """Multiplexed stream: binary frames (b'F' + camera index + JPEG) and JSON messages."""
    _harden(ws)
    ids = list(M.workers)
    sub, focus, maxw = set(), None, 640
    last_seq, last_sent, last_meta = {}, {}, {}
    q = ctx().bus.subscribe()
    ws.send(json.dumps({"type": "hello", "cameras": ids}))
    last_tick = 0
    try:
        while True:
            msg = ws.receive(timeout=0.01)
            if msg:
                try:
                    m = json.loads(msg)
                    if "subscribe" in m:
                        sub = {c for c in m["subscribe"] if c in M.workers}
                    focus = m.get("focus", focus)
                    maxw = int(m.get("maxw", maxw))
                    if m.get("cameras_refresh"):
                        ids = list(M.workers)
                        ws.send(json.dumps({"type": "hello", "cameras": ids}))
                except (ValueError, TypeError):
                    pass
            for _ in range(50):
                try:
                    ev = q.get_nowait()
                except queue.Empty:
                    break
                ws.send(json.dumps(ev, default=str))
            now = time.time()
            for cid in list(sub):
                w = M.workers.get(cid)
                if w is None or cid not in ids:
                    continue
                prof = ctx().network.profile(cid)
                if prof["mode"] == "offline":
                    continue
                fps = prof["fps"] if cid == focus else min(prof["fps"], 6)
                if prof["mode"] == "metadata":
                    if now - last_meta.get(cid, 0) >= 1.0:
                        last_meta[cid] = now
                        ws.send(json.dumps({"type": "meta", "camera": cid, **w.metadata()}))
                    fps = 0.1  # one low-quality keyframe every 10 s
                if w.seq == last_seq.get(cid) or now - last_sent.get(cid, 0) < 1.0 / max(fps, 0.05):
                    continue
                data = w.jpeg(scale=prof["scale"], max_w=None if cid == focus else maxw,
                              quality=prof["quality"] if cid == focus else min(prof["quality"], 65))
                if data:
                    ws.send(b"F" + struct.pack("B", ids.index(cid)) + data)
                    last_seq[cid], last_sent[cid] = w.seq, now
            if now - last_tick >= 1.0:
                last_tick = now
                net = ctx().network.snapshot()
                k = M.kpis()
                ws.send(json.dumps({"type": "tick", "kpis": k, "system": system_status(k, net), "time": iso_ist(),
                                    "cams": {cid: {"stats": w.stats, "alert": now < w.alert_until, "net": net.get(cid),
                                                   "wh": w.wh, "source": w.source_label, "display": w.display, "kind": w.kind,
                                                   "heat": w.show_heat}
                                             for cid, w in M.workers.items()},
                                    "toggles": ctx().toggles, "anpr_busy": ctx().anpr.busy, "anpr_queue": ctx().anpr.q.qsize()},
                                   default=str))
    except ConnectionClosed:
        pass
    except Exception:
        traceback.print_exc()
    finally:
        ctx().bus.unsubscribe(q)


@sock.route("/ws/alerts")
def ws_alerts(ws):
    """C2 integration stream: JSON events only (optionally ?min=high)."""
    _harden(ws)
    order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
    lim = order.get(request.args.get("min", "info"), 3)
    q = ctx().bus.subscribe()
    try:
        while True:
            msg = q.get()
            if msg.get("type") == "event" and order.get(msg["event"]["severity"], 3) <= lim:
                ws.send(json.dumps(msg["event"], default=str))
    finally:
        ctx().bus.unsubscribe(q)


def main():
    global M
    from pehredar.manager import Manager
    M = Manager()
    M.start()
    threading.Thread(target=webhook_dispatcher, daemon=True, name="webhook").start()
    threading.Thread(target=integrity_loop, daemon=True, name="integrity").start()
    print(f"Pehredar.ai running on http://localhost:5000  ·  device: {M.ctx.device_label}", flush=True)
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)


if __name__ == "__main__":
    main()
