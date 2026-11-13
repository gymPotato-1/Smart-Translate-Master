"""Input selection reaches recognition and survives into transcript metadata."""

import queue
import unittest
from unittest.mock import Mock

from test_phase2 import CREDS, FakeSDK, wait_for
from smart_translate_app.azure_service import AzureService
from smart_translate_app.languages import LANGUAGES
from smart_translate_app.live_view import LiveTranslationView
from smart_translate_app.session_controller import SessionController


class InputLanguageTests(unittest.TestCase):
    def run_recognition(self, source):
        sdk = FakeSDK()
        original = sdk.SpeechRecognizer
        sdk.SpeechRecognizer = Mock(side_effect=original)
        sdk.AutoDetectSourceLanguageResult = Mock(side_effect=sdk.AutoDetectSourceLanguageResult)
        events = queue.Queue()
        translator = Mock(return_value="Bonjour")
        service = AzureService("session", LANGUAGES["French"], events, sdk=sdk,
                               translator=translator, credentials=CREDS, source_language=source)
        service.start()
        try:
            self.assertTrue(sdk.started.wait(3))
            sdk.final("Um, hello.", language="ja-JP" if source else "en-US")
            wait_for(lambda: bool(sdk.spoken))
        finally:
            service.stop()
            service.thread.join(3)
        self.assertFalse(service.thread.is_alive())
        recognized = [e.entry for e in list(events.queue) if e.kind == "recognized"]
        self.assertEqual(len(recognized), 1)
        self.assertEqual(recognized[0].source_language, "en-US")
        self.assertEqual(recognized[0].cleaned, "hello.")
        self.assertEqual(translator.call_args.kwargs["source_language"], "en-US")
        options = sdk.SpeechRecognizer.call_args.kwargs
        if source:
            self.assertEqual(options["speech_config"].speech_recognition_language, "en-US")
            self.assertNotIn("auto_detect_source_language_config", options)
            sdk.AutoDetectSourceLanguageResult.assert_not_called()
        else:
            self.assertEqual(options["auto_detect_source_language_config"]["languages"],
                             [lang.speech for lang in LANGUAGES.values()])
            sdk.AutoDetectSourceLanguageResult.assert_called_once()

    def test_fixed_language(self):
        self.run_recognition(LANGUAGES["English"])

    def test_automatic_detection(self):
        self.run_recognition(None)

    def test_controller_snapshots_selected_input(self):
        factory = Mock()
        controller = SessionController(factory)
        self.assertTrue(controller.start(LANGUAGES["French"], LANGUAGES["English"]))
        self.assertEqual(factory.call_args.kwargs["source_language"], LANGUAGES["English"])
        self.assertFalse(controller.start(LANGUAGES["French"], LANGUAGES["Japanese"]))
        factory.assert_called_once()

    def test_ui_passes_selection_and_locks_until_stopped(self):
        view = LiveTranslationView.__new__(LiveTranslationView)
        view.controller = Mock(state="Starting")
        view.target_language = LANGUAGES["French"]
        for name in ("source_var", "source_selector", "transcript_box", "notice",
                     "status", "start_button", "stop_button"):
            setattr(view, name, Mock())
        for selection, expected in (("English", LANGUAGES["English"]), ("Auto detect", None)):
            view.source_var.get.return_value = selection
            view.start_session()
            view.controller.start.assert_called_with(LANGUAGES["French"], source_language=expected)
        for state in ("Starting", "Listening", "Translating", "Stopping", "Stopped"):
            view.controller.state = state
            view.refresh_controls()
            view.source_selector.configure.assert_called_with(
                state="readonly" if state == "Stopped" else "disabled")
