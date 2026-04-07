#!/usr/bin/env python3
"""
Test script for the offline STT engine.
Allows feeding a standalone audio file to verify transcription accuracy
before integrating with X-Plane.
"""

import argparse
import sys
import threading
import time

from ai_atc.voice.stt import ATCVoiceEngine

def main():
    parser = argparse.ArgumentParser(description="Test ATC STT model.")
    parser.add_argument("audio_file", help="Path to a test .wav file containing ATC audio.")
    args = parser.parse_args()

    print(f"Testing local STT with: {args.audio_file}")

    def on_transcription_complete(text: str):
        print(f"\n[RECEIVED TRANSCRIPTION]: {text}\n")
        # Exit after transcription
        sys.exit(0)

    def on_status_change(status: str):
        print(f"[STATUS UPDATE]: {status}")

    engine = ATCVoiceEngine(
        callback=on_transcription_complete,
        status_callback=on_status_change
    )
    
    engine.start()
    time.sleep(1) # Give it a second to load the model
    
    print("Pushing file to queue...")
    engine.transcribe_file(args.audio_file)

    try:
        # Keep main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()
        print("Test stopped.")

if __name__ == "__main__":
    main()
