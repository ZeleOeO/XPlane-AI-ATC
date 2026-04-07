"""
Decision-routed ATC Agent — replaces the free-form LLM with a
decision-tree + heuristic + LLM-fallback architecture inspired by OpenSquawk.
Pipeline:
  1. Pilot speaks → STT transcription
  2. Check readback requirements (if any)
  3. Try heuristic routing (single candidate → instant)
  4. LLM fallback: ask Gemini to pick next_state from candidates
  5. Fill template → TTS
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
import threading
from typing import TYPE_CHECKING, Callable
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
_client = None
if api_key:
    _client = genai.Client(api_key=api_key)
if TYPE_CHECKING:
    from ai_atc.atc.controller import ATCController
    from ai_atc.xplane.aircraft import AircraftState
from ai_atc.atc.decision_tree import (
    DecisionNode,
    get_node,
    get_next_candidates,
    get_initial_state,
    fill_template,
    DECISION_TREE,
)
from ai_atc.atc.readback import (
    quick_readback_check,
    format_missing_fields,
)
logger = logging.getLogger(__name__)
class GenerativeATCAgent:
    def __init__(
        self,
        controller: ATCController,
        get_aircraft_state: Callable[[], AircraftState],
        gui_log_callback: Callable[[str, str], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        model: str = "gemini-1.5-flash",
    ) -> None:
        self.controller = controller
        self.get_state = get_aircraft_state
        self.gui_log = gui_log_callback
        self.status_callback = status_callback
        self.model = model
        self._current_state_id: str = get_initial_state()
        self._previous_state_id: str | None = None
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._start_background_loop, daemon=True
        )
        self._loop_thread.start()
    def _start_background_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
    @property
    def current_decision_state(self) -> str:
        return self._current_state_id
    def callback(self, text: str) -> None:
        """Called by GUI / STT when the pilot speaks."""
        text = text.strip()
        if not text:
            return
        if self.gui_log:
            self.gui_log("PILOT", text)
        state = self.get_state()
        tuned_facility = self.controller._detect_tuned_facility(state)
        if not tuned_facility:
            logger.info(
                "Pilot transmitting on unassigned frequency (com: %d). Ignoring.",
                self.controller._get_active_com_freq(state),
            )
            return
        if tuned_facility == "ATIS":
            return
        asyncio.run_coroutine_threadsafe(
            self._route_decision(text, tuned_facility, state), self._loop
        )
    def _get_variables(self, state: AircraftState) -> dict:
        """Build the template variable dict from current flight state."""
        fp = self.controller.flight_plan
        ctrl = self.controller
        taxi_route = "Alpha, Bravo"
        hold_short = f"hold short runway {ctrl.active_runway}"
        variables = {
            "callsign": fp.airline_callsign or fp.callsign or "unknown",
            "destination": fp.destination_icao or "unknown",
            "origin": fp.origin_icao or "unknown",
            "runway": ctrl.active_runway or "unknown",
            "landing_runway": ctrl.active_runway or "unknown",
            "sid": fp.sid_name or "Radar Vectors",
            "altitude": str(fp.cruise_altitude_ft or 10000),
            "cruise_alt": str(fp.cruise_altitude_ft or 35000),
            "squawk": str(fp.squawk or "1200"),
            "taxi_route": taxi_route,
            "hold_short": hold_short,
            "gate": "the ramp",
            "facility_name": ctrl.target_facility_name,
            "next_facility": ctrl.next_facility_name,
            "next_freq": ctrl.get_facility_freq_str(ctrl.next_facility),
            "wind": "calm",
            "altimeter": "29.92",
            "pushback_direction": "south",
            "heading": str(ctrl.assigned_heading or 0),
            "heading_direction": "left",
            "missing_fields": "",
        }
        if ctrl.metar and ctrl.metar.wind:
            w = ctrl.metar.wind
            variables["wind"] = f"{w.get('direction', 'variable')} at {w.get('speed', 'calm')}"
        if ctrl.metar and ctrl.metar.altimeter:
            variables["altimeter"] = str(ctrl.metar.altimeter)
        return variables
    def _check_radio_check(self, text: str) -> bool:
        """Detect if pilot is doing a radio check."""
        lowered = text.lower()
        return any(
            phrase in lowered
            for phrase in ("radio check", "how do you hear", "how do you read", "comm check")
        )
    def _check_wrong_frequency(self, text: str, tuned_facility: str) -> tuple[bool, str, str]:
        """
        Detect if the pilot is asking for a service that belongs to a different facility.
        Returns (is_wrong, correct_facility, requested_service).
        """
        lowered = text.lower()
        service_facility_map = {
            "clearance": "DELIVERY",
            "ifr clearance": "DELIVERY",
            "pushback": "GROUND",
            "push back": "GROUND",
            "taxi": "GROUND",
            "takeoff": "TOWER",
            "take off": "TOWER",
            "departure": "DEPARTURE",
            "approach": "APPROACH",
            "landing": "TOWER",
            "cleared to land": "TOWER",
        }
        for service, correct_fac in service_facility_map.items():
            if service in lowered and correct_fac != tuned_facility:
                return (True, correct_fac, service)
        return (False, "", "")
    async def _route_decision(
        self, pilot_text: str, tuned_facility: str, aircraft_state: AircraftState
    ) -> None:
        """
        Main decision router: heuristic check → readback check → LLM fallback.
        """
        try:
            if self.status_callback:
                self.status_callback("thinking")
            variables = self._get_variables(aircraft_state)
            current_node = get_node(self._current_state_id)
            if not current_node:
                logger.error("Unknown decision state: %s", self._current_state_id)
                self._current_state_id = get_initial_state()
                current_node = get_node(self._current_state_id)
            if self._check_radio_check(pilot_text):
                radio_node = get_node("RADIO_CHECK")
                if radio_node:
                    response = fill_template(radio_node.say_tpl, variables)
                    self._speak(response, tuned_facility)
                    return
            is_wrong, correct_fac, requested_service = self._check_wrong_frequency(
                pilot_text, tuned_facility
            )
            if is_wrong:
                variables["requested_service"] = requested_service
                variables["correct_facility"] = self.controller.target_facility_name
                variables["correct_freq"] = self.controller.get_facility_freq_str(correct_fac)
                wrong_node = get_node("WRONG_FREQUENCY")
                if wrong_node:
                    response = fill_template(wrong_node.say_tpl, variables)
                    self._speak(response, tuned_facility)
                    return
            if current_node.facility not in ("ANY", tuned_facility):
                expected_fac = current_node.facility
                variables["correct_facility"] = self.controller.target_facility_name
                variables["correct_freq"] = self.controller.get_facility_freq_str(expected_fac)
                variables["requested_service"] = "this service"
                wrong_node = get_node("WRONG_FREQUENCY")
                if wrong_node:
                    response = fill_template(wrong_node.say_tpl, variables)
                    self._speak(response, tuned_facility)
                    return
            if current_node.readback_required:
                status, missing = quick_readback_check(
                    pilot_text, current_node.readback_required, variables
                )
                if status == "missing" and missing:
                    logger.info(
                        "Readback incomplete — missing: %s", missing
                    )
                    variables["missing_fields"] = format_missing_fields(missing)
                    if current_node.bad_next:
                        bad_id = current_node.bad_next[0]
                        bad_node = get_node(bad_id)
                        if bad_node:
                            response = fill_template(bad_node.say_tpl, variables)
                            self._speak(response, tuned_facility)
                            if bad_node.auto_advance and bad_node.next:
                                self._current_state_id = bad_node.next[0]
                            return
                    else:
                        self._speak(
                            fill_template("{callsign}, say again.", variables),
                            tuned_facility,
                        )
                        return
                if status == "ok" and current_node.next:
                    for nid in current_node.next:
                        if "CORRECT" in nid or "OK" in nid:
                            next_node = get_node(nid)
                            if next_node:
                                response = fill_template(next_node.say_tpl, variables)
                                self._speak(response, tuned_facility)
                                self._advance_state(next_node)
                                return
                    self._advance_to_first(current_node, variables, tuned_facility)
                    return
            candidates = get_next_candidates(self._current_state_id)
            if len(candidates) == 1:
                next_node = candidates[0]
                logger.info(
                    "Heuristic: single candidate %s → %s",
                    self._current_state_id,
                    next_node.id,
                )
                response = fill_template(current_node.say_tpl, variables)
                self._speak(response, tuned_facility)
                self._advance_state(next_node)
                return
            if len(candidates) > 1:
                logger.info(
                    "LLM routing: %d candidates from %s",
                    len(candidates),
                    self._current_state_id,
                )
                chosen = await self._llm_decide(
                    pilot_text, current_node, candidates, variables
                )
                if chosen:
                    response = fill_template(chosen.say_tpl, variables)
                    self._speak(response, tuned_facility)
                    self._advance_state(chosen)
                    return
            if not candidates:
                response = fill_template(current_node.say_tpl, variables)
                self._speak(response, tuned_facility)
                if current_node.auto_advance and current_node.next:
                    next_node = get_node(current_node.next[0])
                    if next_node:
                        self._advance_state(next_node)
                return
            off_node = get_node("OFF_SCHEMA")
            if off_node:
                response = fill_template(off_node.say_tpl, variables)
                self._speak(response, tuned_facility)
        except Exception as e:
            logger.exception("Decision routing error: %s", e)
            if self.status_callback:
                self.status_callback("error")
            self.controller._add_instruction(
                "Say again, bad reception.",
                self.controller.current_phase,
                tuned_facility,
            )
        finally:
            if self.status_callback:
                self.status_callback("idle")
    async def _llm_decide(
        self,
        pilot_text: str,
        current_node: DecisionNode,
        candidates: list[DecisionNode],
        variables: dict,
    ) -> DecisionNode | None:
        """
        Ask Gemini to pick the best next_state from the candidate list.
        Returns the chosen DecisionNode or None on failure.
        """
        if not api_key:
            logger.error("GOOGLE_API_KEY not set — falling back to first candidate")
            return candidates[0]
        candidate_summaries = "\n".join(
            f"- {c.id}: {fill_template(c.say_tpl, variables)[:100]}"
            for c in candidates
        )
        system_prompt = (
            "You are an ATC decision router. Given the pilot's transmission and a list of "
            "candidate next states, pick the most appropriate state ID.\n"
            "Respond ONLY with JSON: {\"next_state\": \"STATE_ID\", \"reason\": \"short rationale\"}\n"
            "Only use state IDs from the provided list."
        )
        user_prompt = (
            f"Current state: {current_node.id}\n"
            f"Current facility: {current_node.facility}\n"
            f"Pilot said: \"{pilot_text}\"\n\n"
            f"Candidate next states:\n{candidate_summaries}\n\n"
            f"Flight context: callsign={variables.get('callsign')}, "
            f"runway={variables.get('runway')}, destination={variables.get('destination')}"
        )
        global _client
        if not _client and api_key:
             _client = genai.Client(api_key=api_key)

        try:
            response = await asyncio.to_thread(
                _client.models.generate_content,
                model=self.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.1,
                    max_output_tokens=256,
                    response_mime_type="application/json",
                )
            )
            raw = response.text.strip()
            logger.debug("LLM decision raw: %s", raw)
            parsed = self._extract_json(raw)
            if parsed and "next_state" in parsed:
                chosen_id = parsed["next_state"]
                reason = parsed.get("reason", "")
                logger.info("LLM chose: %s (reason: %s)", chosen_id, reason)
                for c in candidates:
                    if c.id == chosen_id:
                        return c
                logger.warning("LLM chose invalid state %s, using first candidate", chosen_id)
        except Exception as e:
            logger.exception("LLM decision failed: %s", e)
        return candidates[0] if candidates else None
    def _extract_json(self, text: str) -> dict | None:
        """Extract a JSON object from possibly noisy LLM output."""
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return None
    def _advance_state(self, next_node: DecisionNode) -> None:
        """Advance the decision tree to the next node."""
        self._previous_state_id = self._current_state_id
        self._current_state_id = next_node.id
        logger.info(
            "Decision state: %s → %s",
            self._previous_state_id,
            self._current_state_id,
        )
        from ai_atc.atc.state_machine import FlightPhase
        if next_node.facility and next_node.facility != "ANY":
            self.controller._active_facility = next_node.facility
        if next_node.auto_advance and next_node.next:
            auto_next = get_node(next_node.next[0])
            if auto_next and auto_next.id != next_node.id:
                self._previous_state_id = self._current_state_id
                self._current_state_id = auto_next.id
                logger.info(
                    "Auto-advance: %s → %s",
                    self._previous_state_id,
                    self._current_state_id,
                )
    def _advance_to_first(
        self, current_node: DecisionNode, variables: dict, tuned_facility: str
    ) -> None:
        """Advance to the first next candidate and speak its template."""
        if current_node.next:
            first = get_node(current_node.next[0])
            if first:
                response = fill_template(first.say_tpl, variables)
                self._speak(response, tuned_facility)
                self._advance_state(first)
    def _speak(self, text: str, facility: str) -> None:
        """Add an ATC instruction and log it."""
        self.controller._add_instruction(
            text, self.controller.current_phase, facility
        )
        if self.gui_log:
            self.gui_log("ATC", text)