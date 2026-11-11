
import tkinter as tk
from tkinter import ttk
import urllib.request
import urllib.parse
import json
import threading

# ============================================
# AI TRANSLATION HEADSET
# Raspberry Pi Touchscreen Software
#
# Features:
# - Automatic text language detection
# - 39 target languages
# - Continuous speech display
# - Continuous translation display
# - Automatic word wrapping
# - Smart automatic scrolling
# - Scrollable translation history
# - Touchscreen support
# ============================================

LANGUAGES = {
    "English": "en",
    "中文": "zh-CN",
    "繁體中文": "zh-TW",
    "日本語": "ja",
    "한국어": "ko",
    "Español": "es",
    "Français": "fr",
    "Deutsch": "de",
    "Italiano": "it",
    "Português": "pt",
    "Русский": "ru",
    "العربية": "ar",
    "हिन्दी": "hi",
    "বাংলা": "bn",
    "اردو": "ur",
    "Türkçe": "tr",
    "Tiếng Việt": "vi",
    "ไทย": "th",
    "Bahasa Indonesia": "id",
    "Bahasa Melayu": "ms",
    "Nederlands": "nl",
    "Polski": "pl",
    "Українська": "uk",
    "Svenska": "sv",
    "Dansk": "da",
    "Norsk": "no",
    "Suomi": "fi",
    "Ελληνικά": "el",
    "עברית": "he",
    "Čeština": "cs",
    "Română": "ro",
    "Magyar": "hu",
    "தமிழ்": "ta",
    "తెలుగు": "te",
    "فارسی": "fa",
    "Kiswahili": "sw",
    "Filipino": "tl",
    "Català": "ca",
    "Hrvatski": "hr",
    "Slovenčina": "sk"
}

CODE_TO_NAME = {
    code.lower(): name
    for name, code in LANGUAGES.items()
}

CODE_TO_NAME["zh"] = "中文"
CODE_TO_NAME["zh-cn"] = "中文"
CODE_TO_NAME["zh-tw"] = "繁體中文"


