#!/usr/bin/env python3
"""
Jarvis → CMD  |  Sprachsteuerung für die Kommandozeile
Benötigte Pakete:
    pip install SpeechRecognition pyaudio pyperclip pyautogui
Falls pyaudio Probleme macht:
    pip install pipwin && pipwin install pyaudio
"""

import tkinter as tk
import threading
import time
import speech_recognition as sr
import pyperclip
import pyautogui

pyautogui.FAILSAFE = False


class JarvisCMD:
    def __init__(self):
        self.r = sr.Recognizer()
        self.listening = False

        self.win = tk.Tk()
        self.win.title("Jarvis → CMD")
        self.win.geometry("320x155")
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        self.win.configure(bg="#0d1117")

        # Status-Label
        self.lbl = tk.Label(
            self.win,
            text="Bereit",
            font=("Consolas", 11),
            bg="#0d1117",
            fg="#58a6ff",
        )
        self.lbl.pack(pady=(30, 8))

        # Mikrofon-Button
        self.btn = tk.Button(
            self.win,
            text="🎤  Sprechen",
            font=("Consolas", 13, "bold"),
            bg="#21262d",
            fg="#58a6ff",
            activebackground="#388bfd",
            activeforeground="#ffffff",
            relief="flat",
            cursor="hand2",
            padx=24,
            pady=10,
            bd=0,
            command=self.on_click,
        )
        self.btn.pack()

        # Hover-Effekte
        self.btn.bind("<Enter>", lambda e: self.btn.config(bg="#30363d"))
        self.btn.bind("<Leave>", lambda e: self.btn.config(bg="#21262d") if not self.listening else None)

        self.win.mainloop()

    def on_click(self):
        if self.listening:
            return
        self.listening = True
        self.btn.config(bg="#1f0f0f", fg="#f85149", text="⏺  Hört zu...")
        # Fenster minimieren → CMD / anderes Fenster bekommt Fokus
        self.win.iconify()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            with sr.Microphone() as src:
                self.r.adjust_for_ambient_noise(src, duration=0.3)
                try:
                    audio = self.r.listen(src, timeout=8, phrase_time_limit=15)
                except sr.WaitTimeoutError:
                    self._finish("Timeout – nichts gehört", "#d29922")
                    return
        except OSError:
            self._finish("Kein Mikrofon gefunden", "#f85149")
            return

        self._set_lbl("Erkenne Sprache...", "#d29922")

        try:
            text = self.r.recognize_google(audio, language="de-DE")

            # In Zwischenablage → Einfügen ins aktive Fenster (CMD)
            pyperclip.copy(text)
            time.sleep(0.15)
            pyautogui.hotkey("ctrl", "v")

            short = text[:38] + ("…" if len(text) > 38 else "")
            self._finish(f"✓  {short}", "#3fb950")

        except sr.UnknownValueError:
            self._finish("Nicht verstanden", "#f85149")
        except sr.RequestError:
            self._finish("Kein Internet / API-Fehler", "#f85149")

    def _set_lbl(self, text, fg="#58a6ff"):
        self.win.after(0, lambda: self.lbl.config(text=text, fg=fg))

    def _finish(self, msg, fg):
        self._set_lbl(msg, fg)
        self.listening = False

        def restore():
            self.win.deiconify()
            self.btn.config(text="🎤  Sprechen", bg="#21262d", fg="#58a6ff")
            self.win.after(2000, lambda: self.lbl.config(text="Bereit", fg="#58a6ff"))

        self.win.after(2500, restore)


if __name__ == "__main__":
    JarvisCMD()
