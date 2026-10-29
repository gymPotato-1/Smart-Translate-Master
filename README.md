# Smart-Translate-Master

**Setup on Windows**

Run these commands in a Command Prompt terminal inside VS Code.

1. Clone the repository

git clone https://github.com/gymPotato-1/Smart-Translate-Master.git
cd Smart-Translate-Master

If you already cloned and opened the repository, skip this step.

2. Create and activate a virtual environment

  py -m venv .venv
  .venv\Scripts\activate.bat

In VS Code, select the interpreter using:

Ctrl + Shift + P → Python: Select Interpreter → select .venv.

3. Install dependencies

  python -m pip install -r requirements.txt

4. Configure Azure credentials

Create an Azure Speech resource and obtain its key and region. Set them in the same CMD terminal where you will run the program:

  set "SPEECH_KEY=YOUR_AZURE_SPEECH_KEY"
  set "SPEECH_REGION=YOUR_AZURE_REGION"

Replace the placeholders with your resource's values. These settings must be entered again when opening a new terminal.

Never commit your actual key to GitHub or include it in screenshots.

**Run the Prototype**

Connect headphones and select the correct microphone and audio output in Windows.

With the virtual environment active and credentials configured, run:

  python translator.py

Press Enter to begin listening.

Speak one short sentence in the configured source language.

Pause to finish the utterance.

Review the original transcript and translated text.

Listen to the translated speech.

Type q at the next prompt to quit.

**Language Configuration**

The initial configuration in translator.py is English to Mandarin:

SOURCE_LANGUAGE = "en-US"
TARGET_LANGUAGE = "zh-Hans"
TARGET_VOICE = "zh-CN-XiaoxiaoNeural"

To change languages, update the source language, target language, and output voice together. Save the file and restart the program.

The current prototype uses a fixed source language; it does not automatically detect the speaker's language.

**Testing**

Check each stage separately:

Transcription: Does the original text match what was spoken?

Translation: Does the translated text preserve the meaning?

Playback: Does the audio match the translated text and use the correct language?

Include tests with numbers, names, technical terms, and negative statements. Record errors and have a bilingual speaker review translation quality.
