"""Immutable, serializable events for the UI and future meeting persistence."""

from dataclasses import asdict, dataclass
from datetime import datetime


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class TranscriptEntry:
    session_id: str
    sequence: int
    timestamp: str
    original: str
    cleaned: str
    source_language: str
    target_language: str
    target_name: str
    voice: str
    translated: str = ""
    error: str = ""


@dataclass(frozen=True)
class TranslationEvent:
    session_id: str
    kind: str
    timestamp: str
    message: str = ""
    entry: TranscriptEntry | None = None

    def to_dict(self):
        return asdict(self)
