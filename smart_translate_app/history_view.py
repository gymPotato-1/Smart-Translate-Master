"""Asynchronous meeting browser; navigation never controls Azure's lifecycle."""

from datetime import datetime
import tkinter as tk
from tkinter import messagebox
from uuid import uuid4

from screen_language_selection import AITranslator
from .live_view import LiveTranslationView


def meeting_label(meeting):
    start = datetime.fromisoformat(meeting["started_at"])
    duration = meeting["status"].capitalize()
    if meeting["ended_at"]:
        seconds = max(0, int((datetime.fromisoformat(meeting["ended_at"]) - start).total_seconds()))
        duration = f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{start.astimezone():%b %d, %Y  %H:%M:%S}  ·  {duration}"


class HistoryView(AITranslator):
    def __init__(self, parent, storage, on_live):
        self.storage = storage
        self.on_live = on_live
        self.frame = tk.Frame(parent, bg="#101827")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)
        self.meetings = []
        self.selected_id = None
        self.selected_meeting = None
        self.list_request = None
        self.transcript_request = None
        self.active = False
        self.reader_loading = False
        self.pending_changes = {}
        self.rendered_sequences = set()
        self.reader_rows = {}
        self.empty_reader = False
        self.delete_request = None
        self.list_refresh_scheduled = False

        header = tk.Frame(self.frame, bg="#101827")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 4))
        self.title = self.label(header, "Meeting History", 20, bold=True)
        self.title.pack(side="left")
        self.refresh_button = LiveTranslationView._button(header, "Refresh", command=self.refresh)
        self.refresh_button.pack(side="right", padx=(8, 0))
        LiveTranslationView._button(header, "Back to Live", command=on_live).pack(side="right")
        self.notice = self.label(self.frame, "", 11, "#94A3B8")
        self.notice.configure(anchor="w", wraplength=750, justify="left")
        self.notice.grid(row=1, column=0, sticky="w", padx=16, pady=(2, 6))

        self.list_frame = tk.Frame(self.frame, bg="#101827")
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=15, pady=(0, 10))
        self.meeting_list = tk.Listbox(
            self.list_frame, bg="#1E293B", fg="#E2E8F0", font=("Arial", 15),
            selectbackground="#334D6F", selectforeground="#FFFFFF",
            activestyle="none", borderwidth=0, highlightthickness=0,
            height=4, exportselection=False,
        )
        scrollbar = tk.Scrollbar(self.list_frame, command=self.meeting_list.yview, width=24)
        self.meeting_list.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.meeting_list.pack(side="left", fill="both", expand=True)
        self.meeting_list.bind("<ButtonPress-1>", self._touch_start)
        self.meeting_list.bind("<B1-Motion>", self._touch_move)
        self.meeting_list.bind("<ButtonRelease-1>", self._touch_end)
        self.meeting_list.bind("<Return>", self._open_selected)
        self.meeting_list.bind("<Button-4>", lambda e: self.meeting_list.yview_scroll(-2, "units"))
        self.meeting_list.bind("<Button-5>", lambda e: self.meeting_list.yview_scroll(2, "units"))

        self.reader_frame = tk.Frame(self.frame, bg="#101827")
        self.reader_frame.grid(row=2, column=0, sticky="nsew")
        self.reader_frame.grid_remove()
        self.transcript = self.create_text_area(self.reader_frame)
        self.transcript.configure(height=3, width=1, padx=16, pady=8)
        for widget in self.transcript.master.winfo_children():
            if isinstance(widget, tk.Scrollbar):
                widget.configure(width=24)
        self.transcript.tag_configure("meta", foreground="#94A3B8", font=("Arial", 10), spacing1=10)
        self.transcript.tag_configure("source", foreground="#CBD5E1", font=("Arial", 13), spacing1=4)
        self.transcript.tag_configure("translation", foreground="#93C5FD", font=("Arial", 15), spacing1=4, spacing3=10)

        footer = tk.Frame(self.frame, bg="#101827")
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 8))
        footer.columnconfigure(2, weight=1)
        self.delete_button = LiveTranslationView._button(
            footer, "Delete Meeting", command=self.delete_selected, state="disabled",
            background="#572936", foreground="#FECDD3",
        )
        self.delete_button.grid(row=0, column=0, padx=(0, 8))
        self.clear_button = LiveTranslationView._button(
            footer, "Clear All History", command=self.clear_all, state="disabled",
            background="#572936", foreground="#FECDD3",
        )
        self.clear_button.grid(row=0, column=1)
        self.latest_button = LiveTranslationView._button(
            footer, "Back to Latest", command=lambda: self.transcript.see("end"), state="disabled"
        )
        self.latest_button.grid(row=0, column=3)

    def _touch_start(self, event):
        self.touch_y = event.y
        self.dragged = False
        self.meeting_list.scan_mark(event.x, event.y)
        return "break"

    def _touch_move(self, event):
        if abs(event.y - self.touch_y) > 8:
            self.dragged = True
        if self.dragged:
            self.meeting_list.scan_dragto(event.x, event.y)
        return "break"

    def _touch_end(self, event):
        if not self.dragged:
            index = self.meeting_list.nearest(event.y)
            bounds = self.meeting_list.bbox(index) if self.meetings else None
            if bounds and bounds[1] <= event.y <= bounds[1] + bounds[3]:
                self.meeting_list.selection_clear(0, "end")
                self.meeting_list.selection_set(index)
                self._open_selected()
        return "break"

    def show(self):
        self.active = True
        self.show_list()

    def hide(self):
        self.active = False
        # Invalidate pending responses when navigating away.
        self.list_request = self.transcript_request = None

    def show_list(self):
        self.selected_id = None
        self.selected_meeting = None
        self.transcript_request = None
        self.title.configure(text="Meeting History")
        self.reader_frame.grid_remove()
        self.list_frame.grid()
        self.refresh_button.configure(text="Refresh", command=self.refresh)
        self._update_delete_controls()
        self.refresh()

    def refresh(self):
        if self.selected_id is None:
            self.notice.configure(text="Loading local meetings…")
        self.list_request = str(uuid4())
        self.storage.list_meetings(self.list_request)

    def _open_selected(self, event=None):
        selection = self.meeting_list.curselection()
        if not selection or selection[0] // 2 >= len(self.meetings):
            return
        meeting = self.meetings[selection[0] // 2]
        self.selected_id = meeting["meeting_id"]
        self.selected_meeting = meeting
        self.reader_loading = True
        self.pending_changes = {}
        self.rendered_sequences = set()
        self.reader_rows = {}
        self.empty_reader = False
        self._update_delete_controls()
        self.list_request = None
        self.notice.configure(text=meeting_label(meeting))
        self.title.configure(text="Meeting Transcript")
        self.list_frame.grid_remove()
        self.reader_frame.grid()
        self.refresh_button.configure(text="Meetings", command=self.show_list)
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.insert("end", "Loading transcript…")
        self.transcript.configure(state="disabled")
        self.transcript_request = str(uuid4())
        self.storage.get_transcript(self.selected_id, self.transcript_request)

    def handle_storage(self, notification):
        kind = notification["kind"]
        if kind in ("history_deleted", "delete_error"):
            self._deletion_finished(notification)
            return
        if not self.active:
            return
        if kind == "history_changed":
            self._history_changed(notification["data"])
            return
        request_id = notification.get("request_id")
        if request_id not in (self.list_request, self.transcript_request) or request_id is None:
            return
        if kind == "query_error":
            self.notice.configure(text="Could not read history. Check the storage message above.")
        elif kind == "meetings" and request_id == self.list_request:
            self.meetings = notification["data"]
            self.meeting_list.delete(0, "end")
            self._render_meetings(self.meetings, request_id)
            if self.selected_id is None:
                self.notice.configure(text=f"{len(self.meetings)} meeting(s) · Tap a meeting to read it" if self.meetings else "No saved meetings yet. Start a translation from Live.")
            self._update_delete_controls()
        elif kind == "transcript" and request_id == self.transcript_request:
            merged = {entry["sequence"]: entry for entry in notification["data"]}
            merged.update(self.pending_changes)
            self.pending_changes = {}
            self._render_transcript([merged[key] for key in sorted(merged)])

    def _history_changed(self, change):
        meeting, entry = change["meeting"], change["entry"]
        if meeting["meeting_id"] == self.selected_id:
            self.selected_meeting = meeting
            self.notice.configure(text=meeting_label(meeting))
            self._update_delete_controls()
            if entry:
                if self.reader_loading:
                    self.pending_changes[entry["sequence"]] = entry
                else:
                    self._apply_saved_entry(entry)
        # Counts aren't displayed in the list, so ordinary utterances need no query.
        known = next((item for item in self.meetings if item["meeting_id"] == meeting["meeting_id"]), None)
        if known is None or known["status"] != meeting["status"]:
            if known:
                known.update(meeting)
            if not self.list_refresh_scheduled:
                self.list_refresh_scheduled = True
                self.frame.after(100, self._refresh_after_change)

    def _refresh_after_change(self):
        self.list_refresh_scheduled = False
        if self.active:
            self.refresh()

    def _update_delete_controls(self):
        idle = self.delete_request is None
        deletable = self.selected_meeting and self.selected_meeting["status"] in ("ended", "interrupted")
        self.delete_button.configure(state="normal" if idle and deletable else "disabled")
        self.clear_button.configure(state="normal" if idle and any(
            item["status"] in ("ended", "interrupted") for item in self.meetings
        ) else "disabled")
        self.latest_button.configure(state="normal" if self.selected_id else "disabled")

    def delete_selected(self):
        meeting = self.selected_meeting
        if self.delete_request or not meeting or meeting["status"] not in ("ended", "interrupted"):
            return
        meeting_id = meeting["meeting_id"]
        if not messagebox.askyesno(
            "Delete Meeting", f"Permanently delete this meeting and all its original text and translations?\n\n{meeting_label(meeting)}\n\nThis cannot be undone.",
            parent=self.frame, icon="warning", default=messagebox.NO,
        ):
            return
        self.delete_request = str(uuid4())
        self._update_delete_controls()
        self.notice.configure(text="Deleting meeting…")
        self.storage.delete_meeting(meeting_id, self.delete_request)

    def clear_all(self):
        if self.delete_request or not any(item["status"] in ("ended", "interrupted") for item in self.meetings):
            return
        if not messagebox.askyesno(
            "Clear All History", "Permanently delete ALL completed and interrupted meetings, including their original text and translations?\n\nActive meetings will be kept. This cannot be undone.",
            parent=self.frame, icon="warning", default=messagebox.NO,
        ):
            return
        self.delete_request = str(uuid4())
        self._update_delete_controls()
        self.notice.configure(text="Clearing completed and interrupted meetings…")
        self.storage.clear_history(self.delete_request)

    def _deletion_finished(self, notification):
        if notification.get("request_id") != self.delete_request or self.delete_request is None:
            return
        self.delete_request = None
        self._update_delete_controls()
        if notification["kind"] == "delete_error":
            self.notice.configure(text=notification["message"])
        elif self.active:
            removed_id = notification["data"]["meeting_id"]
            if removed_id == self.selected_id or (
                removed_id is None and self.selected_meeting and self.selected_meeting["status"] in ("ended", "interrupted")
            ):
                self.show_list()
            else:
                if self.selected_meeting:
                    self.notice.configure(text=meeting_label(self.selected_meeting))
                self.refresh()

    def _render_meetings(self, meetings, request_id, offset=0):
        if not self.active or request_id != self.list_request:
            return
        for meeting in meetings[offset:offset + 60]:
            # Two rows per meeting provide a touch target around 48 pixels high.
            self.meeting_list.insert("end", meeting_label(meeting), " ")
        if offset + 60 < len(meetings):
            self.frame.after(1, lambda: self._render_meetings(meetings, request_id, offset + 60))

    def _render_transcript(self, entries, offset=0, request_id=None):
        request_id = request_id or self.transcript_request
        if not self.active or request_id != self.transcript_request:
            return
        box = self.transcript
        box.configure(state="normal")
        if offset == 0:
            box.delete("1.0", "end")
            self.rendered_sequences = set()
            self.reader_rows = {}
        for entry in entries[offset:offset + 40]:
            self._insert_entry(entry)
        if not entries:
            box.insert("end", "This meeting has no recognized speech.", "source")
            self.empty_reader = True
        box.configure(state="disabled")
        if offset == 0:
            box.yview_moveto(0)
        if offset + 40 < len(entries):
            self.frame.after(1, lambda: self._render_transcript(entries, offset + 40, request_id))
        else:
            self.reader_loading = False
            pending, self.pending_changes = self.pending_changes, {}
            for key in sorted(pending):
                self._apply_saved_entry(pending[key])

    def _insert_entry(self, entry):
        box = self.transcript
        clock = datetime.fromisoformat(entry["timestamp"]).astimezone().strftime("%H:%M:%S")
        later = sorted(key for key in self.rendered_sequences if key > entry["sequence"])
        start = box.index(f"history_start_{later[0]}" if later else "end-1c")
        translation = entry["error"] or entry["translated"] or f"[{entry['translation_status']}]"
        box.insert(
            start,
            f"{clock}  ·  {entry['source_language'] or 'Auto'} → {entry['target_name']} ({entry['target_language']})\n", ("meta",),
            entry["original"] + "\n", ("source",),
            translation + "\n", ("translation", f"history_translation_{entry['sequence']}"),
            "\n", ("meta",),
        )
        box.mark_set(f"history_start_{entry['sequence']}", start)
        box.mark_gravity(f"history_start_{entry['sequence']}", "right")
        self.rendered_sequences.add(entry["sequence"])
        self.reader_rows[entry["sequence"]] = entry

    def _apply_saved_entry(self, entry):
        if self.reader_rows.get(entry["sequence"]) == entry:
            return
        box = self.transcript
        follow = box.yview()[1] >= 0.97
        if not follow:
            box.mark_set("history_reader_top", box.index("@0,0"))
            box.mark_gravity("history_reader_top", "right")
        box.configure(state="normal")
        if self.empty_reader:
            box.delete("1.0", "end")
            self.empty_reader = False
        if entry["sequence"] not in self.rendered_sequences:
            self._insert_entry(entry)
        else:
            tag = f"history_translation_{entry['sequence']}"
            ranges = box.tag_ranges(tag)
            if ranges:
                start = str(ranges[0])
                box.delete(ranges[0], ranges[1])
                translation = entry["error"] or entry["translated"] or f"[{entry['translation_status']}]"
                box.insert(start, translation + "\n", ("translation", tag))
            self.reader_rows[entry["sequence"]] = entry
        box.configure(state="disabled")
        if follow:
            box.see("end")
        else:
            box.yview("history_reader_top")
