"""ANPR — merged from the standalone Anpr_system project (image_anpr.py).

Pipeline per vehicle track (one run per track, plus manual "Capture & Scan"):
  1. best frame of the track (largest x sharpest) -> vehicle crop
  2. body type: YOUR model, models/anpr_best.pt (YOLOv8l, classes SUV / compact / sedan,
     trained in Anpr_system) — same best-box logic as image_anpr.py
  3. plate: Plate Recognizer cloud API exactly as image_anpr.py did, when
     PLATE_RECOGNIZER_API_TOKEN is set; otherwise (or if the call fails) fully offline:
     YOLOv9-s plate detector (open-image-models) + CCT-XS OCR (fast-plate-ocr)
  4. Indian-format normalisation + regex validation, state decoded from the RTO code
  5. watchlist check (data/watchlist.json) -> event + Vehicle Registry
"""
import base64
import os
import queue
import re
import threading
import time
from collections import deque

import cv2
import numpy as np
import requests

from ..config import MODELS, WATCHLIST_PATH, load_json
from .bodytype import BodyTypeClient

STATES = {
    "AN": "Andaman & Nicobar", "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh", "AS": "Assam", "BR": "Bihar",
    "CG": "Chhattisgarh", "CH": "Chandigarh", "DD": "Daman & Diu", "DL": "Delhi", "DN": "Dadra & Nagar Haveli",
    "GA": "Goa", "GJ": "Gujarat", "HP": "Himachal Pradesh", "HR": "Haryana", "JH": "Jharkhand",
    "JK": "Jammu & Kashmir", "KA": "Karnataka", "KL": "Kerala", "LA": "Ladakh", "LD": "Lakshadweep",
    "MH": "Maharashtra", "ML": "Meghalaya", "MN": "Manipur", "MP": "Madhya Pradesh", "MZ": "Mizoram",
    "NL": "Nagaland", "OD": "Odisha", "OR": "Odisha", "PB": "Punjab", "PY": "Puducherry", "RJ": "Rajasthan",
    "SK": "Sikkim", "TN": "Tamil Nadu", "TR": "Tripura", "TS": "Telangana", "TG": "Telangana",
    "UK": "Uttarakhand", "UA": "Uttarakhand", "UP": "Uttar Pradesh", "WB": "West Bengal",
}
PLATE_RE = re.compile(r"^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{4})$")
BH_RE = re.compile(r"^(\d{2})(BH)(\d{4})([A-Z]{1,2})$")
# Only the classic OCR look-alike pairs. Wider maps (T->7, A->4 ...) can turn a truncated
# read into a valid-looking but wrong plate, which must go to manual review instead.
TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"}
TO_ALPHA = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G"}


def _subst(s, table):
    out, n = [], 0
    for c in s:
        r = table.get(c, c)
        n += r != c
        out.append(r)
    return "".join(out), n


def normalise_plate(raw):
    """Position-aware correction for Indian plates (e.g. letter O in a digit slot -> 0).
    Tries 1- and 2-digit RTO district codes and keeps the valid reading needing the
    fewest substitutions. Returns (plate, valid)."""
    t = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    if BH_RE.match(t):
        return t, True
    if len(t) < 7:
        return t, False
    head, n1 = _subst(t[:2], TO_ALPHA)
    tail, n2 = _subst(t[-4:], TO_DIGIT)
    mid = t[2:-4]
    cands = []
    for nd in (1, 2):
        if len(mid) < nd or len(mid) - nd > 3:
            continue
        d, n3 = _subst(mid[:nd], TO_DIGIT)
        s, n4 = _subst(mid[nd:], TO_ALPHA)
        cand = head + d + s + tail
        if PLATE_RE.match(cand) and head in STATES:
            cands.append((n1 + n2 + n3 + n4, -nd, cand))
    if cands:
        return min(cands)[2], True
    return t, False


def display_plate(p):
    m = PLATE_RE.match(p) or BH_RE.match(p)
    return " ".join(g for g in m.groups() if g) if m else p


def state_of(p):
    if BH_RE.match(p):
        return "Bharat series (national)"
    return STATES.get(p[:2], "Unknown")


