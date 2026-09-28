"""Camera workers.

LiveCamera     — webcam / file / RTSP; capture thread and inference thread are separate
                 (drop-oldest: inference always takes the newest frame), so display fps
                 is not limited by inference speed. Real YOLOv8n + per-camera ByteTrack.
ReplayCamera   — 'recorded': real footage + real YOLOv8n/ByteTrack detections computed
                 once by generate_assets.py and replayed in sync with the video.
                 'synthetic': generated scene + the generator's ground-truth boxes.
Both feed the same analytics pipeline (zones, behaviour, vehicles/ANPR, faces, night).
"""
import base64
import itertools
import json
import os
import threading
import time

import cv2
import numpy as np

from .config import MODULES, UPLOADS, VIDEOS
from .engine.activity import ActivityEngine
from .engine.detector import CLASS_NAMES, new_tracker, tracker_rows_to_dets
from .engine.night import LightMeter, MotionLayer, enhance, thermal
from .engine.tracks import TrackBook
from .engine.vehicles import HEAVY, SIZE_CLASS, direction, dominant_colour, speed_kmh

GREEN = (8, 136, 19)
LIGHT_GREEN = (70, 205, 80)
SAFFRON = (51, 153, 255)
RED = (57, 57, 229)
AMBER = (53, 216, 253)
WHITE = (255, 255, 255)
CYAN = (230, 200, 60)
NAVY_LIGHT = (220, 140, 60)
job_ids = itertools.count(1)


def b64jpg(img, width=200, q=75):
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, max(1, int(h * width / w))))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return base64.b64encode(buf.tobytes()).decode() if ok else None


def _label(img, text, x, y, color, scale):
    fs = 0.42 * scale
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
    x, y = int(x), int(max(th + 4, y))
    cv2.rectangle(img, (x, y - th - 5), (x + tw + 6, y + 1), color, -1)
    cv2.putText(img, text, (x + 3, y - 3), cv2.FONT_HERSHEY_SIMPLEX, fs, (15, 15, 15) if sum(color) > 400 else WHITE, 1, cv2.LINE_AA)


