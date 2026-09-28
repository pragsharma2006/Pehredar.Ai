import copy
import json
import os
import threading
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
GEN = os.path.join(DATA, "generated")
VIDEOS = os.path.join(DATA, "videos")
ONNX = os.path.join(DATA, "models")
FACES_DIR = os.path.join(DATA, "faces")
MODELS = os.path.join(ROOT, "models")
UPLOADS = os.path.join(ROOT, "uploads")
EVENTS_DIR = os.path.join(ROOT, "events")
DB_PATH = os.path.join(ROOT, "events.db")
HISTORY_DB = os.path.join(GEN, "history.db")
SETTINGS_PATH = os.path.join(DATA, "settings.json")
ZONES_PATH = os.path.join(DATA, "zones.json")
WATCHLIST_PATH = os.path.join(DATA, "watchlist.json")
CAMERAS_PATH = os.path.join(DATA, "cameras.json")

for _d in (DATA, GEN, FACES_DIR, UPLOADS, EVENTS_DIR):
    os.makedirs(_d, exist_ok=True)

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    return datetime.now(IST)


def iso_ist(ts=None):
    dt = datetime.fromtimestamp(ts, IST) if ts is not None else now_ist()
    return dt.isoformat(timespec="milliseconds")


# Sources: "live" = real inference on a live/uploaded feed; "recorded" = real YOLO +
# ByteTrack detections precomputed once on real footage and replayed in sync;
# "synthetic" = generated scene, boxes are the generator's ground truth.
DEFAULT_CAMERAS = [
    {"id": "CAM-01", "name": "BOP Alpha Main Gate", "location": "Border Out Post Alpha", "gps": [31.6041, 74.5731],
     "link": "Fibre", "kind": "live", "source": "auto", "modules": ["human", "face", "fence", "activity", "night", "vehicle", "anpr"],
     "anpr_body": True,
     "restricted_post": True, "heavy_restricted": False, "in_vector": [0, 1]},
    {"id": "CAM-02", "name": "Check Post Bravo", "location": "Vehicle Check Post Bravo — ANPR lane", "gps": [31.6112, 74.5608],
     "link": "Fibre", "kind": "recorded", "source": "generated/checkpost_anpr.mp4", "modules": ["vehicle", "anpr"],
     "restricted_post": False, "heavy_restricted": False, "in_vector": [0, 1], "anpr_body": True, "anpr_min_area": 0.25},
    {"id": "CAM-03", "name": "Border Road Charlie", "location": "Patrol Road Charlie, km 14", "gps": [31.6187, 74.5402],
     "link": "4G", "kind": "recorded", "source": "videos/car-detection.mp4", "modules": ["vehicle", "anpr", "activity"],
     "restricted_post": False, "heavy_restricted": True, "in_vector": [0, 1]},
    {"id": "CAM-04", "name": "Watchtower Delta Fence Line", "location": "Watchtower Delta — Fence Line", "gps": [31.6239, 74.5301],
     "link": "Radio", "kind": "synthetic", "source": "generated/fence_line", "modules": ["human", "fence", "activity", "night"],
     "restricted_post": True, "heavy_restricted": False, "in_vector": [0, -1], "one_way": True, "flow": [1, 0],
     "variants": ["", "night"]},
    {"id": "CAM-05", "name": "Riverine Sector Echo", "location": "Riverine Sector Echo — Ravi bank", "gps": [31.6302, 74.5155],
     "link": "VSAT", "kind": "synthetic", "source": "generated/riverine_night", "modules": ["human", "night", "fence", "activity"],
     "restricted_post": True, "heavy_restricted": False, "in_vector": [1, 0], "display": "thermal"},
    {"id": "CAM-06", "name": "BOP Foxtrot Entry Corridor", "location": "BOP Foxtrot — Entry Corridor", "gps": [31.5978, 74.5822],
     "link": "Fibre", "kind": "recorded", "source": "videos/face-demographics-walking.mp4", "modules": ["human", "face"],
     "restricted_post": True, "heavy_restricted": False, "in_vector": [0, 1]},
    {"id": "CAM-07", "name": "Supply Route Golf", "location": "Supply Route Golf — depot yard", "gps": [31.5903, 74.5950],
     "link": "4G", "kind": "recorded", "source": "videos/person-bicycle-car-detection.mp4", "modules": ["human", "vehicle", "anpr", "activity"],
     "restricted_post": False, "heavy_restricted": False, "in_vector": [1, 0]},
    {"id": "CAM-08", "name": "Helipad Hotel", "location": "Helipad Hotel — Sector HQ", "gps": [31.5855, 74.6068],
     "link": "VSAT", "kind": "synthetic", "source": "generated/helipad", "modules": ["human", "vehicle", "fence", "activity", "night"],
     "restricted_post": True, "heavy_restricted": False, "in_vector": [0, 1]},
]

def _octagon(cx, cy, rx, ry, n=10):
    import math
    return [[round(cx + rx * math.cos(2 * math.pi * k / n), 4), round(cy + ry * math.sin(2 * math.pi * k / n), 4)] for k in range(n)]


