"""
Cloud STT Engine — sends audio to Groq (Whisper) for transcription.
Uses an aviation-specific prompt for better accuracy with ATC phraseology.
"""
from __future__ import annotations
import logging
import os
import queue
import threading
logger = logging.getLogger(__name__)
AVIATION_STT_PROMPT = (
    "Transcribe the following pilot radio audio verbatim. "
    "This is ATC radio communication with aviation phraseology "
    "including callsigns, runway numbers, taxiway letters, "
    "SID/STAR names, and standard IFR procedures. "
    "Only return the transcribed text, nothing else."
)
class ATCVoiceEngine:
    def __init__(
        self,
        callback,
        status_callback=None,
        hearing_callback=None,
    ) -> None:
        self.callback = callback
        self.status_callback = status_callback
        self.hearing_callback = hearing_callback
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None
        self.model = None
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="stt-worker"
        )
        self._thread.start()
        logger.info("STT Engine background worker started.")
    def stop(self) -> None:
        self._running = False
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("STT Engine shut down.")
    def transcribe_file(self, filepath: str) -> None:
        self._queue.put(filepath)
    def _worker_loop(self) -> None:
        from dotenv import load_dotenv
        from groq import Groq
        load_dotenv()
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            logger.error("GROQ_API_KEY not found in .env. Cloud STT will fail.")
            return
        client = Groq(api_key=api_key)
        logger.info("Cloud STT Engine Ready (Groq Whisper).")
        if self.status_callback:
            self.status_callback("idle")
        while self._running:
            try:
                filepath = self._queue.get(timeout=1.0)
                if filepath is None:
                    break
                if not self._queue.empty():
                    logger.info("Skipping outdated audio file: %s", filepath)
                    try:
                        os.unlink(filepath)
                    except OSError:
                        pass
                    continue
                if self.status_callback:
                    self.status_callback("thinking")
                logger.info("Transcribing %s via Groq (Whisper)...", filepath)
                
                with open(filepath, "rb") as file:
                    transcription = client.audio.transcriptions.create(
                        file=(filepath, file.read()),
                        model="whisper-large-v3-turbo",
                        prompt="Aviation ATC phraseology, squawk, alpha, bravo, cleared to land, maintain, United Airlines, Speedbird, Delta.",
                        response_format="text",
                        language="en",
                        temperature=0.0
                    )
                
                text = transcription.strip()
                logger.info("Transcribed: '%s'", text)
                if self.hearing_callback and text:
                    self.hearing_callback(text)
                if self.status_callback:
                    self.status_callback("idle")
                if text:
                    self.callback(text)
                try:
                    os.unlink(filepath)
                except OSError:
                    pass
            except queue.Empty:
                continue
            except Exception as e:
                logger.exception("Error during transcription: %s", e)
                if self.status_callback:
                    self.status_callback("error")