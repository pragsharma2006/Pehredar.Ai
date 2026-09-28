"""generate_assets.py — recreates every generated asset and sample data file in one command.

    python generate_assets.py            # everything
    python generate_assets.py --only scenes,plates

Outputs (data/generated/ unless noted):
  scenes/  fence_line(.mp4, _night.mp4, .gt.json), riverine_night, helipad — 1280x720 @12fps
           animated border scenes; *.gt.json = the generator's ground-truth boxes per frame
  checkpost_anpr.mp4 (+ cache/checkpost_anpr.dets.json) — CAM-02 ANPR lane built from the
           real vehicle photos in data/anpr_test/ (original plates + rendered border-state plates)
  cache/*.dets.json — REAL YOLOv8n + ByteTrack detections precomputed on the recorded clips
  plates/  rendered Indian number plates (+ plates on vehicle sprites) — ANPR test images
  sprites/ vehicle sprites; avatars/ illustrated faces (registry display only)
  history.db + history_snaps/ — 7 days of SAMPLE events (flagged synthetic) for Analytics
  static/img/ logo.svg, chakra.svg, contours.svg, sector_map.svg
  data/ watchlist.json, cameras.json, zones.json, operators.json, network_links.json,
        faces/registry.json (sample illustration entries, no biometric templates)
"""
import argparse
import glob
import json
import math
import os
import random
import shutil
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from pehredar.config import (CAMERAS_PATH, DATA, DEFAULT_CAMERAS, DEFAULT_ZONES, FACES_DIR, GEN, HISTORY_DB,  # noqa: E402
                             MODELS, VIDEOS, WATCHLIST_PATH, ZONES_PATH, save_json)

W, H, FPS = 1280, 720, 12
STATIC_IMG = os.path.join(ROOT, "static", "img")
ANPR_TEST = os.path.join(DATA, "anpr_test")
DEFAULT_ANPR_SRC = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "Anpr_system", "Anpr_system")
for d in ("scenes", "cache", "plates", "sprites", "avatars", "history_snaps"):
    os.makedirs(os.path.join(GEN, d), exist_ok=True)
