"""
Cloud STT Engine — sends recorded pilot audio to Groq (Whisper) for
transcription, using a dynamic context-aware prompt to reduce hallucinations.

Architecture:
    AudioCapture → .wav file → STT queue → Groq Whisper → callback(text)

The engine accepts an optional ``get_context`` callback that provides the
current flight phase and last-instruction variables so the Whisper prompt
can be tailored to what the pilot is *expected* to say (e.g. readback
with specific altitude, runway, and squawk values).
"""
from __future__ import annotations

import logging
import os
import queue
import threading
from typing import Callable

logger = logging.getLogger(__name__)

# Confidence threshold — transcriptions below this average are rejected.
CONFIDENCE_THRESHOLD = 0.5

# Fallback prompt when no flight context is available.
DEFAULT_PROMPT = (
    "Aviation ATC radio communication. Callsigns, runway numbers, "
    "taxiway letters, altitudes, squawk codes, SID/STAR names. "
    "United Airlines, Delta, American, Speedbird."
)


def _build_dynamic_prompt(context: dict | None) -> str:
    """
    Build a Whisper initial_prompt that primes the model for the current
    flight phase.  Whisper uses this text as a "style guide" — not as a
    hard constraint — so the model is nudged toward the right vocabulary.
    """
    if not context:
        return DEFAULT_PROMPT

    phase = context.get("phase", "")
    variables = context.get("variables", {})
    callsign = variables.get("callsign", "")
    runway = variables.get("runway", "")
    altitude = variables.get("altitude", "")
    squawk = variables.get("squawk", "")
    destination = variables.get("destination", "")
    sid = variables.get("sid", "")

    # Phase-specific prompt fragments
    phase_prompts: dict[str, str] = {
        "PARKED": (
            f"Context: IFR clearance request. "
            f"Expect callsign {callsign}, destination {destination}, "
            f"radio check, request clearance."
        ),
        "CLEARANCE_DELIVERED": (
            f"Context: IFR clearance readback. "
            f"Expect: cleared to {destination}, {sid} departure, "
            f"runway {runway}, maintain {altitude}, squawk {squawk}."
        ),
        "PUSHBACK": (
            f"Context: Pushback and start request. "
            f"Expect callsign {callsign}, push and start, gate."
        ),
        "TAXI_OUT": (
            f"Context: Taxi instructions. "
            f"Expect runway {runway}, taxiway names (Alpha, Bravo, Charlie), "
            f"hold short."
        ),
        "HOLDING_SHORT": (
            f"Context: Takeoff clearance. "
            f"Expect holding short runway {runway}, ready for departure, "
            f"cleared for takeoff."
        ),
        "INITIAL_CLIMB": (
            f"Context: Departure contact. "
            f"Expect callsign {callsign}, passing altitude, climbing."
        ),
        "CLIMBING": (
            f"Context: Climb instruction readback. "
            f"Expect climb and maintain {altitude}, flight level."
        ),
        "CRUISING": (
            f"Context: En-route. "
            f"Expect callsign {callsign}, level {altitude}."
        ),
        "DESCENDING": (
            f"Context: Descent clearance readback. "
            f"Expect descend and maintain {altitude}, approach."
        ),
        "APPROACH": (
            f"Context: Approach vectors. "
            f"Expect heading, runway {runway}, ILS approach, cleared approach."
        ),
        "FINAL_APPROACH": (
            f"Context: Landing clearance. "
            f"Expect cleared to land, runway {runway}."
        ),
    }

    prompt = phase_prompts.get(phase, DEFAULT_PROMPT)

    # Always append the callsign and common ATC vocabulary
    return (
        f"{prompt} "
        f"Aviation ATC phraseology. Callsign: {callsign}."
    )


