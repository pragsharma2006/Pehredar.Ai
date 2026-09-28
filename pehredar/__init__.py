import os

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("YOLO_VERBOSE", "False")
# OpenMP workers sleep instead of spin-waiting: spinning threads in the inference
# processes were burning ~6 cores while the machine was already saturated.
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")

VERSION = "2.0.0"

import cv2 as _cv2

_cv2.setNumThreads(2)  # avoid 12-thread fan-out per resize/encode competing with PyTorch
