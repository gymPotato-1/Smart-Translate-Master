# Meeting History

Launch from the project directory using the same Python environment and Azure
environment variables that passed Phase 2:

```powershell
python -B main_app.py
```

Azure starts only after pressing Start. History can be read without Azure
credentials. Run one application instance per data directory: opening a database
recovers meetings left active by its previous run.

## Local database

- Windows: `%LOCALAPPDATA%\SmartTranslate\meetings.sqlite3` (with a user-profile
  fallback if LOCALAPPDATA is unset).
- Raspberry Pi OS: `$XDG_DATA_HOME/smart-translate/meetings.sqlite3`, or
  `~/.local/share/smart-translate/meetings.sqlite3` when XDG_DATA_HOME is unset.

The location is independent of the working directory. No audio recordings are
stored. Transcripts are retained indefinitely unless explicitly deleted, with no automatic deletions or
history uploads. A warning appears once per application run when the database
and SQLite WAL total approximately 500 MiB; saving continues beyond that size.

## Manual Windows checks

1. Press Start, speak several sentences, change the target, and speak again.
   Confirm the original text, translations, timestamps and audio still work.
2. While recognition is active, open History. The current meeting should appear
   with an Active label. Tap it to read its saved transcript.
3. Continue speaking while viewing History. Confirm translated audio continues
   and saved utterances and translations appear without reopening the meeting.
4. Return to Live. Confirm all new entries are present, the target and Start/Stop
   state remain correct, and recognition has not restarted.
5. Scroll up while new speech arrives. Confirm automatic scrolling does not
   interrupt reading; use Back to Latest to follow new entries again.
6. Stop and wait for queued translation and audio to finish. Open History and
   confirm the meeting has a duration. Start and stop another meeting; both
   records should remain, newest first.
7. Close the window normally, relaunch with the same Windows user, and open
   History before pressing Start. Both transcripts should remain readable.
8. Optional interruption check: in a disposable test session, speak, wait for a
   translated entry, and end the application process without pressing Stop.
   Relaunch and confirm its meeting is marked Interrupted and committed text
   remains. Pending translations are marked unfinished; they are not retried.

## Automated checks

```powershell
python -B -m unittest discover -s tests -p "test_phase*.py" -v
```

Tests use temporary databases and fake Azure components. They include abrupt
process exit and WAL recovery, transaction rollback, asynchronous persistence,
late results, history navigation during translation, error handling, retention,
and the storage warning using a small injected threshold. No real credentials,
network calls, microphone or speakers are needed.

## Limits

- History receives committed changes automatically, without periodic transcript
  queries. Reading older messages preserves the scroll position; Back to Latest
  resumes following new entries.
- Normal Stop/close finishes accepted translation, audio and queued saves; a long
  audio queue can delay completion while the interface remains responsive.
- An unexpected exit can lose events still waiting in memory. SQLite transactions
  protect committed records. Interrupted work is labeled, not resumed.
- A storage failure leaves translation running and displays a persistent banner.
  Failed writes are not automatically replayed; resolve the cause and restart.
- Transcript reads run in the database worker and UI rendering uses batches, but
  very large histories still consume memory and can delay queued saves while a
  query runs. No retention cap is imposed.
- Raspberry Pi fonts, touch interaction, audio routing and performance still need
  hardware validation. Export, summaries and synchronization are absent.

## Explicit deletion

Use disposable test meetings for these checks:

1. Open a completed or interrupted meeting. Tap Delete Meeting, then cancel.
   Confirm the meeting and transcript remain.
2. Tap Delete Meeting again and confirm permanent deletion. Confirm History
   returns to its refreshed list and the meeting is absent after restart.
3. Start a new meeting and open it in History. Delete Meeting must be disabled.
4. With an active meeting and older saved meetings, tap Clear All History.
   Cancel once to verify nothing changes, then confirm. Completed and interrupted
   meetings should disappear; the active meeting, recognition, audio and saving
   must continue.
5. Relaunch and confirm the explicitly deleted records remain absent.

Both confirmation dialogs default to No and explain that deletion cannot be
undone. SQLite protects active meetings, cascades deletion to all associated
utterances, and rolls back the entire operation on failure. Only opaque deleted
meeting IDs are retained to prevent late callbacks from recreating deleted text.
Deletion does not necessarily shrink the database file immediately. There is no
automatic deletion, storage limit, or retention-policy change.
