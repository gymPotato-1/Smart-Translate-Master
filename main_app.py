"""Launch Smart Translate. Azure starts only when the user presses Start."""

import tkinter as tk

from smart_translate_app.application import SmartTranslateApplication


def main():
    root = tk.Tk()
    root.title("Smart Translate - Live Translation")
    root.geometry("800x480")
    root.minsize(800, 480)
    root.configure(bg="#101827")

    app = SmartTranslateApplication(root)
    root.mainloop()


if __name__ == "__main__":
    main()
