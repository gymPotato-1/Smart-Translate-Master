"""Hardware-free tests. All Azure components and translations are fakes."""

import json
import queue
import threading
import time
import unittest
from unittest.mock import Mock
from types import SimpleNamespace as NS

from smart_translate_app.azure_service import AzureService
from smart_translate_app.languages import LANGUAGES
from smart_translate_app.models import TranslationEvent, timestamp
from smart_translate_app.session_controller import SessionController
from smart_translate_app.live_view import LiveTranslationView


CREDS = {name: "fake" for name in (
    "SPEECH_KEY", "SPEECH_REGION", "TRANSLATOR_KEY", "TRANSLATOR_REGION"
)}


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Background operation timed out")
        time.sleep(0.005)


class Signal:
    def connect(self, callback):
        self.callback = callback

    def fire(self, event):
        self.callback(event)


class Future:
    def __init__(self, result=None, gate=None):
        self.result, self.gate = result, gate

    def get(self):
        if self.gate and not self.gate.wait(3):
            raise TimeoutError("Test gate timed out")
        return self.result


class FakeSDK:
    ResultReason = NS(RecognizedSpeech="recognized", Canceled="canceled")
    PropertyId = NS(SpeechServiceConnection_LanguageIdMode="language_mode")

    def __init__(self):
        self.audio_gate = threading.Event()
        self.audio_gate.set()
        self.start_gate = threading.Event()
        self.start_gate.set()
        self.started = threading.Event()
        self.starts = 0
        self.stops = 0
        self.spoken = []
        self.configurations = []
        self.audio = NS(AudioConfig=lambda **kw: kw, AudioOutputConfig=lambda **kw: kw)
        self.languageconfig = NS(AutoDetectSourceLanguageConfig=lambda **kw: kw)

    def SpeechConfig(self, **kwargs):
        config = NS(set_property=lambda **kw: None)
        self.configurations.append(config)
        return config

    def SpeechRecognizer(self, **kwargs):
        self.recognizer = NS(**{name: Signal() for name in (
            "recognizing", "recognized", "canceled", "session_stopped"
        )})

        def start():
            self.starts += 1
            self.started.set()
            return Future(gate=self.start_gate)

        def stop():
            self.stops += 1
            return Future()

        self.recognizer.start_continuous_recognition_async = start
        self.recognizer.stop_continuous_recognition_async = stop
        return self.recognizer

    def AutoDetectSourceLanguageResult(self, result):
        return NS(language=result.language)

    def SpeechSynthesizer(self, speech_config, audio_config):
        def speak(text):
            self.spoken.append((speech_config.speech_synthesis_voice_name, text))
            return Future(NS(reason="completed"), self.audio_gate)
        return NS(speak_text_async=speak)

    def final(self, text="Um, hello.", language="en-US"):
        self.recognizer.recognized.fire(NS(result=NS(
            text=text, language=language, reason="recognized"
        )))


class AzureServiceTests(unittest.TestCase):
    def setUp(self):
        self.sdk = FakeSDK()
        self.events = queue.Queue()
        self.calls = []

        def translate(text, key, region, **kwargs):
            self.calls.append((text, kwargs))
            return kwargs["target_language"] + ": " + text

        self.service = AzureService(
            "session-one", LANGUAGES["中文"], self.events,
            sdk=self.sdk, translator=translate, credentials=CREDS,
        )
        self.service.start()
        self.assertTrue(self.sdk.started.wait(3))

    def tearDown(self):
        self.sdk.audio_gate.set()
        self.sdk.start_gate.set()
        self.service.stop()
        self.service.thread.join(3)
        self.assertFalse(self.service.thread.is_alive())

    def drain(self):
        result = []
        while not self.events.empty():
            result.append(self.events.get_nowait())
        return result

    def test_live_target_snapshot_order_and_structured_events(self):
        self.sdk.audio_gate.clear()
        self.sdk.final()
        self.service.set_target(LANGUAGES["French"])
        self.sdk.final("Second sentence.")
        wait_for(lambda: len(self.calls) == 2)
        self.service.stop()
        self.sdk.audio_gate.set()
        self.service.thread.join(3)
        events = self.drain()
        entries = [event.entry for event in events if event.kind == "translated"]
        self.assertEqual([e.sequence for e in entries], [1, 2])
        self.assertEqual([e.target_language for e in entries], ["zh-Hans", "fr"])
        self.assertEqual(entries[0].original, "Um, hello.")
        self.assertNotIn("Um", entries[0].cleaned)
        self.assertEqual(self.sdk.starts, 1)
        self.assertEqual([voice for voice, _ in self.sdk.spoken], [
            LANGUAGES["中文"].voice, LANGUAGES["French"].voice
        ])
        json.dumps([event.to_dict() for event in events])
        self.assertEqual(events[-1].message, "Stopped")

    def test_audio_does_not_block_translation(self):
        self.sdk.audio_gate.clear()
        self.sdk.final("First.")
        wait_for(lambda: len(self.sdk.spoken) == 1)
        self.sdk.final("Second.")
        wait_for(lambda: len(self.calls) == 2)
        wait_for(lambda: self.service.pending == 0)
        self.assertEqual(len(self.sdk.spoken), 1)

    def test_translation_failure_keeps_recognizer_alive(self):
        def fail(*args, **kwargs):
            raise RuntimeError("secret fake credential")
        self.service.translator = fail
        self.sdk.final()
        wait_for(lambda: self.service.pending == 0)
        events = self.drain()
        self.assertTrue(any(e.kind == "translation_failed" for e in events))
        self.assertNotIn("secret", json.dumps([e.to_dict() for e in events]))
        self.assertFalse(self.service.stop_requested.is_set())

    def test_matching_language_bypasses_translation(self):
        self.service.set_target(LANGUAGES["English"])
        self.sdk.final("Hello.")
        wait_for(lambda: bool(self.sdk.spoken))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.sdk.spoken[0][1], "Hello.")

    def test_stop_rejects_late_callbacks(self):
        self.service.stop()
        self.sdk.final()
        self.assertEqual(self.service.sequence, 0)

    def test_cancellation_stops_cleanly(self):
        self.sdk.recognizer.canceled.fire(NS())
        self.service.thread.join(3)
        self.assertFalse(self.service.thread.is_alive())
        self.assertTrue(any(e.kind == "error" for e in self.drain()))

    def test_partial_event(self):
        self.sdk.recognizer.recognizing.fire(NS(result=NS(text="hello")))
        self.assertTrue(any(e.kind == "partial" and e.message == "hello" for e in self.drain()))

    def test_audio_failure_does_not_lose_translation(self):
        def fail(**kwargs):
            raise RuntimeError("Audio device unavailable")
        self.sdk.SpeechSynthesizer = fail
        self.sdk.final("Hello.")
        wait_for(lambda: self.service.pending == 0)
        self.service.stop()
        self.service.thread.join(3)
        events = self.drain()
        self.assertTrue(any(e.kind == "translated" for e in events))
        self.assertTrue(any(e.kind == "error" and "Audio" in e.message for e in events))

    def test_filler_only_keeps_original_without_audio(self):
        self.sdk.final("Um")
        wait_for(lambda: self.service.pending == 0)
        events = self.drain()
        self.assertTrue(any(e.kind == "recognized" and e.entry.original == "Um" for e in events))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.sdk.spoken, [])


