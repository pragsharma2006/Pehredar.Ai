"""Network health & bandwidth adaptation.

Link telemetry (bandwidth, latency, jitter, loss, signal) is SIMULATED per link type,
with scripted degradation/outage scenarios so the behaviour is visible in a demo. What
it drives is real: the stream each tile receives is actually downscaled / slowed /
switched to metadata-only, and events raised while a link is down are actually held
in an edge queue and synced into the evidence chain on reconnect.
"""
import random
import threading
import time
from collections import deque

LINKS = {
    "Fibre": {"bw": (18, 45), "lat": (4, 14), "jit": (0.5, 3), "loss": (0.0, 0.2), "sig": (92, 100)},
    "4G": {"bw": (2.5, 12), "lat": (35, 90), "jit": (5, 25), "loss": (0.1, 1.5), "sig": (55, 90)},
    "VSAT": {"bw": (1.8, 3.2), "lat": (560, 680), "jit": (15, 60), "loss": (0.2, 2.5), "sig": (60, 85)},
    "Radio": {"bw": (2.0, 6.0), "lat": (18, 45), "jit": (3, 12), "loss": (0.2, 2.0), "sig": (50, 88)},
}
# (min Mbps, tier, scale of source resolution, fps cap, jpeg quality)
LADDER = [(4.0, "HIGH", 1.0, 15, 80), (1.5, "MEDIUM", 0.75, 12, 70), (0.7, "LOW", 0.5, 8, 60),
          (0.3, "KEYFRAMES", 0.5, 0.5, 60), (0.0, "METADATA", 0.5, 0.2, 55)]
TIER_SEV = {"HIGH": "info", "MEDIUM": "info", "LOW": "medium", "KEYFRAMES": "medium", "METADATA": "high"}


def _walk(v, lo, hi, step):
    mid = (lo + hi) / 2
    v += random.gauss(0, step) + 0.08 * (mid - v)
    return max(lo * 0.6, min(hi * 1.1, v))


