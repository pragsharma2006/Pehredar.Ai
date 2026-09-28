import cv2
import numpy as np

SIZE_CLASS = {"car": "LMV", "bus": "HMV", "truck": "HMV", "motorcycle": "2-wheeler", "bicycle": "2-wheeler"}
HEAVY = {"bus", "truck"}


def dominant_colour(crop):
    """Dominant body colour: k-means (k=3) over the central region of the crop in BGR,
    largest cluster mapped to a colour name via HSV thresholds."""
    if crop is None or crop.size == 0:
        return "unknown"
    h, w = crop.shape[:2]
    roi = crop[int(h * 0.2):int(h * 0.8), int(w * 0.15):int(w * 0.85)]
    if roi.size == 0:
        roi = crop
    px = cv2.resize(roi, (48, 48), interpolation=cv2.INTER_AREA).reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    _, labels, centers = cv2.kmeans(px, 3, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    c = centers[np.bincount(labels.flatten()).argmax()].astype(np.uint8)
    hh, s, v = cv2.cvtColor(c.reshape(1, 1, 3), cv2.COLOR_BGR2HSV)[0, 0].astype(int)
    if v < 50:
        return "black"
    if s < 40:
        return "white" if v > 185 else "silver" if v > 120 else "grey"
    hue = hh * 2
    for limit, name in ((15, "red"), (40, "orange"), (70, "yellow"), (160, "green"), (255, "blue"), (290, "purple"), (340, "pink"), (361, "red")):
        if hue < limit:
            if name == "orange" and v < 140:
                return "brown"
            return name
    return "unknown"


def direction(track, in_vector):
    vx, vy = track.velocity(2.0)
    if abs(vx) + abs(vy) < 1:
        return "STATIONARY"
    return "IN" if vx * in_vector[0] + vy * in_vector[1] >= 0 else "OUT"


def speed_kmh(track, m_per_px):
    return round(track.speed_px(1.0) * m_per_px * 3.6, 1)
