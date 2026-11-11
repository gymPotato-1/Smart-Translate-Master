"""Temporary SQLite and fake-Azure tests; no credentials or hardware required."""

from dataclasses import replace
from contextlib import closing
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

from smart_translate_app.application import SmartTranslateApplication
from smart_translate_app.azure_service import AzureService
from smart_translate_app.history_view import HistoryView, meeting_label
from smart_translate_app.languages import LANGUAGES
from smart_translate_app.meeting_store import HistoryStorage, MeetingStore
from smart_translate_app.models import TranscriptEntry, TranslationEvent, timestamp
from smart_translate_app.session_controller import SessionController
from test_phase2 import CREDS, FakeSDK, wait_for


def event(kind, meeting="meeting-a", sequence=1, text="Hello", message="", time=None):
    entry = TranscriptEntry(meeting, sequence, time or timestamp(), text, text,
                            "en-US", "fr", "French", "fr-FR-DeniseNeural")
    if kind == "translated":
        entry = replace(entry, translated="Bonjour")
    if kind == "translation_failed":
        entry = replace(entry, error="Translation unavailable")
    return TranslationEvent(meeting, kind, time or timestamp(), message,
                            entry if kind in ("recognized", "translated", "translation_failed") else None)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "meetings.sqlite3"
        self.store = MeetingStore(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_create_save_update_end_and_reopen(self):
        self.store.record_event(event("meeting_started"))
        self.store.record_event(event("recognized"))
        saved = self.store.get_transcript("meeting-a")[0]
        self.assertEqual(saved["translation_status"], "pending")
        self.assertEqual(saved["original"], "Hello")
        self.assertEqual(saved["cleaned"], "Hello")
        self.assertEqual(saved["source_language"], "en-US")
        self.assertEqual(saved["target_language"], "fr")
        self.assertEqual(saved["utterance_id"], "meeting-a:1")
        self.store.record_event(event("translated"))
        self.store.record_event(event("status", message="Stopped"))
        self.store.close()
        self.store = MeetingStore(self.path)
        meeting = self.store.list_meetings()[0]
        self.assertEqual(meeting["status"], "ended")
        self.assertIsNotNone(meeting["ended_at"])
        self.assertEqual(self.store.get_transcript("meeting-a")[0]["translated"], "Bonjour")

    def test_incremental_commit_visible_before_stop(self):
        self.store.record_event(event("recognized"))
        with closing(sqlite3.connect(self.path)) as reader:
            self.assertEqual(reader.execute("SELECT original FROM utterances").fetchone()[0], "Hello")
            self.assertEqual(reader.execute("SELECT status FROM meetings").fetchone()[0], "active")

    def test_chronological_sequence_despite_out_of_order_completions(self):
        for sequence in (1, 2, 3):
            self.store.record_event(event("recognized", sequence=sequence))
        for sequence in (3, 1, 2):
            self.store.record_event(event("translated", sequence=sequence))
        entries = self.store.get_transcript("meeting-a")
        self.assertEqual([entry["sequence"] for entry in entries], [1, 2, 3])
        self.assertEqual(len({entry["utterance_id"] for entry in entries}), 3)

    def test_multiple_meetings_newest_first_and_late_results(self):
        self.store.record_event(event("recognized", "old", time="2020-01-01T10:00:00+00:00"))
        self.store.record_event(event("status", "old", message="Stopped"))
        self.store.record_event(event("recognized", "new", time="2026-01-01T10:00:00+00:00"))
        self.store.record_event(event("translated", "old"))
        self.assertEqual([m["meeting_id"] for m in self.store.list_meetings()], ["new", "old"])
        self.assertEqual(self.store.get_transcript("old")[0]["translated"], "Bonjour")
        self.assertEqual(self.store.get_transcript("new")[0]["translated"], "")
        self.assertEqual(self.store.list_meetings()[1]["status"], "ended")

    def test_unfinished_recovery_preserves_completed_work(self):
        self.store.record_event(event("recognized", sequence=1))
        self.store.record_event(event("translated", sequence=1))
        self.store.record_event(event("recognized", sequence=2))
        self.store.close()
        self.store = MeetingStore(self.path)
        meeting = self.store.list_meetings()[0]
        self.assertEqual(meeting["status"], "interrupted")
        self.assertIsNone(meeting["ended_at"])
        entries = self.store.get_transcript("meeting-a")
        self.assertEqual(entries[0]["translated"], "Bonjour")
        self.assertEqual(entries[1]["translation_status"], "interrupted")
        self.assertIn("unfinished", entries[1]["error"])

    def test_abrupt_process_exit_preserves_committed_wal_records(self):
        self.store.close()
        code = """
import os, sys
from smart_translate_app.meeting_store import MeetingStore
from smart_translate_app.models import TranscriptEntry, TranslationEvent, timestamp
store = MeetingStore(sys.argv[1])
now = timestamp()
entry = TranscriptEntry('crashed', 1, now, 'Committed before crash', 'Committed before crash', 'en-US', 'fr', 'French', 'voice')
store.record_event(TranslationEvent('crashed', 'recognized', now, entry=entry))
os._exit(0)
"""
        subprocess.run([sys.executable, "-B", "-c", code, str(self.path)],
                       check=True, timeout=5, capture_output=True)
        self.store = MeetingStore(self.path)
        self.assertEqual(self.store.list_meetings()[0]["status"], "interrupted")
        entry = self.store.get_transcript("crashed")[0]
        self.assertEqual(entry["original"], "Committed before crash")
        self.assertEqual(entry["translation_status"], "interrupted")

    def test_late_recognition_cannot_erase_completed_translation(self):
        self.store.record_event(event("translated"))
        self.store.record_event(event("recognized"))
        self.assertEqual(self.store.get_transcript("meeting-a")[0]["translated"], "Bonjour")

    def test_failed_translation_saved(self):
        self.store.record_event(event("recognized"))
        self.store.record_event(event("translation_failed"))
        saved = self.store.get_transcript("meeting-a")[0]
        self.assertEqual(saved["translation_status"], "failed")
        self.assertEqual(saved["error"], "Translation unavailable")

    def test_transaction_rolls_back_meeting_and_utterance_together(self):
        self.store.connection.execute("""
            CREATE TRIGGER fail_insert BEFORE INSERT ON utterances
            BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END
        """)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.record_event(event("recognized"))
        self.assertEqual(self.store.list_meetings(), [])
        self.assertEqual(self.store.get_transcript("meeting-a"), [])

    def test_no_retention_deletion(self):
        for index in range(125):
            self.store.record_event(event("recognized", f"old-{index}", time="1999-01-01T10:00:00+00:00"))
        self.store.close()
        self.store = MeetingStore(self.path)
        self.assertEqual(len(self.store.list_meetings()), 125)
        self.assertEqual(self.store.get_transcript("old-0")[0]["original"], "Hello")


class AsyncStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "meetings.sqlite3"
        self.storage = HistoryStorage(self.path)
        self.storage.ready.result(3)

    def tearDown(self):
        if not self.storage.closed:
            self.storage.close().result(3)
        self.storage.thread.join(3)
        self.directory.cleanup()

    def test_thread_safe_producers_and_incremental_flush(self):
        def produce(index):
            self.storage.record_event(event("recognized", sequence=index))
            self.storage.record_event(event("translated", sequence=index))
        threads = [threading.Thread(target=produce, args=(index,)) for index in range(1, 16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.storage.flush().result(3)
        entries = self.storage.get_transcript("meeting-a").result(3)
        self.assertEqual([row["sequence"] for row in entries], list(range(1, 16)))
        self.assertTrue(all(row["translated"] == "Bonjour" for row in entries))

    def test_warning_once_and_no_deletion_or_limit(self):
        self.storage.warning_bytes = 1
        for index in range(5):
            self.storage.record_event(event("recognized", f"meeting-{index}"))
        self.storage.flush().result(3)
        warnings = [item for item in list(self.storage.notifications.queue) if item["kind"] == "storage_warning"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(len(self.storage.list_meetings().result(3)), 5)

    def test_warning_checks_existing_database_on_reopen(self):
        self.storage.record_event(event("recognized"))
        self.storage.close().result(3)
        self.storage.thread.join(3)
        self.storage = HistoryStorage(self.path, warning_bytes=1)
        self.storage.ready.result(3)
        warnings = [item for item in list(self.storage.notifications.queue) if item["kind"] == "storage_warning"]
        self.assertEqual(len(warnings), 1)

    def test_initialization_failure_is_nonfatal_and_queries_finish(self):
        self.storage.close().result(3)
        self.storage.thread.join(3)
        # A directory cannot be opened as a SQLite database.
        self.storage = HistoryStorage(Path(self.directory.name))
        with self.assertRaises(sqlite3.OperationalError):
            self.storage.ready.result(3)
        with self.assertRaises(sqlite3.OperationalError):
            self.storage.list_meetings("request").result(3)
        notifications = list(self.storage.notifications.queue)
        self.assertEqual(sum(item["kind"] == "storage_error" for item in notifications), 1)
        self.assertTrue(any(item["kind"] == "query_error" for item in notifications))

    def test_write_failure_does_not_kill_worker(self):
        self.storage.close().result(3)
        self.storage.thread.join(3)
        class FailWrites(MeetingStore):
            def record_event(self, event):
                raise sqlite3.OperationalError("simulated full disk")
        self.storage = HistoryStorage(self.path, repository_factory=FailWrites)
        self.storage.ready.result(3)
        with self.assertRaises(sqlite3.OperationalError):
            self.storage.record_event(event("recognized")).result(3)
        self.assertEqual(self.storage.list_meetings().result(3), [])
        self.assertTrue(self.storage.thread.is_alive())

    def test_slow_database_work_does_not_block_event_producer(self):
        self.storage.close().result(3)
        self.storage.thread.join(3)
        gate, entered = threading.Event(), threading.Event()
        class SlowStore(MeetingStore):
            def record_event(self, event):
                entered.set()
                if not gate.wait(3):
                    raise TimeoutError("Test gate timed out")
                super().record_event(event)
        self.storage = HistoryStorage(self.path, repository_factory=SlowStore)
        self.storage.ready.result(3)
        try:
            future = self.storage.record_event(event("recognized"))
            self.assertTrue(entered.wait(3))
            self.assertFalse(future.done())
            queued = self.storage.record_event(event("translated"))
            self.assertFalse(queued.done())
        finally:
            gate.set()
        queued.result(3)
        self.assertEqual(self.storage.get_transcript("meeting-a").result(3)[0]["translated"], "Bonjour")

    def test_background_navigation_does_not_restart_or_interrupt_azure(self):
        sdk = FakeSDK()
        def factory(session_id, target, events):
            return AzureService(session_id, target, events, sdk=sdk,
                                translator=lambda *a, **kw: "Bonjour", credentials=CREDS)
        controller = SessionController(factory, storage=self.storage)
        controller.start(LANGUAGES["French"])
        self.assertTrue(sdk.started.wait(3))
        session_id = controller.session_id
        app = SmartTranslateApplication.__new__(SmartTranslateApplication)
        app.controller, app.storage = controller, self.storage
        app.root, app.live, app.history = Mock(), Mock(), Mock()
        app.closing = False
        try:
            app.show_history()
            self.assertEqual(app.page, "history")
            sdk.final("Hello from History.")
            wait_for(lambda: bool(sdk.spoken))
            # Persistence is independent even of polling/rendering the Live page.
            self.storage.flush().result(3)
            entries = self.storage.get_transcript(session_id).result(3)
            self.assertEqual(entries[0]["original"], "Hello from History.")
            self.assertEqual(entries[0]["translated"], "Bonjour")
            app.poll()
            app.live.handle_event.assert_called()
            app.show_live()
            self.assertEqual(app.page, "live")
            self.assertEqual(controller.session_id, session_id)
            self.assertEqual(sdk.starts, 1)
            self.assertFalse(controller.service.stop_requested.is_set())
        finally:
            controller.stop()
            controller.service.thread.join(3)
            self.storage.flush().result(3)
        self.assertEqual(self.storage.list_meetings().result(3)[0]["status"], "ended")

    def test_late_events_saved_even_if_controller_filters_them(self):
        class FakeService:
            def __init__(self, *args): pass
            def start(self): pass
        controller = SessionController(FakeService, storage=self.storage)
        controller.start(LANGUAGES["French"])
        current = controller.session_id
        controller.events.put(event("translated", "earlier-meeting"))
        self.assertEqual(controller.poll(), [])
        self.storage.flush().result(3)
        self.assertEqual(self.storage.get_transcript("earlier-meeting").result(3)[0]["translated"], "Bonjour")
        self.assertEqual(controller.session_id, current)

    def test_failed_recognition_start_does_not_create_meeting(self):
        def factory(session_id, target, events):
            return AzureService(session_id, target, events, credentials={key: "" for key in CREDS})
        controller = SessionController(factory, storage=self.storage)
        controller.start(LANGUAGES["French"])
        controller.service.thread.join(3)
        self.storage.flush().result(3)
        self.assertEqual(self.storage.list_meetings().result(3), [])


class HistoryViewTests(unittest.TestCase):
    def test_stale_or_hidden_query_results_are_ignored(self):
        view = HistoryView.__new__(HistoryView)
        view.active = False
        view.meeting_list = Mock()
        view.handle_storage({"kind": "meetings", "request_id": "old", "data": []})
        view.meeting_list.delete.assert_not_called()
        view.active = True
        view.list_request = "new"
        view.transcript_request = None
        view.handle_storage({"kind": "meetings", "request_id": "old", "data": []})
        view.meeting_list.delete.assert_not_called()

    def test_meeting_duration_and_interrupted_label(self):
        meeting = {"started_at": "2026-01-01T10:00:00+00:00",
                   "ended_at": "2026-01-01T10:01:05+00:00", "status": "ended"}
        self.assertIn("1m 05s", meeting_label(meeting))
        meeting.update(ended_at=None, status="interrupted")
        self.assertIn("Interrupted", meeting_label(meeting))


if __name__ == "__main__":
    unittest.main()