def _b64(img, width=360):
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, int(h * width / w)))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return base64.b64encode(buf.tobytes()).decode() if ok else None


class PlateReader:
    CLOUD_URL = "https://api.platerecognizer.com/v1/plate-reader/"

    def __init__(self):
        from fast_plate_ocr import LicensePlateRecognizer
        from open_image_models import LicensePlateDetector
        self.token = os.environ.get("PLATE_RECOGNIZER_API_TOKEN", "").strip()
        self.det = LicensePlateDetector(detection_model="yolo-v9-s-608-license-plate-end2end", conf_thresh=0.35)
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        self.ocr = LicensePlateRecognizer("cct-xs-v2-global-model", device="cpu", sess_options=so)
        self.lock = threading.Lock()
        self.offline_name = "YOLOv9-s-608 plate detector + CCT-XS-v2 OCR (offline)"

    def read(self, img):
        if self.token:
            r = self._cloud(img)
            if r:
                return r
        return self._offline(img)

    def _cloud(self, img):
        ok, buf = cv2.imencode(".jpg", img)
        try:
            resp = requests.post(self.CLOUD_URL, files={"upload": ("frame.jpg", buf.tobytes())},
                                 headers={"Authorization": "Token " + self.token}, timeout=8)
            res = resp.json().get("results") or []
        except Exception as e:  # network down at a remote post -> offline fallback
            print("Plate Recognizer API error, using offline reader:", e)
            return None
        if not res:
            return None
        r0 = res[0]
        b = r0["box"]
        box = [b["xmin"], b["ymin"], b["xmax"], b["ymax"]]
        return {"raw": r0["plate"].upper(), "conf": float(r0.get("score", 0.9)), "det_conf": float(r0.get("dscore", 0.9)),
                "box": box, "source": "Plate Recognizer API (cloud)"}

    def _offline(self, img):
        with self.lock:
            dets = self.det.predict(img)
            if not dets:
                return None
            d = max(dets, key=lambda x: x.confidence)
            b = d.bounding_box
            best = None
            # tight crop first; if the read fails Indian-format validation (often a clipped
            # last character), retry with the plate box widened
            for pad in (0.0, 0.06, 0.12):
                pw, ph = b.x2 - b.x1, b.y2 - b.y1
                x1, y1 = max(0, int(b.x1 - pw * pad)), max(0, int(b.y1 - ph * pad))
                x2, y2 = min(img.shape[1], int(b.x2 + pw * pad)), min(img.shape[0], int(b.y2 + ph * pad))
                crop = img[y1:y2, x1:x2]
                if crop.size == 0:
                    continue
                pred = self.ocr.run(crop, return_confidence=True)[0]
                probs = np.asarray(pred.char_probs, np.float32)
                r = {"raw": pred.plate.replace("_", ""), "conf": float(probs.mean()) if probs.size else 0.0,
                     "min_char": float(probs.min()) if probs.size else 0.0, "det_conf": float(d.confidence),
                     "box": [x1, y1, x2, y2], "source": self.offline_name, "pad": pad}
                if best is None:
                    best = r
                if normalise_plate(r["raw"])[1]:
                    return r
        return best


