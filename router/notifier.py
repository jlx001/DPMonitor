"""In-process notification fan-out to tray toast and webview banner."""


class Notifier:
    def __init__(self):
        self._sinks = []

    def add_sink(self, sink):
        self._sinks.append(sink)

    def notify(self, kind, message, sk_id=None):
        for sink in self._sinks:
            try:
                sink(kind, message, sk_id)
            except Exception:
                pass
