
import re

# Common conversational fillers.
# Keep this list conservative to avoid deleting meaningful words.
FILLERS = {
    "en": ["um", "uh", "umm", "uhh"],
    "zh": ["嗯", "呃", "额"],
    "es": ["eh", "em", "mmm"],
    "fr": ["euh", "heu"],
    "ja": ["えーと", "えっと", "あのー"],
}

# Characters that indicate a likely sentence ending
END_PUNCTUATION = (".", "!", "?", "。", "！", "？")


def remove_fillers(text, language):
    """Remove common filler words for the detected language."""
    lang = language.lower().split("-")[0]
    fillers = FILLERS.get(lang, [])

    result = text

    for filler in sorted(fillers, key=len, reverse=True):
        if lang in ("zh", "ja"):
            # Conservative: only remove fillers at the start
            pattern = r"^\s*" + re.escape(filler) + r"[\s,，、]*"
        else:
            # Remove standalone words, not substrings
            pattern = (
                r"(?<!\w)" + re.escape(filler) +
                r"(?!\w)[\s,，]*"
            )

        result = re.sub(
            pattern,
            "",
            result,
            flags=re.IGNORECASE
        )

    return result.strip(" ,，、")


def is_complete_sentence(text):
    """Simple punctuation-based completion heuristic."""
    return text.rstrip().endswith(END_PUNCTUATION)


class UtteranceFilter:
    def __init__(self):
        self.buffer = ""
        self.language = None

    def process(self, text, language):
        """Return completed text or None if more is needed."""
        cleaned = remove_fillers(text, language)

        if not cleaned:
            return None

        lang = language.lower().split("-")[0]

        # Avoid joining different languages together
        if self.language and lang != self.language:
            self.buffer = ""

        self.language = lang

        if self.buffer:
            separator = "" if lang in ("zh", "ja") else " "
            self.buffer += separator + cleaned
        else:
            self.buffer = cleaned

        if is_complete_sentence(self.buffer):
            completed = self.buffer
            self.buffer = ""
            return completed

        return None

    def flush(self):
        """Release unfinished text at an explicit boundary."""
        result = self.buffer.strip()
        self.buffer = ""
        return result or None
