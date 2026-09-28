"""
simulators.py
Hardcoded-but-real-looking modules for the parts of the IBVAP spec that are
out of scope for a from-scratch model in this prototype: ANPR, vehicle
classification, and face recognition. These do NOT run inference — they
draw a stylised "detection card" (bounding-box style crop with a plate/ID
readout) from sample data pools and push it through the exact same
EventLogger pipeline (SQLite + snapshot + SHA-256 hash chain) that the real
YOLO human-tracking path uses, so the logging/alerting/evidence system
behind them is genuine even though the detections are scripted.

Camera feeds CAM-02..CAM-04 are also simulated here: they loop the bundled
demo clip and draw a scripted, slowly-moving bounding box over it so the
camera grid never looks static.
"""
import os
import time
import math
import random
import threading

import cv2
import numpy as np

BASE_DIR = os.path.dirname(__file__)

# ---------------------------------------------------------------------------
# Sample data pools
# ---------------------------------------------------------------------------
VEHICLE_TYPES = ["Sedan Car", "SUV", "Pickup Truck", "Heavy Truck", "Motorcycle", "Mini Tempo", "Tractor-Trailer"]
VEHICLE_COLORS = ["White", "Black", "Silver", "Red", "Blue", "Grey", "Beige"]
STATE_CODES = ["PB", "RJ", "GJ", "JK", "WB", "AS", "PB", "RJ"]  # weighted toward common land-border states

WATCHLIST_PLATES = {"PB10XX4521", "RJ14YY9087", "JK01ZZ2233"}

FACE_LABELS_CLEAR = ["Unregistered Visitor", "Local Resident", "BSF Patrol Personnel", "Unregistered Visitor"]
WATCHLIST_SUSPECTS = ["SUSPECT-A213", "SUSPECT-B067", "SUSPECT-C118"]

# BGR colors (OpenCV order)
COLOR_GREEN = (50, 190, 90)
COLOR_SAFFRON = (30, 140, 255)
COLOR_RED = (40, 40, 230)
COLOR_NAVY = (140, 70, 20)
COLOR_BG = (24, 18, 14)


def random_plate():
    state = random.choice(STATE_CODES)
    district = random.randint(1, 99)
    series = "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(2))
    number = random.randint(1, 9999)
    return f"{state}{district:02d}{series}{number:04d}"


def _corner_brackets(img, color, margin=10, size=22, thickness=2):
    h, w = img.shape[:2]
    pts = [
        [(margin, margin + size), (margin, margin), (margin + size, margin)],
        [(w - margin - size, margin), (w - margin, margin), (w - margin, margin + size)],
        [(margin, h - margin - size), (margin, h - margin), (margin + size, h - margin)],
        [(w - margin - size, h - margin), (w - margin, h - margin), (w - margin, h - margin - size)],
    ]
    for p1, p2, p3 in pts:
        cv2.line(img, p1, p2, color, thickness)
        cv2.line(img, p2, p3, color, thickness)


