import os

import azure.cognitiveservices.speech as speechsdk


# Example: English speech -> Chinese text and Mandarin speech.
SOURCE_LANGUAGE = "en-US"
TARGET_LANGUAGE = "zh-Hans"
TARGET_VOICE = "zh-CN-XiaoxiaoNeural"


def main():
    key = os.getenv("SPEECH_KEY")
    region = os.getenv("SPEECH_REGION")

    if not key or not region:
        print("Set SPEECH_KEY and SPEECH_REGION in your terminal first.")
        return

    # Recognition and text translation.
    translation_config = speechsdk.translation.SpeechTranslationConfig(
        subscription=key,
        region=region,
    )
    translation_config.speech_recognition_language = SOURCE_LANGUAGE
    translation_config.add_target_language(TARGET_LANGUAGE)

    microphone = speechsdk.audio.AudioConfig(
        use_default_microphone=True
    )

    recognizer = speechsdk.translation.TranslationRecognizer(
        translation_config=translation_config,
        audio_config=microphone,
    )

    # Speak the translated text through the default audio output.
    speech_config = speechsdk.SpeechConfig(
        subscription=key,
        region=region,
    )
    speech_config.speech_synthesis_voice_name = TARGET_VOICE

    output = speechsdk.audio.AudioOutputConfig(
        use_default_speaker=True
    )

    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=output,
    )

    print("English -> Mandarin Chinese")
    print("Use headphones and select them as your default audio output.")

    while True:
        command = input("\nPress Enter to speak, or type q to quit: ")
        if command.strip().lower() == "q":
            break

        print("Listening... Say one short sentence, then pause.")

        result = recognizer.recognize_once_async().get()

        if result.reason == speechsdk.ResultReason.NoMatch:
            print("No speech recognized. Try again.")
            continue

        if result.reason == speechsdk.ResultReason.Canceled:
            print("Recognition canceled:", result.cancellation_details)
            continue

        if result.reason != speechsdk.ResultReason.TranslatedSpeech:
            print("Unexpected recognition result:", result.reason)
            continue

        translated_text = result.translations.get(TARGET_LANGUAGE)

        print("\nORIGINAL:")
        print(result.text)

        print("\nTRANSLATION:")
        print(translated_text or "(No translation returned)")

        if not translated_text:
            continue

        print("\nPlaying translation...")
        spoken = synthesizer.speak_text_async(translated_text).get()

        if spoken.reason == speechsdk.ResultReason.Canceled:
            details = (
                speechsdk.SpeechSynthesisCancellationDetails.from_result(
                    spoken
                )
            )
            print("Speech playback failed:", details)
        else:
            print("Finished.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as error:
        print(f"\nError: {error}")