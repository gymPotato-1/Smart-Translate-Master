"""Shared application lifecycle: page changes never stop the session."""

import queue
import tkinter as tk

from .history_view import HistoryView
from .live_view import LiveTranslationView
from .meeting_store import HistoryStorage
from .session_controller import SessionController


class SmartTranslateApplication:
    def __init__(self, root, *, storage=None, controller=None):
        self.root = root
        self.storage = storage if storage is not None else HistoryStorage()
        self.controller = controller if controller is not None else SessionController(storage=self.storage)
        self.closing = False
        self.close_future = None
        self.page = "live"
        self.banner = tk.Label(root, bg="#452A30", fg="#FFE4E6", font=("Arial", 10),
                               wraplength=760, justify="left", padx=12, pady=5)
        self.banner.pack(fill="x")
        self.banner.pack_forget()
        self.container = tk.Frame(root, bg="#101827")
        self.container.pack(fill="both", expand=True)
        self.live = LiveTranslationView(self.container, self.controller, self.show_history)
        self.history = HistoryView(self.container, self.storage, self.show_live)
        self.live.frame.pack(fill="both", expand=True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(50, self.poll)

    def show_history(self):
        if self.closing:
            return
        self.page = "history"
        self.live.frame.pack_forget()
        self.history.frame.pack(fill="both", expand=True)
        self.history.show()

    def show_live(self):
        self.page = "live"
        self.history.hide()
        self.history.frame.pack_forget()
        self.live.frame.pack(fill="both", expand=True)
        self.live.refresh_controls()

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.show_live()
        self.live.stop_session()
        self.live.start_button.configure(state="disabled")
        self.live.history_button.configure(state="disabled")
        self.root.title("Smart Translate - finishing translations, audio and saving")

    def poll(self):
        # Always process Live events, including while the view is hidden.
        for event in self.controller.poll():
            self.live.handle_event(event)
        for _ in range(100):
            try:
                notification = self.storage.notifications.get_nowait()
            except queue.Empty:
                break
            if notification["kind"] in ("storage_warning", "storage_error"):
                self.banner.configure(text=notification["message"])
                self.banner.pack(before=self.container, fill="x")
            else:
                self.history.handle_storage(notification)
        if self.closing:
            self.live.start_button.configure(state="disabled")
            if self.controller.state == "Stopped":
                if self.close_future is None:
                    self.close_future = self.storage.close()
                elif self.close_future.done():
                    self.root.destroy()
                    return
        self.root.after(50, self.poll)