os.makedirs(STATIC_IMG, exist_ok=True)
rng = np.random.default_rng(7)
random.seed(7)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def font(size, bold=True):
    names = (["bahnschrift.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["bahnschrift.ttf", "arial.ttf", "DejaVuSans.ttf"])
    dirs = [os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"), "/usr/share/fonts/truetype/dejavu", "/Library/Fonts"]
    try:
        import matplotlib
        dirs.append(os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf"))
    except ImportError:
        pass
    for n in names:
        for d in dirs:
            p = os.path.join(d, n)
            if os.path.exists(p):
                f = ImageFont.truetype(p, size)
                if n == "bahnschrift.ttf":
                    try:
                        f.set_variation_by_name("Bold SemiCondensed" if bold else "SemiCondensed")
                    except Exception:
                        pass
                return f
    return ImageFont.load_default()


# ============================================================================ plates
def render_plate(text, w=520, h=112, commercial=False):
    """Indian HSRP-style plate: white (private) / yellow (commercial), black border,
    blue 'IND' strip. No hologram or emblem."""
    img = Image.new("RGB", (w, h), (250, 204, 20) if commercial else (248, 248, 246))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, w - 3, h - 3], radius=int(h * 0.1), outline=(18, 18, 18), width=max(3, h // 22))
    sw = int(w * 0.085)
    d.rectangle([8, 8, 8 + sw, h - 9], fill=(22, 62, 160))
    d.text((8 + sw / 2, h * 0.76), "IND", fill="white", font=font(int(h * 0.2)), anchor="mm")
    size = int(h * 0.74)
    avail = w - sw - 34
    while size > 10:
        f = font(size)
        if d.textlength(text, font=f) <= avail:
            break
        size -= 2
    d.text((8 + sw + (w - 8 - sw) / 2, h / 2 + 2), text, fill=(12, 12, 12), font=f, anchor="mm")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


PLATE_SET = [("PB 10 XX 4521", False), ("JK 01 ZZ 2233", False), ("RJ 14 YY 9087", False), ("GJ 12 AB 3456", False),
             ("PB 65 MK 7788", False), ("JK 02 CD 1122", False), ("PB 08 DK 4410", True), ("RJ 19 GA 2071", True),
             ("GJ 18 BT 6603", False), ("WB 24 AK 9121", False), ("AS 01 BC 7002", True), ("22 BH 4567 AA", False)]


def draw_vehicle_sprite(kind, colour, w=420):
    """Rear view vehicle sprite with a plate bay; returns BGR image and plate rect."""
    h = int(w * 0.72)
    img = np.full((h, w, 3), (205, 208, 210), np.uint8)
    c = tuple(int(v) for v in colour)
    dark = tuple(int(v * 0.55) for v in c)
    if kind == "truck":
        cv2.rectangle(img, (int(w * .08), int(h * .05)), (int(w * .92), int(h * .78)), c, -1)
        cv2.rectangle(img, (int(w * .08), int(h * .05)), (int(w * .92), int(h * .78)), dark, 3)
        for i in range(5):
            x = int(w * (.16 + i * .17))
            cv2.line(img, (x, int(h * .08)), (x, int(h * .75)), dark, 2)
    else:
        top = int(h * (.08 if kind == "suv" else .16))
        cv2.rectangle(img, (int(w * .1), int(h * .38)), (int(w * .9), int(h * .8)), c, -1)
        pts = np.array([[int(w * .18), int(h * .4)], [int(w * .28), top], [int(w * .72), top], [int(w * .82), int(h * .4)]], np.int32)
        cv2.fillPoly(img, [pts], c)
        cv2.fillPoly(img, [np.array([[int(w * .24), int(h * .38)], [int(w * .32), top + 10], [int(w * .68), top + 10], [int(w * .76), int(h * .38)]], np.int32)], (70, 60, 55))
        cv2.rectangle(img, (int(w * .12), int(h * .45)), (int(w * .24), int(h * .54)), (40, 40, 200), -1)
        cv2.rectangle(img, (int(w * .76), int(h * .45)), (int(w * .88), int(h * .54)), (40, 40, 200), -1)
    for x in (int(w * .2), int(w * .8)):
        cv2.ellipse(img, (x, int(h * .84)), (int(w * .08), int(h * .1)), 0, 0, 360, (25, 25, 25), -1)
    plate = (int(w * .33), int(h * .58), int(w * .67), int(h * .72))
    return img, plate


def gen_plates():
    out = os.path.join(GEN, "plates")
    manifest = []
    colours = [(200, 200, 200), (40, 40, 40), (30, 30, 170), (150, 90, 30), (240, 240, 240), (60, 120, 60)]
    for i, (txt, com) in enumerate(PLATE_SET):
        p = render_plate(txt, commercial=com)
        name = f"plate_{txt.replace(' ', '')}.png"
        cv2.imwrite(os.path.join(out, name), p)
        kind = ["car", "suv", "truck"][i % 3]
        spr, (x1, y1, x2, y2) = draw_vehicle_sprite(kind, colours[i % len(colours)])
        spr[y1:y2, x1:x2] = cv2.resize(p, (x2 - x1, y2 - y1), interpolation=cv2.INTER_AREA)
        sname = f"sprite_{kind}_{txt.replace(' ', '')}.png"
        cv2.imwrite(os.path.join(out, sname), spr)
        manifest.append({"plate": txt.replace(" ", ""), "display": txt, "commercial": com, "plate_image": name, "on_sprite": sname})
    save_json(os.path.join(out, "manifest.json"), manifest)
    for kind, col in (("car", (40, 40, 180)), ("suv", (220, 220, 220)), ("truck", (30, 110, 170)), ("jeep", (60, 90, 70))):
        spr, _ = draw_vehicle_sprite("suv" if kind == "jeep" else kind, col, 300)
        cv2.imwrite(os.path.join(GEN, "sprites", f"{kind}.png"), spr)
    log(f"plates: {len(manifest)} rendered plates + vehicle sprites")


# ============================================================================ avatars
AVATARS = [("SAMPLE-01", "HC Gurmeet Singh (illustration)", "Authorised Personnel", "turban", (68, 108, 150), True),
           ("SAMPLE-02", "Const. Neha Rawat (illustration)", "Authorised Personnel", "cap", (95, 140, 190), False),
           ("SAMPLE-03", "SI Arvind Kumar (illustration)", "Authorised Personnel", "cap", (80, 120, 165), True),
           ("SAMPLE-04", "Village Sarpanch (illustration)", "Local Resident", "turban", (70, 110, 160), True),
           ("SAMPLE-05", "Farm worker (illustration)", "Local Resident", "short", (60, 95, 140), False),
           ("SAMPLE-06", "Supply contractor (illustration)", "Unregistered Visitor", "short", (85, 130, 175), False),
           ("SAMPLE-07", "Visitor (illustration)", "Unregistered Visitor", "long", (100, 150, 200), False),
           ("SAMPLE-08", "WL-0417 (sample illustration)", "Watchlist", "cap", (60, 100, 140), True),
           ("SAMPLE-09", "WL-0522 (sample illustration)", "Watchlist", "short", (75, 115, 160), False)]


def draw_avatar(style, skin, beard, cat, size=256):
    bg = {"Authorised Personnel": (19, 136, 8), "Local Resident": (255, 153, 51), "Unregistered Visitor": (90, 110, 140), "Watchlist": (229, 57, 53)}[cat]
    img = Image.new("RGB", (size, size), (18, 27, 46))
    d = ImageDraw.Draw(img)
    d.ellipse([10, 10, size - 10, size - 10], fill=tuple(int(v * 0.35) for v in bg), outline=bg, width=5)
    s = tuple(int(v) for v in skin[::-1])
    uniform = (60, 80, 50) if cat == "Authorised Personnel" else (70, 70, 90) if cat == "Watchlist" else (120, 100, 80)
    d.pieslice([48, 170, size - 48, 330], 180, 360, fill=uniform)
    d.rectangle([108, 150, 148, 185], fill=s)
    d.ellipse([78, 62, 178, 176], fill=s)
    hair = (30, 25, 22)
    if style == "turban":
        d.pieslice([70, 40, 186, 130], 180, 360, fill=(230, 120, 30) if cat != "Watchlist" else (40, 50, 120))
        d.rectangle([72, 82, 184, 100], fill=(230, 120, 30) if cat != "Watchlist" else (40, 50, 120))
    elif style == "cap":
        d.pieslice([74, 44, 182, 128], 180, 360, fill=(50, 70, 45))
        d.rectangle([66, 84, 150, 94], fill=(40, 55, 35))
    elif style == "long":
        d.pieslice([72, 52, 184, 140], 180, 360, fill=hair)
        d.rectangle([72, 96, 90, 170], fill=hair)
        d.rectangle([166, 96, 184, 170], fill=hair)
    else:
        d.pieslice([76, 54, 180, 128], 180, 360, fill=hair)
    for ex in (108, 148):
        d.ellipse([ex - 7, 110, ex + 7, 120], fill=(250, 250, 250))
        d.ellipse([ex - 3, 112, ex + 3, 118], fill=(30, 30, 30))
    d.arc([112, 132, 144, 152], 20, 160, fill=(90, 50, 40), width=3)
    if beard:
        d.chord([86, 120, 170, 182], 10, 170, fill=hair)
        d.arc([112, 134, 144, 150], 20, 160, fill=(200, 160, 140), width=2)
    return img


def gen_avatars():
    reg_path = os.path.join(FACES_DIR, "registry.json")
    reg = json.load(open(reg_path, encoding="utf-8")) if os.path.exists(reg_path) else []
    reg = [e for e in reg if not e["id"].startswith("SAMPLE-")]
    for eid, name, cat, style, skin, beard in AVATARS:
        fn = f"{eid}.png"
        draw_avatar(style, skin, beard, cat).save(os.path.join(GEN, "avatars", fn))
        reg.append({"id": eid, "name": name, "category": cat, "embedding": None, "image": f"generated/avatars/{fn}",
                    "enrolled_at": "2026-09-01T09:00:00.000+05:30", "source": "sample illustration — no biometric template, cannot match",
                    "matches": []})
    save_json(reg_path, reg)
    log(f"avatars: {len(AVATARS)} illustrated registry entries")


# ============================================================================ svg graphics
def gen_svgs():
    spokes = "".join(
        f'<line x1="50" y1="50" x2="{50 + 40 * math.cos(math.radians(i * 15)):.2f}" y2="{50 + 40 * math.sin(math.radians(i * 15)):.2f}"/>'
        for i in range(24))
    chakra = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><g fill="none" stroke="#000080" stroke-width="2.2">'
              f'<circle cx="50" cy="50" r="44"/><circle cx="50" cy="50" r="40" stroke-width="1"/>{spokes}</g>'
              f'<circle cx="50" cy="50" r="7" fill="#000080"/></svg>')
    open(os.path.join(STATIC_IMG, "chakra.svg"), "w", encoding="utf-8").write(chakra)
    logo = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">'
            '<path d="M60 6 L108 24 V60 C108 88 86 106 60 114 C34 106 12 88 12 60 V24 Z" fill="#121B2E" stroke="#FF9933" stroke-width="5"/>'
            '<path d="M60 16 L98 30 V60 C98 82 81 97 60 104 C39 97 22 82 22 60 V30 Z" fill="none" stroke="#138808" stroke-width="3"/>'
            f'<g transform="translate(30 30) scale(0.6)"><g fill="none" stroke="#FFFFFF" stroke-width="3">'
            f'<circle cx="50" cy="50" r="42"/>{spokes}</g><circle cx="50" cy="50" r="8" fill="#FFFFFF"/></g></svg>')
    open(os.path.join(STATIC_IMG, "logo.svg"), "w", encoding="utf-8").write(logo)
    # topographic contour pattern: isolines of a smooth random field
    yy, xx = np.mgrid[0:300, 0:800].astype(np.float32)
    field = sum(np.sin(xx / s1 + p1) * np.cos(yy / s2 + p2) for s1, s2, p1, p2 in
                [(90, 70, 0.3, 1.2), (47, 61, 2.1, 0.4), (130, 45, 1.1, 2.7), (33, 88, 0.7, 1.9)])
    field = cv2.GaussianBlur(field, (0, 0), 6)
    field = ((field - field.min()) / (field.max() - field.min()) * 255).astype(np.uint8)
    paths = []
    for lvl in range(20, 240, 18):
        cnts, _ = cv2.findContours((field > lvl).astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_TC89_KCOS)
        for c in cnts:
            if len(c) > 12:
                pts = " ".join(f"{p[0][0]},{p[0][1]}" for p in c[::2])
                paths.append(f'<polyline points="{pts}"/>')
    open(os.path.join(STATIC_IMG, "contours.svg"), "w", encoding="utf-8").write(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 300" preserveAspectRatio="xMidYMid slice">'
        f'<g fill="none" stroke="#FF9933" stroke-opacity="0.13" stroke-width="1">{"".join(paths)}</g></svg>')
    gen_sector_map()
    log("svg: chakra loader, logo, contour pattern, sector map")


LAT0, LAT1, LON0, LON1 = 31.575, 31.640, 74.500, 74.620


def proj(lat, lon, w=1000, h=700):
    return (lon - LON0) / (LON1 - LON0) * w, (LAT1 - lat) / (LAT1 - LAT0) * h


def gen_sector_map():
    w, h = 1000, 700
    g = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="Rajdhani, Arial, sans-serif">',
         f'<rect width="{w}" height="{h}" fill="#0E1729"/>']
    for x in range(0, w, 50):
        g.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{h}" stroke="#1F2A44" stroke-width="1"/>')
    for y in range(0, h, 50):
        g.append(f'<line x1="0" y1="{y}" x2="{w}" y2="{y}" stroke="#1F2A44" stroke-width="1"/>')
    g.append('<path d="M-10 60 C120 90 180 40 300 90 S470 150 560 110 S760 60 1010 120" fill="none" stroke="#1E5A8A" stroke-width="26" stroke-opacity="0.55"/>')
    g.append('<text x="610" y="96" fill="#5DA9E9" font-size="16" letter-spacing="3">RIVER RAVI (schematic)</text>')
    g.append('<path d="M-10 170 C140 150 220 120 330 150 S520 190 640 160 S840 130 1010 150" fill="none" stroke="#FF9933" stroke-width="3" stroke-dasharray="14 8"/>')
    g.append('<text x="20" y="140" fill="#FF9933" font-size="15" letter-spacing="2">INTERNATIONAL BORDER — SCHEMATIC, NOT TO SCALE</text>')
    g.append('<path d="M-10 196 C140 176 220 146 330 176 S520 216 640 186 S840 156 1010 176" fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-opacity="0.5"/>')
    g.append('<text x="700" y="210" fill="#9FB3C8" font-size="12">border fence</text>')
    for a, b in [((31.604, 74.573), (31.611, 74.561)), ((31.611, 74.561), (31.619, 74.540)), ((31.619, 74.540), (31.624, 74.530)),
                 ((31.604, 74.573), (31.598, 74.582)), ((31.598, 74.582), (31.590, 74.595)), ((31.590, 74.595), (31.5855, 74.607))]:
        (x1, y1), (x2, y2) = proj(*a), proj(*b)
        g.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#6B7A90" stroke-width="5" stroke-linecap="round"/>')
    g.append('<text x="40" y="660" fill="#6B7A90" font-size="13">— patrol / supply road</text>')
    for name, lat, lon in (("BOP ALPHA", 31.6041, 74.5731), ("BOP FOXTROT", 31.5978, 74.5822), ("SECTOR HQ", 31.5855, 74.6068)):
        x, y = proj(lat, lon)
        g.append(f'<rect x="{x - 9:.0f}" y="{y - 9:.0f}" width="18" height="18" fill="#138808" stroke="#FFFFFF" stroke-width="2" transform="rotate(45 {x:.0f} {y:.0f})"/>')
        g.append(f'<text x="{x + 16:.0f}" y="{y + 26:.0f}" fill="#E6EDF3" font-size="14" font-weight="700">{name}</text>')
    g.append('<g transform="translate(940 620)"><circle r="26" fill="none" stroke="#6B7A90"/><path d="M0 -22 L7 4 L0 0 L-7 4 Z" fill="#FF9933"/>'
             '<text y="-30" text-anchor="middle" fill="#E6EDF3" font-size="14">N</text></g>')
    g.append("</svg>")
    open(os.path.join(STATIC_IMG, "sector_map.svg"), "w", encoding="utf-8").write("".join(g))


# ============================================================================ scene sprites
def person(img, fx, fy, h, body, legs, phase=0.0, pose="walk", skin=(90, 120, 160), lw=None):
    h = max(12, h)
    lw = lw or max(2, int(h * 0.075))
    if pose == "crawl":
        cy = int(fy - h * 0.12)
        cv2.ellipse(img, (int(fx), cy), (int(h * 0.42), int(h * 0.1)), 0, 0, 360, body, -1, cv2.LINE_AA)
        cv2.circle(img, (int(fx + h * 0.48), cy - int(h * 0.04)), int(h * 0.085), skin, -1, cv2.LINE_AA)
        for k in (-1, 1):
            cv2.line(img, (int(fx + k * h * 0.2), cy), (int(fx + k * h * 0.3 + math.sin(phase) * h * 0.06), int(fy)), legs, lw, cv2.LINE_AA)
        return [fx - h * 0.46, fy - h * 0.25, fx + h * 0.58, fy]
    r = h * 0.085
    head = (int(fx), int(fy - h + r))
    hip = fy - h * 0.46
    sw = math.sin(phase) * h * 0.13 if pose == "walk" else math.sin(phase * 0.3) * h * 0.015
    cv2.line(img, (int(fx), int(hip)), (int(fx + sw), int(fy)), legs, lw + 1, cv2.LINE_AA)
    cv2.line(img, (int(fx), int(hip)), (int(fx - sw), int(fy)), legs, lw + 1, cv2.LINE_AA)
    top = fy - h + 2 * r
    cv2.rectangle(img, (int(fx - h * 0.12), int(top)), (int(fx + h * 0.12), int(hip + h * 0.04)), body, -1)
    cv2.line(img, (int(fx - h * 0.12), int(top + h * 0.03)), (int(fx - h * 0.14 - sw * 0.6), int(hip + h * 0.02)), body, lw, cv2.LINE_AA)
    cv2.line(img, (int(fx + h * 0.12), int(top + h * 0.03)), (int(fx + h * 0.14 + sw * 0.6), int(hip + h * 0.02)), body, lw, cv2.LINE_AA)
    cv2.circle(img, head, int(r * 1.05), skin, -1, cv2.LINE_AA)
    return [fx - h * 0.17, fy - h, fx + h * 0.17, fy]


def jeep(img, fx, fy, w, colour, facing=1):
    h = w * 0.5
    x0, x1 = fx - w / 2, fx + w / 2
    cv2.rectangle(img, (int(x0), int(fy - h * 0.62)), (int(x1), int(fy - h * 0.18)), colour, -1)
    cab = (int(fx - facing * w * 0.05), int(fy - h), int(fx + facing * w * 0.3), int(fy - h * 0.6))
    cv2.rectangle(img, (min(cab[0], cab[2]), cab[1]), (max(cab[0], cab[2]), cab[3]), colour, -1)
    cv2.rectangle(img, (min(cab[0], cab[2]) + 4, cab[1] + 4), (max(cab[0], cab[2]) - 4, cab[3] - 2), (70, 60, 55), -1)
    for x in (x0 + w * 0.2, x1 - w * 0.2):
        cv2.circle(img, (int(x), int(fy - h * 0.16)), int(h * 0.17), (20, 20, 20), -1, cv2.LINE_AA)
        cv2.circle(img, (int(x), int(fy - h * 0.16)), int(h * 0.07), (120, 120, 120), -1, cv2.LINE_AA)
    return [x0, fy - h, x1, fy]


def bag(img, fx, fy, s):
    cv2.rectangle(img, (int(fx - s * 0.5), int(fy - s)), (int(fx + s * 0.5), int(fy)), (30, 60, 90), -1)
    cv2.rectangle(img, (int(fx - s * 0.3), int(fy - s * 1.25)), (int(fx + s * 0.3), int(fy - s * 0.95)), (20, 40, 60), 2)
    return [fx - s * 0.5, fy - s * 1.25, fx + s * 0.5, fy]


class Actor:
    """Keyframed actor: keys = [(t, x_norm, y_norm, pose), ...]; height from perspective."""

    def __init__(self, tid, cls, keys, kind="person", colour=((60, 80, 120), (50, 50, 60)), size=1.0):
        self.tid, self.cls, self.keys, self.kind, self.colour, self.size = tid, cls, keys, kind, colour, size
        self.dist = 0.0
        self.prev = None

    def at(self, t):
        k = self.keys
        if t < k[0][0] or t > k[-1][0]:
            return None
        for a, b in zip(k, k[1:]):
            if a[0] <= t <= b[0]:
                u = (t - a[0]) / max(b[0] - a[0], 1e-6)
                return a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u, a[3], (b[1] != a[1] or b[2] != a[2])
        return k[-1][1], k[-1][2], k[-1][3], False


def render_scene(name, bg_fn, actors, dur, persp, post_fn=None, dynamic_fn=None, night_variant=None):
    n = int(dur * FPS)
    bg = bg_fn()
    out = os.path.join(GEN, "scenes", f"{name}.mp4")
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    vw_n = cv2.VideoWriter(os.path.join(GEN, "scenes", f"{name}_night.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H)) if night_variant else None
    frames = []
    for f in range(n):
        t = f / FPS
        img = bg.copy()
        if dynamic_fn:
            dynamic_fn(img, t)
        states = []
        for a in actors:
            s = a.at(t)
            if s is None:
                continue
            x, y, pose, moving = s
            states.append((y, a, x, pose, moving))
        gt = []
        for y, a, x, pose, moving in sorted(states, key=lambda s: s[0]):
            fx, fy = x * W, y * H
            hpx = persp(y) * a.size
            if a.kind == "person":
                phase = t * 7.0 + a.tid if moving else t
                box = person(img, fx, fy, hpx, a.colour[0], a.colour[1], phase, pose)
            elif a.kind == "vehicle":
                box = jeep(img, fx, fy, hpx * 1.9, a.colour[0], 1 if pose != "left" else -1)
            else:
                box = bag(img, fx, fy, hpx * 0.18)
            x1, y1, x2, y2 = max(0, box[0]), max(0, box[1]), min(W - 1, box[2]), min(H - 1, box[3])
            if (x2 - x1) * (y2 - y1) > 60:
                gt.append([round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1), a.tid, 1.0, a.cls])
        frames.append(gt)
        if post_fn:
            img = post_fn(img, t)
        img = np.clip(img.astype(np.int16) + rng.normal(0, 4, img.shape).astype(np.int16), 0, 255).astype(np.uint8)
        vw.write(img)
        if vw_n:
            vw_n.write(night_variant(img))
    vw.release()
    if vw_n:
        vw_n.release()
    save_json(os.path.join(GEN, "scenes", f"{name}.gt.json"),
              {"fps": FPS, "frames": frames, "source": "ground truth from generate_assets.py",
               "label": f"Synthetic scene ({name}) · generator ground-truth boxes"})
    log(f"scene {name}: {n} frames, {sum(len(f) for f in frames)} GT boxes" + (" (+ night variant)" if night_variant else ""))


def grad(top, bottom, h):
    t = np.linspace(0, 1, h)[:, None, None]
    return (np.array(top)[None, None] * (1 - t) + np.array(bottom)[None, None] * t)


def texture(h, w, base, amp, blur=3):
    n = rng.normal(0, 1, (h, w, 1)).astype(np.float32)
    n = cv2.GaussianBlur(n, (0, 0), blur)[..., None] if n.ndim == 3 else n
    n = n / (np.abs(n).max() + 1e-6)
    return np.clip(np.array(base, np.float32)[None, None] + n * amp, 0, 255)


def hills(img, y0, y1, colour, seed):
    r = np.random.default_rng(seed)
    xs = np.arange(W)
    prof = y0 + (y1 - y0) * (0.5 + 0.25 * np.sin(xs / 140 + r.uniform(0, 6)) + 0.15 * np.sin(xs / 57 + r.uniform(0, 6)))
    for x in xs:
        img[int(prof[x]):y1 + 2, x] = colour


# ---- CAM-04 fence line (layout matches DEFAULT_ZONES["CAM-04"]) ----
def fence_bg():
    img = np.zeros((H, W, 3), np.float32)
    img[:int(H * .3)] = grad((215, 190, 160), (225, 215, 200), int(H * .3))
    hills(img, int(H * .24), int(H * .31), (120, 125, 118), 3)
    img[int(H * .3):int(H * .52)] = texture(int(H * .52) - int(H * .3), W, (120, 160, 175), 18)
    img[int(H * .52):] = texture(H - int(H * .52), W, (95, 145, 130), 22)
    img = img.astype(np.uint8)
    cv2.rectangle(img, (0, int(H * .8)), (W, int(H * .92)), (150, 180, 195), -1)
    for yy, col, gap in ((0.51, (70, 70, 70), 52), (0.565, (55, 55, 55), 64)):
        y = int(H * yy)
        for x in range(0, W + gap, gap):
            cv2.line(img, (x, y), (x, y - int(H * (0.07 if yy > .55 else .05))), col, 3)
        for k in range(5):
            cv2.line(img, (0, y - k * int(H * .013)), (W, y - k * int(H * .013)), (90, 90, 95), 1, cv2.LINE_AA)
    bx = int(W * .88)
    for dx in (-40, 40):
        cv2.line(img, (bx + dx, int(H * .74)), (bx + dx // 3, int(H * .36)), (40, 50, 60), 6)
    cv2.rectangle(img, (bx - 46, int(H * .3)), (bx + 46, int(H * .37)), (45, 60, 75), -1)
    cv2.rectangle(img, (bx - 38, int(H * .31)), (bx + 38, int(H * .34)), (160, 190, 200), -1)
    cv2.line(img, (int(W * .06), int(H * .64)), (int(W * .06), int(H * .38)), (60, 60, 60), 4)
    cv2.rectangle(img, (int(W * .06) - 14, int(H * .37)), (int(W * .06) + 14, int(H * .39)), (200, 230, 240), -1)
    return img


def fence_persp(y):
    return 34 + (y - 0.3) / 0.7 * 190


def fence_night(img):
    out = cv2.convertScaleAbs(img, alpha=0.26, beta=4)
    out[..., 0] = np.clip(out[..., 0].astype(np.int16) + 10, 0, 255).astype(np.uint8)
    for x in (int(W * .06), int(W * .88)):
        cv2.circle(out, (x, int(H * .38)), 60, (60, 90, 110), -1)
    out = cv2.GaussianBlur(out, (3, 3), 0)
    return np.clip(out.astype(np.int16) + rng.normal(0, 7, out.shape).astype(np.int16), 0, 255).astype(np.uint8)


def fence_actors():
    olive = ((60, 90, 70), (45, 60, 50))
    dark = ((50, 50, 55), (40, 40, 45))
    return [
        Actor(1, 0, [(0, -0.05, .86, "walk"), (40, 1.08, .86, "walk")], colour=olive),
        Actor(2, 0, [(1.2, -0.05, .87, "walk"), (41, 1.05, .87, "walk")], colour=olive),
        Actor(3, 0, [(2, .18, .40, "walk"), (11, .33, .49, "walk"), (12, .34, .505, "crawl"), (18, .37, .56, "crawl"),
                     (18.5, .38, .58, "walk"), (19.7, .62, .82, "walk"), (21.2, .92, .99, "walk"), (21.6, 1.02, 1.03, "walk")], colour=dark),
        Actor(4, 0, [(4, .72, .62, "walk"), (6, .70, .615, "stand"), (30, .705, .62, "stand"), (34, .8, .64, "walk"), (36, .95, .66, "walk")],
              colour=((70, 70, 110), (60, 50, 50)), size=0.95),
        Actor(5, 2, [(20, 1.15, .95, "left"), (33, -0.2, .95, "left")], kind="vehicle", colour=((60, 90, 70),)),
        Actor(6, 0, [(2, .44, .76, "walk"), (6, .56, .76, "walk"), (10, .44, .76, "walk"), (14, .56, .76, "walk"),
                     (18, .44, .76, "walk"), (22, .56, .76, "walk"), (26, .44, .76, "walk"), (29, .40, .80, "walk"), (33, .2, .9, "walk")],
              colour=((80, 80, 80), (50, 50, 50))),
    ]


# ---- CAM-05 riverine night (thermal display) ----
def river_bg():
    img = np.zeros((H, W, 3), np.float32)
    img[:int(H * .26)] = grad((28, 16, 10), (40, 26, 18), int(H * .26))
    img[int(H * .26):int(H * .44)] = texture(int(H * .44) - int(H * .26), W, (20, 30, 26), 8)
    img[int(H * .44):int(H * .62)] = texture(int(H * .62) - int(H * .44), W, (45, 30, 20), 6)
    img[int(H * .62):] = texture(H - int(H * .62), W, (22, 30, 28), 9)
    img = img.astype(np.uint8)
    hills(img, int(H * .22), int(H * .3), (14, 20, 16), 11)
    for _ in range(40):
        cv2.circle(img, (int(rng.uniform(0, W)), int(rng.uniform(0, H * .2))), 1, (150, 150, 140), -1)
    for x in range(0, W, 7):
        top = int(H * .64 + rng.uniform(0, 30))
        cv2.line(img, (x, top), (x + int(rng.uniform(-4, 4)), top - int(rng.uniform(15, 45))), (18, 40, 30), 1)
    return img


def river_dynamic(img, t):
    for k in range(18):
        y = int(H * (.46 + .15 * ((k * 0.37) % 1)))
        x = int((k * 173 + t * (20 + k % 5 * 6)) % (W + 200)) - 100
        cv2.line(img, (x, y), (x + 60, y), (90, 70, 55), 1, cv2.LINE_AA)


def river_persp(y):
    return 30 + (y - 0.3) / 0.7 * 150


def river_actors():
    warm = ((150, 150, 175), (120, 120, 140))
    return [
        Actor(1, 0, [(3, .28, .42, "walk"), (20, .42, .67, "walk"), (26, .75, .72, "walk"), (30, 1.05, .74, "walk")], colour=warm),
        Actor(2, 0, [(0, -0.03, .40, "walk"), (26, 1.03, .41, "walk")], colour=warm, size=0.9),
        Actor(4, 0, [(24, -0.05, .80, "walk"), (27, .12, .80, "stand"), (40, .12, .80, "stand")], colour=warm),
        Actor(5, 0, [(24.5, -0.05, .84, "walk"), (27.5, .17, .83, "stand"), (40, .17, .83, "stand")], colour=warm),
        Actor(6, 0, [(25, -0.05, .77, "walk"), (28, .21, .78, "stand"), (40, .21, .78, "stand")], colour=warm),
        Actor(7, 0, [(25.5, -0.05, .86, "walk"), (28.5, .26, .86, "stand"), (40, .26, .86, "stand")], colour=warm),
    ]


# ---- CAM-08 helipad (restricted octagon matches DEFAULT_ZONES["CAM-08"]) ----
def helipad_bg():
    img = np.zeros((H, W, 3), np.float32)
    img[:int(H * .28)] = grad((200, 170, 150), (215, 200, 185), int(H * .28))
    img[int(H * .28):] = texture(H - int(H * .28), W, (125, 128, 130), 14, blur=2)
    img = img.astype(np.uint8)
    hills(img, int(H * .2), int(H * .29), (110, 118, 112), 21)
    cv2.rectangle(img, (int(W * .78), int(H * .12)), (W, int(H * .36)), (90, 105, 115), -1)
    cv2.rectangle(img, (int(W * .82), int(H * .2)), (int(W * .95), int(H * .36)), (50, 55, 60), -1)
    for x in range(0, W, 40):
        cv2.line(img, (x, int(H * .3)), (x, int(H * .25)), (70, 70, 70), 2)
    cv2.line(img, (0, int(H * .27)), (W, int(H * .27)), (90, 90, 90), 1)
    c = (int(W * .5), int(H * .62))
    cv2.ellipse(img, c, (int(W * .2), int(H * .14)), 0, 0, 360, (95, 98, 100), -1, cv2.LINE_AA)
    cv2.ellipse(img, c, (int(W * .19), int(H * .13)), 0, 0, 360, (0, 200, 240), 5, cv2.LINE_AA)
    hx, hy = c
    for dx in (-40, 40):
        cv2.line(img, (hx + dx, hy - 45), (hx + dx, hy + 45), (245, 245, 245), 14)
    cv2.line(img, (hx - 40, hy), (hx + 40, hy), (245, 245, 245), 14)
    cv2.line(img, (int(W * .1), int(H * .7)), (int(W * .1), int(H * .38)), (160, 160, 160), 3)
    cv2.fillPoly(img, [np.array([[int(W * .1), int(H * .38)], [int(W * .16), int(H * .4)], [int(W * .1), int(H * .42)]])], (30, 120, 250))
    for k in range(10):
        a = 2 * math.pi * k / 10
        cv2.circle(img, (int(hx + W * .205 * math.cos(a)), int(hy + H * .145 * math.sin(a))), 5, (60, 230, 250), -1)
    return img


def helipad_persp(y):
    return 40 + (y - 0.28) / 0.72 * 150


def helipad_actors():
    crew = ((40, 140, 230), (50, 50, 60))
    return [
        Actor(1, 0, [(0, .22, .88, "walk"), (15, .78, .9, "walk"), (30, .22, .88, "walk"), (40, .5, .9, "walk")], colour=crew),
        Actor(2, 0, [(0, .92, .45, "walk"), (20, .7, .41, "walk"), (40, .92, .45, "walk")], colour=crew),
        Actor(3, 2, [(0, .12, .82, "right"), (14, .12, .82, "right"), (27, 1.2, .84, "right")], kind="vehicle", colour=((60, 90, 70),)),
        Actor(4, 0, [(17, .5, .32, "walk"), (22, .5, .55, "walk"), (23, .51, .6, "stand"), (36, .5, .6, "stand"), (40, .3, .45, "walk")],
              colour=((40, 40, 45), (30, 30, 30))),
        Actor(6, 0, [(3, 1.03, .78, "walk"), (8, .8, .8, "walk"), (9, .8, .8, "stand"), (10, .8, .8, "walk"), (15, 1.05, .76, "walk")],
              colour=((90, 70, 60), (50, 50, 50))),
        Actor(7, 24, [(9, .82, .81, "stand"), (40, .82, .81, "stand")], kind="bag"),
    ]


def gen_scenes():
    render_scene("fence_line", fence_bg, fence_actors(), 40, fence_persp, night_variant=fence_night)
    render_scene("riverine_night", river_bg, river_actors(), 40, river_persp, dynamic_fn=river_dynamic)
    render_scene("helipad", helipad_bg, helipad_actors(), 40, helipad_persp)


# ============================================================================ CAM-02 ANPR lane
def copy_anpr_test(src):
    os.makedirs(ANPR_TEST, exist_ok=True)
    if src and os.path.isdir(src):
        for p in sorted(glob.glob(os.path.join(src, "*.jp*g")) + glob.glob(os.path.join(src, "*.png"))):
            if "Screenshot" in p:
                continue
            dst = os.path.join(ANPR_TEST, os.path.basename(p).replace(" ", "_"))
            if not os.path.exists(dst):
                shutil.copy(p, dst)
    return sorted(glob.glob(os.path.join(ANPR_TEST, "*.jp*g")))


def cover(img, w=W, h=H):
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih)
    r = cv2.resize(img, (int(iw * s + 0.5), int(ih * s + 0.5)), interpolation=cv2.INTER_CUBIC)
    y0, x0 = (r.shape[0] - h) // 2, (r.shape[1] - w) // 2
    return r[y0:y0 + h, x0:x0 + w]


def empty_lane():
    img = texture(H, W, (85, 88, 92), 10, blur=2).astype(np.uint8)
    for x in (int(W * .18), int(W * .82)):
        cv2.line(img, (x, 0), (x, H), (230, 230, 230), 8)
    for y in range(0, H, 90):
        cv2.line(img, (W // 2, y), (W // 2, y + 45), (0, 200, 240), 6)
    for k in range(10):
        c = (40, 40, 220) if k % 2 == 0 else (240, 240, 240)
        cv2.rectangle(img, (int(W * .18) + k * 80, int(H * .82)), (int(W * .18) + (k + 1) * 80, int(H * .86)), c, -1)
    return img


def gen_checkpost(anpr_src):
    photos = copy_anpr_test(anpr_src)
    if not photos:
        log("checkpost: no ANPR test photos found — skipping CAM-02 clip (pass --anpr-dir)")
        return
    from open_image_models import LicensePlateDetector
    det = LicensePlateDetector(detection_model="yolo-v9-s-608-license-plate-end2end", conf_thresh=0.35)
    border_plates = ["PB 10 XX 4521", "JK 01 ZZ 2233", "RJ 14 YY 9087", "GJ 12 AB 3456", "PB 65 MK 7788", "JK 02 CD 1122"]
    shots, manifest = [], []
    k = 0
    for p in photos:
        img = cv2.imread(p)
        if img is None:
            continue
        plates = det.predict(img)
        if not plates:
            continue
        shots.append(("original", img))
        manifest.append({"photo": os.path.basename(p), "variant": "original plate (real)"})
        b = max(plates, key=lambda d: d.confidence).bounding_box
        x1, y1, x2, y2 = max(0, b.x1), max(0, b.y1), min(img.shape[1], b.x2), min(img.shape[0], b.y2)
        txt = border_plates[k % len(border_plates)]
        k += 1
        pw, ph = x2 - x1, y2 - y1
        pl = cv2.resize(render_plate(txt, w=max(pw * 4, 200), h=max(ph * 4, 50)), (pw, ph), interpolation=cv2.INTER_AREA)
        var = img.copy()
        roi = var[y1:y2, x1:x2]
        var[y1:y2, x1:x2] = cv2.addWeighted(cv2.GaussianBlur(pl, (3, 3), 0), 0.92, roi, 0.08, 0)
        shots.append(("composited", var))
        manifest.append({"photo": os.path.basename(p), "variant": f"composited plate {txt} (rendered)"})
    order = [s for pair in zip(shots[::2], shots[1::2]) for s in pair]
    out = os.path.join(GEN, "checkpost_anpr.mp4")
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    lane = empty_lane()
    # gap > ByteTrack's lost-track buffer (30 frames) so consecutive cars get distinct track IDs
    n_show, n_fade, n_gap = int(4.5 * FPS), int(0.5 * FPS), int(3.0 * FPS)
    for _, img in order:
        base = cover(img)
        for f in range(n_show):
            z = 1.0 + 0.22 * f / n_show
            cw, ch = int(W / z), int(H / z)
            x0, y0 = (W - cw) // 2, int((H - ch) * 0.6)
            fr = cv2.resize(base[y0:y0 + ch, x0:x0 + cw], (W, H), interpolation=cv2.INTER_LINEAR)
            a = min(1.0, f / n_fade, (n_show - f) / n_fade)
            fr = cv2.addWeighted(fr, a, lane, 1 - a, 0)
            fr = np.clip(fr.astype(np.int16) + rng.normal(0, 3, fr.shape).astype(np.int16), 0, 255).astype(np.uint8)
            vw.write(fr)
        for _ in range(n_gap):
            vw.write(np.clip(lane.astype(np.int16) + rng.normal(0, 3, lane.shape).astype(np.int16), 0, 255).astype(np.uint8))
    vw.release()
    save_json(os.path.join(GEN, "checkpost_manifest.json"), manifest)
    log(f"checkpost: {len(order)} vehicle passes ({len(order) // 2} real plates + {len(order) // 2} composited border-state plates)")


# ============================================================================ precompute real detections
PRECOMPUTE_WEIGHTS = "yolov8m.pt"  # measured: ~2x more vehicles found than v8n on the overhead clips


def precompute(video, out_json, label, conf=0.3):
    from ultralytics import YOLO
    from pehredar.engine.detector import TRACK_CLASSES, new_tracker
    w = os.path.join(MODELS, PRECOMPUTE_WEIGHTS)
    m = YOLO(w if os.path.exists(w) else os.path.join(MODELS, "yolov8n.pt"))
    model_name = "YOLOv8m" if os.path.exists(w) else "YOLOv8n"
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 12
    trk = new_tracker(int(fps))
    frames, t0, confs = [], time.time(), []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        r = m.predict(f, conf=conf, classes=TRACK_CLASSES, verbose=False)[0]
        rows = trk.update(r.boxes.cpu().numpy(), f)
        frames.append([[round(float(x[0]), 1), round(float(x[1]), 1), round(float(x[2]), 1), round(float(x[3]), 1),
                        int(x[4]), round(float(x[5]), 3), int(x[6])] for x in rows])
        confs += [float(x[5]) for x in rows]
    save_json(out_json, {"fps": fps, "frames": frames, "model": f"{model_name} (COCO) + ByteTrack", "conf": conf,
                         "label": label.replace("YOLOv8n", model_name),
                         "stats": {"frames": len(frames), "boxes": sum(len(x) for x in frames),
                                   "tracks": len({b[4] for fr in frames for b in fr}),
                                   "avg_conf": round(sum(confs) / max(len(confs), 1), 3),
                                   "ms_per_frame": round((time.time() - t0) / max(len(frames), 1) * 1000, 1)}})
    st = json.load(open(out_json))["stats"]
    log(f"precompute {os.path.basename(video)}: {st['frames']} frames, {st['boxes']} boxes, {st['tracks']} tracks, "
        f"avg conf {st['avg_conf']}, {st['ms_per_frame']} ms/frame")


def gen_precompute(clips=None):
    jobs = [(os.path.join(GEN, "checkpost_anpr.mp4"), "checkpost_anpr",
             "Recorded ANPR lane (real vehicle photos) · real YOLOv8n + ByteTrack, precomputed"),
            (os.path.join(VIDEOS, "car-detection.mp4"), "car-detection", "Recorded sample (Intel CC-BY) · real YOLOv8n + ByteTrack, precomputed"),
            (os.path.join(VIDEOS, "face-demographics-walking.mp4"), "face-demographics-walking",
             "Recorded sample (Intel CC-BY) · real YOLOv8n + ByteTrack precomputed; faces detected live"),
            (os.path.join(VIDEOS, "person-bicycle-car-detection.mp4"), "person-bicycle-car-detection",
             "Recorded sample (Intel CC-BY) · real YOLOv8n + ByteTrack, precomputed")]
    for video, key, label in jobs:
        if clips and key not in clips:
            continue
        if os.path.exists(video):
            precompute(video, os.path.join(GEN, "cache", f"{key}.dets.json"), label)
        else:
            log(f"precompute: missing {video} — run fetch_assets.py first")


# ============================================================================ sample data
def gen_data():
    save_json(WATCHLIST_PATH, [
        {"plate": "PB10XX4521", "display": "PB 10 XX 4521", "reason": "Reported stolen (sample entry)", "since": "2026-08-14", "severity": "critical"},
        {"plate": "JK01ZZ2233", "display": "JK 01 ZZ 2233", "reason": "Linked to smuggling FIR (sample entry)", "since": "2026-07-02", "severity": "critical"},
        {"plate": "RJ14YY9087", "display": "RJ 14 YY 9087", "reason": "Wanted for questioning (sample entry)", "since": "2026-09-01", "severity": "critical"},
    ])
    default_ids = {d["id"] for d in DEFAULT_CAMERAS}
    cams = json.load(open(CAMERAS_PATH, encoding="utf-8")) if os.path.exists(CAMERAS_PATH) else []
    save_json(CAMERAS_PATH, DEFAULT_CAMERAS + [c for c in cams if c["id"] not in default_ids])  # keep onboarded RTSP cameras
    if not os.path.exists(ZONES_PATH):
        save_json(ZONES_PATH, DEFAULT_ZONES)
    save_json(os.path.join(DATA, "operators.json"), [
        {"id": "OP-0147", "name": "Insp. R. Singh", "role": "Duty Officer, Sector Control", "shift": "20:00–08:00"},
        {"id": "OP-0212", "name": "SI P. Chauhan", "role": "Surveillance Operator", "shift": "08:00–20:00"},
        {"id": "OP-0309", "name": "HC M. Yadav", "role": "Quick Reaction Team lead", "shift": "on call"}])
    from pehredar.network import LINKS
    save_json(os.path.join(DATA, "network_links.json"), {"note": "Baseline ranges used by the SIMULATED link telemetry", "links": LINKS})
    log("data: watchlist, cameras, zones, operators, network link baselines")


EVENT_TEMPLATES = [
    ("fence", "Fence Breach", "critical", "Intrusion", "Person #{n} entered restricted zone 'Fence strip'", ["CAM-04", "CAM-05"], 0.12),
    ("fence", "Buffer Zone Entry", "high", "Intrusion", "Person #{n} entered buffer zone 'Inner buffer'", ["CAM-04"], 0.1),
    ("activity", "Loitering", "medium", "Behaviour", "#{n} inside Inner buffer for 24s · risk 52/100", ["CAM-04", "CAM-01", "CAM-08"], 0.12),
    ("activity", "Running", "medium", "Behaviour", "#{n} moving 2.1 body-heights/s · risk 38/100", ["CAM-01", "CAM-04"], 0.06),
    ("activity", "Crawling Near Fence", "high", "Behaviour", "#{n} low profile near Fence strip · risk 78/100", ["CAM-04"], 0.03),
    ("activity", "Group Gathering", "medium", "Behaviour", "4 people clustered for 9s · risk 49/100", ["CAM-05", "CAM-07"], 0.05),
    ("anpr", "Vehicle Plate Read", "info", "ANPR", "{plate} · plate read · OCR 97%", ["CAM-02", "CAM-03"], 0.2),
    ("anpr", "Watchlisted Vehicle Detected", "critical", "ANPR — Watchlist", "{plate} · WATCHLIST: sample entry", ["CAM-02"], 0.015),
    ("anpr", "Plate Read — Manual Review", "medium", "ANPR", "{plate} · low confidence — manual review", ["CAM-02", "CAM-03"], 0.04),
    ("face", "Face Detected", "info", "Identity", "No registry match (best similarity 0.21 < 0.40)", ["CAM-06", "CAM-01"], 0.1),
    ("face", "Unregistered Person at Restricted Post", "medium", "Identity", "No registry match at restricted post", ["CAM-06"], 0.05),
    ("night", "Night Movement Near Border", "high", "Night", "Person #{n} moving near the border in low light", ["CAM-05", "CAM-04"], 0.06),
    ("vehicle", "Heavy Vehicle on Restricted Road", "high", "Vehicle", "truck #{n} (HMV) on a road closed to heavy vehicles", ["CAM-03"], 0.02),
    ("network", "Bandwidth Adaptation", "medium", "Network", "{cam} bandwidth 0.6 Mbps (VSAT) — adapted to LOW", ["CAM-05", "CAM-08"], 0.03),
]


def gen_history(days=7):
    from pehredar.events import EventStore
    if os.path.exists(HISTORY_DB):
        os.remove(HISTORY_DB)
    snaps = os.path.join(GEN, "history_snaps")
    shutil.rmtree(snaps, ignore_errors=True)
    os.makedirs(snaps)
    store = EventStore(HISTORY_DB, snaps)
    cams = {c["id"]: c for c in DEFAULT_CAMERAS}
    thumbs = {}
    for cid, path in (("CAM-04", "scenes/fence_line.mp4"), ("CAM-05", "scenes/riverine_night.mp4"), ("CAM-08", "scenes/helipad.mp4"),
                      ("CAM-02", "checkpost_anpr.mp4")):
        cap = cv2.VideoCapture(os.path.join(GEN, path))
        cap.set(cv2.CAP_PROP_POS_FRAMES, 60)
        ok, f = cap.read()
        if ok:
            thumbs[cid] = cv2.resize(f, (640, 360))
    blank = np.full((360, 640, 3), (46, 27, 18), np.uint8)
    plates = [p for p, _ in PLATE_SET[3:10]]
    weights = [t[6] for t in EVENT_TEMPLATES]
    now = time.time()
    start = now - days * 86400
    ops = ["Insp. R. Singh", "SI P. Chauhan", "HC M. Yadav"]
    events = []
    for d in range(days):
        n = random.randint(38, 70)
        for _ in range(n):
            hr = random.choices(range(24), weights=[6, 7, 8, 8, 7, 5, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 4, 5, 6, 7, 7, 6])[0]
            ts = start + d * 86400 + hr * 3600 + random.uniform(0, 3599)
            if ts < now - 600:
                events.append((ts, random.choices(EVENT_TEMPLATES, weights=weights)[0]))
    for ts, (module, name, sev, atype, desc, cam_ids, _) in sorted(events):
        cid = random.choice(cam_ids)
        img = thumbs.get(cid, blank).copy()
        x, y = random.randint(80, 520), random.randint(80, 240)
        cv2.rectangle(img, (x, y), (x + 50, y + 100), (57, 57, 229), 2)
        cv2.putText(img, "SAMPLE HISTORY", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (51, 153, 255), 2)
        plate = random.choice(plates)
        dsc = desc.format(n=random.randint(1, 60), plate=plate, cam=cid)
        night = random.random() < 0.6 if (ts % 86400) / 3600 < 6 else False
        extra = {"sample_history": True}
        if module == "fence":
            extra["zone"] = random.choice(["Fence strip", "Inner buffer", "River channel", "Helipad (no entry)"])
        if module == "anpr":
            extra.update(plate=plate, state="Punjab" if plate.startswith("PB") else "Jammu & Kashmir" if plate.startswith("JK") else "Rajasthan")
        ev = store.log(event_name=name, module=module, severity=sev, camera=cams[cid], frame=img, description=dsc, alert_type=atype,
                       model_used="(sample history)", confidence=round(random.uniform(0.55, 0.97), 3), extra=extra, ts=ts,
                       night=night, synthetic=True)
        r = random.random()
        if sev in ("critical", "high", "medium") and r < 0.85:
            ack = ts + random.uniform(15, 240 if sev == "critical" else 600)
            if ack < now:
                act = "false_alarm" if random.random() < 0.12 else "acknowledge"
                store.action(ev["event_id"], act, random.choice(ops), "sample history", ts=ack)
                if act == "acknowledge" and random.random() < 0.7:
                    store.action(ev["event_id"], "resolve", random.choice(ops), "sample history", ts=ack + random.uniform(60, 900))
    res = store.verify()
    log(f"history: {res['total']} sample events over {days} days, chain verified={res['ok']}")


# ============================================================================ main
STEPS = {"plates": gen_plates, "avatars": gen_avatars, "svg": gen_svgs, "scenes": gen_scenes, "data": gen_data}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma list: plates,avatars,svg,scenes,checkpost,precompute,data,history")
    ap.add_argument("--anpr-dir", default=DEFAULT_ANPR_SRC, help="folder with real vehicle test photos (your Anpr_system)")
    ap.add_argument("--clips", default="", help="precompute only these clip keys (comma list)")
    a = ap.parse_args()
    only = set(filter(None, a.only.split(",")))
    order = ["plates", "avatars", "svg", "scenes", "checkpost", "precompute", "data", "history"]
    t0 = time.time()
    for step in order:
        if only and step not in only:
            continue
        if step == "checkpost":
            gen_checkpost(a.anpr_dir)
        elif step == "precompute":
            gen_precompute(set(filter(None, a.clips.split(","))))
        elif step == "history":
            gen_history()
        else:
            STEPS[step]()
    log(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