class AITranslator:

    def __init__(self, root):
        self.root = root

        self.root.title("AI Translation Headset")
        self.root.geometry("800x480")
        self.root.minsize(600, 400)
        self.root.configure(bg="#101827")

        self.target_language = "zh-CN"
        self.request_number = 0

        # Keeps original speech history
        self.speech_history = []

        # Keeps translation history
        self.translation_history = []

        self.build_interface()

    # ========================================
    # UI HELPERS
    # ========================================

    def label(self, parent, text, size=13,
              color="#FFFFFF", bold=False):

        return tk.Label(
            parent,
            text=text,
            font=(
                "Arial",
                size,
                "bold" if bold else "normal"
            ),
            fg=color,
            bg="#101827"
        )

    def create_text_area(self, parent):

        frame = tk.Frame(
            parent,
            bg="#1E293B"
        )

        frame.pack(
            fill="both",
            expand=True,
            padx=15,
            pady=(3, 8)
        )

        text_box = tk.Text(
            frame,
            font=("Arial", 15),
            bg="#1E293B",
            fg="#FFFFFF",
            insertbackground="white",
            wrap="word",
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=8,
            spacing1=0,
            spacing2=0,
            spacing3=0,
            state="disabled",
            cursor="arrow"
        )

        scrollbar = tk.Scrollbar(
            frame,
            orient="vertical",
            command=text_box.yview
        )

        text_box.configure(
            yscrollcommand=scrollbar.set
        )

        scrollbar.pack(
            side="right",
            fill="y"
        )

        text_box.pack(
            side="left",
            fill="both",
            expand=True
        )

        # Mouse wheel scrolling
        def mouse_scroll(event):
            if event.num == 4:
                text_box.yview_scroll(-3, "units")
            elif event.num == 5:
                text_box.yview_scroll(3, "units")
            elif event.delta:
                direction = -1 if event.delta > 0 else 1
                text_box.yview_scroll(
                    direction * 3, "units"
                )
            return "break"

        text_box.bind("<MouseWheel>", mouse_scroll)
        text_box.bind("<Button-4>", mouse_scroll)
        text_box.bind("<Button-5>", mouse_scroll)

        # Touch drag scrolling
        touch_position = {"y": None}

        def touch_start(event):
            touch_position["y"] = event.y
            return "break"

        def touch_move(event):
            previous = touch_position["y"]

            if previous is not None:
                difference = previous - event.y

                if abs(difference) >= 3:
                    text_box.yview_scroll(
                        int(difference / 3),
                        "units"
                    )
                    touch_position["y"] = event.y

            return "break"

        def touch_end(event):
            touch_position["y"] = None
            return "break"

        text_box.bind("<ButtonPress-1>", touch_start)
        text_box.bind("<B1-Motion>", touch_move)
        text_box.bind("<ButtonRelease-1>", touch_end)

        return text_box

    # ========================================
    # BUILD SCREEN INTERFACE
    # ========================================

    def build_interface(self):

        # Header
        self.label(
            self.root,
            "AI TRANSLATOR",
            22,
            "#FFFFFF",
            True
        ).pack(pady=(8, 1))

        self.status = self.label(
            self.root,
            "READY",
            10,
            "#4ADE80",
            True
        )
        self.status.pack(pady=(0, 5))

        # Language selection section
        language_frame = tk.Frame(
            self.root,
            bg="#101827"
        )
        language_frame.pack(
            fill="x",
            padx=15,
            pady=3
        )

        left = tk.Frame(
            language_frame,
            bg="#101827"
        )
        left.pack(
            side="left",
            fill="x",
            expand=True
        )

        right = tk.Frame(
            language_frame,
            bg="#101827"
        )
        right.pack(
            side="right",
            fill="x",
            expand=True
        )

        self.label(
            left,
            "Detected Language",
            12,
            "#94A3B8"
        ).pack()

        self.detected_label = self.label(
            left,
            "Waiting...",
            17,
            "#60A5FA",
            True
        )
        self.detected_label.pack(pady=4)

        self.label(
            right,
            "Select Target Language",
            12,
            "#94A3B8"
        ).pack()

        self.language_var = tk.StringVar(
            value="中文"
        )

        self.language_selector = ttk.Combobox(
            right,
            textvariable=self.language_var,
            values=list(LANGUAGES.keys()),
            state="readonly",
            font=("Arial", 14),
            width=19,
            justify="center"
        )

        self.language_selector.pack(pady=4)

        self.language_selector.bind(
            "<<ComboboxSelected>>",
            self.change_language
        )

        # Original speech title
        self.label(
            self.root,
            "Original Speech",
            13,
            "#93C5FD",
            True
        ).pack(pady=(4, 0))

        # Original speech continuous text area
        self.original_box = self.create_text_area(
            self.root
        )

        # Translation title
        self.label(
            self.root,
            "Translation",
            13,
            "#93C5FD",
            True
        ).pack(pady=(2, 0))

        # Translation continuous text area
        self.translation_box = self.create_text_area(
            self.root
        )

        # Test input section
        test_frame = tk.Frame(
            self.root,
            bg="#101827"
        )

        test_frame.pack(
            fill="x",
            padx=15,
            pady=(2, 8)
        )

        self.input_box = tk.Entry(
            test_frame,
            font=("Arial", 13),
            bg="#1E293B",
            fg="white",
            insertbackground="white",
            relief="flat"
        )

        self.input_box.pack(
            side="left",
            fill="x",
            expand=True,
            ipady=7,
            padx=(0, 8)
        )

        self.input_box.bind(
            "<Return>",
            lambda event: self.test_translation()
        )

        self.translate_button = tk.Button(
            test_frame,
            text="Test",
            font=("Arial", 12, "bold"),
            bg="#2563EB",
            fg="white",
            relief="flat",
            command=self.test_translation,
            padx=16,
            pady=5
        )

        self.translate_button.pack(
            side="right"
        )

        # Back to latest button
        self.latest_button = tk.Button(
            self.root,
            text="Back to Latest",
            font=("Arial", 10),
            bg="#334155",
            fg="white",
            relief="flat",
            command=self.scroll_to_latest,
            pady=4
        )

        self.latest_button.pack(
            pady=(0, 5)
        )

    # ========================================
    # CONTINUOUS TEXT DISPLAY
    # ========================================

    def append_text(self, text_box, new_text):

        if not new_text:
            return

        # Check whether user is viewing latest text
        at_bottom = text_box.yview()[1] >= 0.99

        text_box.config(state="normal")

        existing = text_box.get(
            "1.0", "end-1c"
        )

        # Append continuously without new lines
        if existing:
            separator = (
                "" if existing.endswith((" ", "\n"))
                else " "
            )
            text_box.insert(
                "end",
                separator + new_text.strip()
            )
        else:
            text_box.insert(
                "end",
                new_text.strip()
            )

        text_box.config(state="disabled")

        # Auto-scroll only when user was at bottom
        if at_bottom:
            text_box.see("end")

    def scroll_to_latest(self):

        self.original_box.see("end")
        self.translation_box.see("end")

    # ========================================
    # LANGUAGE SELECTION
    # ========================================

    def change_language(self, event=None):

        name = self.language_var.get()

        self.target_language = LANGUAGES[name]

        self.status.config(
            text="TARGET: " + name,
            fg="#4ADE80"
        )

        # Previous translations remain unchanged.
        # New speech uses the new target language.

    # ========================================
    # TEST TRANSLATION
    # ========================================

    def test_translation(self):

        text = self.input_box.get().strip()

        if not text:
            return

        self.input_box.delete(0, "end")

        self.receive_speech(text)

    # ========================================
    # SPEECH INPUT
    # ========================================

    def receive_speech(self, recognized_text):

        # Safe when called from a microphone thread
        self.root.after(
            0,
            self.process_speech,
            recognized_text
        )

    def process_speech(self, text):

        if not text or not text.strip():
            return

        text = text.strip()

        self.speech_history.append(text)

        # Add new speech to original display
        self.append_text(
            self.original_box,
            text
        )

        self.request_number += 1

        request_id = self.request_number

        target = self.target_language

        self.status.config(
            text="TRANSLATING...",
            fg="#FACC15"
        )

        # Translation runs in background
        threading.Thread(
            target=self.translate_worker,
            args=(text, target, request_id),
            daemon=True
        ).start()

    # ========================================
    # ONLINE TRANSLATION
    # ========================================

    def translate_worker(
        self, text, target, request_id
    ):

        try:

            parameters = urllib.parse.urlencode({
                "client": "gtx",
                "sl": "auto",
                "tl": target,
                "dt": "t",
                "q": text
            })

            url = (
                "https://translate.googleapis.com/"
                "translate_a/single?"
                + parameters
            )

            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0"
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=15
            ) as response:

                result = json.loads(
                    response.read().decode("utf-8")
                )

            translated_text = "".join(
                part[0] or ""
                for part in result[0]
                if part and part[0]
            )

            if not translated_text:
                raise ValueError(
                    "Empty translation"
                )

            detected_code = (
                str(result[2]).lower()
                if len(result) > 2
                else ""
            )

            detected_name = CODE_TO_NAME.get(
                detected_code,
                detected_code or "Unknown"
            )

            self.root.after(
                0,
                self.translation_completed,
                translated_text,
                detected_name,
                request_id
            )

        except Exception as error:

            self.root.after(
                0,
                self.translation_failed,
                str(error),
                request_id
            )

    # ========================================
    # ORDERED TRANSLATION RESULTS
    # ========================================

    def translation_completed(
        self,
        translated,
        detected_name,
        request_id
    ):

        # Store result in correct speech order
        self.translation_history.append(
            (request_id, translated)
        )

        self.pending_results[request_id] = (
            translated,
            detected_name
        )

        self.display_pending_results()

    def translation_failed(
        self,
        error,
        request_id
    ):

        print("Translation error:", error)

        self.pending_results[request_id] = (
            "[Translation unavailable]",
            None
        )

        self.display_pending_results()

    def display_pending_results(self):

        # Display translations in original order,
        # even if online requests finish out of order.
        while self.next_result_id in self.pending_results:

            translated, detected = (
                self.pending_results.pop(
                    self.next_result_id
                )
            )

            self.append_text(
                self.translation_box,
                translated
            )

            if detected:
                self.detected_label.config(
                    text=detected
                )

            self.next_result_id += 1

        if self.next_result_id > self.request_number:
            self.status.config(
                text="READY",
                fg="#4ADE80"
            )

    # ========================================
    # INITIALIZE TRANSLATION QUEUE
    # ========================================

    pending_results = None
    next_result_id = 1


# ============================================
# RUN APPLICATION
# ============================================

if __name__ == "__main__":

    root = tk.Tk()

    app = AITranslator(root)

    # Translation result queue
    app.pending_results = {}
    app.next_result_id = 1

    root.mainloop()
