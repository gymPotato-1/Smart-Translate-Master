
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import azure.cognitiveservices.speech as speechsdk

from utterance_filter import remove_fillers
from text_translation import translate_text


LANGUAGES = {
    "1": {
        "name": "English",
        "speech": "en-US",
        "translate": "en",
        "voice": "en-US-JennyNeural",
    },
    "2": {
        "name": "Chinese",
        "speech": "zh-CN",
        "translate": "zh-Hans",
        "voice": "zh-CN-XiaoxiaoNeural",
    },
    "3": {
        "name": "Spanish",
        "speech": "es-ES",
        "translate": "es",
        "voice": "es-ES-ElviraNeural",
    },
    "4": {
        "name": "French",
        "speech": "fr-FR",
        "translate": "fr",
        "voice": "fr-FR-DeniseNeural",
    },
    "5": {
        "name": "Japanese",
        "speech": "ja-JP",
        "translate": "ja",
        "voice": "ja-JP-NanamiNeural",
    },
}


def select_language():
    print("\nSelect target language:")

    for number, language in LANGUAGES.items():
        print(f"{number}. {language['name']}")

    while True:
        choice = input("Enter 1-5: ").strip()

        if choice in LANGUAGES:
            return LANGUAGES[choice]

        print("Invalid selection.")


def main():
    key = os.getenv("SPEECH_KEY")
    region = os.getenv("SPEECH_REGION")

    translator_key = os.getenv("TRANSLATOR_KEY")
    translator_region = os.getenv("TRANSLATOR_REGION")

    if not all([key, region, translator_key, translator_region]):
        print("Missing Azure environment variables.")
        return

    target = select_language()

    print(f"\nTarget: {target['name']}")

    # Configure continuous speech recognition.
    speech_config = speechsdk.SpeechConfig(
        subscription=key,
        region=region,
    )

    # Automatically identify one of the five languages.
    auto_detect_config = (
        speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=[
                lang["speech"]
                for lang in LANGUAGES.values()
            ]
        )
    )

    # Continuous language identification.
    speech_config.set_property(
        property_id=speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode,
        value="Continuous",
    )

    microphone = speechsdk.audio.AudioConfig(
        use_default_microphone=True
    )

    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        auto_detect_source_language_config=auto_detect_config,
        audio_config=microphone,
    )

    # Configure text-to-speech.
    synthesis_config = speechsdk.SpeechConfig(
        subscription=key,
        region=region,
    )

    synthesis_config.speech_synthesis_voice_name = target["voice"]

    output = speechsdk.audio.AudioOutputConfig(
        use_default_speaker=True
    )

    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=synthesis_config,
        audio_config=output,
    )

    stop_event = threading.Event()
    speech_lock = threading.Lock()

    # Process finalized segments in order.
    executor = ThreadPoolExecutor(max_workers=1)

    def get_language(result):
        detected = (
            speechsdk.AutoDetectSourceLanguageResult(
                result
            ).language
        )
        return detected or ""

    def translate_segment(text, source_language):
        try:
            # Skip translation if source and target match.
            if source_language.split("-")[0] == (
                target["speech"].split("-")[0]
            ):
                translated = text
            else:
                translated = translate_text(
                    text,
                    translator_key,
                    translator_region,
                    source_language=source_language,
                    target_language=target["translate"],
                )

            print("\nTRANSLATION:")
            print(translated)

            if not translated:
                return

            # Speak one completed segment at a time.
            with speech_lock:
                spoken = synthesizer.speak_text_async(
                    translated
                ).get()

                if spoken.reason == speechsdk.ResultReason.Canceled:
                    print(
                        "Speech synthesis canceled:",
                        spoken.cancellation_details,
                    )

        except Exception as error:
            print("Translation error:", error)

    def on_recognizing(evt):
        # Partial results change as Azure recognizes speech.
        text = evt.result.text

        if text:
            print(f"\rLIVE: {text[:120]:120}", end="", flush=True)

    def on_recognized(evt):
        if evt.result.reason != speechsdk.ResultReason.RecognizedSpeech:
            return

        text = evt.result.text
        language = get_language(evt.result)

        if not language:
            print("\nCould not identify source language.")
            return

        cleaned = remove_fillers(text, language)

        if not cleaned:
            return

        print(f"\nSOURCE ({language}): {cleaned}")

        # Do not block the Azure recognition callback.
        executor.submit(
            translate_segment,
            cleaned,
            language,
        )

    def on_canceled(evt):
        print("\nRecognition canceled:", evt)
        stop_event.set()

    def on_stopped(evt):
        print("\nRecognition session stopped.")
        stop_event.set()

    recognizer.recognizing.connect(on_recognizing)
    recognizer.recognized.connect(on_recognized)
    recognizer.canceled.connect(on_canceled)
    recognizer.session_stopped.connect(on_stopped)

    print("\nStarting continuous translation...")
    print("Press Enter to stop.")
    print("Use headphones to prevent audio feedback.\n")

    recognizer.start_continuous_recognition_async().get()

    try:
        input()
    except KeyboardInterrupt:
        pass
    finally:
        recognizer.stop_continuous_recognition_async().get()
        executor.shutdown(wait=True)
        print("\nStopped.")


if __name__ == "__main__":
    main()