def draw_detection_card(kind, headline, subline, badge_text, badge_color, w=360, h=260):
    """Stylised detection crop: dark ground, targeting-style corner brackets,
    a bounding box for the subject silhouette, and text readout — used as
    the 'snapshot' for hardcoded ANPR / vehicle / face events."""
    img = np.full((h, w, 3), COLOR_BG, dtype=np.uint8)

    box_color = badge_color
    if kind == "vehicle":
        bx1, by1, bx2, by2 = int(w * 0.14), int(h * 0.32), int(w * 0.86), int(h * 0.74)
        cv2.rectangle(img, (bx1, by1), (bx2, by2), box_color, 2)
        cv2.rectangle(img, (bx1 + 14, by1 + 10), (bx1 + 46, by1 + 26), box_color, 1)  # windshield hint
        cv2.circle(img, (bx1 + 20, by2), 8, box_color, 2)
        cv2.circle(img, (bx2 - 20, by2), 8, box_color, 2)
    else:  # face
        cx, cy = w // 2, int(h * 0.44)
        cv2.circle(img, (cx, cy), int(h * 0.16), box_color, 2)
        cv2.ellipse(img, (cx, int(h * 0.86)), (int(w * 0.22), int(h * 0.22)), 0, 180, 360, box_color, 2)
        bx1, by1, bx2, by2 = int(w * 0.24), int(h * 0.16), int(w * 0.76), int(h * 0.95)
        cv2.rectangle(img, (bx1, by1), (bx2, by2), box_color, 1)

    _corner_brackets(img, box_color)

    # badge (top-right)
    (tw, th), _ = cv2.getTextSize(badge_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
    cv2.rectangle(img, (w - tw - 26, 8), (w - 8, 8 + th + 12), badge_color, -1)
    cv2.putText(img, badge_text, (w - tw - 18, 8 + th + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

    # readout footer
    cv2.rectangle(img, (0, h - 46), (w, h), (14, 12, 10), -1)
    cv2.putText(img, headline, (10, h - 26), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (240, 240, 240), 2)
    cv2.putText(img, subline, (10, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (170, 170, 170), 1)

    ts = time.strftime("%d-%m-%Y %H:%M:%S")
    cv2.putText(img, ts, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 150, 150), 1)
    return img


# ---------------------------------------------------------------------------
# Background simulators — log into the shared EventLogger + hash chain
# ---------------------------------------------------------------------------
class VehicleSimulator(threading.Thread):
    def __init__(self, logger, camera_id="CAM-02", interval_range=(9, 19)):
        super().__init__(daemon=True)
        self.logger = logger
        self.camera_id = camera_id
        self.interval_range = interval_range
        self.running = True
        self.latest = None

    def run(self):
        while self.running:
            time.sleep(random.uniform(*self.interval_range))
            try:
                self._fire()
            except Exception:
                pass

    def _fire(self):
        vtype = random.choice(VEHICLE_TYPES)
        color = random.choice(VEHICLE_COLORS)
        plate = random.choice(list(WATCHLIST_PLATES)) if random.random() < 0.16 else random_plate()
        flagged = plate in WATCHLIST_PLATES
        confidence = random.randint(88, 99)

        event_type = "Watchlist Alert" if flagged else "Vehicle Detected"
        badge = "WATCHLIST HIT" if flagged else "CLEARED"
        badge_color = COLOR_RED if flagged else COLOR_GREEN
        desc = (f"{color} {vtype} · ANPR plate {plate} · {confidence}% confidence"
                + (" · MATCHED WATCHLIST ENTRY" if flagged else " · no flags on record"))

        card = draw_detection_card("vehicle", plate, f"{color} {vtype}  ·  {confidence}% match", badge, badge_color)
        ev = self.logger.log(event_type, None, desc, card, False, camera_id=self.camera_id, module="vehicle")
        self.latest = {**ev, "vehicle_type": vtype, "color": color, "plate": plate,
                        "confidence": confidence, "flagged": flagged}

    def stop(self):
        self.running = False


class FaceSimulator(threading.Thread):
    def __init__(self, logger, camera_id="CAM-04", interval_range=(11, 24)):
        super().__init__(daemon=True)
        self.logger = logger
        self.camera_id = camera_id
        self.interval_range = interval_range
        self.running = True
        self.latest = None

    def run(self):
        while self.running:
            time.sleep(random.uniform(*self.interval_range))
            try:
                self._fire()
            except Exception:
                pass

    def _fire(self):
        flagged = random.random() < 0.14
        confidence = random.randint(82, 98)
        if flagged:
            suspect = random.choice(WATCHLIST_SUSPECTS)
            event_type = "Face Watchlist Match"
            badge, badge_color = "WATCHLIST", COLOR_RED
            headline, sub = suspect, f"{confidence}% match confidence"
            desc = f"Face match against watchlist — {suspect} ({confidence}% confidence)"
        else:
            label = random.choice(FACE_LABELS_CLEAR)
            event_type = "Face Detected"
            badge, badge_color = "NO MATCH", COLOR_SAFFRON
            headline, sub = label, f"{confidence}% detection confidence"
            desc = f"Face detected — {label}, no watchlist match ({confidence}% confidence)"

        card = draw_detection_card("face", headline, sub, badge, badge_color)
        ev = self.logger.log(event_type, None, desc, card, False, camera_id=self.camera_id, module="face")
        self.latest = {**ev, "confidence": confidence, "flagged": flagged}

    def stop(self):
        self.running = False


# ---------------------------------------------------------------------------
# Simulated camera feeds (CAM-02..CAM-04): real demo footage, scripted overlay
# ---------------------------------------------------------------------------
class SimulatedCamera:
    def __init__(self, label, video_path, seed=0):
        self.label = label
        self.video_path = video_path
        self.cap = cv2.VideoCapture(video_path) if video_path and os.path.exists(video_path) else None
        self.seed = seed
        self.t0 = time.time()

    def _read_frame(self):
        if self.cap is not None and self.cap.isOpened():
            ok, frame = self.cap.read()
            if not ok:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self.cap.read()
            if ok:
                return frame
        return np.full((360, 640, 3), (16, 20, 24), dtype=np.uint8)

    def _annotate(self, frame):
        h, w = frame.shape[:2]
        t = (time.time() - self.t0) * 0.5 + self.seed * 12.0
        cx = w * 0.5 + w * 0.28 * math.sin(t * 0.35)
        cy = h * 0.55 + h * 0.18 * math.cos(t * 0.27)
        bw, bh = w * 0.11, h * 0.30
        x1, y1, x2, y2 = int(cx - bw / 2), int(cy - bh / 2), int(cx + bw / 2), int(cy + bh / 2)
        cycle = int(t // 7) % 3
        label = ["PERSON", "VEHICLE", "PERSON"][cycle]
        color = COLOR_GREEN if label == "PERSON" else COLOR_SAFFRON
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, max(y1 - 8, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        cv2.rectangle(frame, (0, 0), (w, 24), (18, 16, 14), -1)
        cv2.putText(frame, f"{self.label}  |  AI ANALYTICS ACTIVE  |  REC",
                    (8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 220, 160), 1)
        return frame

    def mjpeg_generator(self):
        while True:
            frame = cv2.resize(self._read_frame(), (640, 360))
            frame = self._annotate(frame)
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
            time.sleep(0.08)
