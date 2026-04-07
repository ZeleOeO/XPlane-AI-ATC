"""
Decision-routed ATC Agent — replaces free-form LLM generation with a
decision-tree + heuristic + LLM-fallback architecture.

Pipeline:
    1. Pilot speaks → STT transcription
    2. Correction layer extracts critical numbers from noisy text
    3. Check readback requirements (if any) using fuzzy validation
    4. Try heuristic routing (single candidate → instant response)
    5. LLM fallback: ask Groq (Llama 3) to pick next_state from candidates
    6. Fill template → TTS
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from typing import TYPE_CHECKING, Callable

from dotenv import load_dotenv
from groq import Groq

from ai_atc.atc.decision_tree import (
    DECISION_TREE,
    DecisionNode,
    fill_template,
    get_initial_state,
    get_next_candidates,
    get_node,
)
from ai_atc.atc.readback import (
    format_missing_fields,
    quick_readback_check,
)
from ai_atc.voice.correction import (
    classify_intent,
    clean_transcription,
    validate_readback,
)

if TYPE_CHECKING:
    from ai_atc.atc.controller import ATCController
    from ai_atc.xplane.aircraft import AircraftState

load_dotenv()

logger = logging.getLogger(__name__)

_api_key = os.getenv("GROQ_API_KEY")
_client: Groq | None = Groq(api_key=_api_key) if _api_key else None


class GenerativeATCAgent:
    """
    The brain of the AI ATC.  Processes pilot speech through a structured
    decision tree, validates readbacks using a fuzzy correction layer, and
    falls back to an LLM for ambiguous multi-candidate routing decisions.
    """

    def __init__(
        self,
        controller: "ATCController",
        get_aircraft_state: Callable[[], "AircraftState"],
        gui_log_callback: Callable[[str, str], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        model: str = "llama-3.3-70b-versatile",
    ) -> None:
        self.controller = controller
        self.get_state = get_aircraft_state
        self.gui_log = gui_log_callback
        self.status_callback = status_callback
        self.model = model

        self._current_state_id: str = get_initial_state()
        self._previous_state_id: str | None = None
        self._last_instruction_vars: dict[str, str] = {}

        # Background event loop for async LLM calls
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._start_background_loop, daemon=True,
        )
        self._loop_thread.start()

    # ------------------------------------------------------------------ #
    #  Event loop                                                        #
    # ------------------------------------------------------------------ #

    def _start_background_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    # ------------------------------------------------------------------ #
    #  Public interface                                                  #
    # ------------------------------------------------------------------ #

    @property
    def current_decision_state(self) -> str:
        return self._current_state_id

    def callback(self, text: str) -> None:
        """Called by the STT engine when the pilot speaks."""
        text = text.strip()
        if not text:
            return

        # Handle low-confidence rejection from STT
        if text == "__LOW_CONFIDENCE__":
            state = self.get_state()
            tuned = self.controller._detect_tuned_facility(state)
            if tuned and tuned != "ATIS":
                variables = self._get_variables(state)
                self._speak(
                    fill_template("{callsign}, say again, transmission garbled.", variables),
                    tuned,
                )
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
            self._route_decision(text, tuned_facility, state),
            self._loop,
        )

    def get_stt_context(self) -> dict | None:
        """
        Provide current flight context to the STT engine for dynamic
        prompt generation.  Returns phase name and expected variables.
        """
        phase = self.controller.current_phase
        return {
            "phase": phase.name if hasattr(phase, "name") else str(phase),
            "variables": dict(self._last_instruction_vars),
        }

    # ------------------------------------------------------------------ #
    #  Template variables                                                #
    # ------------------------------------------------------------------ #

    def _get_variables(self, state: "AircraftState") -> dict[str, str]:
        """Build the template variable dict from current flight state."""
        fp = self.controller.flight_plan
        ctrl = self.controller

        taxi_route = "Alpha, Bravo"
        hold_short = f"hold short runway {ctrl.active_runway}"

        variables: dict[str, str] = {
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
            dir_str = "variable" if w.variable else f"{w.direction:03d}"
            spd_str = "calm" if w.calm else str(w.speed)
            variables["wind"] = f"{dir_str} at {spd_str}"

        if ctrl.metar and ctrl.metar.altimeter_inhg:
            variables["altimeter"] = str(ctrl.metar.altimeter_inhg)

        # Store for STT context
        self._last_instruction_vars = dict(variables)

        return variables

    # ------------------------------------------------------------------ #
    #  Intent detection helpers                                          #
    # ------------------------------------------------------------------ #

    def _check_radio_check(self, text: str) -> bool:
        """Detect if pilot is doing a radio check."""
        return classify_intent(text) == "radio_check"

    def _check_wrong_frequency(
        self, text: str, tuned_facility: str,
    ) -> tuple[bool, str, str]:
        """
        Detect if the pilot is asking for a service that belongs to a
        different facility.
        """
        lowered = text.lower()

        service_map: dict[str, str] = {
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

        for service, correct_fac in service_map.items():
            if service in lowered and correct_fac != tuned_facility:
                return (True, correct_fac, service)

        return (False, "", "")

    # ------------------------------------------------------------------ #
    #  Main decision router                                              #
    # ------------------------------------------------------------------ #

    async def _route_decision(
        self,
        pilot_text: str,
        tuned_facility: str,
        aircraft_state: "AircraftState",
    ) -> None:
        """
        Core decision pipeline:
            radio check → wrong frequency → readback check → heuristic → LLM
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

            # --- Radio check (intercept before anything else) ---
            if self._check_radio_check(pilot_text):
                self._handle_radio_check(variables, tuned_facility)
                return

            # --- Wrong frequency detection ---
            if self._handle_wrong_frequency(pilot_text, tuned_facility, variables):
                return

            # --- Facility mismatch ---
            if current_node.facility not in ("ANY", tuned_facility):
                self._handle_facility_mismatch(
                    current_node, tuned_facility, variables,
                )
                return

            # --- Readback validation (uses correction layer) ---
            if current_node.readback_required:
                result = self._handle_readback(
                    pilot_text, current_node, variables, tuned_facility,
                )
                if result:
                    return

            # --- Heuristic routing (single candidate) ---
            candidates = get_next_candidates(self._current_state_id)

            if len(candidates) == 1:
                self._handle_single_candidate(
                    current_node, candidates[0], variables, tuned_facility,
                )
                return

            # --- LLM fallback (multiple candidates) ---
            if len(candidates) > 1:
                await self._handle_llm_routing(
                    pilot_text, current_node, candidates, variables, tuned_facility,
                )
                return

            # --- No candidates (leaf node) ---
            if not candidates:
                self._handle_leaf_node(current_node, variables, tuned_facility)
                return

            # --- Fallback ---
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

    # ------------------------------------------------------------------ #
    #  Decision handler methods                                          #
    # ------------------------------------------------------------------ #

    def _handle_radio_check(
        self, variables: dict, tuned_facility: str,
    ) -> None:
        radio_node = get_node("RADIO_CHECK")
        if radio_node:
            response = fill_template(radio_node.say_tpl, variables)
            self._speak(response, tuned_facility)

    def _handle_wrong_frequency(
        self,
        pilot_text: str,
        tuned_facility: str,
        variables: dict,
    ) -> bool:
        """Returns True if the pilot is on the wrong freq (handled)."""
        is_wrong, correct_fac, requested_service = self._check_wrong_frequency(
            pilot_text, tuned_facility,
        )
        if not is_wrong:
            return False

        variables["requested_service"] = requested_service
        variables["correct_facility"] = self.controller.target_facility_name
        variables["correct_freq"] = self.controller.get_facility_freq_str(correct_fac)

        wrong_node = get_node("WRONG_FREQUENCY")
        if wrong_node:
            response = fill_template(wrong_node.say_tpl, variables)
            self._speak(response, tuned_facility)

        return True

    def _handle_facility_mismatch(
        self,
        current_node: DecisionNode,
        tuned_facility: str,
        variables: dict,
    ) -> None:
        expected_fac = current_node.facility
        variables["correct_facility"] = self.controller.target_facility_name
        variables["correct_freq"] = self.controller.get_facility_freq_str(expected_fac)
        variables["requested_service"] = "this service"

        wrong_node = get_node("WRONG_FREQUENCY")
        if wrong_node:
            response = fill_template(wrong_node.say_tpl, variables)
            self._speak(response, tuned_facility)

    def _handle_readback(
        self,
        pilot_text: str,
        current_node: DecisionNode,
        variables: dict,
        tuned_facility: str,
    ) -> bool:
        """
        Validate readback using BOTH the strict string matcher AND the
        fuzzy correction layer.  The correction layer catches cases where
        Whisper garbled the words but the critical numbers are correct.

        Returns True if handled (caller should return).
        """
        # --- Try the fuzzy correction layer FIRST ---
        fuzzy_passed, fuzzy_missing = validate_readback(
            pilot_text,
            variables,
            required_fields=current_node.readback_required,
        )

        if fuzzy_passed:
            logger.info("Fuzzy readback validation PASSED.")
            # Find the "CORRECT" / "OK" next state
            for nid in current_node.next:
                if "CORRECT" in nid or "OK" in nid:
                    next_node = get_node(nid)
                    if next_node:
                        response = fill_template(next_node.say_tpl, variables)
                        self._speak(response, tuned_facility)
                        self._advance_state(next_node)
                        return True

            # No explicit CORRECT node — just advance
            self._advance_to_first(current_node, variables, tuned_facility)
            return True

        # --- Fall back to strict string matching ---
        status, missing = quick_readback_check(
            pilot_text, current_node.readback_required, variables,
        )

        if status == "ok":
            for nid in current_node.next:
                if "CORRECT" in nid or "OK" in nid:
                    next_node = get_node(nid)
                    if next_node:
                        response = fill_template(next_node.say_tpl, variables)
                        self._speak(response, tuned_facility)
                        self._advance_state(next_node)
                        return True

            self._advance_to_first(current_node, variables, tuned_facility)
            return True

        # --- Readback failed — report missing fields ---
        if status == "missing" and missing:
            # Use the smaller missing list (fuzzy is usually more lenient)
            effective_missing = fuzzy_missing if len(fuzzy_missing) < len(missing) else missing
            logger.info("Readback incomplete — missing: %s", effective_missing)

            variables["missing_fields"] = format_missing_fields(effective_missing)

            if current_node.bad_next:
                bad_node = get_node(current_node.bad_next[0])
                if bad_node:
                    response = fill_template(bad_node.say_tpl, variables)
                    self._speak(response, tuned_facility)
                    if bad_node.auto_advance and bad_node.next:
                        self._current_state_id = bad_node.next[0]
                    return True

            self._speak(
                fill_template("{callsign}, say again.", variables),
                tuned_facility,
            )
            return True

        return False

    def _handle_single_candidate(
        self,
        current_node: DecisionNode,
        next_node: DecisionNode,
        variables: dict,
        tuned_facility: str,
    ) -> None:
        logger.info(
            "Heuristic: single candidate %s → %s",
            self._current_state_id, next_node.id,
        )
        response = fill_template(current_node.say_tpl, variables)
        self._speak(response, tuned_facility)
        self._advance_state(next_node)

    async def _handle_llm_routing(
        self,
        pilot_text: str,
        current_node: DecisionNode,
        candidates: list[DecisionNode],
        variables: dict,
        tuned_facility: str,
    ) -> None:
        logger.info(
            "LLM routing: %d candidates from %s",
            len(candidates), self._current_state_id,
        )
        chosen = await self._llm_decide(
            pilot_text, current_node, candidates, variables,
        )
        if chosen:
            response = fill_template(chosen.say_tpl, variables)
            self._speak(response, tuned_facility)
            self._advance_state(chosen)

    def _handle_leaf_node(
        self,
        current_node: DecisionNode,
        variables: dict,
        tuned_facility: str,
    ) -> None:
        response = fill_template(current_node.say_tpl, variables)
        self._speak(response, tuned_facility)
        if current_node.auto_advance and current_node.next:
            next_node = get_node(current_node.next[0])
            if next_node:
                self._advance_state(next_node)

    # ------------------------------------------------------------------ #
    #  LLM decision fallback                                             #
    # ------------------------------------------------------------------ #

    async def _llm_decide(
        self,
        pilot_text: str,
        current_node: DecisionNode,
        candidates: list[DecisionNode],
        variables: dict,
    ) -> DecisionNode | None:
        """
        Ask Groq (Llama 3) to pick the best next_state from candidates.
        Returns the chosen DecisionNode or the first candidate on failure.
        """
        global _client

        if not _api_key:
            logger.error("GROQ_API_KEY not set — falling back to first candidate")
            return candidates[0]

        candidate_summaries = "\n".join(
            f"- {c.id}: {fill_template(c.say_tpl, variables)[:100]}"
            for c in candidates
        )

        system_prompt = (
            "You are an ATC decision router. Given the pilot's transmission "
            "and a list of candidate next states, pick the most appropriate "
            "state ID.\n"
            'Respond ONLY with JSON: {"next_state": "STATE_ID", '
            '"reason": "short rationale"}\n'
            "Only use state IDs from the provided list."
        )

        user_prompt = (
            f"Current state: {current_node.id}\n"
            f"Current facility: {current_node.facility}\n"
            f'Pilot said: "{pilot_text}"\n\n'
            f"Candidate next states:\n{candidate_summaries}\n\n"
            f"Flight context: callsign={variables.get('callsign')}, "
            f"runway={variables.get('runway')}, "
            f"destination={variables.get('destination')}"
        )

        if not _client and _api_key:
            _client = Groq(api_key=_api_key)

        try:
            response = await asyncio.to_thread(
                _client.chat.completions.create,
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            logger.debug("LLM decision raw: %s", raw)

            parsed = self._extract_json(raw)
            if parsed and "next_state" in parsed:
                chosen_id = parsed["next_state"]
                reason = parsed.get("reason", "")
                logger.info("LLM chose: %s (reason: %s)", chosen_id, reason)

                for c in candidates:
                    if c.id == chosen_id:
                        return c

                logger.warning(
                    "LLM chose invalid state %s, using first candidate", chosen_id,
                )

        except Exception as e:
            logger.exception("LLM decision failed: %s", e)

        return candidates[0] if candidates else None

    # ------------------------------------------------------------------ #
    #  Utility methods                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_json(text: str) -> dict | None:
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
            self._previous_state_id, self._current_state_id,
        )

        if next_node.facility and next_node.facility != "ANY":
            self.controller._active_facility = next_node.facility

        # Auto-advance to next node if flagged
        if next_node.auto_advance and next_node.next:
            auto_next = get_node(next_node.next[0])
            if auto_next and auto_next.id != next_node.id:
                self._previous_state_id = self._current_state_id
                self._current_state_id = auto_next.id
                logger.info(
                    "Auto-advance: %s → %s",
                    self._previous_state_id, self._current_state_id,
                )

    def _advance_to_first(
        self,
        current_node: DecisionNode,
        variables: dict,
        tuned_facility: str,
    ) -> None:
        """Advance to the first next candidate and speak its template."""
        if current_node.next:
            first = get_node(current_node.next[0])
            if first:
                response = fill_template(first.say_tpl, variables)
                self._speak(response, tuned_facility)
                self._advance_state(first)

    def _speak(self, text: str, facility: str) -> None:
        """Add an ATC instruction and log it to the GUI."""
        self.controller._add_instruction(
            text, self.controller.current_phase, facility,
        )
        if self.gui_log:
            self.gui_log("ATC", text)