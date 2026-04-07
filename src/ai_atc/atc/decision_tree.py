"""
ATC Decision Tree — defines every interaction node for a full IFR flight.
Each node specifies:
  - id:                  Unique state identifier
  - facility:            Which ATC facility owns this node
  - say_tpl:             Template for ATC to speak (variables filled at runtime)
  - utterance_tpl:       What we expect the pilot to say (for UI hints)
  - next:                List of valid next state IDs (candidates for routing)
  - bad_next:            State to go to on a bad readback / wrong response
  - readback_required:   Fields pilot must read back before advancing
  - auto_advance:        If True, advance to next[0] automatically without pilot input
  - triggers:            Conditions for automatic transitions (phase-based)
"""
from __future__ import annotations
from dataclasses import dataclass, field
@dataclass
class DecisionNode:
    id: str
    facility: str
    say_tpl: str
    utterance_tpl: str = ""
    next: list[str] = field(default_factory=list)
    bad_next: list[str] = field(default_factory=list)
    readback_required: list[str] = field(default_factory=list)
    auto_advance: bool = False
    triggers: dict = field(default_factory=dict)
DECISION_TREE: dict[str, DecisionNode] = {}
def _register(*nodes: DecisionNode) -> None:
    for node in nodes:
        DECISION_TREE[node.id] = node
