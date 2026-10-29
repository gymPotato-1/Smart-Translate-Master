# First Vosk test, can delete
import json
import queue
from pathlib import Path

import sounddevice as sd
from vosk import Model, KaldiRecognizer


MODEL_PATH = (
    Path(__file__).resolve().parent
    / "language-models"
    / "vosk-model-small-en-us-0.15"
)

audio_queue = queue.Queue()


def audio_callback(indata, frames, time_info, status):
    if status:
        print("Audio warning:", status)

    audio_queue.put(bytes(indata))


def main():
    if not MODEL_PATH.is_dir():
        print("Model folder not found:")
        print(MODEL_PATH)
        print("Download and extract the Vosk model first.")
        return

    # Use the microphone's default sample rate.
    device_info = sd.query_devices(kind="input")
    sample_rate = int(device_info["default_samplerate"])

    print("Loading recognition model...")
    model = Model(str(MODEL_PATH))
    recognizer = KaldiRecognizer(model, sample_rate)

    print("\nMicrophone:", device_info["name"])
    print("Speak in English, then pause.")
    print("Press Ctrl+C to stop.\n")

    try:
        with sd.RawInputStream(
            samplerate=sample_rate,
            blocksize=8000,
            dtype="int16",
            channels=1,
            callback=audio_callback,
        ):
            while True:
                audio = audio_queue.get()

                if recognizer.AcceptWaveform(audio):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "")

                    if text:
                        print("Original:", text)

    except KeyboardInterrupt:
        remaining = json.loads(recognizer.FinalResult())
        text = remaining.get("text", "")

        if text:
            print("Original:", text)

        print("\nStopped.")


if __name__ == "__main__":
    main()