"""Transactional local history and a single thread owning all SQLite access."""

from concurrent.futures import Future
from dataclasses import asdict
import os
from pathlib import Path
import queue
import sqlite3
import threading

WARNING_BYTES = 500 * 1024 * 1024


def default_database_path():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "SmartTranslate" / "meetings.sqlite3"
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "smart-translate" / "meetings.sqlite3"


class MeetingStore:
    """Synchronous repository, used exclusively on its owning database thread."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=3)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA journal_mode = WAL")
            self.connection.execute("PRAGMA synchronous = FULL")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS meetings (
                    meeting_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    last_activity_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS utterances (
                    utterance_id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL REFERENCES meetings(meeting_id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    original TEXT NOT NULL,
                    cleaned TEXT NOT NULL,
                    translated TEXT NOT NULL DEFAULT '',
                    source_language TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    voice TEXT NOT NULL,
                    translation_status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    UNIQUE(meeting_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS meetings_started ON meetings(started_at);
                CREATE TABLE IF NOT EXISTS deleted_meetings (
                    meeting_id TEXT PRIMARY KEY
                );
                CREATE TRIGGER IF NOT EXISTS protect_active_meeting
                BEFORE DELETE ON meetings WHEN OLD.status='active'
                BEGIN SELECT RAISE(ABORT, 'Active meetings cannot be deleted'); END;
            """)
            # Never guess an end time or discard previously committed work.
            with self.connection:
                self.connection.execute("UPDATE meetings SET status='interrupted' WHERE status='active'")
                self.connection.execute("""
                    UPDATE utterances SET translation_status='interrupted',
                        error='Translation was unfinished when the application closed.'
                    WHERE translation_status='pending'
                """)
        except Exception:
            self.connection.close()
            raise

    def _begin(self, meeting_id, started_at):
        if self.connection.execute("SELECT 1 FROM deleted_meetings WHERE meeting_id=?", (meeting_id,)).fetchone():
            return False
        self.connection.execute("""
            INSERT OR IGNORE INTO meetings(meeting_id, started_at, last_activity_at)
            VALUES (?, ?, ?)
        """, (meeting_id, started_at, started_at))
        return True

    def record_event(self, event):
        meeting_id = event.session_id
        with self.connection:
            if event.kind == "meeting_started":
                if not self._begin(event.session_id, event.timestamp):
                    return None
            elif event.kind in ("recognized", "translated", "translation_failed") and event.entry:
                entry = event.entry
                # Entry identity is authoritative, even for a late result.
                meeting_id = entry.session_id
                if not self._begin(entry.session_id, entry.timestamp):
                    return None
                values = asdict(entry)
                values.update(
                    utterance_id=f"{entry.session_id}:{entry.sequence}",
                    meeting_id=entry.session_id,
                    translation_status={"recognized": "pending", "translated": "translated",
                                        "translation_failed": "failed"}[event.kind],
                )
                self.connection.execute("""
                    INSERT INTO utterances VALUES (
                        :utterance_id, :meeting_id, :sequence, :timestamp, :original,
                        :cleaned, :translated, :source_language, :target_language,
                        :target_name, :voice, :translation_status, :error
                    ) ON CONFLICT(meeting_id, sequence) DO UPDATE SET
                        translated=excluded.translated,
                        translation_status=excluded.translation_status,
                        error=excluded.error
                    WHERE excluded.translation_status != 'pending'
                """, values)
                self.connection.execute("""
                    UPDATE meetings SET last_activity_at=? WHERE meeting_id=?
                """, (event.timestamp, entry.session_id))
            elif event.kind == "status" and event.message == "Stopped":
                self.connection.execute("""
                    UPDATE meetings SET ended_at=?, last_activity_at=?, status='ended'
                    WHERE meeting_id=? AND status='active'
                """, (event.timestamp, event.timestamp, event.session_id))
        meeting = self.connection.execute("SELECT * FROM meetings WHERE meeting_id=?", (meeting_id,)).fetchone()
        if meeting is None:
            return None
        row = None
        if event.entry:
            row = self.connection.execute(
                "SELECT * FROM utterances WHERE meeting_id=? AND sequence=?",
                (meeting_id, event.entry.sequence),
            ).fetchone()
        return {"meeting": dict(meeting), "entry": dict(row) if row else None}

    def delete_meeting(self, meeting_id):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute("SELECT status FROM meetings WHERE meeting_id=?", (meeting_id,)).fetchone()
            if row is None:
                return 0
            if row["status"] not in ("ended", "interrupted"):
                raise ValueError("Active meetings cannot be deleted.")
            self.connection.execute("INSERT OR IGNORE INTO deleted_meetings VALUES (?)", (meeting_id,))
            return self.connection.execute("DELETE FROM meetings WHERE meeting_id=?", (meeting_id,)).rowcount

    def clear_history(self):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute("""
                INSERT OR IGNORE INTO deleted_meetings
                SELECT meeting_id FROM meetings WHERE status IN ('ended', 'interrupted')
            """)
            return self.connection.execute("DELETE FROM meetings WHERE status IN ('ended', 'interrupted')").rowcount

    def list_meetings(self):
        return [dict(row) for row in self.connection.execute("""
            SELECT meetings.*, (SELECT count(*) FROM utterances
                WHERE utterances.meeting_id=meetings.meeting_id) AS utterance_count
            FROM meetings ORDER BY julianday(started_at) DESC, meeting_id DESC
        """)]

    def get_transcript(self, meeting_id):
        return [dict(row) for row in self.connection.execute("""
            SELECT * FROM utterances WHERE meeting_id=? ORDER BY sequence
        """, (meeting_id,))]

    def storage_bytes(self):
        return sum(path.stat().st_size for path in (
            self.path, Path(str(self.path) + "-wal")
        ) if path.exists())

    def close(self):
        self.connection.close()


