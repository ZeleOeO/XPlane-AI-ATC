from __future__ import annotations
import logging
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from ai_atc.atc.state_machine import FlightPhase, FlightStateMachine
from ai_atc.flightplan.flight_plan import FlightPlan
from ai_atc.navdata.airport import Airport, ATCFrequency
from ai_atc.navdata.procedures import AirportProcedures
from ai_atc.navdata.taxiway import TaxiRoute, TaxiwayRouter
from ai_atc.navdata.navigation import distance_nm, bearing_degrees, cross_track_error_nm
from ai_atc.navdata.artcc import get_nearest_artcc
from ai_atc.weather.metar import MetarData
from ai_atc.xplane.aircraft import AircraftState
from ai_atc.atc.decision_tree import get_initial_state, DECISION_TREE
logger = logging.getLogger(__name__)
FACILITY_NAMES = {
    "ATIS": "ATIS",
    "DELIVERY": "Clearance Delivery",
    "GROUND": "Ground Control",
    "TOWER": "Tower",
    "DEPARTURE": "Departure",
    "APPROACH": "Approach",
    "CENTER": "Center",
}
FALLBACK_FREQUENCIES: dict[str, int] = {
    "ATIS": 13500,
    "DELIVERY": 12150,
    "GROUND": 12170,
    "TOWER": 11910,
    "DEPARTURE": 12490,
    "APPROACH": 12490,
    "CENTER": 13245,
}
PHASE_FACILITY_MAP: dict[FlightPhase, str] = {
    FlightPhase.PARKED: "DELIVERY",
    FlightPhase.CLEARANCE_DELIVERED: "DELIVERY",
    FlightPhase.PUSHBACK: "GROUND",
    FlightPhase.TAXI_OUT: "GROUND",
    FlightPhase.HOLDING_SHORT: "TOWER",
    FlightPhase.TAKEOFF_ROLL: "TOWER",
    FlightPhase.INITIAL_CLIMB: "DEPARTURE",
    FlightPhase.CLIMBING: "CENTER",
    FlightPhase.CRUISING: "CENTER",
    FlightPhase.DESCENDING: "CENTER",
    FlightPhase.APPROACH: "APPROACH",
    FlightPhase.FINAL_APPROACH: "TOWER",
    FlightPhase.LANDING_ROLL: "TOWER",
    FlightPhase.TAXI_IN: "GROUND",
}
@dataclass
class ATCInstruction:
    text: str
    timestamp: float = field(default_factory=time.time)
    phase: FlightPhase = FlightPhase.PARKED
    spoken: bool = False
    facility: str = "TOWER"
    @property
    def time_str(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.timestamp))
