import multiprocessing as mp
import platform
import threading
import time

import numpy as np
import torch
import ultralytics
from ultralytics.engine.results import Boxes
from ultralytics.trackers.byte_tracker import BYTETracker
from ultralytics.utils import IterableSimpleNamespace

PERSON = 0
VEHICLES = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
OBJECTS = {24: "backpack", 26: "handbag", 28: "suitcase"}
TRACK_CLASSES = [PERSON] + list(VEHICLES) + list(OBJECTS)
CLASS_NAMES = {PERSON: "person", **VEHICLES, **OBJECTS}


def pick_device():
    if torch.cuda.is_available():
        return "cuda:0", f"GPU · {torch.cuda.get_device_name(0)}"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps", "GPU · Apple MPS"
    import os
    return "cpu", f"CPU · {platform.processor() or platform.machine()} ({os.cpu_count()} logical cores)"


def new_tracker(fps=15):
    args = IterableSimpleNamespace(tracker_type="bytetrack", track_high_thresh=0.3, track_low_thresh=0.1,
                                   new_track_thresh=0.35, track_buffer=max(30, int(fps * 2)), match_thresh=0.8,
                                   fuse_score=True)
    return BYTETracker(args)


def tracker_rows_to_dets(rows):
    """BYTETracker output rows [x1,y1,x2,y2,track_id,score,cls,idx] -> det dicts."""
    out = []
    for r in rows:
        cls = int(r[6])
        out.append({"tid": int(r[4]), "cls": cls, "name": CLASS_NAMES.get(cls, str(cls)), "conf": float(r[5]),
                    "box": [float(r[0]), float(r[1]), float(r[2]), float(r[3])]})
    return out


class SharedDetector:
    """One YOLO instance shared by every live camera, running in its OWN PROCESS: the main
    process is GIL-bound by 8 camera pipelines + streaming, which starved in-process
    inference (measured 100 ms standalone -> >10 s per frame under dashboard load).
    Each camera keeps its own BYTETracker in the main process so IDs never mix."""

    def __init__(self, weights, device, imgsz=640, threads=3):
        ctx = mp.get_context("spawn")
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=_detector_proc, args=(child, weights, device, threads),
                                daemon=True, name="yolo-live")
        self.proc.start()
        self.device = device
        self.imgsz = imgsz
        self.lock = threading.Lock()
        self.version = f"YOLOv8n (COCO) · ultralytics {ultralytics.__version__}"
        self.ms_avg = None
        self.ids = 0
        self.conn.recv()  # wait for model load + warm-up

    def detect(self, frame, conf=0.3, classes=TRACK_CLASSES, imgsz=None):
        with self.lock:
            self.ids += 1
            jid = self.ids
            self.conn.send((jid, frame, conf, list(classes), imgsz or self.imgsz))
            rid, data, shape, ms = self.conn.recv()
        self.ms_avg = ms if self.ms_avg is None else 0.9 * self.ms_avg + 0.1 * ms
        return Boxes(data, shape).numpy(), ms


def _detector_proc(conn, weights, device, threads):
    import torch
    torch.set_num_threads(threads)
    from ultralytics import YOLO as _YOLO
    m = _YOLO(weights)
    m.predict(np.zeros((640, 640, 3), np.uint8), verbose=False, device=device)
    conn.send("ready")
    while True:
        jid, frame, conf, classes, imgsz = conn.recv()
        t0 = time.perf_counter()
        r = m.predict(frame, conf=conf, classes=classes, imgsz=imgsz, device=device, verbose=False)[0]
        conn.send((jid, r.boxes.data.cpu().numpy(), frame.shape[:2], (time.perf_counter() - t0) * 1000))
