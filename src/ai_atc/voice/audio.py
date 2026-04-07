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
class AudioCapture:
    def __init__(self, on_capture_complete: Callable[[str], None], status_callback: Callable[[str], None] | None = None, volume_callback: Callable[[float], None] | None = None, samplerate: int = 16000):
        self.samplerate = samplerate
        self.on_capture_complete = on_capture_complete
        self.status_callback = status_callback
        self.volume_callback = volume_callback
        self._is_recording = False
        self._buffer = []
        self._stream = None
        self._lock = threading.Lock()
        
        # Keep stream running continuously to avoid CoreAudio tear-down lockups
        if _AUDIO_SUPPORTED:
            try:
                self._stream = sd.InputStream(
                    samplerate=self.samplerate,
                    channels=1,
                    callback=self._audio_callback
                )
                self._stream.start()
            except Exception as e:
                logger.error("Failed to start background audio stream: %s", e)

    def start_recording(self) -> None:
        if not _AUDIO_SUPPORTED:
            logger.error("Audio packages (numpy/sounddevice/soundfile) missing. Cannot capture audio.")
            return

        with self._lock:
            if self._is_recording:
                return
            # Check if stream is active
            if not self._stream or not self._stream.active:
                logger.error("Audio stream is not active. Capture failed.")
                return
                
            self._is_recording = True
            self._buffer = []
            logger.info("Audio capture started.")
            if self.status_callback:
                self.status_callback("recording")

    def stop_recording(self) -> None:
        with self._lock:
            if not self._is_recording:
                return
            self._is_recording = False
            # We don't stop/close the Stream, we just stop collecting data.
            logger.info("Audio capture stopped.")
            
            if self.status_callback:
                self.status_callback("idle")
                
            if not self._buffer:
                logger.debug("Captured audio buffer is empty.")
                return
                
            threading.Thread(target=self._save_and_dispatch, daemon=True).start()

    def stop(self) -> None:
        """Fully shutdown the stream on app exit."""
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass

    def _audio_callback(self, indata, frames, time, status):
        if status:
            logger.warning("Audio capture status: %s", status)
        if self._is_recording:
            self._buffer.append(indata.copy())
            if self.volume_callback:
                # Calculate RMS safely on the audio thread
                rms = np.sqrt(np.mean(indata**2))
                self.volume_callback(float(rms))
    def _save_and_dispatch(self) -> None:
        if not _AUDIO_SUPPORTED:
            return
        with self._lock:
            audio_data = self._buffer
            self._buffer = []
        if not audio_data:
            return
        recording = np.concatenate(audio_data, axis=0)
        tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        filepath = tmp_wav.name
        tmp_wav.close()
        sf.write(filepath, recording, self.samplerate)
        logger.debug("Saved %d frames to %s", len(recording), filepath)
        self.on_capture_complete(filepath)