_register(
    DecisionNode(
        id="CD_INITIAL_CONTACT",
        facility="DELIVERY",
        say_tpl="{callsign}, {facility_name}, go ahead.",
        utterance_tpl="{facility_name}, {callsign}, request IFR clearance to {destination}.",
        next=["CD_ISSUE_CLEARANCE"],
        bad_next=["CD_SAY_AGAIN"],
    ),
    DecisionNode(
        id="CD_ISSUE_CLEARANCE",
        facility="DELIVERY",
        say_tpl=(
            "{callsign}, cleared to {destination} airport via the {sid} departure, "
            "runway {runway}, climb via SID except maintain {altitude}, "
            "expect {cruise_alt} ten minutes after departure, "
            "squawk {squawk}."
        ),
        utterance_tpl=(
            "{callsign}, cleared to {destination} via {sid}, runway {runway}, "
            "climb and maintain {altitude}, squawk {squawk}."
        ),
        next=["CD_READBACK_CORRECT", "CD_READBACK_BAD"],
        bad_next=["CD_ISSUE_CLEARANCE"],
        readback_required=["destination", "sid", "runway", "altitude", "squawk"],
    ),
    DecisionNode(
        id="CD_READBACK_CORRECT",
        facility="DELIVERY",
        say_tpl="{callsign}, readback correct. Contact {next_facility} on {next_freq} when ready for pushback.",
        utterance_tpl="",
        next=["GRD_INITIAL_CONTACT"],
        auto_advance=True,
    ),
    DecisionNode(
        id="CD_READBACK_BAD",
        facility="DELIVERY",
        say_tpl="{callsign}, say again — you missed {missing_fields}.",
        utterance_tpl="",
        next=["CD_ISSUE_CLEARANCE"],
        auto_advance=True,
    ),
    DecisionNode(
        id="CD_SAY_AGAIN",
        facility="DELIVERY",
        say_tpl="{callsign}, say again.",
        utterance_tpl="",
        next=["CD_INITIAL_CONTACT"],
        auto_advance=True,
    ),
)
_register(
    DecisionNode(
        id="GRD_INITIAL_CONTACT",
        facility="GROUND",
        say_tpl="{callsign}, {facility_name}, go ahead.",
        utterance_tpl="{facility_name}, {callsign}, ready to push and start, gate as filed.",
        next=["GRD_PUSHBACK_APPROVED", "GRD_PUSHBACK_HOLD"],
    ),
    DecisionNode(
        id="GRD_PUSHBACK_APPROVED",
        facility="GROUND",
        say_tpl="{callsign}, push and start approved, face {pushback_direction}.",
        utterance_tpl="{callsign}, push and start approved.",
        next=["GRD_TAXI_REQUEST"],
        bad_next=["GRD_PUSHBACK_APPROVED"],
    ),
    DecisionNode(
        id="GRD_PUSHBACK_HOLD",
        facility="GROUND",
        say_tpl="{callsign}, hold position, expect push in approximately five minutes.",
        utterance_tpl="",
        next=["GRD_PUSHBACK_APPROVED"],
        auto_advance=True,
    ),
    DecisionNode(
        id="GRD_TAXI_REQUEST",
        facility="GROUND",
        say_tpl="{callsign}, {facility_name}, go ahead.",
        utterance_tpl="{facility_name}, {callsign}, request taxi.",
        next=["GRD_TAXI_CLEARANCE"],
    ),
    DecisionNode(
        id="GRD_TAXI_CLEARANCE",
        facility="GROUND",
        say_tpl=(
            "{callsign}, taxi to runway {runway} via {taxi_route}, "
            "{hold_short}."
        ),
        utterance_tpl=(
            "{callsign}, taxi runway {runway} via {taxi_route}, {hold_short}."
        ),
        next=["GRD_TAXI_READBACK_CORRECT", "GRD_TAXI_READBACK_BAD"],
        bad_next=["GRD_TAXI_CLEARANCE"],
        readback_required=["runway", "taxi_route", "hold_short"],
    ),
    DecisionNode(
        id="GRD_TAXI_READBACK_CORRECT",
        facility="GROUND",
        say_tpl="{callsign}, readback correct.",
        utterance_tpl="",
        next=["GRD_HOLDING_SHORT"],
        auto_advance=True,
    ),
    DecisionNode(
        id="GRD_TAXI_READBACK_BAD",
        facility="GROUND",
        say_tpl="{callsign}, negative — {missing_fields}. Taxi runway {runway} via {taxi_route}, {hold_short}.",
        utterance_tpl="",
        next=["GRD_TAXI_CLEARANCE"],
        auto_advance=True,
    ),
    DecisionNode(
        id="GRD_HOLDING_SHORT",
        facility="GROUND",
        say_tpl="{callsign}, continue taxi. Monitor tower on {next_freq}.",
        utterance_tpl="{callsign}, holding short {hold_short}, ready for takeoff.",
        next=["TWR_INITIAL_CONTACT"],
        triggers={"phase": "HOLDING_SHORT"},
    ),
)
_register(
    DecisionNode(
        id="TWR_INITIAL_CONTACT",
        facility="TOWER",
        say_tpl="{callsign}, {facility_name}, runway {runway}, hold short.",
        utterance_tpl="{facility_name}, {callsign}, holding short runway {runway}, ready for departure.",
        next=["TWR_LINE_UP_AND_WAIT", "TWR_CLEARED_FOR_TAKEOFF"],
    ),
    DecisionNode(
        id="TWR_LINE_UP_AND_WAIT",
        facility="TOWER",
        say_tpl="{callsign}, runway {runway}, line up and wait.",
        utterance_tpl="{callsign}, line up and wait, runway {runway}.",
        next=["TWR_CLEARED_FOR_TAKEOFF"],
        readback_required=["runway", "cleared_takeoff"],
        bad_next=["TWR_LINE_UP_AND_WAIT"],
    ),
    DecisionNode(
        id="TWR_CLEARED_FOR_TAKEOFF",
        facility="TOWER",
        say_tpl=(
            "{callsign}, runway {runway}, cleared for takeoff, "
            "wind {wind}, fly runway heading."
        ),
        utterance_tpl="{callsign}, cleared for takeoff runway {runway}.",
        next=["TWR_TAKEOFF_READBACK_CORRECT", "TWR_TAKEOFF_READBACK_BAD"],
        bad_next=["TWR_CLEARED_FOR_TAKEOFF"],
        readback_required=["runway", "cleared_takeoff"],
    ),
    DecisionNode(
        id="TWR_TAKEOFF_READBACK_CORRECT",
        facility="TOWER",
        say_tpl="{callsign}, readback correct. Good day.",
        utterance_tpl="",
        next=["DEP_INITIAL_CONTACT"],
        auto_advance=True,
        triggers={"phase": "INITIAL_CLIMB"},
    ),
    DecisionNode(
        id="TWR_TAKEOFF_READBACK_BAD",
        facility="TOWER",
        say_tpl="{callsign}, say again — confirm runway {runway}, cleared for takeoff.",
        utterance_tpl="",
        next=["TWR_CLEARED_FOR_TAKEOFF"],
        auto_advance=True,
    ),
)
_register(
    DecisionNode(
        id="DEP_INITIAL_CONTACT",
        facility="DEPARTURE",
        say_tpl=(
            "{callsign}, {facility_name}, radar contact. "
            "Climb and maintain {altitude}, fly the {sid} departure."
        ),
        utterance_tpl="{facility_name}, {callsign}, passing {altitude}, climbing.",
        next=["DEP_CLIMB_INSTRUCTION", "DEP_FREQUENCY_CHANGE"],
    ),
    DecisionNode(
        id="DEP_CLIMB_INSTRUCTION",
        facility="DEPARTURE",
        say_tpl="{callsign}, climb and maintain {cruise_alt}.",
        utterance_tpl="{callsign}, climbing to {cruise_alt}.",
        next=["DEP_FREQUENCY_CHANGE"],
        readback_required=["altitude"],
        bad_next=["DEP_CLIMB_INSTRUCTION"],
    ),
    DecisionNode(
        id="DEP_FREQUENCY_CHANGE",
        facility="DEPARTURE",
        say_tpl="{callsign}, contact {next_facility} on {next_freq}. Good day.",
        utterance_tpl="{callsign}, over to {next_facility} on {next_freq}. Good day.",
        next=["CTR_INITIAL_CONTACT"],
        auto_advance=True,
    ),
)
_register(
    DecisionNode(
        id="CTR_INITIAL_CONTACT",
        facility="CENTER",
        say_tpl="{callsign}, {facility_name}, radar contact, cruise {cruise_alt}.",
        utterance_tpl="{facility_name}, {callsign}, level {cruise_alt}.",
        next=["CTR_CRUISING", "CTR_DESCENT_CLEARANCE"],
    ),
    DecisionNode(
        id="CTR_CRUISING",
        facility="CENTER",
        say_tpl="{callsign}, continue as filed.",
        utterance_tpl="",
        next=["CTR_DESCENT_CLEARANCE"],
        auto_advance=True,
        triggers={"phase": "CRUISING"},
    ),
    DecisionNode(
        id="CTR_DESCENT_CLEARANCE",
        facility="CENTER",
        say_tpl=(
            "{callsign}, descend and maintain {altitude}, "
            "expect approach {landing_runway} at {destination}."
        ),
        utterance_tpl="{callsign}, leaving {cruise_alt} for {altitude}.",
        next=["CTR_FREQ_CHANGE"],
        readback_required=["altitude"],
        bad_next=["CTR_DESCENT_CLEARANCE"],
        triggers={"phase": "DESCENDING"},
    ),
    DecisionNode(
        id="CTR_FREQ_CHANGE",
        facility="CENTER",
        say_tpl="{callsign}, contact {next_facility} on {next_freq}. Good day.",
        utterance_tpl="{callsign}, over to {next_facility} on {next_freq}. Good day.",
        next=["APP_INITIAL_CONTACT"],
        auto_advance=True,
    ),
)
_register(
    DecisionNode(
        id="APP_INITIAL_CONTACT",
        facility="APPROACH",
        say_tpl=(
            "{callsign}, {facility_name}, expect ILS approach runway {landing_runway}. "
            "Descend and maintain {altitude}."
        ),
        utterance_tpl="{facility_name}, {callsign}, descending for the ILS runway {landing_runway}.",
        next=["APP_VECTOR_FINAL", "APP_CLEARED_APPROACH"],
    ),
    DecisionNode(
        id="APP_VECTOR_FINAL",
        facility="APPROACH",
        say_tpl=(
            "{callsign}, turn {heading_direction} heading {heading}, "
            "intercept the localizer runway {landing_runway}."
        ),
        utterance_tpl="{callsign}, heading {heading}, runway {landing_runway}.",
        next=["APP_CLEARED_APPROACH"],
        readback_required=["heading"],
        bad_next=["APP_VECTOR_FINAL"],
    ),
    DecisionNode(
        id="APP_CLEARED_APPROACH",
        facility="APPROACH",
        say_tpl=(
            "{callsign}, three miles from the outer marker, "
            "cleared ILS runway {landing_runway} approach. "
            "Contact {next_facility} on {next_freq}."
        ),
        utterance_tpl="{callsign}, cleared ILS runway {landing_runway}. Over to tower.",
        next=["TWR_LANDING_CONTACT"],
        auto_advance=True,
        triggers={"phase": "FINAL_APPROACH"},
    ),
)
_register(
    DecisionNode(
        id="TWR_LANDING_CONTACT",
        facility="TOWER",
        say_tpl="{callsign}, {facility_name}, runway {landing_runway}, cleared to land. Wind {wind}.",
        utterance_tpl="{callsign}, cleared to land runway {landing_runway}.",
        next=["TWR_LANDING_READBACK_OK", "TWR_LANDING_READBACK_BAD"],
        bad_next=["TWR_LANDING_CONTACT"],
        readback_required=["landing_runway", "cleared_landing"],
    ),
    DecisionNode(
        id="TWR_LANDING_READBACK_OK",
        facility="TOWER",
        say_tpl="{callsign}, readback correct. Exit the runway when able, contact {next_facility} on {next_freq}.",
        utterance_tpl="",
        next=["GRD_TAXI_IN_REQUEST"],
        auto_advance=True,
        triggers={"phase": "TAXI_IN"},
    ),
    DecisionNode(
        id="TWR_LANDING_READBACK_BAD",
        facility="TOWER",
        say_tpl="{callsign}, say again — cleared to land runway {landing_runway}.",
        utterance_tpl="",
        next=["TWR_LANDING_CONTACT"],
        auto_advance=True,
    ),
)
_register(
    DecisionNode(
        id="GRD_TAXI_IN_REQUEST",
        facility="GROUND",
        say_tpl="{callsign}, {facility_name}, go ahead.",
        utterance_tpl="{facility_name}, {callsign}, off runway {landing_runway}, request taxi to gate.",
        next=["GRD_TAXI_IN_CLEARANCE"],
    ),
    DecisionNode(
        id="GRD_TAXI_IN_CLEARANCE",
        facility="GROUND",
        say_tpl="{callsign}, taxi to {gate} via {taxi_route}.",
        utterance_tpl="{callsign}, taxi to {gate} via {taxi_route}.",
        next=["GRD_TAXI_IN_READBACK_OK"],
        bad_next=["GRD_TAXI_IN_CLEARANCE"],
        readback_required=["gate", "taxi_route"],
    ),
    DecisionNode(
        id="GRD_TAXI_IN_READBACK_OK",
        facility="GROUND",
        say_tpl="{callsign}, readback correct. Welcome to {destination}.",
        utterance_tpl="",
        next=[],
        auto_advance=True,
    ),
)
_register(
    DecisionNode(
        id="RADIO_CHECK",
        facility="ANY",
        say_tpl="{callsign}, loud and clear. {facility_name}.",
        utterance_tpl="Radio check.",
        next=["__RETURN__"],  # Special: return to previous state
    ),
    DecisionNode(
        id="OFF_SCHEMA",
        facility="ANY",
        say_tpl="{callsign}, say again, say intentions.",
        utterance_tpl="",
        next=["__RETURN__"],
    ),
    DecisionNode(
        id="WRONG_FREQUENCY",
        facility="ANY",
        say_tpl=(
            "{callsign}, you are on {facility_name}. "
            "For {requested_service}, contact {correct_facility} on {correct_freq}."
        ),
        utterance_tpl="",
        next=["__RETURN__"],
    ),
)
def get_node(state_id: str) -> DecisionNode | None:
    """Look up a node by its state ID."""
    return DECISION_TREE.get(state_id)
def get_next_candidates(state_id: str) -> list[DecisionNode]:
    """Get all valid next nodes from a given state."""
    node = get_node(state_id)
    if not node:
        return []
    return [DECISION_TREE[nid] for nid in node.next if nid in DECISION_TREE]
def get_initial_state() -> str:
    """Return the first state of the flight."""
    return "CD_INITIAL_CONTACT"
def fill_template(template: str, variables: dict) -> str:
    """Fill a say_tpl/utterance_tpl with current flight variables."""
    try:
        return template.format_map(_SafeDict(variables))
    except (KeyError, ValueError):
        return template
class _SafeDict(dict):
    """dict subclass that returns '{key}' for missing keys instead of raising KeyError."""
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"