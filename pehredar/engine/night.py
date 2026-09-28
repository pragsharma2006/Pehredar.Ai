import cv2
import numpy as np


class LightMeter:
    """Day/night from mean grayscale brightness, smoothed with an EMA and switched with
    hysteresis (enter night below one level, return to day above a higher one) so the
    label doesn't flicker on a single dark frame."""

    def __init__(self):
        self.level = None
        self.night = False

    def update(self, frame, cfg):
        small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
        b = float(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).mean())
        self.level = b if self.level is None else 0.9 * self.level + 0.1 * b
        mode = cfg.get("mode", "auto")
        if mode == "day":
            self.night = False
        elif mode == "night":
            self.night = True
        elif self.night and self.level > cfg["exit_above"]:
            self.night = False
        elif not self.night and self.level < cfg["enter_below"]:
            self.night = True
        return self.night


_luts = {}


def enhance(frame, clip=3.0, gamma=1.6):
    """Low-light enhancement: CLAHE on the L channel (LAB), then gamma lift."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)).apply(l)
    out = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    key = round(gamma, 2)
    if key not in _luts:
        _luts[key] = np.array([((i / 255.0) ** (1.0 / gamma)) * 255 for i in range(256)], np.uint8)
    return cv2.LUT(out, _luts[key])


def thermal(frame):
    """False-colour 'thermal' look (inferno palette over normalised luminance)."""
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    g = cv2.normalize(cv2.GaussianBlur(g, (5, 5), 0), None, 0, 255, cv2.NORM_MINMAX)
    return cv2.applyColorMap(g, cv2.COLORMAP_INFERNO)


class MotionLayer:
    """MOG2 background subtraction — a second detection layer for darkness, where YOLO
    confidence drops but moving pixels are still visible."""

    def __init__(self):
        self.sub = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=28, detectShadows=False)
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    def blobs(self, frame, min_frac=0.003):
        small = cv2.resize(frame, (frame.shape[1] // 2, frame.shape[0] // 2))
        m = self.sub.apply(small)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, self.kernel)
        m = cv2.dilate(m, self.kernel, iterations=2)
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        area_min = min_frac * small.shape[0] * small.shape[1]
        out = []
        for c in cnts:
            if cv2.contourArea(c) >= area_min:
                x, y, w, h = cv2.boundingRect(c)
                out.append([x * 2, y * 2, (x + w) * 2, (y + h) * 2])
        return out