class HistoryStorage:
    """Nonblocking FIFO API. Futures are for tests; Tk uses notifications."""

    def __init__(self, path=None, *, warning_bytes=WARNING_BYTES, repository_factory=MeetingStore):
        self.path = Path(path) if path is not None else default_database_path()
        self.warning_bytes = warning_bytes
        self.repository_factory = repository_factory
        self.jobs = queue.Queue()
        self.notifications = queue.Queue()
        self.ready = Future()
        self.warning_sent = False
        self.error_sent = False
        self.closed = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _submit(self, operation, value=None, request_id=None):
        future = Future()
        if self.closed:
            future.set_exception(RuntimeError("History storage is closed"))
        else:
            self.jobs.put((operation, value, request_id, future))
        return future

    def record_event(self, event):
        if event.kind in ("meeting_started", "recognized", "translated", "translation_failed") or (
            event.kind == "status" and event.message == "Stopped"
        ):
            return self._submit("record", event)

    def list_meetings(self, request_id=None):
        return self._submit("meetings", request_id=request_id)

    def get_transcript(self, meeting_id, request_id=None):
        return self._submit("transcript", meeting_id, request_id)

    def delete_meeting(self, meeting_id, request_id=None):
        return self._submit("delete_meeting", meeting_id, request_id)

    def clear_history(self, request_id=None):
        return self._submit("clear_history", request_id=request_id)

    def flush(self):
        return self._submit("flush")

    def close(self):
        future = self._submit("close")
        self.closed = True
        return future

    def _report_error(self, error):
        if not self.error_sent:
            self.error_sent = True
            self.notifications.put({
                "kind": "storage_error",
                "message": f"History storage failed ({type(error).__name__}). Translation can continue, but saving may be incomplete. Restart after checking disk space and permissions.",
            })

    def _check_size(self, repository):
        if not self.warning_sent and repository.storage_bytes() >= self.warning_bytes:
            self.warning_sent = True
            self.notifications.put({
                "kind": "storage_warning",
                "message": "Local history is approximately 500 MB or larger. Check available storage. No history is deleted automatically; recording continues.",
            })

    def _run(self):
        repository = None
        try:
            repository = self.repository_factory(self.path)
            self._check_size(repository)
            self.ready.set_result(True)
        except Exception as error:
            self._report_error(error)
            self.ready.set_exception(error)
        while True:
            operation, value, request_id, future = self.jobs.get()
            try:
                if operation == "close":
                    if repository:
                        repository.close()
                    future.set_result(True)
                    return
                if repository is None:
                    raise sqlite3.OperationalError("History database unavailable")
                if operation == "record":
                    change = repository.record_event(value)
                    if change:
                        self.notifications.put({"kind": "history_changed", "data": change})
                    self._check_size(repository)
                    result = None
                elif operation == "meetings":
                    result = repository.list_meetings()
                elif operation == "transcript":
                    result = repository.get_transcript(value)
                elif operation in ("delete_meeting", "clear_history"):
                    count = repository.delete_meeting(value) if operation == "delete_meeting" else repository.clear_history()
                    result = {"count": count, "meeting_id": value}
                    self.notifications.put({"kind": "history_deleted", "request_id": request_id, "data": result})
                else:
                    result = None
                if operation in ("meetings", "transcript"):
                    self.notifications.put({"kind": operation, "request_id": request_id, "data": result})
                future.set_result(result)
            except Exception as error:
                if not isinstance(error, ValueError):
                    self._report_error(error)
                if operation in ("delete_meeting", "clear_history"):
                    self.notifications.put({
                        "kind": "delete_error", "request_id": request_id,
                        "message": str(error) if isinstance(error, ValueError) else "Deletion failed. No records were deleted. Check storage and try again.",
                    })
                future.set_exception(error)
                if request_id is not None and operation not in ("delete_meeting", "clear_history"):
                    self.notifications.put({"kind": "query_error", "request_id": request_id})
                if operation == "close":
                    return