class LifecycleTests(unittest.TestCase):
    def test_start_failure_is_reported(self):
        def fail(*args):
            raise RuntimeError("Unavailable")
        controller = SessionController(fail)
        self.assertFalse(controller.start(LANGUAGES["English"]))
        self.assertEqual(controller.state, "Stopped")
        self.assertEqual(controller.poll()[0].kind, "error")

    def test_missing_credentials_without_sdk(self):
        events = queue.Queue()
        service = AzureService("missing", LANGUAGES["English"], events,
                               credentials={name: "" for name in CREDS})
        service.start()
        service.thread.join(3)
        result = list(events.queue)
        self.assertEqual(result[0].kind, "error")
        self.assertIn("SPEECH_KEY", result[0].message)
        self.assertEqual(result[-1].message, "Stopped")

    def test_stop_during_startup(self):
        sdk = FakeSDK()
        sdk.start_gate.clear()
        events = queue.Queue()
        service = AzureService("starting", LANGUAGES["English"], events,
                               sdk=sdk, translator=lambda *a, **kw: "ok", credentials=CREDS)
        service.start()
        self.assertTrue(sdk.started.wait(3))
        service.stop()
        sdk.start_gate.set()
        service.thread.join(3)
        self.assertFalse(service.thread.is_alive())
        self.assertNotIn("Listening", [e.message for e in list(events.queue)])

    def test_controller_duplicate_start_stop_and_session_isolation(self):
        class Service:
            def __init__(self, *args): pass
            def start(self): pass
            def stop(self): pass
            def set_target(self, target): self.target = target
        controller = SessionController(Service)
        self.assertTrue(controller.start(LANGUAGES["English"]))
        first = controller.session_id
        self.assertFalse(controller.start(LANGUAGES["French"]))
        controller.stop()
        controller.events.put(TranslationEvent(first, "status", timestamp(), "Listening"))
        controller.poll()
        self.assertEqual(controller.state, "Stopping")
        controller.events.put(TranslationEvent(first, "status", timestamp(), "Stopped"))
        controller.poll()
        self.assertTrue(controller.start(LANGUAGES["French"]))
        self.assertNotEqual(first, controller.session_id)
        controller.events.put(TranslationEvent(first, "status", timestamp(), "Stopped"))
        self.assertEqual(controller.poll(), [])
        self.assertEqual(controller.state, "Starting")


class ViewTests(unittest.TestCase):
    def test_timestamped_pair_and_scroll_behavior_without_tk_window(self):
        from smart_translate_app.models import TranscriptEntry
        view = LiveTranslationView.__new__(LiveTranslationView)
        entry = TranscriptEntry("session", 1, timestamp(), "Hello", "Hello",
                                "en-US", "fr", "French", "voice", "Bonjour")
        for bottom, follows in ((1.0, True), (0.98, True), (0.5, False)):
            box = Mock()
            box.yview.return_value = (0.0, bottom)
            view.transcript_box = box
            view.show_entry(entry)
            inserts = box.insert.call_args_list
            self.assertIn("en-US → French", inserts[0].args[1])
            self.assertEqual(inserts[1].args[1], "Hello\n")
            self.assertEqual(box.see.called, follows)
            box.reset_mock()
            box.tag_ranges.return_value = ("3.0", "4.0")
            view.show_entry(entry, completed=True)
            box.delete.assert_called_once_with("3.0", "4.0")
            self.assertEqual(box.insert.call_args.args[1], "Bonjour\n")
            self.assertEqual(box.see.called, follows)


if __name__ == "__main__":
    unittest.main()
