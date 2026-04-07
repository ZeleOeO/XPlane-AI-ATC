from __future__ import annotations
import logging
from enum import Enum, auto
from typing import Callable
from ai_atc.xplane.aircraft import AircraftState
logger = logging.getLogger(__name__)
class FlightPhase(Enum):
    PARKED = auto()
    CLEARANCE_DELIVERED = auto()
    PUSHBACK = auto()
    TAXI_OUT = auto()
    HOLDING_SHORT = auto()
    TAKEOFF_ROLL = auto()
    INITIAL_CLIMB = auto()
    CLIMBING = auto()
    CRUISING = auto()
    DESCENDING = auto()
    APPROACH = auto()
    FINAL_APPROACH = auto()
    LANDING_ROLL = auto()
    TAXI_IN = auto()
    @property
    def display(self) -> str:
        return self.name.replace("_", " ").title()
    @property
    def is_ground(self) -> bool:
        return self in (
            FlightPhase.PARKED,
            FlightPhase.CLEARANCE_DELIVERED,
            FlightPhase.PUSHBACK,
            FlightPhase.TAXI_OUT,
            FlightPhase.HOLDING_SHORT,
            FlightPhase.TAKEOFF_ROLL,
            FlightPhase.LANDING_ROLL,
            FlightPhase.TAXI_IN,
        )
    @property
    def is_airborne(self) -> bool:
        return not self.is_ground or self == FlightPhase.TAKEOFF_ROLL
PhaseCallback = Callable[[FlightPhase, FlightPhase, AircraftState], None]
class FlightStateMachine:
    def __init__(self) -> None:
        self._phase = FlightPhase.PARKED
        self._callbacks: list[PhaseCallback] = []
        self._transition_time: float = 0.0
        self._clearance_given = False
        self._takeoff_cleared = False
        self._landing_cleared = False
    @property
    def phase(self) -> FlightPhase:
        return self._phase
    def on_transition(self, callback: PhaseCallback) -> None:
        self._callbacks.append(callback)
    def set_clearance_given(self) -> None:
        self._clearance_given = True
    def set_takeoff_cleared(self) -> None:
        self._takeoff_cleared = True
    def set_landing_cleared(self) -> None:
        self._landing_cleared = True
    def force_phase(self, phase: FlightPhase) -> None:
        self._transition(phase, AircraftState())
    def update(self, state: AircraftState) -> FlightPhase:
        import time
        now = time.time()
        phase = self._phase
        if phase == FlightPhase.PARKED:
            if self._clearance_given:
                self._transition(FlightPhase.CLEARANCE_DELIVERED, state)
        elif phase == FlightPhase.CLEARANCE_DELIVERED:
            if state.engines_running and not state.parking_brake_set:
                self._transition(FlightPhase.PUSHBACK, state)
        elif phase == FlightPhase.PUSHBACK:
            if state.is_moving and state.groundspeed_kts > 3:
                self._transition(FlightPhase.TAXI_OUT, state)
        elif phase == FlightPhase.TAXI_OUT:
            if not state.is_moving and self._takeoff_cleared:
                self._transition(FlightPhase.HOLDING_SHORT, state)
        elif phase == FlightPhase.HOLDING_SHORT:
            if state.groundspeed_kts > 30:
                self._transition(FlightPhase.TAKEOFF_ROLL, state)
        elif phase == FlightPhase.TAKEOFF_ROLL:
            if state.is_airborne and state.altitude_ft > 50:
                self._transition(FlightPhase.INITIAL_CLIMB, state)
        elif phase == FlightPhase.INITIAL_CLIMB:
            if state.altitude_ft > 1500:
                self._transition(FlightPhase.CLIMBING, state)
        elif phase == FlightPhase.CLIMBING:
            if state.altitude_ft > 10000 and abs(state.vertical_speed_fpm) < 300:
                self._transition(FlightPhase.CRUISING, state)
        elif phase == FlightPhase.CRUISING:
            if state.vertical_speed_fpm < -500:
                self._transition(FlightPhase.DESCENDING, state)
        elif phase == FlightPhase.DESCENDING:
            if state.altitude_ft < 5000 and state.airspeed_kts < 200:
                self._transition(FlightPhase.APPROACH, state)
        elif phase == FlightPhase.APPROACH:
            if state.gear_is_down and state.altitude_ft < 2000:
                self._transition(FlightPhase.FINAL_APPROACH, state)
        elif phase == FlightPhase.FINAL_APPROACH:
            if state.on_ground and state.groundspeed_kts > 30:
                self._transition(FlightPhase.LANDING_ROLL, state)
        elif phase == FlightPhase.LANDING_ROLL:
            if state.groundspeed_kts < 25:
                self._transition(FlightPhase.TAXI_IN, state)
        elif phase == FlightPhase.TAXI_IN:
            if not state.is_moving and state.parking_brake_set:
                self._transition(FlightPhase.PARKED, state)
        return self._phase
    def _transition(self, new_phase: FlightPhase, state: AircraftState) -> None:
        old_phase = self._phase
        self._phase = new_phase
        logger.info("Phase transition: %s -> %s", old_phase.display, new_phase.display)
        for callback in self._callbacks:
            try:
                callback(old_phase, new_phase, state)
            except Exception:
                logger.exception("Error in phase transition callback")