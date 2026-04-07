#!/usr/bin/env python3
"""Quick smoke test for AI ATC modules."""

import sys
import os
from pathlib import Path

# Add src to path if needed
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_imports():
    print("Testing imports...")
    from ai_atc.xplane.connection import XPlaneConnection
    from ai_atc.xplane.aircraft import AircraftState, AircraftStateManager
    from ai_atc.navdata.airport import AirportParser
    from ai_atc.navdata.procedures import CIFPParser
    from ai_atc.flightplan.flight_plan import load_flight_plan, FlightPlan
    from ai_atc.atc.state_machine import FlightPhase
    from ai_atc.atc.controller import ATCController
    from ai_atc.atc.decision_tree import fill_template, get_node
    from ai_atc.voice.tts import ATCVoice
    print("  ✓ All imports OK\n")

def test_callsign_resolution():
    print("Testing callsign telephony resolution...")
    from ai_atc.flightplan.flight_plan import FlightPlan
    
    # Test Airline
    fp_baw = FlightPlan(callsign="BAW123")
    print(f"  BAW123 -> {fp_baw.airline_callsign}")
    assert fp_baw.airline_callsign == "Speedbird 123"
    
    # Test Regionals
    fp_edv = FlightPlan(callsign="EDV456")
    print(f"  EDV456 -> {fp_edv.airline_callsign}")
    assert fp_edv.airline_callsign == "Endeavor 456"
    
    # Test GA (N-Number)
    fp_ga = FlightPlan(callsign="N731NR")
    print(f"  N731NR -> {fp_ga.airline_callsign}")
    assert fp_ga.airline_callsign == "November 731NR"
    
    print("  ✓ Callsign resolution OK\n")

def test_templates():
    print("Testing ATC templates...")
    from ai_atc.atc.decision_tree import fill_template
    vars = {
        "callsign": "Speedbird 123",
        "runway": "31L",
        "altitude": "5000",
        "squawk": "4521"
    }
    tpl = "{callsign}, cleared to destination, runway {runway}, climb and maintain {altitude}, squawk {squawk}."
    res = fill_template(tpl, vars)
    print(f"  Result: {res}")
    assert "Speedbird 123" in res and "4521" in res
    print("  ✓ Template system OK\n")

def test_flight_plan():
    print("Testing flight plan loader...")
    from ai_atc.flightplan.flight_plan import load_flight_plan
    fp_path = Path("flight_plan.json")
    if fp_path.exists():
        fp = load_flight_plan(str(fp_path))
        print(f"  Callsign:    {fp.callsign}")
        print(f"  Route:       {fp.origin_icao} → {fp.destination_icao}")
        print("  ✓ Flight plan OK\n")
    else:
        print("  ⚠ flight_plan.json not found, skipping\n")

def test_state_machine():
    print("Testing state machine...")
    from ai_atc.atc.state_machine import FlightStateMachine, FlightPhase
    from ai_atc.xplane.aircraft import AircraftState
    sm = FlightStateMachine()
    print(f"  Initial phase: {sm.phase.name}")
    assert sm.phase == FlightPhase.PARKED
    sm.set_clearance_given()
    sm.update(AircraftState())
    print(f"  After clearance: {sm.phase.name}")
    assert sm.phase == FlightPhase.CLEARANCE_DELIVERED
    print("  ✓ State machine OK\n")

if __name__ == "__main__":
    try:
        test_imports()
        test_callsign_resolution()
        test_templates()
        test_flight_plan()
        test_state_machine()
        print("=" * 50)
        print("Tests completed successfully!")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
