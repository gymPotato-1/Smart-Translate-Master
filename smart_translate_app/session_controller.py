"""Application-owned session lifecycle, independent of any visible page."""

import queue
from uuid import uuid4

from .azure_service import AzureService
from .models import TranslationEvent, timestamp


class SessionEvents(queue.Queue):
    """Persist every session's events before UI filtering, including late results."""

    def __init__(self, storage=None):
        super().__init__()
        self.storage = storage

    def put(self, event, block=True, timeout=None):
        if self.storage is not None:
            self.storage.record_event(event)
        super().put(event, block, timeout)


class SessionController:
    def __init__(self, service_factory=AzureService, *, storage=None):
        self.events = SessionEvents(storage)
        self.service_factory = service_factory
        self.service = None
        self.session_id = None
        self.state = "Stopped"

    def start(self, target):
        if self.state != "Stopped":
            return False
        self.session_id = str(uuid4())
        self.state = "Starting"
        try:
            self.service = self.service_factory(self.session_id, target, self.events)
            self.service.start()
        except Exception:
            self.state = "Stopped"
            self.events.put(TranslationEvent(
                self.session_id, "error", timestamp(), "Could not start the background translation service."
            ))
            return False
        return True

    def stop(self):
        if self.state not in ("Stopped", "Stopping"):
            self.state = "Stopping"
            self.service.stop()

    def set_target(self, target):
        if self.service is not None:
            self.service.set_target(target)

    def poll(self, limit=100):
        result = []
        for _ in range(limit):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event.session_id != self.session_id:
                continue
            if event.kind == "status":
                if self.state != "Stopping" or event.message == "Stopped":
                    self.state = event.message
            result.append(event)
        return result
