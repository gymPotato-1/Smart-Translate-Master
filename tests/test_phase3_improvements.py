"""Commit-driven History updates and explicit deletion, without Tk or Azure."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from smart_translate_app.history_view import HistoryView
from smart_translate_app.meeting_store import HistoryStorage, MeetingStore
from smart_translate_app.azure_service import AzureService
from smart_translate_app.languages import LANGUAGES
from smart_translate_app.session_controller import SessionController
from test_phase2 import CREDS, FakeSDK, wait_for
from test_phase3 import event


class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "meetings.sqlite3"
        self.store = MeetingStore(self.path)
        for meeting_id in ("completed", "interrupted", "active"):
            self.store.record_event(event("recognized", meeting_id))
            self.store.record_event(event("translated", meeting_id))
        self.store.record_event(event("status", "completed", message="Stopped"))
        with self.store.connection:
            self.store.connection.execute("UPDATE meetings SET status='interrupted' WHERE meeting_id='interrupted'")

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_individual_delete_cascades_and_preserves_other_meetings(self):
        self.assertEqual(self.store.delete_meeting("completed"), 1)
        self.assertEqual(self.store.get_transcript("completed"), [])
        self.assertEqual({m["meeting_id"] for m in self.store.list_meetings()}, {"interrupted", "active"})
        self.assertEqual(len(self.store.get_transcript("active")), 1)
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_interrupted_meeting_can_be_deleted(self):
        self.assertEqual(self.store.delete_meeting("interrupted"), 1)
        self.assertEqual(self.store.get_transcript("interrupted"), [])

    def test_active_meeting_rejected_by_api_and_sqlite_trigger(self):
        with self.assertRaises(ValueError):
            self.store.delete_meeting("active")
        with self.assertRaises(sqlite3.IntegrityError), self.store.connection:
            self.store.connection.execute("DELETE FROM meetings WHERE meeting_id='active'")
        self.assertEqual(len(self.store.get_transcript("active")), 1)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM deleted_meetings").fetchone()[0], 0)

    def test_clear_all_retains_active_and_cascades_other_transcripts(self):
        self.assertEqual(self.store.clear_history(), 2)
        self.assertEqual([m["meeting_id"] for m in self.store.list_meetings()], ["active"])
        self.assertEqual(self.store.get_transcript("completed"), [])
        self.assertEqual(self.store.get_transcript("interrupted"), [])
        self.assertEqual(len(self.store.get_transcript("active")), 1)
        self.assertEqual(self.store.clear_history(), 0)
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_bulk_failure_rolls_back_deletions_and_tombstones(self):
        self.store.connection.execute("""
            CREATE TRIGGER fail_cascade BEFORE DELETE ON utterances
            WHEN OLD.meeting_id='interrupted'
            BEGIN SELECT RAISE(ABORT, 'simulated failure'); END
        """)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.clear_history()
        self.assertEqual(len(self.store.list_meetings()), 3)
        self.assertEqual(len(self.store.get_transcript("completed")), 1)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM deleted_meetings").fetchone()[0], 0)

    def test_single_failure_rolls_back_meeting_and_transcript(self):
        self.store.connection.execute("""
            CREATE TRIGGER fail_cascade BEFORE DELETE ON utterances
            BEGIN SELECT RAISE(ABORT, 'simulated failure'); END
        """)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.delete_meeting("completed")
        self.assertEqual(len(self.store.list_meetings()), 3)
        self.assertEqual(len(self.store.get_transcript("completed")), 1)

    def test_deleted_meeting_cannot_be_resurrected_by_late_events(self):
        self.store.delete_meeting("completed")
        self.store.close()
        self.store = MeetingStore(self.path)
        for kind in ("meeting_started", "recognized", "translated"):
            self.assertIsNone(self.store.record_event(event(kind, "completed")))
        self.assertEqual(self.store.get_transcript("completed"), [])
        self.assertNotIn("completed", [m["meeting_id"] for m in self.store.list_meetings()])

    def test_missing_delete_is_safe_and_foreign_keys_reject_orphans(self):
        self.assertEqual(self.store.delete_meeting("missing"), 0)
        with self.assertRaises(sqlite3.IntegrityError), self.store.connection:
            self.store.connection.execute("UPDATE utterances SET meeting_id='missing' WHERE meeting_id='active'")
        self.assertEqual(len(self.store.get_transcript("active")), 1)


class CommitNotificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage = HistoryStorage(Path(self.directory.name) / "history.sqlite3")
        self.storage.ready.result(3)

    def tearDown(self):
        self.storage.close().result(3)
        self.storage.thread.join(3)
        self.directory.cleanup()

    def test_saved_rows_are_pushed_after_commit_without_queries(self):
        self.storage.record_event(event("recognized")).result(3)
        first = self.storage.notifications.get_nowait()
        self.assertEqual(first["kind"], "history_changed")
        self.assertEqual(first["data"]["entry"]["translation_status"], "pending")
        self.storage.record_event(event("translated")).result(3)
        second = self.storage.notifications.get_nowait()
        self.assertEqual(second["data"]["entry"]["translated"], "Bonjour")
        with sqlite3.connect(self.storage.path) as reader:
            self.assertEqual(reader.execute("SELECT translated FROM utterances").fetchone()[0], "Bonjour")
        reader.close()
        self.assertTrue(self.storage.notifications.empty())

    def test_failed_commit_never_emits_live_update(self):
        self.storage.close().result(3)
        self.storage.thread.join(3)
        class FailWrites(MeetingStore):
            def record_event(self, event):
                raise sqlite3.OperationalError("simulated failure")
        self.storage = HistoryStorage(Path(self.directory.name) / "broken.sqlite3", repository_factory=FailWrites)
        self.storage.ready.result(3)
        with self.assertRaises(sqlite3.OperationalError):
            self.storage.record_event(event("recognized")).result(3)
        self.assertFalse(any(n["kind"] == "history_changed" for n in list(self.storage.notifications.queue)))

    def test_async_delete_and_bulk_delete_notifications(self):
        for meeting_id in ("one", "two", "active"):
            self.storage.record_event(event("recognized", meeting_id)).result(3)
        for meeting_id in ("one", "two"):
            self.storage.record_event(event("status", meeting_id, message="Stopped")).result(3)
        result = self.storage.delete_meeting("one", "delete-one").result(3)
        self.assertEqual(result["count"], 1)
        result = self.storage.clear_history("clear").result(3)
        self.assertEqual(result["count"], 1)
        notifications = [n for n in list(self.storage.notifications.queue) if n["kind"] == "history_deleted"]
        self.assertEqual([n["request_id"] for n in notifications], ["delete-one", "clear"])
        self.assertEqual([m["meeting_id"] for m in self.storage.list_meetings().result(3)], ["active"])

    def test_active_delete_failure_is_reported_and_worker_survives(self):
        self.storage.record_event(event("recognized", "active")).result(3)
        with self.assertRaises(ValueError):
            self.storage.delete_meeting("active", "rejected").result(3)
        notification = next(n for n in list(self.storage.notifications.queue) if n["kind"] == "delete_error")
        self.assertEqual(notification["request_id"], "rejected")
        self.assertIn("Active", notification["message"])
        self.storage.record_event(event("translated", "active")).result(3)
        self.assertEqual(self.storage.get_transcript("active").result(3)[0]["translated"], "Bonjour")

    def test_database_delete_failure_reports_error_without_success(self):
        self.storage.close().result(3)
        self.storage.thread.join(3)
        class FailDelete(MeetingStore):
            def delete_meeting(self, meeting_id):
                raise sqlite3.OperationalError("simulated disk failure")
        self.storage = HistoryStorage(Path(self.directory.name) / "failed-delete.sqlite3", repository_factory=FailDelete)
        self.storage.ready.result(3)
        self.storage.record_event(event("recognized")).result(3)
        self.storage.record_event(event("status", message="Stopped")).result(3)
        with self.assertRaises(sqlite3.OperationalError):
            self.storage.delete_meeting("meeting-a", "failed").result(3)
        notifications = list(self.storage.notifications.queue)
        self.assertTrue(any(n["kind"] == "delete_error" for n in notifications))
        self.assertFalse(any(n["kind"] == "history_deleted" for n in notifications))
        self.assertEqual(len(self.storage.get_transcript("meeting-a").result(3)), 1)

    def test_clear_history_during_recognition_audio_and_translation(self):
        self.storage.record_event(event("recognized", "old")).result(3)
        self.storage.record_event(event("status", "old", message="Stopped")).result(3)
        sdk = FakeSDK()
        sdk.audio_gate.clear()
        def factory(meeting_id, target, events):
            return AzureService(meeting_id, target, events, sdk=sdk,
                                translator=lambda *a, **kw: "Bonjour", credentials=CREDS)
        controller = SessionController(factory, storage=self.storage)
        controller.start(LANGUAGES["French"])
        self.assertTrue(sdk.started.wait(3))
        try:
            sdk.final("First sentence")
            wait_for(lambda: bool(sdk.spoken))
            self.assertEqual(self.storage.clear_history("clear").result(3)["count"], 1)
            sdk.final("Still recognizing after clear")
            wait_for(lambda: controller.service.pending == 0)
            self.storage.flush().result(3)
            entries = self.storage.get_transcript(controller.session_id).result(3)
            self.assertEqual(len(entries), 2)
            self.assertTrue(all(row["translated"] == "Bonjour" for row in entries))
            self.assertEqual(self.storage.get_transcript("old").result(3), [])
            self.assertEqual(sdk.starts, 1)
            self.assertFalse(controller.service.stop_requested.is_set())
        finally:
            sdk.audio_gate.set()
            controller.stop()
            controller.service.thread.join(3)
            self.assertFalse(controller.service.thread.is_alive())


def view_fixture():
    view = HistoryView.__new__(HistoryView)
    view.frame, view.storage = Mock(), Mock()
    view.transcript, view.notice = Mock(), Mock()
    view.delete_button, view.clear_button, view.latest_button = Mock(), Mock(), Mock()
    view.meeting_list = Mock()
    view.transcript.yview.return_value = (0, 1)
    view.transcript.index.return_value = "1.0"
    view.transcript.tag_ranges.return_value = ("2.0", "3.0")
    view.active = True
    view.selected_id = "meeting-a"
    view.selected_meeting = {"meeting_id": "meeting-a", "status": "active",
                             "started_at": event("recognized").timestamp, "ended_at": None}
    view.meetings = [dict(view.selected_meeting)]
    view.list_request, view.transcript_request = None, "reader"
    view.reader_loading = False
    view.pending_changes, view.reader_rows = {}, {}
    view.rendered_sequences = set()
    view.empty_reader = False
    view.delete_request = None
    view.list_refresh_scheduled = False
    return view


def saved_row(sequence=1, translated=""):
    entry = event("recognized", sequence=sequence).entry
    return {**entry.__dict__, "meeting_id": entry.session_id,
            "translated": translated, "translation_status": "translated" if translated else "pending"}


class LiveHistoryTests(unittest.TestCase):
    def test_new_entries_and_completed_translations_update_in_place(self):
        view = view_fixture()
        row = saved_row()
        view._history_changed({"meeting": view.selected_meeting, "entry": row})
        self.assertIn(1, view.rendered_sequences)
        view.transcript.delete.assert_not_called()
        view._history_changed({"meeting": view.selected_meeting, "entry": saved_row(translated="Bonjour")})
        view.transcript.delete.assert_called_once_with("2.0", "3.0")
        self.assertEqual(view.reader_rows[1]["translated"], "Bonjour")
        view.storage.get_transcript.assert_not_called()
        view.storage.list_meetings.assert_not_called()
        view.frame.after.assert_not_called()

    def test_older_reader_keeps_anchor_instead_of_jumping_to_bottom(self):
        view = view_fixture()
        view.transcript.yview.return_value = (0.1, 0.4)
        view._apply_saved_entry(saved_row())
        view.transcript.mark_set.assert_any_call("history_reader_top", "1.0")
        view.transcript.yview.assert_called_with("history_reader_top")
        view.transcript.see.assert_not_called()

    def test_near_bottom_follows_new_entry_and_duplicate_update_is_ignored(self):
        view = view_fixture()
        view.transcript.yview.return_value = (0.7, 0.98)
        row = saved_row()
        view._apply_saved_entry(row)
        view.transcript.see.assert_called_once_with("end")
        view.transcript.reset_mock()
        view._apply_saved_entry(row)
        view.transcript.insert.assert_not_called()

    def test_changes_during_snapshot_and_batched_render_are_preserved(self):
        view = view_fixture()
        view.reader_loading = True
        latest = saved_row(2, "Latest translation")
        view._history_changed({"meeting": view.selected_meeting, "entry": latest})
        rows = [saved_row(n) for n in range(1, 42)]
        view.handle_storage({"kind": "transcript", "request_id": "reader", "data": rows})
        self.assertTrue(view.reader_loading)
        newer = saved_row(3, "Arrived while rendering")
        view._history_changed({"meeting": view.selected_meeting, "entry": newer})
        callback = view.frame.after.call_args.args[1]
        callback()
        self.assertFalse(view.reader_loading)
        self.assertEqual(view.reader_rows[2]["translated"], "Latest translation")
        self.assertEqual(view.reader_rows[3]["translated"], "Arrived while rendering")
        self.assertEqual(len(view.rendered_sequences), 41)

    def test_unrelated_and_hidden_meetings_do_not_change_reader(self):
        view = view_fixture()
        view.handle_storage({"kind": "history_changed", "data": {
            "meeting": {**view.selected_meeting, "meeting_id": "other"}, "entry": saved_row()
        }})
        view.transcript.insert.assert_not_called()
        view.active = False
        view.handle_storage({"kind": "history_changed", "data": {
            "meeting": view.selected_meeting, "entry": saved_row()
        }})
        view.transcript.insert.assert_not_called()

    def test_empty_snapshot_replaced_by_first_saved_utterance(self):
        view = view_fixture()
        view.empty_reader = True
        view._apply_saved_entry(saved_row())
        view.transcript.delete.assert_called_once_with("1.0", "end")
        self.assertFalse(view.empty_reader)

    def test_out_of_order_new_row_inserted_before_later_row(self):
        view = view_fixture()
        view._apply_saved_entry(saved_row(2))
        view.transcript.reset_mock()
        view._apply_saved_entry(saved_row(1))
        view.transcript.index.assert_any_call("history_start_2")


class DeletionControlTests(unittest.TestCase):
    @patch("smart_translate_app.history_view.messagebox.askyesno", return_value=False)
    def test_cancel_prevents_individual_and_bulk_deletion(self, confirm):
        view = view_fixture()
        view.selected_meeting["status"] = "ended"
        view.meetings = [view.selected_meeting]
        view.delete_selected()
        view.clear_all()
        self.assertEqual(confirm.call_count, 2)
        self.assertEqual(confirm.call_args.kwargs["default"], "no")
        view.storage.delete_meeting.assert_not_called()
        view.storage.clear_history.assert_not_called()

    @patch("smart_translate_app.history_view.messagebox.askyesno", return_value=True)
    def test_active_selection_never_offers_individual_deletion(self, confirm):
        view = view_fixture()
        view.delete_selected()
        confirm.assert_not_called()
        view._update_delete_controls()
        view.delete_button.configure.assert_called_with(state="disabled")

    @patch("smart_translate_app.history_view.messagebox.askyesno", return_value=True)
    def test_confirmed_delete_refreshes_list(self, confirm):
        view = view_fixture()
        view.selected_meeting["status"] = "interrupted"
        view.delete_selected()
        request = view.delete_request
        view.storage.delete_meeting.assert_called_once_with("meeting-a", request)
        self.assertIn("permanently", confirm.call_args.args[1].lower())
        view.show_list = Mock()
        view.handle_storage({"kind": "history_deleted", "request_id": request,
                             "data": {"meeting_id": "meeting-a", "count": 1}})
        view.show_list.assert_called_once()
        self.assertIsNone(view.delete_request)

    @patch("smart_translate_app.history_view.messagebox.askyesno", return_value=True)
    def test_bulk_confirm_keeps_active_reader_and_refreshes_list(self, confirm):
        view = view_fixture()
        view.meetings.append({**view.selected_meeting, "meeting_id": "old", "status": "ended"})
        view.clear_all()
        request = view.delete_request
        view.storage.clear_history.assert_called_once_with(request)
        self.assertIn("Active meetings will be kept", confirm.call_args.args[1])
        view.refresh = Mock()
        view.handle_storage({"kind": "history_deleted", "request_id": request,
                             "data": {"meeting_id": None, "count": 1}})
        view.refresh.assert_called_once()
        self.assertEqual(view.selected_id, "meeting-a")

    def test_deletion_error_restores_controls_without_clearing_reader(self):
        view = view_fixture()
        view.selected_meeting["status"] = "ended"
        view.delete_request = "failed"
        view.handle_storage({"kind": "delete_error", "request_id": "failed", "message": "Deletion failed"})
        self.assertIsNone(view.delete_request)
        view.notice.configure.assert_called_with(text="Deletion failed")
        view.transcript.delete.assert_not_called()
        view.delete_button.configure.assert_called_with(state="normal")


if __name__ == "__main__":
    unittest.main()