class CameraWorker(threading.Thread):
    kind = "base"
    face_every = 1

    def __init__(self, cfg, ctx):
        super().__init__(daemon=True, name=cfg["id"])
        self.cfg, self.id, self.ctx = cfg, cfg["id"], ctx
        self.lock = threading.Lock()
        self.frame = None
        self.seq = 0
        self.wh = (0, 0)
        self.overlay = {"tracks": [], "faces": [], "blobs": [], "alert": set(), "synthetic": False}
        self.book = TrackBook()
        self.activity = ActivityEngine()
        self.light = LightMeter()
        self.motion = MotionLayer()
        self.motion_warm = 0
        self.heat = np.zeros((36, 64), np.float32)
        self.show_heat = False
        self.display = cfg.get("display", "normal")
        self.alert_until = 0.0
        self.source_label = ""
        self.stats = {"fps": 0.0, "infer_fps": 0.0, "infer_ms": None, "people": 0, "vehicles": 0, "objects": 0, "faces": 0,
                      "entries": 0, "exits": 0, "people_seen": 0, "vehicles_seen": 0, "status": "starting", "night": False,
                      "light": None, "night_raw": None, "night_enh": None, "analysis_fps": 0.0}
        self._fps = [0, time.time()]
        self._afps = [0, time.time()]
        self.face_tracks = {}
        self._face_ids = itertools.count(1)
        self.frame_i = 0
        self._jcache = {}
        self.running = True

    # ------------------------------------------------------------------ basics
    def has(self, m):
        return m in self.cfg.get("modules", [])

    def conf(self, section):
        return self.ctx.settings.get(section)

    @staticmethod
    def _rate(counter, key, stats):
        counter[0] += 1
        now = time.time()
        if now - counter[1] >= 1.0:
            stats[key] = round(counter[0] / (now - counter[1]), 1)
            counter[0], counter[1] = 0, now

    def publish_frame(self, frame):
        with self.lock:
            self.frame = frame
            self.seq += 1
            self.wh = (frame.shape[1], frame.shape[0])
        self.ctx.network.src_wh[self.id] = self.wh
        self._rate(self._fps, "fps", self.stats)

    # ------------------------------------------------------------------ analytics pipeline
    def analyze(self, frame, dets, t, synthetic=False):
        night = self.light.update(frame, self.conf("night"))
        self.stats["night"], self.stats["light"] = night, round(self.light.level, 1)
        active, ended = self.book.update(dets, t)
        wh = (frame.shape[1], frame.shape[0])
        persons = [tr for tr in active if tr.is_person]
        vehicles = [tr for tr in active if tr.is_vehicle]
        alert = set()
        cool = self.conf("alerts")["cooldown_s"]
        zones = self.ctx.zones
        restricted_ids = {z["id"] for z in zones.get(self.id) if z["type"] == "restricted"}

        if self.has("fence"):
            for tr in active:
                for hit in zones.check(self.id, tr, wh, night, t):
                    z = hit["zone"]
                    if z["type"] == "count":
                        self.stats["entries" if hit["direction"] == "forward" else "exits"] += 1
                        continue
                    if hit["kind"] == "inside":
                        if z["type"] == "restricted":
                            alert.add(tr.tid)
                        continue
                    breach = z["type"] in ("restricted", "tripwire")
                    name = "Fence Breach" if breach else "Buffer Zone Entry"
                    if night:
                        name += " (Night)"
                    if tr.cooldown(("zone", z["id"]), t, cool):
                        alert.add(tr.tid)
                        how = f"crossed tripwire '{z['name']}' ({hit['direction']})" if hit["kind"] == "cross" else f"entered {z['type']} zone '{z['name']}'"
                        self.emit(name, "fence", "critical" if breach else "high", f"{tr.name.title()} #{tr.tid} {how}", frame, [tr],
                                  extra={"zone": z["name"], "zone_type": z["type"], "direction": hit.get("direction"),
                                         "object": tr.name, "schedule": z["schedule"]},
                                  alert_type="Intrusion", night=night)

        if self.has("human"):
            for tr in persons:
                fx, fy = tr.foot
                gx, gy = min(63, int(fx / wh[0] * 64)), min(35, int(fy / wh[1] * 36))
                self.heat[gy, gx] += 1
            thr = self.conf("human")["crowd_threshold"]
            if len(persons) >= thr and self.ctx.store.cooldown_ok(("crowd", self.id), 60):
                self.emit("Crowd Above Threshold", "human", "medium", f"{len(persons)} people in view (threshold {thr})",
                          frame, persons, extra={"count": len(persons), "threshold": thr}, alert_type="Crowd", night=night)

        if self.has("activity"):
            for f in self.activity.evaluate(self.cfg, active, zones, wh, night, t, self.conf("activity")):
                lead = f["tracks"][0]
                ok = self.ctx.store.cooldown_ok(("group", self.id), 60) if f["kind"] == "Group Gathering" \
                    else lead.cooldown(("act", f["kind"]), t, max(cool, 30))
                if ok:
                    if f["severity"] in ("critical", "high"):
                        alert.update(f["tids"])
                    timeline = [{"t": round(tr.first - t, 1), "event": f"#{tr.tid} first seen"} for tr in f["tracks"][:4]]
                    timeline.append({"t": 0, "event": f["kind"]})
                    self.emit(f["kind"], "activity", f["severity"], f"{f['desc']} · risk {f['risk']}/100", frame, f["tracks"],
                              extra={"activity": f["kind"], "risk": f["risk"], "tracks": f["tids"], "zone": f["zone"],
                                     "duration_s": f["duration"], "timeline": timeline},
                              model="Behaviour rules over ByteTrack tracks", alert_type="Behaviour", night=night)

        if self.has("vehicle") or self.has("anpr"):
            vcfg = self.conf("vehicle")
            for tr in vehicles:
                self._update_best(tr, frame, t)
                if self.cfg.get("heavy_restricted") and tr.name in HEAVY and tr.dwell > 1.0 and tr.cooldown("heavy", t, 1e9):
                    alert.add(tr.tid)
                    self.emit("Heavy Vehicle on Restricted Road", "vehicle", "high", f"{tr.name} #{tr.tid} (HMV) on a road closed to heavy vehicles",
                              frame, [tr], extra={"vehicle": tr.name, "size_class": "HMV"}, alert_type="Vehicle", night=night)
                if tr.dwell >= vcfg["stopped_seconds"] and tr.speed_bh(3.0) < 0.05 and tr.cooldown("stopped", t, 1e9):
                    self.emit("Vehicle Stopped Too Long", "vehicle", "medium", f"{tr.name} #{tr.tid} stationary for {tr.dwell:.0f}s",
                              frame, [tr], extra={"vehicle": tr.name, "stopped_s": round(tr.dwell)}, alert_type="Vehicle", night=night)

        blobs = []
        if night and self.has("night"):
            self.motion_warm += 1
            blobs = self.motion.blobs(frame)
            if self.motion_warm > 40:
                outside = [tr for tr in persons if not any(tr.zone_inside.get(zid) for zid in restricted_ids)]
                if outside and self.cfg.get("restricted_post") and self.ctx.store.cooldown_ok(("night", self.id), 60):
                    alert.update(tr.tid for tr in outside)
                    ids = ", ".join(f"#{tr.tid}" for tr in outside[:6])
                    self.emit("Night Movement Near Border", "night", "high", f"{len(outside)} person(s) ({ids}) moving near the border "
                              f"in low light (scene brightness {self.light.level:.0f}/255)", frame, outside,
                              extra={"light_level": round(self.light.level, 1), "tracks": [tr.tid for tr in outside]},
                              alert_type="Night", night=True)
                loose = [b for b in blobs if not any(self._overlap(b, tr.box) > 0.3 for tr in active)]
                if loose and self.ctx.store.cooldown_ok(("motion", self.id), 45):
                    self.emit("Unclassified Night Motion", "night", "medium",
                              f"{len(loose)} moving region(s) with no YOLO detection — MOG2 motion layer", frame, [],
                              extra={"blobs": loose[:6], "light_level": round(self.light.level, 1)},
                              model="OpenCV MOG2 background subtraction", alert_type="Night", night=True, blobs=loose)
        else:
            self.motion_warm = 0

        faces_live = []
        if self.has("face") and self.ctx.faces.available and self.frame_i % self.face_every == 0:
            faces_live = self._faces(frame, t, persons, night)
        elif self.has("face"):
            faces_live = self.overlay["faces"]

        for tr in ended:
            if tr.is_vehicle:
                self._vehicle_done(tr, night)

        for tr in persons:
            if any(tr.zone_inside.get(zid) for zid in restricted_ids):
                alert.add(tr.tid)
        with self.lock:
            self.overlay = {"tracks": [(tr.tid, tr.name, tr.conf, tuple(tr.box), tr.trail(30)) for tr in active],
                            "faces": faces_live, "blobs": blobs, "alert": alert, "synthetic": synthetic}
        s = self.stats
        s["people"], s["vehicles"] = len(persons), len(vehicles)
        s["objects"] = len([tr for tr in active if tr.is_object])
        s["people_seen"], s["vehicles_seen"] = self.book.people_seen, self.book.vehicles_seen
        if alert:
            self.alert_until = max(self.alert_until, time.time() + 1.5)
        self.frame_i += 1
        self._rate(self._afps, "analysis_fps", s)

    @staticmethod
    def _overlap(a, b):
        ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
        area = max(1, (a[2] - a[0]) * (a[3] - a[1]))
        return ix * iy / area

    # ------------------------------------------------------------------ events
    def emit(self, name, module, severity, desc, frame, tracks, extra=None, model=None, alert_type=None, night=False,
             crops=None, faces=None, blobs=None, conf=None):
        snap = self.render(frame, highlight={tr.tid for tr in tracks}, faces=faces, blobs=blobs, snapshot=True)
        extra = dict(extra or {})
        extra["source"] = self.source_label
        kwargs = dict(event_name=name, module=module, severity=severity, camera=self.cfg, frame=snap, description=desc,
                      alert_type=alert_type, model_used=model or MODULES[module]["model"],
                      confidence=conf if conf is not None else (tracks[0].conf if tracks else None),
                      track_id=tracks[0].tid if tracks else None, extra=extra, night=night,
                      synthetic=self.kind == "synthetic", crops=crops)
        if severity in ("critical", "high"):
            self.alert_until = time.time() + 5
        return self.ctx.network.deliver(self.id, kwargs)

    # ------------------------------------------------------------------ vehicles → ANPR
    def _update_best(self, tr, frame, t):
        x1, y1, x2, y2 = [int(v) for v in tr.box]
        H, W = frame.shape[:2]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(W, x2), min(H, y2)
        area = (x2 - x1) * (y2 - y1)
        if area <= 64:
            return
        edge = 0.6 if (x1 < 4 or y1 < 4 or x2 > W - 4 or y2 > H - 4) else 1.0
        score = area * edge
        if tr.best is not None and score <= tr.best[0] * 1.05:
            return
        crop = frame[y1:y2, x1:x2]
        sharp = cv2.Laplacian(cv2.cvtColor(cv2.resize(crop, (96, 64)), cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        score *= min(1.0, 0.4 + sharp / 300.0)
        if tr.best is None or score > tr.best[0]:
            tr.best = (score, frame.copy(), [x1, y1, x2, y2])
            tr.meta["best_t"] = t

    def _vehicle_done(self, tr, night):
        if tr.best is None or tr.dwell < 1.0:
            return
        _, bframe, box = tr.best
        crop = bframe[box[1]:box[3], box[0]:box[2]]
        name = tr.major_name
        colour = dominant_colour(crop)
        d = direction(tr, self.cfg.get("in_vector", [0, 1]))
        sp = speed_kmh(tr, self.conf("vehicle")["m_per_px"])
        size = SIZE_CLASS.get(name, "—")
        self.ctx.store.add_observation(ts_epoch=time.time(), camera_id=self.id, track_key=f"{self.id}:{tr.tid}", cls=name,
                                       size_class=size, colour=colour, direction=d, speed_kmh=sp)
        item = {"camera": self.id, "tid": tr.tid, "cls": name, "size": size, "colour": colour, "direction": d,
                "speed": sp, "ts": time.time(), "crop": b64jpg(crop, 160), "conf": round(tr.conf, 2)}
        self.ctx.vehicle_feed.appendleft(item)
        self.ctx.bus.publish({"type": "vehicle", "item": item})
        area_frac = (box[2] - box[0]) * (box[3] - box[1]) / float(bframe.shape[0] * bframe.shape[1])
        if self.has("anpr") and name in ("car", "bus", "truck", "motorcycle") and area_frac >= self.cfg.get("anpr_min_area", 0.0):
            self.ctx.anpr.submit({"job_id": next(job_ids), "camera": self.cfg, "frame": bframe, "box": box, "cls": name,
                                  "tid": tr.tid, "colour": colour, "direction": d, "speed": sp, "night": night,
                                  "body": self.cfg.get("anpr_body", False), "ts": time.time()})

    def capture_scan(self):
        """Manual 'Capture & Scan': run vehicle detection on the current frame and hand the
        largest vehicles to ANPR; run face detection + matching; return what was found."""
        with self.lock:
            frame = None if self.frame is None else self.frame.copy()
        if frame is None:
            return {"ok": False, "error": "no frame"}
        boxes, _ = self.ctx.detector.detect(frame, conf=0.3, classes=[2, 3, 5, 7])
        vs = sorted(boxes.xyxy.tolist(), key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))[:2]
        jobs = []
        for i, b in enumerate(vs):
            jid = next(job_ids)
            cls = CLASS_NAMES.get(int(boxes.cls[i]), "vehicle")
            crop = frame[int(b[1]):int(b[3]), int(b[0]):int(b[2])]
            self.ctx.anpr.submit({"job_id": jid, "camera": self.cfg, "frame": frame, "box": b, "cls": cls, "tid": None,
                                  "colour": dominant_colour(crop), "direction": None, "speed": None, "manual": True,
                                  "body": True, "ts": time.time()})
            jobs.append(jid)
        faces = []
        if self.ctx.faces.available:
            for f in self.ctx.faces.detect(frame):
                emb, _ = self.ctx.faces.embed(frame, f)
                e, s = self.ctx.faces.match(emb, self.conf("face")["match_threshold"])
                faces.append({"box": f["box"], "score": round(f["score"], 3), "match": e["name"] if e else None,
                              "category": e["category"] if e else "Unregistered", "similarity": round(s, 3)})
        return {"ok": True, "vehicles": len(vs), "anpr_jobs": jobs, "faces": faces, "frame": b64jpg(frame, 480)}

    # ------------------------------------------------------------------ faces
    def _face_key(self, cx, cy, w, t):
        for k, ft in self.face_tracks.items():
            if k[0] == "f" and t - ft["last"] < 1.0 and abs(ft["c"][0] - cx) < 0.6 * w and abs(ft["c"][1] - cy) < 0.6 * w:
                return k
        return ("f", next(self._face_ids))

    def _faces(self, frame, t, persons, night):
        fcfg = self.conf("face")
        fe = self.ctx.faces
        faces = fe.detect(frame)
        live = []
        for f in faces:
            x1, y1, x2, y2 = f["box"]
            fw, cx, cy = x2 - x1, (x1 + x2) / 2, (y1 + y2) / 2
            owner = next((tr for tr in persons if tr.box[0] <= cx <= tr.box[2]
                          and tr.box[1] <= cy <= tr.box[1] + 0.55 * (tr.box[3] - tr.box[1])), None)
            key = ("p", owner.tid) if owner else self._face_key(cx, cy, fw, t)
            ft = self.face_tracks.setdefault(key, {"first": t, "best_q": -1.0, "logged": False, "label": None,
                                                   "tid": owner.tid if owner else None})
            ft.update(last=t, box=f["box"], c=(cx, cy))
            q, _ = fe.quality(frame, f)
            if fw >= fcfg["min_face_px"] and q > ft["best_q"]:
                ft["best_q"], ft["best"] = q, (frame.copy(), f)
            live.append((f["box"], ft["label"] or f"face {f['score']:.2f} · q {q:.2f}", ft.get("cat")))
        self.stats["faces"] = len(faces)
        for key, ft in list(self.face_tracks.items()):
            ready = not ft["logged"] and ft.get("best") is not None and (
                (t - ft["first"] >= 1.2 and ft["best_q"] >= 0.5) or (t - ft["last"] > 1.0 and ft["best_q"] >= 0.3))
            if ready:
                self._face_log(ft, night)
            if t - ft["last"] > 4:
                del self.face_tracks[key]
        return live

    def _face_log(self, ft, night):
        fe = self.ctx.faces
        fcfg = self.conf("face")
        bframe, f = ft["best"]
        emb, aligned = fe.embed(bframe, f)
        entry, score = fe.match(emb, fcfg["match_threshold"])
        cat = entry["category"] if entry else "Unregistered"
        ft["logged"] = True
        ft["cat"] = cat
        ft["label"] = f"{entry['name']} · {cat} {score:.2f}" if entry else f"Unregistered (best {max(score, 0):.2f})"
        if entry and cat == "Watchlist":
            name, sev = "Watchlist Face Match", "critical"
        elif not entry and self.cfg.get("restricted_post"):
            name, sev = "Unregistered Person at Restricted Post", "medium"
        else:
            name, sev = "Face Detected", "info"
        desc = (f"{entry['name']} ({cat}) matched, similarity {score:.2f}" if entry
                else f"No registry match (best similarity {max(score, 0):.2f} < {fcfg['match_threshold']})")
        desc += f" · quality {ft['best_q']:.2f}" + (f" · person #{ft['tid']}" if ft["tid"] else "")
        extra = {"faces": [{"box": [round(v) for v in f["box"]], "category": cat}], "match": entry["name"] if entry else None,
                 "face_id": entry["id"] if entry else None, "category": cat, "similarity": round(score, 3),
                 "quality": ft["best_q"], "det_score": round(f["score"], 3)}
        ev = self.emit(name, "face", sev, desc, bframe, [], extra=extra, alert_type="Identity", night=night, conf=f["score"],
                       model=f"{fe.detector_name} + {fe.recognizer_name}", crops={"face": aligned},
                       faces=[(f["box"], ft["label"], cat)])
        if entry and ev:
            fe.record_match(entry["id"], self.id, score, ev["event_id"])
        self.ctx.bus.publish({"type": "face", "camera": self.id, "category": cat, "label": ft["label"],
                              "crop": b64jpg(aligned, 112), "quality": ft["best_q"], "ts": time.time()})

    # ------------------------------------------------------------------ rendering
    def render(self, frame=None, highlight=None, faces=None, blobs=None, snapshot=False, mode=None, out_w=None):
        with self.lock:
            base = self.frame if frame is None else frame
            ov = self.overlay
        if base is None:
            return None
        mode = mode or self.display
        k = 1.0
        if out_w and out_w < base.shape[1]:
            # downscale first, then draw: overlays at tile size cost a fraction of full-res drawing
            k = out_w / base.shape[1]
            base = cv2.resize(base, (int(out_w), int(base.shape[0] * k)), interpolation=cv2.INTER_AREA)
        img = thermal(base) if mode == "thermal" else enhance(base, self.conf("night")["clahe_clip"], self.conf("night")["gamma"]) \
            if mode == "enhanced" else base.copy()
        tg = self.ctx.toggles
        H, W = img.shape[:2]
        sc = max(0.8, H / 540)
        lw = max(1, int(round(2 * sc)))
        if self.show_heat and self.heat.max() > 0 and not snapshot:
            hm = cv2.resize(self.heat / self.heat.max(), (W, H))
            hm = cv2.applyColorMap((np.clip(hm, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_JET)
            mask = cv2.resize((self.heat > 0).astype(np.uint8) * 255, (W, H))
            img = np.where(mask[..., None] > 0, cv2.addWeighted(img, 0.55, hm, 0.45, 0), img)
        if tg.get("fence", True) or snapshot:
            self._draw_zones(img, W, H, lw, sc)
        synthetic = ov.get("synthetic")
        for tid, name, cf, box, trail in ov["tracks"]:
            person = name == "person"
            vehicle = name in ("car", "bus", "truck", "motorcycle", "bicycle")
            if not snapshot and ((person and not tg.get("human", True)) or (vehicle and not tg.get("vehicle", True))):
                continue
            hot = tid in ov["alert"] or (highlight and tid in highlight)
            col = RED if hot else LIGHT_GREEN if person else SAFFRON if vehicle else AMBER
            x1, y1, x2, y2 = [int(v * k) for v in box]
            cv2.rectangle(img, (x1, y1), (x2, y2), col, lw + (1 if hot else 0))
            if person and len(trail) > 1 and (tg.get("human", True) or snapshot):
                cv2.polylines(img, [(np.array(trail, np.float32) * k).astype(np.int32)], False, col, max(1, lw - 1), cv2.LINE_AA)
            _label(img, f"{name} {'GT' if synthetic else f'{cf:.2f}'} #{tid}", x1, y1 - 2, col, sc)
        if tg.get("face", True) or snapshot:
            for fb, lab, cat in (faces if faces is not None else ov["faces"]):
                x1, y1, x2, y2 = [int(v * k) for v in fb]
                col = RED if cat == "Watchlist" else GREEN if cat in ("Authorised Personnel", "Local Resident") else NAVY_LIGHT
                cv2.rectangle(img, (x1, y1), (x2, y2), col, lw)
                _label(img, lab, x1, y2 + 16 * sc, col, sc * 0.9)
        if tg.get("night", True) or snapshot:
            for b in (blobs if blobs is not None else ov["blobs"]):
                x1, y1, x2, y2 = [int(v * k) for v in b]
                for i in range(x1, x2, 10):
                    cv2.line(img, (i, y1), (min(i + 5, x2), y1), AMBER, 1)
                    cv2.line(img, (i, y2), (min(i + 5, x2), y2), AMBER, 1)
                for j in range(y1, y2, 10):
                    cv2.line(img, (x1, j), (x1, min(j + 5, y2)), AMBER, 1)
                    cv2.line(img, (x2, j), (x2, min(j + 5, y2)), AMBER, 1)
                _label(img, "MOTION", x1, y1 - 2, AMBER, sc * 0.8)
        return img

    def _draw_zones(self, img, W, H, lw, sc):
        over = img.copy()
        for z in self.ctx.zones.get(self.id):
            pts = np.array([[int(x * W), int(y * H)] for x, y in z["points"]], np.int32)
            col = {"restricted": RED, "buffer": SAFFRON, "tripwire": WHITE, "count": CYAN}[z["type"]]
            if z["type"] in ("restricted", "buffer"):
                cv2.fillPoly(over, [pts], col)
                cv2.polylines(img, [pts], True, col, lw, cv2.LINE_AA)
            else:
                cv2.line(img, tuple(pts[0]), tuple(pts[1]), col, lw + 1, cv2.LINE_AA)
                (ax, ay), (bx, by) = pts[0], pts[1]
                mx, my = (ax + bx) // 2, (ay + by) // 2
                nx, ny = (by - ay), -(bx - ax)
                n = max(1.0, (nx * nx + ny * ny) ** 0.5)
                tip = (int(mx + nx / n * 26 * sc), int(my + ny / n * 26 * sc))
                cv2.arrowedLine(img, (mx, my), tip, col, lw, cv2.LINE_AA, tipLength=0.4)
            lx, ly = pts[:, 0].min(), pts[:, 1].min()
            _label(img, f"{z['name']}{'' if self.ctx.zones.armed(z, self.light.night) else ' (disarmed)'}", int(lx), int(ly) - 2, col, sc * 0.85)
        cv2.addWeighted(over, 0.18, img, 0.82, 0, img)

    def jpeg(self, scale=1.0, max_w=None, quality=75):
        key = (self.seq, round(scale, 2), max_w, quality, self.display, self.show_heat)
        cached = self._jcache.get(key[1:])
        if cached and cached[0] == self.seq:
            return cached[1]
        with self.lock:
            src_w = self.wh[0] or 1
        w = src_w * scale
        if max_w:
            w = min(w, max_w)
        img = self.render(out_w=int(w))
        if img is None:
            return None
        if int(w) < img.shape[1]:
            img = cv2.resize(img, (int(w), int(img.shape[0] * w / img.shape[1])), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        data = buf.tobytes() if ok else None
        self._jcache[key[1:]] = (self.seq, data)
        return data

    def raw_jpeg(self, mode):
        with self.lock:
            base = None if self.frame is None else self.frame.copy()
        if base is None:
            return None
        img = thermal(base) if mode == "thermal" else enhance(base, self.conf("night")["clahe_clip"], self.conf("night")["gamma"]) \
            if mode == "enhanced" else base
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None

    def metadata(self):
        with self.lock:
            ov = self.overlay
            wh = self.wh
        return {"wh": wh, "tracks": [{"tid": tid, "name": n, "conf": round(c, 2), "box": [round(v) for v in b]}
                                     for tid, n, c, b, _ in ov["tracks"]]}

    def tracks_info(self):
        now = time.time()
        out = []
        for tr in list(self.book.tracks.values()):
            if now - tr.last > 1.0:
                continue
            out.append({"tid": tr.tid, "name": tr.major_name, "conf": round(tr.conf, 2), "dwell_s": round(tr.dwell, 1),
                        "speed_bh_s": round(tr.speed_bh(1.0), 2),
                        "zones": [zid for zid, inside in tr.zone_inside.items() if inside]})
        return sorted(out, key=lambda x: -x["dwell_s"])

    def info(self):
        return {**{k: self.cfg.get(k) for k in ("id", "name", "location", "gps", "link", "kind", "modules", "restricted_post")},
                "source": self.source_label, "stats": dict(self.stats), "wh": self.wh, "display": self.display,
                "heatmap": self.show_heat, "alert": time.time() < self.alert_until, "zones": self.ctx.zones.get(self.id)}


class LiveCamera(CameraWorker):
    kind = "live"
    face_every = 3

    def __init__(self, cfg, ctx):
        super().__init__(cfg, ctx)
        self.src_lock = threading.Lock()
        self.cap = None
        self.latest = None
        self.latest_seq = 0
        self.tracker = new_tracker(15)
        self.black_n = 0
        self.src_fps = 25.0
        self.is_file = True
        self.source = None
        self.last_night_cmp = 0
        self._inf = [0, time.time()]
        self.set_source(cfg.get("source", "auto"))

    @staticmethod
    def sample_path(name):
        for d in (UPLOADS, VIDEOS):
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
        return None

    @staticmethod
    def probe_webcam(idx=0):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(idx)
        ok_frames, bright = 0, 0.0
        for _ in range(20):
            ok, f = cap.read()
            if ok:
                ok_frames += 1
                bright = float(f.mean())
        cap.release()
        return ok_frames > 5 and bright > 8

    def set_source(self, src):
        if src == "auto":
            src = "webcam:0" if self.probe_webcam(0) else "sample:people-detection.mp4"
        if src.startswith("webcam:"):
            idx = int(src.split(":")[1])
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(idx)
            label, is_file = f"Webcam {idx} (live)", False
        elif src.startswith("sample:") or src.startswith("file:"):
            name = src.split(":", 1)[1]
            path = self.sample_path(name) if src.startswith("sample:") else name
            cap = cv2.VideoCapture(path) if path else None
            label, is_file = f"Sample clip: {os.path.basename(name)}", True
        else:
            cap = cv2.VideoCapture(src)
            label, is_file = f"RTSP/IP stream: {src.split('@')[-1]}", False
        if cap is None or not cap.isOpened():
            self.stats["status"] = f"cannot open source {src}"
            return False
        with self.src_lock:
            if self.cap is not None:
                self.cap.release()
            self.cap, self.source, self.is_file = cap, src, is_file
            self.src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            if self.src_fps > 60 or self.src_fps < 1:
                self.src_fps = 25.0
            self.tracker = new_tracker(int(self.src_fps))
            self.book = TrackBook()
            self.activity = ActivityEngine()
            self.black_n = 0
        self.source_label = label
        self.stats["status"] = "online"
        return True

    def run(self):
        threading.Thread(target=self._infer_loop, daemon=True, name=self.id + "-infer").start()
        next_t = time.time()
        while self.running:
            with self.src_lock:
                cap, is_file, fps = self.cap, self.is_file, self.src_fps
            if cap is None:
                time.sleep(0.3)
                continue
            ok, frame = cap.read()
            if not ok:
                if is_file:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                self.stats["status"] = "NO SIGNAL — stream read failed"
                time.sleep(0.5)
                continue
            if not is_file:
                if frame.mean() < 3:
                    self.black_n += 1
                    if self.black_n == 45:
                        self.stats["status"] = "NO SIGNAL — webcam returning black frames; switched to sample clip"
                        self.set_source("sample:people-detection.mp4")
                        continue
                else:
                    self.black_n = 0
                    self.stats["status"] = "online"
            if frame.shape[1] > 1280:
                frame = cv2.resize(frame, (1280, int(frame.shape[0] * 1280 / frame.shape[1])))
            self.publish_frame(frame)
            with self.lock:
                self.latest = (frame, time.time())
                self.latest_seq += 1
            if is_file:
                next_t += 1.0 / fps
                d = next_t - time.time()
                if d > 0:
                    time.sleep(d)
                elif d < -1:
                    next_t = time.time()

    def _infer_loop(self):
        last = 0
        while self.running:
            with self.lock:
                seq, item = self.latest_seq, self.latest
            if seq == last or item is None:
                time.sleep(0.004)
                continue
            last = seq
            frame, t = item
            night = self.light.night and self.has("night")
            img = enhance(frame, self.conf("night")["clahe_clip"], self.conf("night")["gamma"]) if night else frame
            h = self.conf("human")
            boxes, ms = self.ctx.detector.detect(img, conf=min(h["conf"], self.conf("vehicle")["conf"]), imgsz=h["imgsz"])
            with self.src_lock:
                rows = self.tracker.update(boxes, img)
            self.stats["infer_ms"] = round(ms, 1)
            self.analyze(frame, tracker_rows_to_dets(rows), t)
            self._rate(self._inf, "infer_fps", self.stats)
            if night and time.time() - self.last_night_cmp > 3:
                self.last_night_cmp = time.time()
                raw, _ = self.ctx.detector.detect(frame, conf=h["conf"], classes=[0])
                enh, _ = self.ctx.detector.detect(img, conf=h["conf"], classes=[0])
                self.stats["night_raw"], self.stats["night_enh"] = len(raw), len(enh)


class ReplayCamera(CameraWorker):
    def __init__(self, cfg, ctx, video, dets_path, kind):
        super().__init__(cfg, ctx)
        self.kind = kind
        self.video = video
        self.video_next = None
        with open(dets_path, encoding="utf-8") as f:
            data = json.load(f)
        self.frames = data["frames"]
        self.fps = float(data.get("fps") or 12)
        self.loop = 0
        self.source_label = data.get("label") or (
            "Recorded sample · real YOLOv8n + ByteTrack detections (precomputed, replayed in sync)" if kind == "recorded"
            else "Synthetic scene · generator ground-truth boxes")
        self.stats["status"] = "online"

    def run(self):
        cap = cv2.VideoCapture(self.video)
        i = 0
        next_t = time.time()
        while self.running:
            if self.video_next:
                cap.release()
                self.video, self.video_next = self.video_next, None
                cap = cv2.VideoCapture(self.video)
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, frame = cap.read()
            if not ok or i >= len(self.frames):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                i = 0
                self.loop += 1
                for tr in self.book.flush():
                    if tr.is_vehicle:
                        self._vehicle_done(tr, self.light.night)
                self.activity = ActivityEngine()
                continue
            off = (self.loop % 50) * 1000
            dets = [{"tid": int(r[4]) + off, "cls": int(r[6]), "name": CLASS_NAMES.get(int(r[6]), str(int(r[6]))),
                     "conf": float(r[5]), "box": [float(v) for v in r[:4]]} for r in self.frames[i]]
            t = time.time()
            self.publish_frame(frame)
            try:
                if i % 3 == 0:  # analytics at 1/3 of the clip rate (~4 Hz) keeps CPU free for live inference
                    self.analyze(frame, dets, t, synthetic=self.kind == "synthetic")
            except Exception as e:
                print(f"{self.id} analyze error:", repr(e))
            i += 1
            next_t += 1.0 / self.fps
            d = next_t - time.time()
            if d > 0:
                time.sleep(d)
            elif d < -1:
                next_t = time.time()


class MissingCamera(CameraWorker):
    """Placeholder when a source file hasn't been generated/downloaded yet."""

    def __init__(self, cfg, ctx, reason):
        super().__init__(cfg, ctx)
        self.kind = cfg.get("kind", "missing")
        self.stats["status"] = reason
        self.source_label = reason

    def run(self):
        img = np.full((360, 640, 3), (32, 27, 11), np.uint8)
        cv2.putText(img, "SOURCE NOT AVAILABLE", (150, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (51, 153, 255), 2, cv2.LINE_AA)
        cv2.putText(img, "run: python generate_assets.py", (170, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
        while self.running:
            self.publish_frame(img)
            time.sleep(1.0)