class ATCVoiceEngine:
    """
    Background worker that transcribes pilot audio files via Groq's
    Whisper API.  Files are processed sequentially from a queue; stale
    files (if a newer recording arrives) are skipped and deleted.
    """

    def __init__(
        self,
        callback: Callable[[str], None],
        status_callback: Callable[[str], None] | None = None,
        hearing_callback: Callable[[str], None] | None = None,
        get_context: Callable[[], dict | None] | None = None,
    ) -> None:
        self.callback = callback
        self.status_callback = status_callback
        self.hearing_callback = hearing_callback
        self.get_context = get_context

        self._queue: queue.Queue[str | None] = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Spin up the background transcription worker."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="stt-worker",
        )
        self._thread.start()
        logger.info("STT Engine background worker started.")

    def stop(self) -> None:
        """Signal the worker to shut down and wait for it."""
        self._running = False
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("STT Engine shut down.")

    def transcribe_file(self, filepath: str) -> None:
        """Enqueue an audio file for transcription."""
        self._queue.put(filepath)

    # ------------------------------------------------------------------ #
    #  Background worker                                                  #
    # ------------------------------------------------------------------ #

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

                # Skip stale files if a newer one is queued
                if not self._queue.empty():
                    logger.info("Skipping outdated audio file: %s", filepath)
                    self._cleanup_file(filepath)
                    continue

                if self.status_callback:
                    self.status_callback("thinking")

                # Build context-aware prompt
                context = self.get_context() if self.get_context else None
                prompt = _build_dynamic_prompt(context)
                logger.debug("STT prompt: %s", prompt[:120])

                logger.info("Transcribing %s via Groq (Whisper)...", filepath)

                with open(filepath, "rb") as f:
                    transcription = client.audio.transcriptions.create(
                        file=(filepath, f.read()),
                        model="whisper-large-v3-turbo",
                        prompt=prompt,
                        response_format="verbose_json",
                        language="en",
                        temperature=0.0,
                    )

                # --- Confidence scoring ---
                text = ""
                avg_confidence = 1.0

                if hasattr(transcription, "segments") and transcription.segments:
                    segments = transcription.segments
                    confidences = []
                    text_parts = []

                    for seg in segments:
                        text_parts.append(seg.get("text", ""))
                        if "avg_logprob" in seg and seg["avg_logprob"] is not None:
                            # avg_logprob is negative; closer to 0 = higher confidence
                            # Convert to 0-1 scale: e^(logprob)
                            import math
                            conf = math.exp(seg["avg_logprob"])
                            confidences.append(conf)

                    text = " ".join(text_parts).strip()
                    if confidences:
                        avg_confidence = sum(confidences) / len(confidences)
                elif hasattr(transcription, "text"):
                    text = transcription.text.strip()
                elif isinstance(transcription, dict) and "text" in transcription:
                    text = transcription["text"].strip()

                logger.info(
                    "Transcribed: '%s' (confidence: %.2f)", text, avg_confidence,
                )

                # Reject low-confidence transcriptions
                if avg_confidence < CONFIDENCE_THRESHOLD and text:
                    logger.warning(
                        "Transcription confidence %.2f below threshold %.2f — rejecting.",
                        avg_confidence, CONFIDENCE_THRESHOLD,
                    )
                    if self.status_callback:
                        self.status_callback("idle")
                    # Still fire the hearing callback so the user sees what was heard
                    if self.hearing_callback:
                        self.hearing_callback(f"[low confidence] {text}")
                    # Fire callback with special marker so the agent can respond
                    self.callback("__LOW_CONFIDENCE__")
                    self._cleanup_file(filepath)
                    continue

                if self.hearing_callback and text:
                    self.hearing_callback(text)

                if self.status_callback:
                    self.status_callback("idle")

                if text:
                    self.callback(text)

                self._cleanup_file(filepath)

            except queue.Empty:
                continue
            except Exception as e:
                logger.exception("Error during transcription: %s", e)
                if self.status_callback:
                    self.status_callback("error")

    @staticmethod
    def _cleanup_file(filepath: str) -> None:
        """Silently delete a temporary audio file."""
        try:
            os.unlink(filepath)
        except OSError:
            pass