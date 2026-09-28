"""
anpr.py
Real ANPR module — replaces simulators.VehicleSimulator with actual inference,
wired into the same EventLogger pipeline (SQLite + snapshot + SHA-256 hash
chain) as every other module, so it shows up identically in the dashboard,
event log and tamper-evidence chain.

Model provenance: models/anpr_best.pt is a YOLOv8 model trained in the
standalone Anpr_system project (custom-trained, 3 classes: SUV / compact /
sedan) and only copied in here — training code/data live in that project.

Two real stages, same as the source project's image_anpr.py:
  1. Vehicle-type detection — local YOLO inference (models/anpr_best.pt).
     Always real, no API key needed.
  2. Plate OCR — cloud call to Plate Recognizer (api.platerecognizer.com).
     The custom YOLO model was never trained to localize plates, so this
     stage needs PLATE_RECOGNIZER_API_TOKEN set in the environment. Without
     it, vehicle-type detection still runs for real and events still log,
     just with the plate read marked NOT-READ instead of fabricated.
"""
import os
import time
import random
import threading

import cv2
import requests
from ultralytics import YOLO

BASE_DIR = os.path.dirname(__file__)
MODEL_PATH = os.path.join(BASE_DIR, "models", "anpr_best.pt")

PLATE_API_TOKEN = os.environ.get("PLATE_RECOGNIZER_API_TOKEN", "")
PLATE_API_URL = "https://api.platerecognizer.com/v1/plate-reader/"

# Kept in sync with simulators.py's sample watchlist so the two modules
# agree on what counts as a hit.
WATCHLIST_PLATES = {"PB10XX4521", "RJ14YY9087", "JK01ZZ2233"}

COLOR_GREEN = (50, 190, 90)
COLOR_RED = (40, 40, 230)


class ANPRProcessor(threading.Thread):
    """
    Real vehicle-type detection (custom YOLOv8) + optional real plate OCR
    (Plate Recognizer API). Runs as a background thread pulling frames from
    a video source, same shape as simulators.VehicleSimulator so it drops
    into app.py without touching the dashboard/event-log code.
    """

    def __init__(self, logger, video_path, camera_id="CAM-02", interval_range=(9, 19), conf_threshold=0.4):
        super().__init__(daemon=True)
        self.logger = logger
        self.camera_id = camera_id
        self.interval_range = interval_range
        self.conf_threshold = conf_threshold
        self.running = True
        self.latest = None

        self.model = YOLO(MODEL_PATH)
        self.cap = cv2.VideoCapture(video_path) if video_path and os.path.exists(video_path) else None

    def run(self):
        while self.running:
            time.sleep(random.uniform(*self.interval_range))
            try:
                self._fire()
            except Exception as e:
                print("ANPR error:", e)

    def stop(self):
        self.running = False

    # ---- frame source ---------------------------------------------------
    def _read_frame(self):
        if self.cap is None or not self.cap.isOpened():
            return None
        ok, frame = self.cap.read()
        if not ok:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
        return frame if ok else None

    # ---- stage 1: real local vehicle-type detection ----------------------
    def _detect_vehicle(self, frame):
        """Best-confidence box + class name from the real YOLO model."""
        results = self.model(frame, verbose=False)
        best_box, best_conf, vehicle_class = None, 0.0, None
        for r in results:
            if r.boxes is None or len(r.boxes) == 0:
                continue
            boxes = r.boxes.xyxy.cpu().numpy()
            classes = r.boxes.cls.cpu().numpy()
            scores = r.boxes.conf.cpu().numpy()
            for box, cls, conf in zip(boxes, classes, scores):
                if conf > best_conf and conf >= self.conf_threshold:
                    best_conf, best_box = float(conf), box
                    vehicle_class = self.model.names[int(cls)]
        return best_box, vehicle_class, best_conf

    # ---- stage 2: real cloud plate OCR (optional) -------------------------
    def _ocr_plate(self, frame):
        """Returns (plate_text, (x1,y1,x2,y2)) or (None, None)."""
        if not PLATE_API_TOKEN:
            return None, None
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            return None, None
        try:
            resp = requests.post(
                PLATE_API_URL,
                files={"upload": ("frame.jpg", buf.tobytes())},
                headers={"Authorization": "Token " + PLATE_API_TOKEN},
                timeout=8,
            )
            data = resp.json()
            results = data.get("results") or []
            if results:
                r0 = results[0]
                plate = r0["plate"].upper()
                b = r0["box"]
                return plate, (b["xmin"], b["ymin"], b["xmax"], b["ymax"])
        except Exception as e:
            print("Plate Recognizer API error:", e)
        return None, None

    # ---- one detection pass -------------------------------------------------
    def _fire(self):
        frame = self._read_frame()
        if frame is None:
            return

        best_box, vehicle_class, conf = self._detect_vehicle(frame)
        if best_box is None:
            return  # no real detection this pass — don't fabricate an event

        annotated = frame.copy()
        x1, y1, x2, y2 = map(int, best_box)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), COLOR_GREEN, 3)
        cv2.putText(annotated, vehicle_class.upper(), (x1 + 8, max(y1 - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, COLOR_GREEN, 2, cv2.LINE_AA)

        plate_text, plate_box = self._ocr_plate(frame)
        flagged = bool(plate_text and plate_text in WATCHLIST_PLATES)

        if plate_text and plate_box:
            px1, py1, px2, py2 = map(int, plate_box)
            box_color = COLOR_RED if flagged else COLOR_GREEN
            cv2.rectangle(annotated, (px1, py1), (px2, py2), box_color, 3)
            cv2.putText(annotated, plate_text, (px1, max(py1 - 10, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, box_color, 2, cv2.LINE_AA)

        # NOTE: description format is parsed by the dashboard's
        # parseVehicleDesc() regex in templates/index.html — keep the
        # "<word> <type> · ANPR plate <plate> · <int>% confidence" shape.
        plate_label = plate_text or "NOT-READ"
        conf_pct = int(round(conf * 100))
        event_type = "Watchlist Alert" if flagged else "Vehicle Detected"
        desc = (f"Vehicle {vehicle_class} · ANPR plate {plate_label} · {conf_pct}% confidence"
                + (" · MATCHED WATCHLIST ENTRY" if flagged else " · no flags on record"))

        ev = self.logger.log(event_type, None, desc, annotated, False,
                              camera_id=self.camera_id, module="vehicle")
        self.latest = {**ev, "vehicle_type": vehicle_class, "plate": plate_text,
                        "confidence": conf_pct, "flagged": flagged}
