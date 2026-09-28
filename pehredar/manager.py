import os
import platform
import sys
import time
from collections import deque
from datetime import datetime

import cv2
import torch

from . import VERSION
from .bus import Bus
from .cameras import LiveCamera, MissingCamera, ReplayCamera
from .config import (CAMERAS_PATH, DB_PATH, DEFAULT_CAMERAS, DEFAULT_ZONES, EVENTS_DIR, GEN, HISTORY_DB, IST, MODELS, MODULES,
                     ROOT, Settings, load_cameras, save_json)
from .engine.anpr import ANPRPipeline
from .engine.detector import SharedDetector, pick_device
from .engine.faces import FaceEngine
from .engine.zones import ZoneEngine
from .events import EventStore
from .network import NetworkSim


class Context:
    pass


def _resolve(cfg):
    """Map a camera's configured source to (video, detections-json) for replay cameras."""
    src = cfg["source"]
    if cfg["kind"] == "synthetic":
        name = src.split("/", 1)[1]
        variant = cfg.get("variant")
        video = os.path.join(GEN, "scenes", f"{name}{'_' + variant if variant else ''}.mp4")
        return video, os.path.join(GEN, "scenes", f"{name}.gt.json")
    rel = src.split("/", 1)
    base = os.path.splitext(rel[1])[0]
    video = os.path.join(GEN, rel[1]) if rel[0] == "generated" else os.path.join(ROOT, "data", src)
    return video, os.path.join(GEN, "cache", f"{base}.dets.json")


