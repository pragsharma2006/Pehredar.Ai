"""fetch_assets.py — one-time downloads so Pehredar.ai then runs fully offline.

    python fetch_assets.py

  data/videos/     real sample footage — Intel IoT DevKit sample-videos, CC-BY 4.0
                   (https://github.com/intel-iot-devkit/sample-videos)
  data/models/     OpenCV Zoo YuNet face detector + SFace face recogniser (ONNX)
  models/          yolov8m.pt (used offline to precompute detections on recorded clips)
  static/fonts/    Rajdhani (Latin + Devanagari), Inter, JetBrains Mono  (SIL OFL)
  static/vendor/   Chart.js 4 (MIT)
  ~/.cache         offline plate detector + OCR ONNX models (open-image-models / fast-plate-ocr)
"""
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}

VIDEOS = ["car-detection.mp4", "person-bicycle-car-detection.mp4", "face-demographics-walking.mp4",
          "people-detection.mp4", "one-by-one-person-detection.mp4"]
FILES = [(f"https://github.com/intel-iot-devkit/sample-videos/raw/master/{v}", f"data/videos/{v}") for v in VIDEOS] + [
    ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
     "data/models/face_detection_yunet_2023mar.onnx"),
    ("https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
     "data/models/face_recognition_sface_2021dec.onnx"),
    ("https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m.pt", "models/yolov8m.pt"),
    ("https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt", "models/yolov8n.pt"),
    ("https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js", "static/vendor/chart.umd.min.js"),
]
FONTS_CSS = ("https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700"
             "&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap")


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def fetch(url, rel):
    path = os.path.join(ROOT, rel)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print(f"  ok   {rel}")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print(f"  get  {rel} ...", end="", flush=True)
    data = get(url)
    with open(path, "wb") as f:
        f.write(data)
    print(f" {len(data) / 1e6:.1f} MB")


def fonts():
    out = os.path.join(ROOT, "static", "fonts")
    os.makedirs(out, exist_ok=True)
    css = get(FONTS_CSS).decode()
    for i, url in enumerate(sorted(set(re.findall(r"url\((https://[^)]+\.woff2)\)", css)))):
        name = f"f{i:02d}_" + url.rsplit("/", 1)[1]
        p = os.path.join(out, name)
        if not os.path.exists(p):
            with open(p, "wb") as f:
                f.write(get(url))
        css = css.replace(url, f"/static/fonts/{name}")
    with open(os.path.join(out, "fonts.css"), "w", encoding="utf-8") as f:
        f.write(css)
    print(f"  ok   static/fonts/fonts.css ({css.count('@font-face')} faces)")


def plate_models():
    from fast_plate_ocr import LicensePlateRecognizer
    from open_image_models import LicensePlateDetector
    LicensePlateDetector(detection_model="yolo-v9-s-608-license-plate-end2end", conf_thresh=0.35)
    LicensePlateRecognizer("cct-xs-v2-global-model", device="cpu")
    print("  ok   offline plate detector + OCR models cached")


def main():
    print("Downloading assets (one time) ...")
    failed = []
    for url, rel in FILES:
        try:
            fetch(url, rel)
        except Exception as e:
            failed.append(rel)
            print(f"\n  FAIL {rel}: {e}")
    for fn in (fonts, plate_models):
        try:
            fn()
        except Exception as e:
            failed.append(fn.__name__)
            print(f"  FAIL {fn.__name__}: {e}")
    if failed:
        print("Some downloads failed (the app degrades gracefully; rerun when online):", ", ".join(failed))
        sys.exit(1)
    print("Done. Next: python generate_assets.py")


if __name__ == "__main__":
    main()
