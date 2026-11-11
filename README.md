# Smart-Translate-Master

A speech-to-speech translation system using Microsoft Azure Speech and Translator services. The project recognizes spoken language, removes unnecessary filler words, translates the cleaned text, and generates translated audio.

## Setup on Windows

Run these commands in a **Command Prompt (CMD)** terminal inside VS Code.

### 1. Clone the repository

```cmd
git clone https://github.com/gymPotato-1/Smart-Translate-Master.git
cd Smart-Translate-Master
```

If you already cloned and opened the repository, skip this step.

### 2. Create and activate a virtual environment

Python 3.11 or 3.12 is recommended for compatibility.

```cmd
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
```

If Python 3.11 is unavailable, use a supported installed Python version.

In VS Code, select the interpreter:

`Ctrl + Shift + P` → `Python: Select Interpreter` → select `.venv`.

### 3. Install dependencies

```cmd
python -m pip install -r requirements.txt
```

The `requirements.txt` file should include:

```text
azure-cognitiveservices-speech
requests
```

### 4. Configure Azure credentials

This project requires access to two Azure services:

**Azure Speech**
- Speech-to-text recognition
- Text-to-speech generation

**Azure Translator**
- Text translation after filler-word removal

Create the required resources through the [Azure Portal](https://portal.azure.com/).

Obtain the API key and region for each resource.

Set the environment variables in the same CMD terminal where you will run the program:

```cmd
set "SPEECH_KEY=YOUR_AZURE_SPEECH_KEY"
set "SPEECH_REGION=eastus"

set "TRANSLATOR_KEY=YOUR_AZURE_TRANSLATOR_KEY"
set "TRANSLATOR_REGION=eastus"
```

Replace the placeholder keys and regions with your resource values.

These settings are temporary and must be entered again when opening a new terminal.

**Security:** Never commit API keys to GitHub or include them in screenshots.

### 5. Verify environment variables

In CMD:

```cmd
if defined SPEECH_KEY (echo Speech key is set) else (echo Speech key is missing)
if defined TRANSLATOR_KEY (echo Translator key is set) else (echo Translator key is missing)
```

Both keys should be set before running the program.

## Run the Prototype

Connect headphones and select the correct microphone and audio output in Windows.

With the virtual environment active and Azure credentials configured, run:

```cmd
python Modules/translator.py
```

1. Select target language by entering a number.
2. Start speaking.
3. The translator module will display both original and translated text.
4. Press Enter to stop.

## Translation Pipeline

```text
Microphone
    ↓
Azure Speech-to-Text
    ↓
Utterance Filter
    ↓
Azure Text Translator
    ↓
Translated Text
    ↓
Azure Text-to-Speech
    ↓
Speaker / Headphones
```

### Utterance Filtering

The `utterance_filter.py` module uses regular expressions to remove common hesitation words.

Example:

**Original speech:**

"Um, I think, uh, we should start the meeting."

**Filtered text:**

"I think we should start the meeting."

The cleaned text is sent to Azure Translator instead of the unfiltered transcription.

This reduces unnecessary filler words in the displayed text, translation, and generated audio.

## Testing

Test each component separately.

### 1. Speech Recognition

- Does Azure correctly recognize spoken sentences?
- Can it recognize academic vocabulary?
- Does background noise affect transcription accuracy?

### 2. Utterance Filtering

- Does the filter remove "um," "uh," and similar filler words?
- Does it preserve meaningful words?
- Does the cleaned text maintain the original meaning?

### 3. Text Translation

- Does Azure translate the filtered text correctly?
- Does the translation preserve the meaning of the original sentence?
- Does filtering improve translation quality?

### 4. Text-to-Speech

- Does the generated audio match the translated text?
- Is the output language correct?
- Is the audio understandable?

### 5. End-to-End Testing

Test the complete pipeline from microphone input to translated audio output.

Record transcription accuracy, translation accuracy, filler removal performance, and overall response time.

## Future Improvements

- Improved recognition of technical vocabulary
- Noise reduction for microphone input
- Improved sentence segmentation for long speech
- Raspberry Pi integration
- Touchscreen interface for language selection and text display

## Technologies

- Python
- Microsoft Azure Speech SDK
- Microsoft Azure Translator API
- Regular expressions (`re`)
- Requests library
- Raspberry Pi (planned hardware integration)

## References

- [Azure Speech SDK Documentation](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/)
- [Azure Translator Documentation](https://learn.microsoft.com/en-us/azure/ai-services/translator/)
- [Python Regular Expressions](https://docs.python.org/3/library/re.html)
