
import re

# Common English hesitation sounds.
FILLER_WORDS = [
    "um",
    "umm",
    "ummm",
    "uh",
    "uhh",
    "uhhh",
    "erm",
    "er",
    "hmm",
    "hm",
    "ahh",
]

# Match whole words only, ignoring capitalization.
FILLER_PATTERN = re.compile(
    r"\b(?:" + "|".join(FILLER_WORDS) + r")\b",
    flags=re.IGNORECASE,
)


def remove_fillers(text):
    if not text:
        return ""

    # Remove filler words.
    cleaned = FILLER_PATTERN.sub("", text)

    # Remove punctuation left behind by fillers.
    cleaned = re.sub(r"^\s*[,;:]+\s*", "", cleaned)
    cleaned = re.sub(r"\s+[,;:](?=\s|$)", "", cleaned)
    cleaned = re.sub(r"([,;:])\s*[,;:]+", r"\1", cleaned)

    # Fix spaces before punctuation.
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)

    # Remove extra spaces.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Capitalize the first letter.
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]

    return cleaned


if __name__ == "__main__":
    examples = [
        "Um, I think, uh, this is working.",
        "Uhh, can you explain this?",
        "The, um, meeting starts at 3 PM.",
        "I hmm think we should leave.",
        "Hello everyone!",
    ]

    for sentence in examples:
        print("Before:", sentence)
        print("After: ", remove_fillers(sentence))
        print()
