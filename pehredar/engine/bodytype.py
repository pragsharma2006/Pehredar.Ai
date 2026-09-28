"""Runs your anpr_best.pt (YOLOv8l) in its own process with a capped thread count, so
a multi-second CPU inference never starves the live camera's YOLOv8n."""
import itertools
import multiprocessing as mp
import queue
import threading


def _worker(inq, outq, weights, threads):
    import torch
    torch.set_num_threads(threads)
    from ultralytics import YOLO
    import time
    m = YOLO(weights)
    names = m.names
    outq.put(("ready", dict(names), 0, 0))
    while True:
        jid, img = inq.get()
        if jid is None:
            return
        t0 = time.perf_counter()
        r = m.predict(img, verbose=False, imgsz=640, device="cpu")[0]
        best, conf = None, 0.0
        if r.boxes is not None:
            for c, s in zip(r.boxes.cls.cpu().numpy(), r.boxes.conf.cpu().numpy()):
                if s > conf:
                    best, conf = names[int(c)], float(s)
        outq.put((jid, best, conf, (time.perf_counter() - t0) * 1000))


class BodyTypeClient:
    def __init__(self, weights, threads=3):
        ctx = mp.get_context("spawn")
        self.inq, self.outq = ctx.Queue(), ctx.Queue()
        self.proc = ctx.Process(target=_worker, args=(self.inq, self.outq, weights, threads), daemon=True, name="anpr-body")
        self.proc.start()
        self.ids = itertools.count(1)
        self.lock = threading.Lock()
        self.names = None

    def classify(self, img, timeout=60):
        with self.lock:
            jid = next(self.ids)
            self.inq.put((jid, img))
            while True:
                try:
                    msg = self.outq.get(timeout=timeout)
                except queue.Empty:
                    return None, 0.0, None
                if msg[0] == "ready":
                    self.names = msg[1]
                    continue
                if msg[0] == jid:
                    return msg[1], msg[2], msg[3]

    def close(self):
        self.inq.put((None, None))