class ANPRPipeline(threading.Thread):
    def __init__(self, store, bus, settings, device="cpu"):
        super().__init__(daemon=True, name="anpr")
        self.store, self.bus, self.settings, self.device = store, bus, settings, device
        self.q = queue.Queue(maxsize=16)
        self.body = BodyTypeClient(os.path.join(MODELS, "anpr_best.pt"), threads=2)
        self.body_names = {0: "SUV", 1: "compact", 2: "sedan"}
        self.plates = PlateReader()
        self.watchlist = {}
        self.reload_watchlist()
        self.recent = deque(maxlen=40)
        self.deliver = None
        self.stats = {"jobs": 0, "plates_read": 0, "valid": 0, "manual_review": 0, "no_plate": 0, "watch_hits": 0,
                      "dropped": 0, "skipped_small": 0, "ms_body": None, "ms_plate": None}
        self.busy = False

    def reload_watchlist(self):
        self.watchlist = {w["plate"]: w for w in load_json(WATCHLIST_PATH, [])}

    @property
    def plate_source(self):
        return "Plate Recognizer API (cloud) + offline fallback" if self.plates.token else self.plates.offline_name

    def submit(self, job):
        try:
            self.q.put_nowait(job)
            return True
        except queue.Full:
            self.stats["dropped"] += 1
            return False

    def run(self):
        while True:
            job = self.q.get()
            self.busy = True
            try:
                self._process(job)
            except Exception as e:
                print("ANPR job error:", repr(e))
            finally:
                self.busy = False

    def _stage(self, job, stage, **kw):
        self.bus.publish({"type": "anpr", "job": job["job_id"], "camera": job["camera"]["id"], "stage": stage, **kw})

    @staticmethod
    def _ema(old, new):
        return new if old is None else 0.8 * old + 0.2 * new

    def _body_type(self, crop):
        """Your model, your best-box logic (image_anpr.py), run in its own process."""
        best, conf, ms = self.body.classify(crop)
        if ms is not None:
            self.stats["ms_body"] = self._ema(self.stats["ms_body"], ms)
        return best, conf

    def _process(self, job):
        cfg = self.settings.get("anpr")
        cam, frame, box = job["camera"], job["frame"], job["box"]
        H, W = frame.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in box]
        px, py = int((x2 - x1) * 0.06), int((y2 - y1) * 0.06)
        x1, y1, x2, y2 = max(0, x1 - px), max(0, y1 - py), min(W, x2 + px), min(H, y2 + py)
        crop = frame[y1:y2, x1:x2].copy()
        self.stats["jobs"] += 1
        self._stage(job, "captured", crop=_b64(crop), vehicle=job.get("cls"), track=job.get("tid"))
        if min(crop.shape[:2]) < cfg["min_crop_px"] and not job.get("manual"):
            self.stats["skipped_small"] += 1
            self._stage(job, "skipped", reason=f"vehicle only {crop.shape[1]}x{crop.shape[0]} px — too small for a plate read at this range")
            return

        body, body_conf = (None, 0.0)
        if job.get("cls") in ("car", "truck", None) and job.get("body", True):
            self._stage(job, "classifying")
            body, body_conf = self._body_type(crop)

        self._stage(job, "reading")
        work = crop if crop.shape[1] >= 360 else cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        scale = work.shape[1] / crop.shape[1]
        t0 = time.perf_counter()
        pr = self.plates.read(work)
        self.stats["ms_plate"] = self._ema(self.stats["ms_plate"], (time.perf_counter() - t0) * 1000)

        result = {"job": job["job_id"], "camera": cam["id"], "track": job.get("tid"), "vehicle": job.get("cls"),
                  "body_type": body, "body_conf": round(body_conf, 3), "colour": job.get("colour"),
                  "direction": job.get("direction"), "speed_kmh": job.get("speed"), "ts": time.time(), "manual": job.get("manual", False)}
        if pr and (len(re.sub(r"[^A-Z0-9]", "", pr["raw"].upper())) < 6 or pr["det_conf"] < 0.5):
            pr = None  # junk read (tiny/oblique plate) — treat as no readable plate, not a manual-review event
        if not pr:
            self.stats["no_plate"] += 1
            result.update(status="no_plate", plate=None)
            self._finish(job, result, crop, None)
            return

        self.stats["plates_read"] += 1
        plate, valid = normalise_plate(pr["raw"])
        low = pr["conf"] < cfg["ocr_min_conf"]
        pb = [int(v / scale) for v in pr["box"]]
        plate_crop = crop[max(0, pb[1]):pb[3], max(0, pb[0]):pb[2]].copy()
        watch = self.watchlist.get(plate) if valid else None
        status = "watchlist" if watch else ("valid" if valid and not low else "manual_review")
        self.stats["valid" if status == "valid" else "watch_hits" if watch else "manual_review"] += 1
        result.update(status=status, plate=plate, plate_display=display_plate(plate) if valid else plate,
                      raw=pr["raw"], ocr_conf=round(pr["conf"], 3), plate_det_conf=round(pr["det_conf"], 3),
                      state=state_of(plate) if valid else "—", valid=valid, ocr_source=pr["source"],
                      watch_reason=watch.get("reason") if watch else None)
        self._stage(job, "plate", plate=result["plate_display"], plate_crop=_b64(plate_crop, 240), status=status)

        if not job.get("manual") and not self.store.cooldown_ok(("plate", plate), cfg["plate_cooldown_s"]):
            result["status_note"] = "same plate seen recently — not re-logged"
            self._finish(job, result, crop, plate_crop)
            return

        # snapshot: full frame, vehicle + plate boxes, zoomed plate inset
        snap = frame.copy()
        col = (57, 57, 229) if watch else (8, 136, 19) if status == "valid" else (53, 216, 253)
        cv2.rectangle(snap, (x1, y1), (x2, y2), col, 3)
        gx1, gy1 = x1 + pb[0], y1 + pb[1]
        cv2.rectangle(snap, (gx1, gy1), (x1 + pb[2], y1 + pb[3]), (255, 255, 255), 2)
        label = f"{result['plate_display']}  {body or job.get('cls') or ''}".strip()
        cv2.putText(snap, label, (x1, max(22, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2, cv2.LINE_AA)
        if plate_crop.size:
            inset = cv2.resize(plate_crop, (min(W // 3, 320), int(min(W // 3, 320) * plate_crop.shape[0] / max(plate_crop.shape[1], 1))))
            ih, iw = inset.shape[:2]
            if ih < H // 2:
                snap[8:8 + ih, 8:8 + iw] = inset
                cv2.rectangle(snap, (6, 6), (10 + iw, 10 + ih), col, 2)

        if watch:
            name, sev = "Watchlisted Vehicle Detected", "critical"
        elif status == "valid":
            name, sev = "Vehicle Plate Read", "info"
        else:
            name, sev = "Plate Read — Manual Review", "medium"
        desc = (f"{result['plate_display']} ({result['state']}) · {job.get('colour') or ''} {body or job.get('cls') or 'vehicle'}"
                f" · {job.get('direction') or ''} · OCR {pr['conf']:.0%}")
        if watch:
            desc += f" · WATCHLIST: {watch.get('reason')}"
        if status == "manual_review":
            desc += " · low confidence / invalid format — manual review"
        extra = {k: result.get(k) for k in ("plate", "plate_display", "raw", "state", "valid", "ocr_conf", "plate_det_conf",
                                            "ocr_source", "body_type", "body_conf", "colour", "direction", "speed_kmh",
                                            "vehicle", "watch_reason", "manual")}
        extra["body_model"] = "anpr_best.pt (YOLOv8l, Anpr_system)" if body else None
        kwargs = dict(event_name=name, module="anpr", severity=sev, camera=cam, frame=snap, description=desc,
                      alert_type="ANPR — Watchlist" if watch else "ANPR",
                      model_used=(f"anpr_best.pt + {pr['source']}" if body else pr["source"]),
                      confidence=pr["conf"], track_id=job.get("tid"), extra=extra, ts=job.get("ts"),
                      night=job.get("night", False), crops={"vehicle": crop, "plate": plate_crop})
        ev = self.deliver(cam["id"], kwargs) if self.deliver else self.store.log(**kwargs)
        result["event_id"] = ev["event_id"] if ev else None
        if ev is None:
            result["status_note"] = "link offline — queued at edge node"
        if valid:
            self.store.upsert_vehicle(plate, result["plate_display"], result["state"], job.get("cls") or "vehicle", body,
                                      job.get("colour"), cam["id"], result["event_id"], bool(watch),
                                      watch.get("reason") if watch else None, ev["extra"].get("vehicle_img") if ev else None,
                                      job.get("direction"), time.time())
        self._finish(job, result, crop, plate_crop)

    def _finish(self, job, result, crop, plate_crop):
        result["crop"] = _b64(crop)
        result["plate_crop"] = _b64(plate_crop, 240) if plate_crop is not None and plate_crop.size else None
        self.recent.appendleft({k: v for k, v in result.items()})
        self._stage(job, "done", result=result)
