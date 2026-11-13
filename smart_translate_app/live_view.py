"""Live Azure transcript using the original text and touch helpers."""

import tkinter as tk
from tkinter import ttk

from datetime import datetime

from screen_language_selection import AITranslator
from .languages import LANGUAGES


class LiveTranslationView(AITranslator):
    """Tkinter-only presentation; the application owns the session controller."""

    def __init__(self, parent, controller, on_history=None):
        self.frame = tk.Frame(parent, bg="#101827")
        self.controller = controller
        self.on_history = on_history
        self.target_language = LANGUAGES["中文"]
        self.has_error = False
        self.build_interface()

    def build_interface(self):
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(3, weight=1)

        header = tk.Frame(self.frame, bg="#101827")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 5))
        self.label(header, "Smart Translate", 21, bold=True).pack(side="left")
        self.status = self.label(header, "● Stopped", 12, "#94A3B8")
        self.status.pack(side="left", padx=20)
        self.history_button = self._button(
            header, "History", command=self.on_history,
            state="normal" if self.on_history else "disabled"
        )
        self.history_button.pack(side="right")

        language_row = tk.Frame(self.frame, bg="#101827")
        language_row.grid(row=1, column=0, sticky="ew", padx=16, pady=4)
        self.language_var = tk.StringVar(master=self.frame, value="中文")
        style = ttk.Style(self.frame)
        style.theme_use("clam")
        style.configure(
            "SmartTranslate.TCombobox", padding=7,
            fieldbackground="#1E293B", background="#334155",
            foreground="#E2E8F0", arrowcolor="#CBD5E1", borderwidth=0,
        )
        style.map(
            "SmartTranslate.TCombobox",
            fieldbackground=[("readonly", "#1E293B")],
            foreground=[("readonly", "#E2E8F0")],
            selectbackground=[("readonly", "#1E293B")],
            selectforeground=[("readonly", "#E2E8F0")],
        )
        # Increase dropdown row height for touch selection in this application.
        self.frame.option_add("*TCombobox*Listbox.font", ("Arial", 16))
        self.frame.option_add("*TCombobox*Listbox.background", "#1E293B")
        self.frame.option_add("*TCombobox*Listbox.foreground", "#E2E8F0")
        self.label(language_row, "Input", 12, "#94A3B8").pack(side="left", padx=(0, 8))
        self.source_var = tk.StringVar(master=self.frame, value="Auto detect")
        self.source_selector = ttk.Combobox(
            language_row, textvariable=self.source_var,
            values=["Auto detect", *LANGUAGES], state="readonly",
            font=("Arial", 14), width=13, height=6,
            style="SmartTranslate.TCombobox",
        )
        self.source_selector.pack(side="left")
        self.label(language_row, "Translate to", 12, "#94A3B8").pack(
            side="left", padx=(16, 8)
        )
        self.language_selector = ttk.Combobox(
            language_row,
            textvariable=self.language_var,
            values=list(LANGUAGES),
            state="readonly",
            font=("Arial", 14),
            width=12,
            height=6,
            style="SmartTranslate.TCombobox",
        )
        self.language_selector.pack(side="left")
        self.language_selector.bind("<<ComboboxSelected>>", self.change_language)
        self.notice = self.label(
            self.frame,
            "Choose input before Start; translation target can change anytime. Meetings are saved locally.",
            10, "#FBBF24",
        )
        self.notice.configure(anchor="w", wraplength=750, justify="left")
        self.notice.grid(row=2, column=0, sticky="ew", padx=16, pady=(5, 6))

        panel = tk.Frame(self.frame, bg="#101827")
        panel.grid(row=3, column=0, sticky="nsew")
        self.transcript_box = self.create_text_area(panel)
        self.transcript_box.configure(
            height=3, width=1, padx=16, pady=12,
            highlightthickness=1, highlightbackground="#29364A",
        )
        for child in self.transcript_box.master.winfo_children():
            if isinstance(child, tk.Scrollbar):
                child.configure(width=24)
        self.transcript_box.tag_configure(
            "timestamp", font=("Arial", 10), foreground="#94A3B8", spacing1=8
        )
        self.transcript_box.tag_configure(
            "original", font=("Arial", 13), foreground="#CBD5E1", spacing1=3
        )
        self.transcript_box.tag_configure(
            "translated", font=("Arial", 15), foreground="#93C5FD",
            spacing1=4, spacing3=12,
        )

        controls = tk.Frame(self.frame, bg="#101827")
        controls.grid(row=4, column=0, sticky="ew", padx=16, pady=(2, 10))
        controls.columnconfigure(2, weight=1)

        self.start_button = self._button(
            controls, "Start", command=self.start_session, background="#145344",
            foreground="#A7F3D0",
        )
        self.start_button.grid(row=0, column=0, padx=(0, 8))
        self.stop_button = self._button(
            controls, "Stop", command=self.stop_session, state="disabled", background="#572936",
            foreground="#FECDD3",
        )
        self.stop_button.grid(row=0, column=1)
        self.latest_button = self._button(
            controls, "Back to Latest", command=self.scroll_to_latest
        )
        self.latest_button.grid(row=0, column=3)

    def show_entry(self, entry, completed=False):
        """Render raw speech immediately, then replace its translation placeholder."""
        box = self.transcript_box
        follow_latest = box.yview()[1] >= 0.97
        box.configure(state="normal")
        tag = f"entry_{entry.sequence}"
        if completed:
            ranges = box.tag_ranges(tag)
            if ranges:
                start = str(ranges[0])
                box.delete(ranges[0], ranges[1])
                box.insert(start, (entry.error or entry.translated) + "\n", ("translated", tag))
        else:
            clock = datetime.fromisoformat(entry.timestamp).strftime("%H:%M:%S")
            box.insert("end", f"{clock}   ·   {entry.source_language or 'Auto'} → {entry.target_name}\n", "timestamp")
            box.insert("end", entry.original + "\n", "original")
            box.insert("end", "Translating…\n", ("translated", tag))
            box.insert("end", "\n", "timestamp")
        box.configure(state="disabled")
        if follow_latest:
            box.see("end")

    def start_session(self):
        source = LANGUAGES.get(self.source_var.get())
        if self.controller.start(self.target_language, source_language=source):
            self.has_error = False
            self.transcript_box.configure(state="normal")
            self.transcript_box.delete("1.0", "end")
            self.transcript_box.configure(state="disabled")
            self.notice.configure(text=f"Starting microphone recognition · Input: {self.source_var.get()}…", fg="#94A3B8")
        self.refresh_controls()

    def stop_session(self):
        self.controller.stop()
        self.notice.configure(text="Stopping recognition; finishing queued translations and audio…", fg="#94A3B8")
        self.refresh_controls()

    def refresh_controls(self):
        state = self.controller.state
        self.source_selector.configure(state="readonly" if state == "Stopped" else "disabled")
        self.status.configure(text=f"● {state}", fg="#93C5FD" if state != "Stopped" else "#94A3B8")
        self.start_button.configure(state="normal" if state == "Stopped" else "disabled")
        self.stop_button.configure(state="normal" if state not in ("Stopped", "Stopping") else "disabled")

    def handle_event(self, event):
        if event.kind == "recognized":
            self.show_entry(event.entry)
            self.notice.configure(text="", fg="#94A3B8")
        elif event.kind in ("translated", "translation_failed"):
            self.show_entry(event.entry, completed=True)
        elif event.kind == "partial":
            self.notice.configure(text="Hearing: " + event.message[:160], fg="#94A3B8")
        elif event.kind == "error":
            self.has_error = True
            self.notice.configure(text=event.message, fg="#FDA4AF")
        elif event.kind == "status" and event.message == "Stopped" and not self.has_error:
            self.notice.configure(text="Stopped. Transcript remains here until you start a new session.", fg="#94A3B8")
        self.refresh_controls()

    def scroll_to_latest(self):
        self.transcript_box.see("end")

    @staticmethod
    def _button(parent, text, command=None, state="normal",
                background="#263449", foreground="#E2E8F0"):
        return tk.Button(
            parent,
            text=text,
            command=command,
            state=state,
            font=("Arial", 11, "bold"),
            bg=background,
            fg=foreground,
            disabledforeground=foreground,
            activebackground="#475569",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=14,
            pady=11,
        )

    def change_language(self, event=None):
        """Update subsequent utterances without restarting recognition."""
        self.target_language = LANGUAGES[self.language_var.get()]
        self.controller.set_target(self.target_language)

    def receive_speech(self, recognized_text):
        raise NotImplementedError("Use structured session events for speech input.")

    def process_speech(self, text):
        raise NotImplementedError("Speech processing belongs to AzureService.")

    def translate_worker(self, text, target, request_id):
        raise NotImplementedError("Translation belongs to AzureService.")
