#!/usr/bin/env python3
"""Quick smoke test for AI ATC modules."""

import sys
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
    from ai_atc.voice.correction import (
        extract_numbers, extract_runway, classify_intent, validate_readback,
    )
    from ai_atc.atc.readback import fuzzy_number_match
    print("  ✓ All imports OK\n")


def test_callsign_resolution():
    print("Testing callsign telephony resolution...")
    from ai_atc.flightplan.flight_plan import FlightPlan

    fp_baw = FlightPlan(callsign="BAW123")
    print(f"  BAW123 -> {fp_baw.airline_callsign}")
    assert fp_baw.airline_callsign == "Speedbird 123"

    fp_edv = FlightPlan(callsign="EDV456")
    print(f"  EDV456 -> {fp_edv.airline_callsign}")
    assert fp_edv.airline_callsign == "Endeavor 456"

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
        "squawk": "4521",
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


# ------------------------------------------------------------------ #
#  NEW: Correction layer tests                                        #
# ------------------------------------------------------------------ #

def test_extract_numbers():
    print("Testing number extraction...")
    from ai_atc.voice.correction import extract_numbers

    # Raw digits
    r1 = extract_numbers("maintain 5000 feet")
    print(f"  'maintain 5000 feet' → {r1}")
    assert 5000 in r1

    # Squawk code
    r2 = extract_numbers("squawk 1200")
    print(f"  'squawk 1200' → {r2}")
    assert 1200 in r2

    # Compound spoken
    r3 = extract_numbers("thirty five thousand feet")
    print(f"  'thirty five thousand feet' → {r3}")
    assert 35000 in r3

    # Twelve hundred
    r4 = extract_numbers("twelve hundred")
    print(f"  'twelve hundred' → {r4}")
    assert 1200 in r4

    print("  ✓ Number extraction OK\n")


def test_extract_runway():
    print("Testing runway extraction...")
    from ai_atc.voice.correction import extract_runway

    # Explicit
    r1 = extract_runway("runway 23 left")
    print(f"  'runway 23 left' → {r1}")
    assert r1 == "23L"

    # Suffix proximity
    r2 = extract_runway("23 left")
    print(f"  '23 left' → {r2}")
    assert r2 is not None and "23" in r2

    # Hallucinated — "point 3 left" with expected "23L"
    r3 = extract_runway("point 3 left", expected_runway="23L")
    print(f"  'point 3 left' (expected 23L) → {r3}")
    assert r3 is not None  # Should accept via suffix proximity

    # Spelled out
    r4 = extract_runway("two three left")
    print(f"  'two three left' → {r4}")
    assert r4 is not None and r4.endswith("L")

    print("  ✓ Runway extraction OK\n")


def test_classify_intent():
    print("Testing intent classification...")
    from ai_atc.voice.correction import classify_intent

    assert classify_intent("United 410 radio check") == "radio_check"
    print("  'United 410 radio check' → radio_check ✓")

    assert classify_intent("request clearance to KORD") == "request_clearance"
    print("  'request clearance to KORD' → request_clearance ✓")

    assert classify_intent("request taxi") == "request_taxi"
    print("  'request taxi' → request_taxi ✓")

    assert classify_intent("roger wilco") == "affirm"
    print("  'roger wilco' → affirm ✓")

    print("  ✓ Intent classification OK\n")


def test_validate_readback():
    print("Testing readback validation...")
    from ai_atc.voice.correction import validate_readback

    expected = {
        "destination": "KORD",
        "sid": "Radar Vectors",
        "runway": "23L",
        "altitude": "5000",
        "squawk": "1200",
    }

    # Good readback (garbled words but correct numbers)
    good = "climbed via sid effects maintain 5000 block 1200 runway 23 left"
    passed, missing = validate_readback(good, expected)
    print(f"  Good readback: passed={passed}, missing={missing}")
    assert passed or len(missing) <= 2  # destination/SID may be missing

    # Bad readback (wrong numbers)
    bad = "maintain 3000 squawk 4521"
    passed2, missing2 = validate_readback(bad, expected)
    print(f"  Bad readback: passed={passed2}, missing={missing2}")
    assert not passed2

    # Hallucinated readback with correct critical data
    hallucinated = "deporture on point 3 left block 1200 five thousand"
    passed3, missing3 = validate_readback(
        hallucinated, expected,
        required_fields=["altitude", "squawk"],
    )
    print(f"  Hallucinated: passed={passed3}, missing={missing3}")
    assert passed3  # altitude=5000 and squawk=1200 should match

    print("  ✓ Readback validation OK\n")


def test_fuzzy_number_match():
    print("Testing fuzzy number matching...")
    from ai_atc.atc.readback import fuzzy_number_match

    assert fuzzy_number_match("maintain 5000", "5000")
    print("  'maintain 5000' matches '5000' ✓")

    assert fuzzy_number_match("squawk twelve hundred", "1200")
    print("  'squawk twelve hundred' matches '1200' ✓")

    assert not fuzzy_number_match("maintain 3000", "5000")
    print("  'maintain 3000' does NOT match '5000' ✓")

    print("  ✓ Fuzzy matching OK\n")


if __name__ == "__main__":
    try:
        test_imports()
        test_callsign_resolution()
        test_templates()
        test_flight_plan()
        test_state_machine()
        test_extract_numbers()
        test_extract_runway()
        test_classify_intent()
        test_validate_readback()
        test_fuzzy_number_match()
        print("=" * 50)
        print("All tests completed successfully!")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