# Normalised (0..1) zone geometry. The synthetic scenes in generate_assets.py are laid
# out against these same coordinates, so fences/rivers/helipads line up with the zones.
DEFAULT_ZONES = {
    "CAM-01": [
        {"id": "c01-count", "name": "Gate counting line", "type": "count", "points": [[0.05, 0.78], [0.95, 0.78]], "objects": "person"},
        {"id": "c01-armoury", "name": "Armoury door", "type": "restricted", "points": [[0.74, 0.5], [0.99, 0.5], [0.99, 0.99], [0.74, 0.99]], "objects": "person"},
    ],
    "CAM-04": [
        {"id": "c04-fence", "name": "Fence strip", "type": "restricted", "points": [[0, 0.505], [1, 0.505], [1, 0.57], [0, 0.57]]},
        {"id": "c04-buffer", "name": "Inner buffer", "type": "buffer", "points": [[0, 0.57], [1, 0.57], [1, 0.68], [0, 0.68]], "objects": "person"},
        {"id": "c04-gate", "name": "Patrol gate line", "type": "count", "points": [[0.5, 0.7], [0.5, 1.0]]},
    ],
    "CAM-05": [
        {"id": "c05-river", "name": "River channel", "type": "restricted", "points": [[0, 0.44], [1, 0.44], [1, 0.62], [0, 0.62]],
         "objects": "person", "schedule": "night"},
        {"id": "c05-bank", "name": "Near-bank tripwire", "type": "tripwire", "points": [[1, 0.645], [0, 0.645]],
         "direction": "forward", "objects": "person", "schedule": "night"},
    ],
    "CAM-06": [
        {"id": "c06-count", "name": "Corridor entry line", "type": "count", "points": [[0.05, 0.9], [0.95, 0.9]], "objects": "person"},
    ],
    "CAM-08": [
        {"id": "c08-pad", "name": "Helipad (no entry)", "type": "restricted", "points": _octagon(0.5, 0.62, 0.2, 0.14), "objects": "person"},
    ],
}

MODULES = {
    "human": {"name": "Human Tracking", "model": "YOLOv8n (COCO) + ByteTrack", "short": "YOLOv8n"},
    "vehicle": {"name": "Vehicle Detection", "model": "YOLOv8n (COCO) + ByteTrack + colour/speed", "short": "YOLOv8n"},
    "face": {"name": "Face Detection", "model": "OpenCV YuNet 2023mar + SFace 2021dec", "short": "YuNet"},
    "anpr": {"name": "ANPR", "model": "anpr_best.pt (YOLOv8l, 3-class) + YOLOv9-s plate det + CCT-XS OCR", "short": "ANPR"},
    "fence": {"name": "Virtual Fence", "model": "Zone engine (foot-point, direction-aware)", "short": "Zones"},
    "activity": {"name": "Suspicious Activity", "model": "Track behaviour rules + risk score", "short": "Rules"},
    "night": {"name": "Night Vision", "model": "Brightness EMA + CLAHE/gamma + MOG2", "short": "CLAHE"},
    "network": {"name": "Network Health", "model": "Adaptive streaming controller", "short": "ABR"},
}

DEFAULT_SETTINGS = {
    "operator": {"name": "Insp. R. Singh", "role": "Duty Officer, Sector Control", "id": "OP-0147"},
    "sector": "Punjab Frontier — Sector 7",
    "sound": True,
    "human": {"conf": 0.35, "crowd_threshold": 8, "imgsz": 480, "infer_every": 1},
    "vehicle": {"conf": 0.35, "stopped_seconds": 20, "m_per_px": 0.06},
    "face": {"det_conf": 0.8, "match_threshold": 0.40, "privacy_blur": True, "min_face_px": 40},
    "anpr": {"ocr_min_conf": 0.6, "plate_cooldown_s": 300, "min_crop_px": 90},
    "activity": {"loiter_seconds": 12, "run_speed_bh_s": 1.6, "group_size": 4, "group_radius_bh": 1.5,
                  "group_seconds": 6, "crawl_aspect": 1.15, "repeat_passes": 3, "abandon_seconds": 15},
    "night": {"mode": "auto", "enter_below": 55, "exit_above": 70, "gamma": 1.6, "clahe_clip": 3.0},
    "alerts": {"cooldown_s": 25, "banner": True},
    "network": {"adaptive": True},
    "integrations": {"webhook_url": ""},
}


def _deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    def __init__(self):
        self._lock = threading.Lock()
        saved = {}
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                saved = json.load(f)
        self.data = _deep_merge(DEFAULT_SETTINGS, saved)

    def get(self, section, key=None, default=None):
        sec = self.data.get(section, {})
        if key is None:
            return sec
        return sec.get(key, default) if isinstance(sec, dict) else default

    def update(self, patch):
        with self._lock:
            self.data = _deep_merge(self.data, patch)
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        return self.data


def load_cameras():
    """Built-in cameras come from DEFAULT_CAMERAS; cameras.json adds any onboarded RTSP/ONVIF ones."""
    cams = copy.deepcopy(DEFAULT_CAMERAS)
    ids = {c["id"] for c in cams}
    if os.path.exists(CAMERAS_PATH):
        with open(CAMERAS_PATH, encoding="utf-8") as f:
            cams += [c for c in json.load(f) if c["id"] not in ids]
    return cams


def save_cameras(cams):
    with open(CAMERAS_PATH, "w", encoding="utf-8") as f:
        json.dump(cams, f, indent=2, ensure_ascii=False)


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return copy.deepcopy(default)


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
