"""
Audio Capture — manages a persistent microphone stream and provides
push-to-talk recording via start_recording() / stop_recording().

Architecture:
    The CoreAudio stream is opened once at __init__ and stays open for
    the lifetime of the application.  This avoids macOS IPC lockups that
    occur when rapidly creating/destroying audio streams during PTT.

    When the user is NOT recording, the audio callback still fires but
    the samples are silently discarded.  When recording starts, samples
    are appended to an internal buffer.  On stop, the buffer is
    normalized, silence-trimmed, and saved to a temporary .wav file
    which is dispatched to the STT engine for transcription.
"""
from __future__ import annotations

import logging
import tempfile
import threading
from typing import Callable

try:
    import numpy as np
    import sounddevice as sd
    import soundfile as sf
    _AUDIO_SUPPORTED = True
except ImportError:
    _AUDIO_SUPPORTED = False

logger = logging.getLogger(__name__)

# VAD threshold — peak amplitude below this is considered silence.
SILENCE_THRESHOLD = 0.005

# Silence trimming threshold — frames below this amplitude are stripped
# from the head and tail to reduce Whisper hallucination from silence pads.
TRIM_THRESHOLD = 0.01


def _trim_silence(
    audio: "np.ndarray", samplerate: int = 16000, threshold: float = TRIM_THRESHOLD,
) -> "np.ndarray":
    """
    Strip leading and trailing silence from a 1-D audio array.
    Preserves a small ~100ms pad on each side for natural onset/offset.
    """
    abs_audio = np.abs(audio.flatten())
    above = np.where(abs_audio > threshold)[0]

    if len(above) == 0:
        return audio  # entirely silent — return as-is (VAD will catch it)

    pad = int(0.1 * samplerate)  # 100ms pad
    start = max(0, above[0] - pad)
    end = min(len(audio), above[-1] + pad)

    return audio[start:end]


class AudioCapture:
    """
    Push-to-talk audio capture with persistent microphone stream.

    The stream captures at the OS-native sample rate (typically 48 kHz
    on macOS) to avoid CoreAudio resampling artifacts.  Audio is
    normalized to 0 dBFS before export so Whisper receives loud,
    clear input regardless of the user's microphone gain setting.
    """

    def __init__(
        self,
        on_capture_complete: Callable[[str], None],
        status_callback: Callable[[str], None] | None = None,
        volume_callback: Callable[[float], None] | None = None,
        samplerate: int = 16000,
    ) -> None:
        self.samplerate = samplerate
        self.on_capture_complete = on_capture_complete
        self.status_callback = status_callback
        self.volume_callback = volume_callback

        self._is_recording = False
        self._buffer: list["np.ndarray"] = []
        self._stream: "sd.InputStream | None" = None
        self._lock = threading.Lock()

        # Open the microphone stream once and keep it alive.
        if _AUDIO_SUPPORTED:
            try:
                self._stream = sd.InputStream(
                    channels=1,
                    dtype="float32",
                    callback=self._audio_callback,
                )
                self.samplerate = int(self._stream.samplerate)
                self._stream.start()
                logger.info(
                    "Audio stream opened (sample rate: %d Hz).", self.samplerate,
                )
            except Exception as e:
                logger.error("Failed to start background audio stream: %s", e)

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def start_recording(self) -> None:
        """Begin capturing microphone audio into the internal buffer."""
        if not _AUDIO_SUPPORTED:
            logger.error(
                "Audio packages (numpy/sounddevice/soundfile) missing. "
                "Cannot capture audio.",
            )
            return

        with self._lock:
            if self._is_recording:
                return
            if not self._stream or not self._stream.active:
                logger.error("Audio stream is not active. Capture failed.")
                return

            self._is_recording = True
            self._buffer = []
            logger.info("Audio capture started.")

            if self.status_callback:
                self.status_callback("recording")

    def stop_recording(self) -> None:
        """Stop capturing and dispatch the recording for transcription."""
        with self._lock:
            if not self._is_recording:
                return
            self._is_recording = False
            logger.info("Audio capture stopped.")

            if self.status_callback:
                self.status_callback("idle")

            if not self._buffer:
                logger.debug("Captured audio buffer is empty.")
                return

            threading.Thread(
                target=self._save_and_dispatch, daemon=True,
            ).start()

    def stop(self) -> None:
        """Fully shutdown the stream on application exit."""
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    #  Internals                                                          #
    # ------------------------------------------------------------------ #

    def _audio_callback(self, indata, frames, time, status) -> None:
        """PortAudio callback — runs on the audio thread."""
        if status:
            logger.warning("Audio capture status: %s", status)

        if self._is_recording:
            self._buffer.append(indata.copy())

            if self.volume_callback:
                rms = float(np.sqrt(np.mean(indata ** 2)))
                self.volume_callback(rms)

    def _save_and_dispatch(self) -> None:
        """Concatenate, normalize, trim, and export the recording."""
        if not _AUDIO_SUPPORTED:
            return

        with self._lock:
            audio_data = self._buffer
            self._buffer = []

        if not audio_data:
            return

        recording = np.concatenate(audio_data, axis=0)

        # Voice activity detection — discard pure silence
        max_amp = float(np.max(np.abs(recording)))
        if max_amp < SILENCE_THRESHOLD:
            logger.info(
                "Recording was silent (peak %.4f). Discarding to prevent "
                "STT hallucinations.",
                max_amp,
            )
            return

        # Normalize to 0 dBFS for consistent Whisper input levels
        recording = recording / max_amp

        # Trim leading/trailing silence
        recording = _trim_silence(recording, self.samplerate)

        # Export as 16-bit PCM WAV (Whisper's expected format)
        tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        filepath = tmp_wav.name
        tmp_wav.close()

        sf.write(filepath, recording, self.samplerate, subtype="PCM_16")
        logger.debug(
            "Saved %d frames (%.1fs) to %s",
            len(recording),
            len(recording) / self.samplerate,
            filepath,
        )

        self.on_capture_complete(filepath)