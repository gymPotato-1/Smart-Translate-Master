import os

import azure.cognitiveservices.speech as speechsdk

from utterance_filter import remove_fillers
from text_translation import translate_text


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

    # Speech-to-text recognition.
    speech_config = speechsdk.SpeechConfig(
        subscription=key,
        region=region,
    )

    speech_config.speech_recognition_language = SOURCE_LANGUAGE

    microphone = speechsdk.audio.AudioConfig(
        use_default_microphone=True
    )

    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
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

    translator_key = os.getenv("TRANSLATOR_KEY")
    translator_region = os.getenv("TRANSLATOR_REGION")

    if not translator_key:
        print("Set TRANSLATOR_KEY in your terminal first.")
        return

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

        if result.reason != speechsdk.ResultReason.RecognizedSpeech:
            print("Unexpected recognition result:", result.reason)
            continue

        # Remove filler words from recognized speech.
        cleaned_text = remove_fillers(result.text)

        print("\nORIGINAL (FILTERED):")
        print(cleaned_text)

        if not cleaned_text:
            continue

        # Translate filtered English text into Mandarin.
        try:
            translated_text = translate_text(
                cleaned_text,
                translator_key,
                translator_region,
            )
        except Exception as error:
            print("Translation failed:", error)
            continue

        print("\nTRANSLATION:")
        print(translated_text)

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