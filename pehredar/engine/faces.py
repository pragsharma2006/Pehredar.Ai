"""Face detection (OpenCV YuNet) + recognition (OpenCV SFace), both small ONNX models
that run on CPU. Matching is cosine similarity against enrolled embeddings; sample
registry entries that are only illustrations carry no embedding and can never match."""
import os
import threading
import time
import uuid

import cv2
import numpy as np

from ..config import DATA, FACES_DIR, ONNX, iso_ist, load_json, save_json

REGISTRY_PATH = os.path.join(FACES_DIR, "registry.json")
CATEGORIES = ["Authorised Personnel", "Local Resident", "Unregistered Visitor", "Watchlist"]
YUNET = os.path.join(ONNX, "face_detection_yunet_2023mar.onnx")
SFACE = os.path.join(ONNX, "face_recognition_sface_2021dec.onnx")


class FaceEngine:
    detector_name = "OpenCV YuNet (face_detection_yunet_2023mar)"
    recognizer_name = "OpenCV SFace (face_recognition_sface_2021dec)"

    def __init__(self, det_conf=0.8):
        self.available = os.path.exists(YUNET) and os.path.exists(SFACE)
        self.lock = threading.Lock()
        self.reg_lock = threading.Lock()
        self.registry = load_json(REGISTRY_PATH, [])
        self.ms_avg = None
        if self.available:
            self.det = cv2.FaceDetectorYN.create(YUNET, "", (320, 320), det_conf, 0.3, 50)
            self.rec = cv2.FaceRecognizerSF.create(SFACE, "")

    def detect(self, frame):
        if not self.available:
            return []
        h, w = frame.shape[:2]
        scale = 1.0
        if w > 960:
            scale = 960 / w
            frame = cv2.resize(frame, (960, int(h * scale)))
        with self.lock:
            t0 = time.perf_counter()
            self.det.setInputSize((frame.shape[1], frame.shape[0]))
            _, faces = self.det.detect(frame)
            ms = (time.perf_counter() - t0) * 1000
        self.ms_avg = ms if self.ms_avg is None else 0.9 * self.ms_avg + 0.1 * ms
        out = []
        for f in faces if faces is not None else []:
            row = f.copy()
            row[:14] /= scale
            x, y, fw, fh = row[:4]
            out.append({"box": [float(x), float(y), float(x + fw), float(y + fh)], "score": float(row[14]), "row": row})
        return out

    @staticmethod
    def quality(frame, face):
        x1, y1, x2, y2 = [int(v) for v in face["box"]]
        crop = frame[max(0, y1):y2, max(0, x1):x2]
        if crop.size == 0:
            return 0.0, 0.0
        sharp = cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        size_s = min(1.0, (y2 - y1) / 110.0)
        sharp_s = min(1.0, sharp / 120.0)
        return round(0.55 * size_s + 0.45 * sharp_s, 3), float(sharp)

    def embed(self, frame, face):
        with self.lock:
            aligned = self.rec.alignCrop(frame, face["row"])
            feat = self.rec.feature(aligned)
        v = feat.flatten().astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-9), aligned

    def match(self, emb, threshold):
        best, best_s = None, -1.0
        with self.reg_lock:
            for e in self.registry:
                if not e.get("embedding"):
                    continue
                s = float(np.dot(emb, np.asarray(e["embedding"], np.float32)))
                if s > best_s:
                    best, best_s = e, s
        if best is not None and best_s >= threshold:
            return best, best_s
        return None, best_s

    # ------------------------------------------------------------------ registry
    def entries(self):
        with self.reg_lock:
            return [{k: v for k, v in e.items() if k != "embedding"} | {"has_template": True}
                    for e in self.registry if e.get("embedding")]

    def enroll(self, frame, face, name, category):
        emb, aligned = self.embed(frame, face)
        eid = "FACE-" + uuid.uuid4().hex[:6].upper()
        img = f"{eid}.jpg"
        cv2.imwrite(os.path.join(FACES_DIR, img), aligned)
        entry = {"id": eid, "name": name, "category": category, "embedding": [round(float(x), 6) for x in emb],
                 "image": f"faces/{img}", "enrolled_at": iso_ist(), "source": "live enrolment", "matches": []}
        with self.reg_lock:
            self.registry.append(entry)
            save_json(REGISTRY_PATH, self.registry)
        return {k: v for k, v in entry.items() if k != "embedding"}

    def remove(self, eid):
        with self.reg_lock:
            self.registry = [e for e in self.registry if e["id"] != eid]
            save_json(REGISTRY_PATH, self.registry)

    def record_match(self, eid, camera_id, score, event_id):
        with self.reg_lock:
            for e in self.registry:
                if e["id"] == eid:
                    e.setdefault("matches", []).insert(0, {"ts": iso_ist(), "camera": camera_id,
                                                          "score": round(score, 3), "event_id": event_id})
                    e["matches"] = e["matches"][:50]
                    e["last_seen"] = iso_ist()
            save_json(REGISTRY_PATH, self.registry)