class ATCController:
    def __init__(
        self,
        flight_plan: FlightPlan,
        airport: Airport | None = None,
        procedures: AirportProcedures | None = None,
        metar: MetarData | None = None,
    ) -> None:
        self.flight_plan = flight_plan
        self.airport = airport
        self.procedures = procedures
        self.metar = metar
        self.state_machine = FlightStateMachine()
        self.state_machine.on_transition(self._on_phase_transition)
        self.instructions: list[ATCInstruction] = []
        self._taxi_router: TaxiwayRouter | None = None
        if airport:
            self._taxi_router = TaxiwayRouter(airport)
        self._active_runway: str = ""
        self._taxi_route: TaxiRoute | None = None
        self._assigned_heading: int = 0
        self._assigned_altitude: int = 0
        self._assigned_speed: int = 0
        self._is_vectored: bool = False
        self._active_facility: str = "DELIVERY"
        self._last_squawk_nag_time: float = 0.0
        self._last_freq_nag_time: float = 0.0
        self._last_nav_nag_time: float = 0.0
        self._current_com_freq: int = 0
        self._current_artcc: str = "Center"
        self._facility_frequencies: dict[str, int] = dict(FALLBACK_FREQUENCIES)
        if airport:
            self._load_airport_frequencies(airport)
        self._decision_state_id: str = get_initial_state()
        self._decision_transition_cb = None  # set by agent
    def _load_airport_frequencies(self, airport: Airport) -> None:
        for facility in ("ATIS", "DELIVERY", "GROUND", "TOWER", "DEPARTURE", "APPROACH"):
            freq = airport.get_primary_frequency(facility)
            if freq:
                self._facility_frequencies[facility] = freq.freq_hz
                logger.info(
                    "Loaded %s frequency: %s (%s)",
                    facility,
                    freq.freq_str,
                    freq.name,
                )
    def get_facility_frequency(self, facility: str) -> int:
        return self._facility_frequencies.get(facility, 0)
    def get_facility_freq_str(self, facility: str) -> str:
        hz = self.get_facility_frequency(facility)
        if not hz:
            return "unknown"
        mhz = hz / 100.0
        return f"{mhz:.3f}"
    def get_all_frequencies(self) -> dict[str, int]:
        return dict(self._facility_frequencies)
    @property
    def current_phase(self) -> FlightPhase:
        return self.state_machine.phase
    @property
    def active_facility(self) -> str:
        return self._active_facility
    @property
    def target_facility(self) -> str:
        return self._active_facility
    @property
    def target_frequency(self) -> int:
        return self.get_facility_frequency(self._active_facility)
    @property
    def next_facility(self) -> str:
        fac = self._active_facility
        phase = self.current_phase
        if fac == "DELIVERY": return "GROUND"
        if fac == "GROUND": return "TOWER"
        if fac == "TOWER":
            if phase in (FlightPhase.FINAL_APPROACH, FlightPhase.LANDING_ROLL, FlightPhase.TAXI_IN):
                return "GROUND"
            return "DEPARTURE"
        if fac == "DEPARTURE": return "CENTER"
        if fac == "CENTER": return "APPROACH"
        if fac == "APPROACH": return "TOWER"
        return ""
    @property
    def next_frequency(self) -> int:
        return self.get_facility_frequency(self.next_facility) if self.next_facility else 0
    @property
    def active_airport(self) -> str | None:
        phase = self.current_phase
        if phase in (FlightPhase.CRUISING, FlightPhase.DESCENDING, FlightPhase.APPROACH, 
                     FlightPhase.FINAL_APPROACH, FlightPhase.LANDING_ROLL, FlightPhase.TAXI_IN):
            return self.flight_plan.destination_icao
        return self.flight_plan.origin_icao
    @property
    def target_facility_name(self) -> str:
        fac = self._active_facility
        if fac == "CENTER":
            return f"{self._current_artcc} Center"
        airport = self.active_airport
        labels = {
            "ATIS": "ATIS", "DELIVERY": "Clearance", "GROUND": "Ground",
            "TOWER": "Tower", "DEPARTURE": "Departure", "APPROACH": "Approach"
        }
        name = labels.get(fac, fac)
        return f"{airport} {name}" if airport else name
    @property
    def next_facility_name(self) -> str:
        fac = self.next_facility
        if not fac:
            return "---"
        if fac == "CENTER":
            return f"{self._current_artcc} Center"
        phase = self.current_phase
        if fac in ("APPROACH", "TOWER", "GROUND") and phase in (
            FlightPhase.CRUISING, FlightPhase.DESCENDING, FlightPhase.APPROACH, 
            FlightPhase.FINAL_APPROACH, FlightPhase.LANDING_ROLL, FlightPhase.TAXI_IN
        ):
            airport = self.flight_plan.destination_icao
        elif fac == "APPROACH":
            airport = self.flight_plan.destination_icao
        else:
            airport = self.flight_plan.origin_icao
        labels = {
            "ATIS": "ATIS", "DELIVERY": "Clearance", "GROUND": "Ground",
            "TOWER": "Tower", "DEPARTURE": "Departure", "APPROACH": "Approach"
        }
        name = labels.get(fac, fac)
        return f"{airport} {name}" if airport else name
    @property
    def active_com_freq(self) -> int:
        return self._current_com_freq
    @property
    def handoff_pending(self) -> bool:
        if self.target_frequency == 0:
            return False
        if self._current_com_freq == 0:
            return False
        return self._current_com_freq != self.target_frequency
    @property
    def active_runway(self) -> str:
        return self._active_runway
    @property
    def latest_instruction(self) -> ATCInstruction | None:
        return self.instructions[-1] if self.instructions else None
    @property
    def assigned_altitude(self) -> int:
        return self._assigned_altitude
    @property
    def assigned_heading(self) -> int:
        return self._assigned_heading
    @property
    def assigned_speed(self) -> int:
        return self._assigned_speed
    @property
    def assigned_waypoint(self) -> str:
        if self.flight_plan.current_waypoint:
            return self.flight_plan.current_waypoint.name
        return "---"
    @property
    def assigned_squawk(self) -> int:
        return self.flight_plan.squawk or 0
    def set_active_runway(self, runway: str) -> None:
        self._active_runway = runway
        logger.info("Active runway set to %s", runway)
    def update_metar(self, metar: MetarData) -> None:
        self.metar = metar
    def _get_active_com_freq(self, state: AircraftState) -> int:
        return state.com1_freq if state.com_selection == 0 else state.com2_freq
    def _detect_tuned_facility(self, state: AircraftState) -> str | None:
        active_freq = self._get_active_com_freq(state)
        if not active_freq:
            return None
        for facility, hz in self._facility_frequencies.items():
            if active_freq == hz:
                return facility
        return None
    def update(self, state: AircraftState) -> FlightPhase:
        self._current_artcc = get_nearest_artcc(state.latitude, state.longitude)
        self._current_com_freq = self._get_active_com_freq(state)
        new_phase = self.state_machine.update(state)
        return new_phase
    def _on_phase_transition(
        self, old_phase: FlightPhase, new_phase: FlightPhase, state: AircraftState
    ) -> None:
        """Called when the flight phase changes — auto-advances the decision tree."""
        logger.info(
            "Phase transition callback: %s → %s", old_phase.display, new_phase.display
        )
        new_facility = PHASE_FACILITY_MAP.get(new_phase)
        if new_facility:
            self._active_facility = new_facility
        phase_to_state: dict[FlightPhase, str] = {
            FlightPhase.INITIAL_CLIMB: "DEP_INITIAL_CONTACT",
            FlightPhase.CLIMBING: "CTR_INITIAL_CONTACT",
            FlightPhase.DESCENDING: "CTR_DESCENT_CLEARANCE",
            FlightPhase.FINAL_APPROACH: "APP_CLEARED_APPROACH",
            FlightPhase.TAXI_IN: "GRD_TAXI_IN_REQUEST",
        }
        target_state = phase_to_state.get(new_phase)
        if target_state and target_state in DECISION_TREE:
            self._decision_state_id = target_state
            logger.info("Decision tree auto-advanced to: %s", target_state)
            if self._decision_transition_cb:
                try:
                    self._decision_transition_cb(target_state)
                except Exception:
                    logger.exception("Error in decision transition callback")
    @property
    def current_decision_state_id(self) -> str:
        return self._decision_state_id
    def advance_decision_state(self, new_state_id: str) -> None:
        """Advance the decision tree to a new state (called by the agent)."""
        if new_state_id in DECISION_TREE:
            self._decision_state_id = new_state_id
            logger.info("Decision state advanced to: %s", new_state_id)
        else:
            logger.warning("Unknown decision state: %s", new_state_id)
    def _format_freq_for_voice(self, freq_hz: int) -> str:
        s = str(freq_hz)
        if len(s) >= 5:
            return f"{s[0]} {s[1]} {s[2]} decimal {s[3]} {s[4]}"
        return s
    def _add_instruction(
        self, text: str, phase: FlightPhase, facility: str = "TOWER"
    ) -> ATCInstruction:
        instr = ATCInstruction(text=text, phase=phase, facility=facility)
        self.instructions.append(instr)
        logger.info("[%s] ATC: %s", facility, text)
        return instr