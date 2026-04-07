"""
Readback verification — checks that a pilot's utterance contains
the required fields (runway, squawk, SID, altitude, etc.) by matching
against spoken variants of the expected values.
Ported from OpenSquawk's readback logic in openai.ts.
"""
from __future__ import annotations
import re
import logging
logger = logging.getLogger(__name__)
ICAO_PHONETIC = {
    "A": "alpha", "B": "bravo", "C": "charlie", "D": "delta",
    "E": "echo", "F": "foxtrot", "G": "golf", "H": "hotel",
    "I": "india", "J": "juliet", "K": "kilo", "L": "lima",
    "M": "mike", "N": "november", "O": "oscar", "P": "papa",
    "Q": "quebec", "R": "romeo", "S": "sierra", "T": "tango",
    "U": "uniform", "V": "victor", "W": "whiskey", "X": "xray",
    "Y": "yankee", "Z": "zulu",
}
ICAO_DIGITS = {
    "0": "zero", "1": "one", "2": "two", "3": "tree",
    "4": "fower", "5": "fife", "6": "six", "7": "seven",
    "8": "eight", "9": "niner",
}
SPOKEN_DIGITS = {
    "0": "zero", "1": "one", "2": "two", "3": "three",
    "4": "four", "5": "five", "6": "six", "7": "seven",
    "8": "eight", "9": "nine",
}
def to_icao_phonetic(text: str) -> str:
    """Convert text to ICAO phonetic alphabet."""
    return " ".join(ICAO_PHONETIC.get(c.upper(), c) for c in text if c.strip())
def spell_icao_digits(number: str) -> str:
    """Spell out digits using ICAO pronunciation."""
    return " ".join(ICAO_DIGITS.get(c, c) for c in str(number) if c.isdigit())
def spell_digits(number: str) -> str:
    """Spell out digits using common pronunciation."""
    return " ".join(SPOKEN_DIGITS.get(c, c) for c in str(number) if c.isdigit())
def _sanitize(text: str) -> str:
    """Normalize text for matching: lowercase, collapse whitespace, strip punctuation."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
def build_spoken_variants(key: str, value: str) -> list[str]:
    """
    Generate all the ways a value might be spoken by a pilot.
    E.g., runway "28L" -> ["28L", "28 left", "two eight left", "runway 28L", ...]
    """
    normalized = str(value or "").strip()
    if not normalized:
        return []
    variants: set[str] = set()
    variants.add(normalized)
    variants.add(normalized.upper())
    variants.add(normalized.lower())
    if key == "hold_short":
        base = re.sub(r"^holding\s+short", "hold short", normalized, flags=re.IGNORECASE)
        variants.add(base)
        if "runway" not in base.lower():
            variants.add(re.sub(r"^(hold short)", r"\1 runway", base, flags=re.IGNORECASE))
    if key in ("cleared_takeoff", "cleared_landing"):
        variants.add(normalized.replace("take-off", "takeoff"))
        variants.add(normalized.replace("take-off", "take off"))
        variants.add("cleared for takeoff")
        variants.add("cleared takeoff")
        variants.add("cleared to land")
        variants.add("cleared for landing")
    upper = normalized.upper()
    if re.match(r"^[A-Z]{3,4}$", upper):
        variants.add(to_icao_phonetic(upper))
    if re.match(r"^\d{4}$", normalized):
        variants.add(" ".join(normalized))  # "4 5 2 1"
        variants.add(spell_icao_digits(normalized))  # "fower fife two one"
        variants.add(spell_digits(normalized))  # "four five two one"
    rwy_match = re.match(r"^(\d{1,2})([LCR]?)$", normalized, re.IGNORECASE)
    if rwy_match:
        digits = rwy_match.group(1)
        suffix = rwy_match.group(2).upper()
        suffix_word = {"L": "left", "R": "right", "C": "center"}.get(suffix, "")
        variants.add(f"runway {normalized}")
        variants.add(f"runway {digits}")
        spelled = spell_icao_digits(digits)
        if spelled:
            full = f"{spelled} {suffix_word}".strip() if suffix_word else spelled
            variants.add(f"runway {full}")
            variants.add(full)
    if "altitude" in key or "level" in key or key in ("altitude", "cruise_alt"):
        digits_only = re.sub(r"[^0-9]", "", normalized)
        if digits_only:
            variants.add(digits_only)
            variants.add(" ".join(digits_only))
            variants.add(spell_icao_digits(digits_only))
            variants.add(spell_digits(digits_only))
            if len(digits_only) >= 3:
                fl = digits_only[:3]
                variants.add(f"flight level {spell_digits(fl)}")
                variants.add(f"FL{fl}")
    if key == "sid" or key == "star":
        variants.add(normalized.upper())
        variants.add(normalized.lower())
    if key == "heading":
        digits_only = re.sub(r"[^0-9]", "", normalized)
        if digits_only:
            variants.add(digits_only)
            variants.add(spell_icao_digits(digits_only))
            variants.add(spell_digits(digits_only))
            variants.add(f"heading {digits_only}")
    if key in ("destination", "origin"):
        upper_val = normalized.upper()
        if re.match(r"^[A-Z]{3,4}$", upper_val):
            variants.add(to_icao_phonetic(upper_val))
            variants.add(upper_val)
    return list(variants)
def resolve_readback_value(key: str, variables: dict) -> str | None:
    """
    Resolve the expected value for a readback field from the variables dict.
    Handles aliases like cleared_takeoff -> "cleared for takeoff".
    """
    if key == "cleared_takeoff":
        return "cleared for takeoff"
    if key == "cleared_landing":
        return "cleared to land"
    return variables.get(key)
def quick_readback_check(
    utterance: str,
    readback_keys: list[str],
    variables: dict,
) -> tuple[str, list[str]]:
    """
    Verify that the pilot's utterance contains the required readback fields.
    Returns:
        (status, missing_keys) where status is 'ok' or 'missing'
    """
    if not readback_keys:
        return ("ok", [])
    sanitized = _sanitize(utterance)
    missing: list[str] = []
    for key in readback_keys:
        expected = resolve_readback_value(key, variables)
        if not expected:
            continue  # Can't verify if no expected value
        variants = build_spoken_variants(key, expected)
        found = any(_sanitize(v) in sanitized for v in variants)
        if not found:
            missing.append(key)
    status = "ok" if not missing else "missing"
    return (status, missing)
def format_missing_fields(missing: list[str]) -> str:
    """Format a list of missing field keys into human-readable ATC phraseology."""
    labels = {
        "destination": "destination",
        "sid": "SID",
        "runway": "runway",
        "altitude": "altitude",
        "cruise_alt": "cruise altitude",
        "squawk": "squawk code",
        "taxi_route": "taxi route",
        "hold_short": "hold short point",
        "gate": "gate",
        "heading": "heading",
        "cleared_takeoff": "takeoff clearance",
        "cleared_landing": "landing clearance",
        "landing_runway": "landing runway",
    }
    readable = [labels.get(k, k) for k in missing]
    if len(readable) == 1:
        return readable[0]
    return ", ".join(readable[:-1]) + " and " + readable[-1]