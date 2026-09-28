import queue
import threading


class Bus:
    """In-process pub/sub feeding WebSocket clients and the webhook dispatcher."""

    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()

    def subscribe(self, maxsize=500):
        q = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def publish(self, msg):
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except (queue.Empty, queue.Full):
                    pass
