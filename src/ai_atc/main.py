from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import threading
import time
from pathlib import Path

from ai_atc.atc.controller import ATCController
from ai_atc.config import config
from ai_atc.flightplan.flight_plan import (
    FlightPlan,
    load_flight_plan,
    fetch_from_simbrief,
)
from ai_atc.navdata.airport import AirportParser
from ai_atc.navdata.procedures import CIFPParser
from ai_atc.voice.audio import AudioCapture
from ai_atc.voice.llm_agent import GenerativeATCAgent
from ai_atc.voice.stt import ATCVoiceEngine
from ai_atc.voice.tts import ATCVoice
from ai_atc.weather.metar import MetarService
from ai_atc.xplane.aircraft import AircraftStateManager
from ai_atc.xplane.connection import XPlaneConnection
from ai_atc.ui.gui import ATCApp

logger = logging.getLogger("ai_atc")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Air Traffic Controller for X-Plane",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Default values now pulled from config settings if not provided
    parser.add_argument("--airport", default="KJFK", help="Airport ICAO code")
    parser.add_argument("--callsign", default=config.get("callsign", "N12345"), help="Aircraft callsign")
    parser.add_argument("--flight-plan", type=str, default="", help="Path to flight plan JSON")
    parser.add_argument("--simbrief", type=str, default=config.get("simbrief_username", ""), help="SimBrief Username")
    parser.add_argument("--xplane-host", default="127.0.0.1")
    parser.add_argument("--xplane-port", type=int, default=49000)
    parser.add_argument("--listen-port", type=int, default=49008)
    parser.add_argument("--xplane-path", default=config.get("xplane_path", ""), help="Path to X-Plane installation")
    parser.add_argument("--no-voice", action="store_true", help="Disable TTS output")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()

def run_background_loop(aircraft_mgr, controller, xp_conn, voice_out, gui):
    """Main loop for X-Plane telemetry updates and ATIS playback."""
    logger.info("Background X-Plane update loop started.")
    last_instruction_count = 0
    last_connected = False
    was_on_atis = False
    atis_last_played_time = 0.0

    while True:
        try:
            if not xp_conn.connected:
                try:
                    xp_conn.connect()
                except OSError:
                    pass

            is_connected = xp_conn.connected
            if is_connected != last_connected:
                gui.update_xplane_connection(is_connected)
                last_connected = is_connected

            state = aircraft_mgr.update()
            controller.update(state)

            # Play back pending ATC instructions
            if len(controller.instructions) > last_instruction_count:
                for instr in controller.instructions[last_instruction_count:]:
                    if not instr.spoken:
                        voice_out.speak(instr.text)
                        instr.spoken = True
                last_instruction_count = len(controller.instructions)

            gui.update_aircraft_state(state)

            # Handle ATIS playback loop if tuned
            active_freq = controller.active_com_freq
            atis_freq = controller.get_facility_frequency("ATIS")
            is_on_atis = (atis_freq > 0 and active_freq == atis_freq)

            if is_on_atis:
                if not was_on_atis:
                    atis_last_played_time = 0.0
                was_on_atis = True

                if (time.time() - atis_last_played_time > 3.0) and voice_out.is_idle():
                    if controller.metar and controller.airport:
                        runway = controller.active_runway or "01"
                        airport_name = controller.active_airport or controller.airport.name
                        text = controller.metar.generate_atis(airport_name, runway)
                        voice_out.speak(text)
                        atis_last_played_time = time.time()
            else:
                if was_on_atis:
                    voice_out.abort()
                    was_on_atis = False

            time.sleep(0.2)
        except Exception:
            logger.exception("Error in background loop")
            time.sleep(1.0)

def main() -> None:
    args = parse_args()

    # Logging setup
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        filename="ai_atc.log",
        filemode="w",
    )

    print("Initializing AI ATC...")

    # Load flight plan
    flight_plan = None
    if args.simbrief:
        print(f"Fetching SimBrief data for user {args.simbrief}...")
        flight_plan = fetch_from_simbrief(args.simbrief)
    
    if args.flight_plan:
        flight_plan = load_flight_plan(args.flight_plan)
    
    if not flight_plan:
        flight_plan = FlightPlan(callsign=args.callsign, origin_icao=args.airport)

    # Boot initialization of nav data
    airport_icao = flight_plan.origin_icao or args.airport
    xplane_path = args.xplane_path

    airport = None
    procedures = None
    if xplane_path:
        print(f"Loading navigation data for {airport_icao} from {xplane_path}...")
        try:
            airport_parser = AirportParser(xplane_path)
            airport = airport_parser.parse_airport(airport_icao)
            cifp_parser = CIFPParser(xplane_path)
            procedures = cifp_parser.parse(airport_icao)
        except Exception as e:
            print(f"Failed to load navigation data: {e}")

    # Weather
    print("Fetching METAR...")
    metar_service = MetarService()
    try:
        metar = asyncio.run(metar_service.fetch(airport_icao))
    except Exception:
        metar = None

    # Determine active runway if missing
    active_runway = flight_plan.departure_runway
    if not active_runway and airport and metar and metar.wind:
        runway_pairs = airport.get_runway_pairs()
        if runway_pairs:
            active_runway = metar_service.determine_active_runway(runway_pairs)
            flight_plan.departure_runway = active_runway

    # Connectivity and State
    xp_conn = XPlaneConnection(host=args.xplane_host, xplane_port=args.xplane_port, listen_port=args.listen_port)
    aircraft_mgr = AircraftStateManager(xp_conn)
    controller = ATCController(flight_plan, airport, procedures, metar)
    if active_runway:
        controller.set_active_runway(active_runway)

    # Voice & Agent Setup
    voice_out = ATCVoice()
    if not args.no_voice:
        voice_out.start()

    agent = GenerativeATCAgent(
        controller=controller,
        get_aircraft_state=lambda: aircraft_mgr.state,
    )

    # Wire Agent callbacks to Controller state transitions
    controller._decision_transition_cb = lambda state_id: setattr(agent, "_current_state_id", state_id)

    stt_engine = ATCVoiceEngine(callback=lambda text: agent.callback(text))
    stt_engine.start()

    audio_capture = AudioCapture(on_capture_complete=stt_engine.transcribe_file)

    # GUI
    print("Launching Tactical Controller GUI...")
    gui = ATCApp(controller, audio_capture, stt_engine)

    # Final Wiring
    agent.gui_log = lambda role, text: gui.comm_log.append(role, text)
    agent.status_callback = lambda s: gui.set_led_status("brain", s)
    stt_engine.status_callback = lambda s: gui.set_led_status("brain", s)
    stt_engine.hearing_callback = lambda text: gui.set_hearing(text)
    voice_out._status_callback = lambda s: gui.set_led_status("mouth", s)
    audio_capture.status_callback = lambda s: gui.set_led_status("mic", s)
    audio_capture.volume_callback = lambda v: gui.update_vu(v)

    # Connect & Start
    try:
        xp_conn.connect()
    except OSError:
        pass

    aircraft_mgr.start()
    
    bg_thread = threading.Thread(
        target=run_background_loop,
        args=(aircraft_mgr, controller, xp_conn, voice_out, gui),
        daemon=True,
    )
    bg_thread.start()

    try:
        gui.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        voice_out.stop()
        audio_capture.stop_recording()
        stt_engine.stop()
        aircraft_mgr.stop()
        xp_conn.disconnect()
        print("\nShutdown complete.")

if __name__ == "__main__":
    main()