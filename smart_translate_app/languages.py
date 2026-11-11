"""Azure mappings matching the five languages in the original prototype."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    name: str
    speech: str
    translate: str
    voice: str


LANGUAGES = {
    language.name: language for language in (
        Language("English", "en-US", "en", "en-US-JennyNeural"),
        Language("中文", "zh-CN", "zh-Hans", "zh-CN-XiaoxiaoNeural"),
        Language("Spanish", "es-ES", "es", "es-ES-ElviraNeural"),
        Language("French", "fr-FR", "fr", "fr-FR-DeniseNeural"),
        Language("Japanese", "ja-JP", "ja", "ja-JP-NanamiNeural"),
    )
}