class Manager:
    def __init__(self):
        torch.set_num_threads(2)  # live YOLO runs in its own process; little torch work here
        c = self.ctx = Context()
        c.settings = Settings()
        c.bus = Bus()
        c.store = EventStore(DB_PATH, EVENTS_DIR, c.bus, c.settings)
        c.history = EventStore(HISTORY_DB, os.path.join(GEN, "history_snaps"), readonly=True) if os.path.exists(HISTORY_DB) else None
        c.device, c.device_label = pick_device()
        c.detector = SharedDetector(os.path.join(MODELS, "yolov8n.pt"), c.device)
        c.faces = FaceEngine(c.settings.get("face", "det_conf"))
        c.zones = ZoneEngine(DEFAULT_ZONES)
        self.cams = load_cameras()
        c.network = NetworkSim(self.cams, c.store, c.bus, c.settings)
        c.network.snapshot_fn = self._net_snapshot
        c.anpr = ANPRPipeline(c.store, c.bus, c.settings, c.device)
        c.anpr.deliver = c.network.deliver
        c.toggles = {m: True for m in MODULES}
        c.vehicle_feed = deque(maxlen=80)
        self.workers = {}
        for cfg in self.cams:
            self.workers[cfg["id"]] = self._make(cfg)
        self.started = time.time()

    def _make(self, cfg):
        c = self.ctx
        if cfg["kind"] == "live":
            return LiveCamera(cfg, c)
        video, dets = _resolve(cfg)
        if not os.path.exists(video) or not os.path.exists(dets):
            return MissingCamera(cfg, c, f"source missing: {os.path.relpath(video, ROOT)} — run generate_assets.py")
        return ReplayCamera(cfg, c, video, dets, cfg["kind"])

    def start(self):
        self.ctx.network.start()
        self.ctx.anpr.start()
        for w in self.workers.values():
            w.start()

    def add_camera(self, cfg):
        self.cams.append(cfg)
        extra = [x for x in self.cams if x["id"] not in {d["id"] for d in DEFAULT_CAMERAS}]
        save_json(CAMERAS_PATH, extra)
        self.ctx.network.add_camera(cfg)
        w = self.workers[cfg["id"]] = self._make(cfg)
        w.start()
        return w

    def set_variant(self, cam_id, variant):
        w = self.workers[cam_id]
        cfg = w.cfg
        if cfg["kind"] != "synthetic":
            raise ValueError("variants exist for synthetic scenes only")
        cfg["variant"] = variant or None
        video, _ = _resolve(cfg)
        if not os.path.exists(video):
            raise ValueError("variant not generated")
        w.video_next = video

    def _net_snapshot(self, cam_id, label):
        w = self.workers.get(cam_id)
        img = w.render(snapshot=True) if w else None
        if img is None:
            return None
        img = img.copy()
        h, wd = img.shape[:2]
        cv2.rectangle(img, (0, 0), (wd, 34), (30, 30, 30), -1)
        cv2.putText(img, f"NETWORK: {label}", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (51, 153, 255), 2, cv2.LINE_AA)
        return img

    # ------------------------------------------------------------------ status
    def midnight(self):
        now = datetime.now(IST)
        return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def kpis(self):
        c = self.ctx.store.counts_since(self.midnight())
        net = self.ctx.network.snapshot()
        online = sum(1 for cid, w in self.workers.items() if net.get(cid, {}).get("online", True)
                     and not str(w.stats.get("status", "")).startswith(("source missing", "cannot", "NO SIGNAL")))
        faces = sum(v for k, v in c["by_name"].items() if "Face" in k or "Unregistered" in k)
        intr = sum(v for k, v in c["by_name"].items() if k.startswith(("Fence Breach", "Buffer Zone")))
        return {"people_now": sum(w.stats["people"] for w in self.workers.values()),
                "vehicles_today": c["vehicles"], "plates_today": c["plates"], "faces_today": faces,
                "intrusions_today": intr, "active_alerts": c["active_alerts"],
                "avg_response_s": round(c["avg_response_s"], 1) if c["avg_response_s"] else None,
                "cameras_online": online, "cameras_total": len(self.workers), "events_total": c["total"]}

    def models(self):
        out = {}
        ws = list(self.workers.values())
        a = self.ctx.anpr
        for key, meta in MODULES.items():
            cams = [w for w in ws if key in w.cfg.get("modules", [])] if key != "network" else ws
            fps = [w.stats["analysis_fps"] for w in cams if w.stats.get("analysis_fps")]
            ms = {"human": self.ctx.detector.ms_avg, "vehicle": self.ctx.detector.ms_avg, "face": self.ctx.faces.ms_avg,
                  "anpr": a.stats["ms_plate"]}.get(key)
            src = sorted({("live inference" if w.kind == "live" else "recorded sample set" if w.kind == "recorded" else
                           "synthetic scene (ground truth)") for w in cams})
            if key == "network":
                src = ["simulated link telemetry (adaptation applied for real)"]
            if key == "anpr":
                src = [f"{s} → real plate OCR" for s in src]
            out[key] = {"key": key, **meta, "enabled": self.ctx.toggles.get(key, True), "running": any(w.is_alive() for w in cams),
                        "fps": round(sum(fps) / len(fps), 1) if fps else 0, "ms": round(ms, 1) if ms else None,
                        "cameras": [w.id for w in cams], "sources": src}
        out["face"]["available"] = self.ctx.faces.available
        out["anpr"]["plate_source"] = a.plate_source
        out["anpr"]["stats"] = a.stats
        return out

    def system_info(self):
        import ultralytics
        a = self.ctx.anpr
        return {
            "version": VERSION, "python": sys.version.split()[0], "platform": platform.platform(),
            "device": self.ctx.device_label, "torch": torch.__version__, "opencv": cv2.__version__,
            "ultralytics": ultralytics.__version__, "uptime_s": round(time.time() - self.started),
            "models": [
                {"module": "Human / Vehicle (live)", "model": "YOLOv8n COCO (models/yolov8n.pt) + ByteTrack per camera", "device": self.ctx.device},
                {"module": "Human / Vehicle (recorded clips)", "model": "YOLOv8m COCO + ByteTrack, precomputed once by generate_assets.py", "device": "offline"},
                {"module": "ANPR body type", "model": "anpr_best.pt — YOLOv8l, 3 classes (SUV/compact/sedan), trained in Anpr_system", "device": "cpu (separate process)"},
                {"module": "ANPR plate", "model": a.plate_source, "device": "cpu"},
                {"module": "Face detection", "model": self.ctx.faces.detector_name, "device": "cpu"},
                {"module": "Face recognition", "model": self.ctx.faces.recognizer_name, "device": "cpu"},
                {"module": "Night", "model": "Brightness EMA + hysteresis, CLAHE + gamma, OpenCV MOG2", "device": "cpu"},
            ],
            "sources": [{"camera": w.id, "name": w.cfg["name"], "kind": w.kind, "source": w.source_label} for w in self.workers.values()],
            "data_sources": {
                "Human Tracking": "live inference on CAM-01; recorded clips replay real YOLOv8m detections; synthetic scenes use ground truth",
                "Vehicle Detection": "recorded sample set (real detections, precomputed) + live CAM-01; colour/direction/speed computed live",
                "ANPR": "real — your anpr_best.pt + real plate OCR on every vehicle crop; composited border-state plates on CAM-02 are rendered",
                "Face Detection": "live inference (YuNet+SFace) on CAM-01 and on the recorded CAM-06 clip; registry illustrations have no templates",
                "Virtual Fence": "real zone engine on live, recorded and synthetic tracks",
                "Suspicious Activity": "real rules over tracks; synthetic scenes are scripted to exercise each behaviour",
                "Night Vision": "real brightness / CLAHE / MOG2 on every feed; CAM-05 is a synthetic night scene",
                "Network Health": "SIMULATED link telemetry; adaptation, metadata-only mode and edge buffering are applied for real",
                "Analytics history": "optional 7-day SAMPLE history (generated, flagged) in data/generated/history.db",
            },
        }