class Link:
    def __init__(self, cam):
        r = LINKS.get(cam.get("link"), LINKS["4G"])
        self.cam = cam
        self.r = r
        self.bw = sum(r["bw"]) / 2
        self.lat = sum(r["lat"]) / 2
        self.jit = sum(r["jit"]) / 2
        self.loss = sum(r["loss"]) / 2
        self.sig = sum(r["sig"]) / 2
        self.online = True
        self.tier = "HIGH"
        self.hist = deque(maxlen=300)
        self.up_since = time.time()
        self.down_total = 0.0
        self.started = time.time()
        self.queue = []
        self.scenario = None
        self.last_log = 0
        self.down_since = time.time()
        self.eff = {"bw": self.bw, "lat": self.lat, "loss": self.loss, "sig": self.sig}
        self.tier = next(name for th, name, *_ in LADDER if self.bw >= th)  # start at the right tier, no startup log

    def as_dict(self, src_wh=None):
        tier = LADDER[[t[1] for t in LADDER].index(self.tier)] if self.online else None
        out_wh = None
        if src_wh and tier:
            out_wh = [int(src_wh[0] * tier[2]) // 2 * 2, int(src_wh[1] * tier[2]) // 2 * 2]
        elapsed = max(1.0, time.time() - self.started)
        down = self.down_total + (time.time() - self.down_since if not self.online else 0)
        e = self.eff
        return {"camera": self.cam["id"], "link": self.cam.get("link"), "online": self.online, "tier": self.tier if self.online else "OFFLINE",
                "bandwidth": round(e["bw"], 2) if self.online else 0, "latency": round(e["lat"]), "jitter": round(self.jit, 1),
                "loss": round(e["loss"], 2), "signal": round(e["sig"]), "uptime_pct": round(100 * (1 - down / elapsed), 2),
                "queued": len(self.queue), "fps_cap": tier[3] if tier else 0, "out_wh": out_wh,
                "scenario": self.scenario["kind"] if self.scenario else None}


class NetworkSim(threading.Thread):
    def __init__(self, cams, store, bus, settings):
        super().__init__(daemon=True, name="network")
        self.store, self.bus, self.settings = store, bus, settings
        self.links = {c["id"]: Link(c) for c in cams}
        self.lock = threading.Lock()
        self.snapshot_fn = None
        self.src_wh = {}
        self.t0 = time.time()
        # scripted demo scenarios: (camera, kind, first start after boot, period, duration)
        self.auto = [("CAM-05", "degrade", 45, 170, 50), ("CAM-08", "outage", 95, 230, 28), ("CAM-03", "congest", 140, 260, 30)]
        self.next_auto = {c: self.t0 + first for c, _, first, _, _ in self.auto}

    def add_camera(self, cam):
        with self.lock:
            self.links[cam["id"]] = Link(cam)

    def trigger(self, cam_id, kind, duration=30):
        with self.lock:
            if cam_id in self.links:
                self.links[cam_id].scenario = {"kind": kind, "start": time.time(), "dur": duration}

    def profile(self, cam_id):
        lk = self.links.get(cam_id)
        if lk is None or not self.settings.get("network", "adaptive", True):
            return {"tier": "HIGH", "scale": 1.0, "fps": 15, "quality": 80, "mode": "video"}
        if not lk.online:
            return {"tier": "OFFLINE", "scale": 0.5, "fps": 0, "quality": 50, "mode": "offline"}
        _, tier, scale, fps, q = LADDER[[t[1] for t in LADDER].index(lk.tier)]
        mode = "metadata" if tier == "METADATA" else "keyframes" if tier == "KEYFRAMES" else "video"
        return {"tier": tier, "scale": scale, "fps": fps, "quality": q, "mode": mode}

    def online(self, cam_id):
        lk = self.links.get(cam_id)
        return lk is None or lk.online

    def deliver(self, cam_id, log_kwargs):
        """Edge store-and-forward: log now if the link is up, else hold at the edge."""
        lk = self.links.get(cam_id)
        if lk is not None and not lk.online:
            with self.lock:
                log_kwargs.setdefault("ts", time.time())
                lk.queue.append(log_kwargs)
            self.bus.publish({"type": "edge", "camera": cam_id, "queued": len(lk.queue)})
            return None
        return self.store.log(**log_kwargs)

    def snapshot(self):
        with self.lock:
            return {cid: lk.as_dict(self.src_wh.get(cid)) for cid, lk in self.links.items()}

    def history(self, cam_id):
        lk = self.links.get(cam_id)
        return list(lk.hist) if lk else []

    # ------------------------------------------------------------------ loop
    def run(self):
        while True:
            time.sleep(1.0)
            now = time.time()
            for cid, kind, _, period, dur in self.auto:
                if now >= self.next_auto[cid] and cid in self.links:
                    self.trigger(cid, kind, dur)
                    self.next_auto[cid] = now + period
            for lk in list(self.links.values()):
                try:
                    self._step(lk, now)
                except Exception as e:
                    print("network sim error:", e)

    def _step(self, lk, now):
        r = lk.r
        lk.bw = _walk(lk.bw, *r["bw"], step=(r["bw"][1] - r["bw"][0]) * 0.04)
        lk.lat = _walk(lk.lat, *r["lat"], step=(r["lat"][1] - r["lat"][0]) * 0.06)
        lk.jit = _walk(lk.jit, *r["jit"], step=(r["jit"][1] - r["jit"][0]) * 0.08)
        lk.loss = _walk(lk.loss, *r["loss"], step=(r["loss"][1] - r["loss"][0]) * 0.08)
        lk.sig = _walk(lk.sig, *r["sig"], step=2)
        bw, lat, loss, sig, online = lk.bw, lk.lat, lk.loss, lk.sig, True
        sc = lk.scenario
        if sc:
            p = (now - sc["start"]) / sc["dur"]
            if p >= 1:
                lk.scenario = None
            elif sc["kind"] == "outage":
                online = False
            else:
                depth = 0.08 if sc["kind"] == "degrade" else 0.3
                f = 1 - (1 - depth) * min(1.0, p / 0.35) if p < 0.7 else depth + (1 - depth) * (p - 0.7) / 0.3
                bw = lk.bw * f
                lat = lk.lat * (1 + (1 - f) * 0.6)
                loss = min(12.0, lk.loss + (1 - f) * 4)
                sig = max(15.0, lk.sig * (0.6 + 0.4 * f))
        lk.eff = {"bw": bw, "lat": lat, "loss": loss, "sig": sig}
        lk.hist.append([round(now, 1), round(bw if online else 0, 2), round(lat), round(lk.jit, 1), round(loss, 2)])

        if online != lk.online:
            self._set_online(lk, online, now)
        if not online:
            return
        new_tier = self._tier_for(bw, lk.tier)
        if new_tier != lk.tier:
            old = lk.tier
            lk.tier = new_tier
            if self.settings.get("network", "adaptive", True):
                self._log_tier(lk, old, bw)

    @staticmethod
    def _tier_for(bw, current):
        names = [t[1] for t in LADDER]
        ci = names.index(current)
        for i, (th, name, *_rest) in enumerate(LADDER):
            if bw >= th:
                # hysteresis: only step up if comfortably above the next threshold
                if i < ci and bw < th * 1.15:
                    return current
                return name
        return "METADATA"

    def _log_tier(self, lk, old, bw):
        cam = lk.cam
        prof = self.profile(cam["id"])
        wh = lk.as_dict(self.src_wh.get(cam["id"]))["out_wh"]
        res = f"{wh[0]}×{wh[1]}" if wh else ""
        if lk.tier == "METADATA":
            what = "switched to METADATA-ONLY (detections + snapshots, no video)"
        elif lk.tier == "KEYFRAMES":
            what = f"adapted to KEYFRAMES-ONLY {res} @ 1 frame/2s"
        else:
            what = f"adapted to {lk.tier} {res} @ {prof['fps']} fps"
        desc = f"{cam['id']} bandwidth {bw:.1f} Mbps ({cam.get('link')}) — {what} (was {old})"
        self.bus.publish({"type": "net_log", "camera": cam["id"], "text": desc})
        worse = [t[1] for t in LADDER].index(lk.tier) > [t[1] for t in LADDER].index(old)
        if time.time() - lk.last_log < 12 and not lk.tier == "METADATA":
            return
        lk.last_log = time.time()
        self.store.log(event_name="Bandwidth Adaptation" if lk.tier != "METADATA" else "Metadata-only Mode", module="network",
                       severity=TIER_SEV[lk.tier] if worse else "info", camera=cam, frame=self._snap(cam["id"], lk.tier),
                       description=desc, alert_type="Network", model_used="Adaptive streaming controller (simulated link telemetry)",
                       extra={"bandwidth_mbps": round(bw, 2), "tier": lk.tier, "from": old, "latency_ms": round(lk.lat),
                              "loss_pct": round(lk.loss, 2), "link": cam.get("link"), "telemetry": "simulated"})

    def _set_online(self, lk, online, now):
        cam = lk.cam
        lk.online = online
        if not online:
            lk.down_since = now
            self.store.log(event_name="Camera Link Offline", module="network", severity="high", camera=cam,
                           frame=self._snap(cam["id"], "OFFLINE"), alert_type="Network",
                           description=f"{cam['id']} {cam.get('link')} link lost — edge node buffering events locally",
                           model_used="Link monitor (simulated link telemetry)", extra={"link": cam.get("link"), "telemetry": "simulated"})
            self.bus.publish({"type": "edge", "camera": cam["id"], "queued": 0, "offline": True})
            return
        lk.down_total += now - getattr(lk, "down_since", now)
        with self.lock:
            q, lk.queue = lk.queue, []
        n = len(q)
        for i, kw in enumerate(q):
            kw.setdefault("extra", {})["edge_synced"] = True
            kw["extra"]["edge_queued_s"] = round(now - kw.get("ts", now), 1)
            self.store.log(**kw)
            self.bus.publish({"type": "sync", "camera": cam["id"], "done": i + 1, "total": n})
        self.store.log(event_name="Camera Link Restored", module="network", severity="info", camera=cam,
                       frame=self._snap(cam["id"], "RESTORED"), alert_type="Network",
                       description=f"{cam['id']} link restored after {now - getattr(lk, 'down_since', now):.0f}s — {n} events synced from edge",
                       model_used="Link monitor (simulated link telemetry)", extra={"synced": n, "telemetry": "simulated"})
        self.bus.publish({"type": "edge", "camera": cam["id"], "queued": 0, "offline": False, "synced": n})

    def _snap(self, cam_id, label):
        return self.snapshot_fn(cam_id, label) if self.snapshot_fn else None
