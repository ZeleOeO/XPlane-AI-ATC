from __future__ import annotations

import logging
import os
import platform
import queue
import subprocess
import tempfile
import threading
import time

logger = logging.getLogger(__name__)

# FFmpeg radio filter chain
RADIO_FILTER = (
    "[0:a]"
    "highpass=f=300,"
    "lowpass=f=3400,"
    "compand=attacks=0.02:decays=0.25:points=-80/-900|-70/-20|0/-10|20/-8:gain=6,"
    "volume=1.2"
    "[a];"
    "anoisesrc=color=white:amplitude=0.01[ns];"
    "[a][ns]amix=inputs=2:weights=1 0.2:duration=shortest,"
    "volume=1.0,"
    "aecho=0.6:0.7:8:0.08,"
    "acompressor=threshold=0.6:ratio=6:attack=20:release=200"
)

def _has_command(cmd: str) -> bool:
    """Check if a command exists on the PATH."""
    try:
        subprocess.run([cmd, "-version" if cmd == "ffmpeg" else "--version"], capture_output=True, timeout=2)
        return True
    except Exception:
        return False

class ATCVoice:
    def __init__(
        self,
        rate: int = 200,
        volume: float = 1.0,
        voice_id: str | None = None,
        status_callback=None,
        radio_effect: bool = True,
    ) -> None:
        self._rate = rate
        self._volume = volume
        self._voice_id = voice_id
        self._status_callback = status_callback
        
        self._has_ffmpeg = _has_command("ffmpeg")
        self._has_ffplay = _has_command("ffplay")
        self._radio_effect = radio_effect and self._has_ffmpeg and self._has_ffplay
        
        self._os = platform.system()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        self._current_process = None

        if radio_effect and not self._radio_effect:
            logger.warning("FFmpeg/ffplay not found — radio effect and cross-platform playback limited.")

    def is_idle(self) -> bool:
        return self._current_process is None and self._queue.empty()

    def abort(self) -> None:
        """Immediately stop current playback and clear queue."""
        with self._queue.mutex:
            self._queue.queue.clear()
        if self._current_process:
            try:
                self._current_process.kill()
            except Exception:
                pass
            self._current_process = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._voice_loop, daemon=True, name="atc-voice")
        self._thread.start()
        logger.info("ATC voice engine started (OS: %s, radio_effect: %s).", self._os, self._radio_effect)

    def stop(self) -> None:
        self._running = False
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=2.0)

    def speak(self, text: str) -> None:
        self._queue.put(text)

    def _voice_loop(self) -> None:
        while self._running:
            try:
                text = self._queue.get(timeout=0.5)
                if text is None: break
                
                if self._status_callback: self._status_callback("talking")
                
                clean_text = text.replace('"', "").replace("'", "")
                
                if self._radio_effect:
                    self._speak_with_radio_effect(clean_text)
                else:
                    self._speak_fallback(clean_text)
                    
                if self._status_callback: self._status_callback("idle")
            except queue.Empty:
                continue
            except Exception:
                logger.exception("TTS processing error")

    def _speak_fallback(self, text: str) -> None:
        """Standard OS-specific speech without radio filters."""
        if self._os == "Darwin": # macOS
            cmd = ["say", "-r", str(self._rate)]
            if self._voice_id: cmd.extend(["-v", self._voice_id])
            cmd.append(text)
        elif self._os == "Windows":
            # Use PowerShell SAPI5
            ps_cmd = f"Add-Type -AssemblyName System.Speech; $speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; $speak.Rate = 2; $speak.Speak('{text}')"
            cmd = ["powershell", "-Command", ps_cmd]
        else:
            # Linux fallback
            cmd = ["espeak", text]

        try:
            self._current_process = subprocess.Popen(cmd)
            self._current_process.wait()
        except Exception as e:
            logger.error("Fallback TTS failed: %s", e)
        finally:
            self._current_process = None

    def _speak_with_radio_effect(self, text: str) -> None:
        """Generate speech to file -> filter via FFmpeg -> play via ffplay."""
        tmp_clean = tempfile.mktemp(suffix=".wav")
        tmp_radio = tempfile.mktemp(suffix=".wav")
        
        try:
            # 1. Generate clean speech file
            if self._os == "Darwin":
                gen_cmd = ["say", "-r", str(self._rate), "-o", tmp_clean, "--data-format=LEI16@16000", text]
            elif self._os == "Windows":
                ps_gen = f"Add-Type -AssemblyName System.Speech; $speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; $speak.SetOutputToWaveFile('{tmp_clean}'); $speak.Speak('{text}'); $speak.Dispose()"
                gen_cmd = ["powershell", "-Command", ps_gen]
            else:
                gen_cmd = ["espeak", "-w", tmp_clean, text]

            subprocess.run(gen_cmd, capture_output=True, timeout=20)
            
            # 2. Apply FFmpeg filter
            filter_cmd = ["ffmpeg", "-y", "-i", tmp_clean, "-filter_complex", RADIO_FILTER, tmp_radio]
            subprocess.run(filter_cmd, capture_output=True, timeout=10)
            
            # 3. Play back via ffplay
            # -nodisp -autoexit ensures it plays audio only and closes
            self._current_process = subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp_radio])
            self._current_process.wait()
            
        except Exception as e:
            logger.warning("Radio effect failed: %s. Falling back.", e)
            self._speak_fallback(text)
        finally:
            self._current_process = None
            for f in (tmp_clean, tmp_radio):
                if os.path.exists(f): 
                    try: os.unlink(f)
                    except: pass