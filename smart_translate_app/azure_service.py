"""Background adapter for the original Azure pipeline; never accesses Tkinter."""

from dataclasses import replace
import os
import queue
import threading

from Modules.utterance_filter import remove_fillers
from .languages import LANGUAGES
from .models import TranscriptEntry, TranslationEvent, timestamp


class AzureService:
    def __init__(self, session_id, target, events, *, sdk=None, translator=None,
                 credentials=None, source_language=None):
        self.session_id = session_id
        self.target = target
        self.source_language = source_language
        self.events = events
        self.sdk = sdk
        self.translator = translator
        self.credentials = credentials
        self.stop_requested = threading.Event()
        self.lock = threading.RLock()
        self.accepting = False
        self.sequence = 0
        self.pending = 0
        self.translation_queue = queue.Queue()
        self.audio_queue = queue.Queue()
        self.thread = None

    def emit(self, kind, message="", entry=None):
        self.events.put(TranslationEvent(
            self.session_id, kind, timestamp(), message, entry
        ))

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        with self.lock:
            self.accepting = False
            self.stop_requested.set()

    def set_target(self, target):
        with self.lock:
            self.target = target

    def _error(self, context, error):
        # Do not expose credentials through SDK or HTTP exception messages.
        self.emit("error", f"{context} ({type(error).__name__}). Check credentials, network and audio settings.")

    def _run(self):
        recognizer = None
        workers = []
        try:
            names = ("SPEECH_KEY", "SPEECH_REGION", "TRANSLATOR_KEY", "TRANSLATOR_REGION")
            self.credentials = self.credentials or {name: os.getenv(name, "") for name in names}
            missing = [name for name in names if not self.credentials.get(name)]
            if missing:
                self.emit("error", "Missing environment variables: " + ", ".join(missing))
                return
            if self.sdk is None:
                import azure.cognitiveservices.speech as speechsdk
                self.sdk = speechsdk
            if self.translator is None:
                from Modules.text_translation import translate_text
                self.translator = translate_text
            sdk = self.sdk
            config = self._speech_config()
            recognition_options = {}
            if self.source_language is not None:
                config.speech_recognition_language = self.source_language.speech
            else:
                config.set_property(
                    property_id=sdk.PropertyId.SpeechServiceConnection_LanguageIdMode,
                    value="Continuous",
                )
                recognition_options["auto_detect_source_language_config"] = (
                    sdk.languageconfig.AutoDetectSourceLanguageConfig(
                        languages=[lang.speech for lang in LANGUAGES.values()]
                    )
                )
            recognizer = sdk.SpeechRecognizer(
                speech_config=config,
                audio_config=sdk.audio.AudioConfig(use_default_microphone=True),
                **recognition_options,
            )
            recognizer.recognizing.connect(self._on_partial)
            recognizer.recognized.connect(self._on_final)
            recognizer.canceled.connect(self._on_canceled)
            recognizer.session_stopped.connect(lambda event: self.stop())
            for target in (self._translate_loop, self._audio_loop):
                worker = threading.Thread(target=target, daemon=True)
                worker.start()
                workers.append(worker)
            with self.lock:
                self.accepting = not self.stop_requested.is_set()
            if not self.stop_requested.is_set():
                recognizer.start_continuous_recognition_async().get()
                self.emit("meeting_started")
                with self.lock:
                    if not self.stop_requested.is_set():
                        self.emit("status", "Translating" if self.pending else "Listening")
                self.stop_requested.wait()
        except Exception as error:
            self._error("Could not run Azure recognition", error)
        finally:
            self.stop()
            self.emit("status", "Stopping")
            if recognizer is not None:
                try:
                    recognizer.stop_continuous_recognition_async().get()
                except Exception as error:
                    self._error("Could not stop recognition", error)
            # Drain accepted text and audio before allowing another session.
            self.translation_queue.put(None)
            if workers:
                workers[0].join()
            self.audio_queue.put(None)
            if len(workers) > 1:
                workers[1].join()
            self.emit("status", "Stopped")

    def _speech_config(self):
        return self.sdk.SpeechConfig(
            subscription=self.credentials["SPEECH_KEY"],
            region=self.credentials["SPEECH_REGION"],
        )

    def _on_partial(self, event):
        with self.lock:
            if self.accepting and event.result.text:
                self.emit("partial", event.result.text)

    def _on_final(self, event):
        try:
            if event.result.reason != self.sdk.ResultReason.RecognizedSpeech:
                return
            original = event.result.text.strip()
            if not original:
                return
            source = (self.source_language.speech if self.source_language is not None
                      else self.sdk.AutoDetectSourceLanguageResult(event.result).language or "")
            with self.lock:
                if not self.accepting:
                    return
                target = self.target  # Snapshot at final recognition, not translation time.
                self.sequence += 1
                entry = TranscriptEntry(
                    self.session_id, self.sequence, timestamp(), original,
                    remove_fillers(original, source), source, target.translate,
                    target.name, target.voice,
                )
                self.emit("recognized", entry=entry)
                self.pending += 1
                self.emit("status", "Translating")
                self.translation_queue.put(entry)
        except Exception as error:
            self._error("Could not process recognized speech", error)

    def _on_canceled(self, event):
        self.emit("error", "Azure recognition canceled. Check credentials, network and microphone settings.")
        self.stop()

    def _translate_loop(self):
        while True:
            entry = self.translation_queue.get()
            if entry is None:
                return
            try:
                if not entry.cleaned:
                    translated = "[Filler-only speech; no translation]"
                elif entry.source_language.split("-")[0] == entry.target_language.split("-")[0]:
                    translated = entry.cleaned
                else:
                    translated = self.translator(
                        entry.cleaned, self.credentials["TRANSLATOR_KEY"],
                        self.credentials["TRANSLATOR_REGION"],
                        source_language=entry.source_language or None,
                        target_language=entry.target_language,
                    )
                    if not translated:
                        raise ValueError("Empty translation")
                completed = replace(entry, translated=translated)
                self.emit("translated", entry=completed)
                if entry.cleaned:
                    self.audio_queue.put(completed)
            except Exception as error:
                failed = replace(entry, error="Translation unavailable; check network and Azure settings.")
                self.emit("translation_failed", entry=failed)
                self._error("Translation failed", error)
            finally:
                with self.lock:
                    self.pending -= 1
                    if self.pending == 0 and not self.stop_requested.is_set():
                        self.emit("status", "Listening")

    def _audio_loop(self):
        synthesizers = {}
        while True:
            entry = self.audio_queue.get()
            if entry is None:
                return
            try:
                if entry.voice not in synthesizers:
                    config = self._speech_config()
                    config.speech_synthesis_voice_name = entry.voice
                    synthesizers[entry.voice] = self.sdk.SpeechSynthesizer(
                        speech_config=config,
                        audio_config=self.sdk.audio.AudioOutputConfig(use_default_speaker=True),
                    )
                result = synthesizers[entry.voice].speak_text_async(entry.translated).get()
                if result.reason == self.sdk.ResultReason.Canceled:
                    raise RuntimeError("Synthesis canceled")
                self.emit("audio_completed", entry=entry)
            except Exception as error:
                self._error("Audio playback failed", error)
