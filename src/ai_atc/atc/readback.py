"""
Readback verification — checks that a pilot's utterance contains the
required fields (runway, squawk, SID, altitude, etc.) by matching
against spoken variants of the expected values.

Supports both strict string matching (original logic) and a fuzzy path
that handles Whisper mistranscriptions ("tree" → 3, "won" → 1, etc.).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Phonetic / digit lookup tables
# ---------------------------------------------------------------------------

ICAO_PHONETIC: dict[str, str] = {
    "A": "alpha", "B": "bravo", "C": "charlie", "D": "delta",
    "E": "echo", "F": "foxtrot", "G": "golf", "H": "hotel",
    "I": "india", "J": "juliet", "K": "kilo", "L": "lima",
    "M": "mike", "N": "november", "O": "oscar", "P": "papa",
    "Q": "quebec", "R": "romeo", "S": "sierra", "T": "tango",
    "U": "uniform", "V": "victor", "W": "whiskey", "X": "xray",
    "Y": "yankee", "Z": "zulu",
}

ICAO_DIGITS: dict[str, str] = {
    "0": "zero", "1": "one", "2": "two", "3": "tree",
    "4": "fower", "5": "fife", "6": "six", "7": "seven",
    "8": "eight", "9": "niner",
}

SPOKEN_DIGITS: dict[str, str] = {
    "0": "zero", "1": "one", "2": "two", "3": "three",
    "4": "four", "5": "five", "6": "six", "7": "seven",
    "8": "eight", "9": "nine",
}

# Common Whisper mistranscriptions → correct digit
WHISPER_TYPO_MAP: dict[str, str] = {
    "won": "1", "to": "2", "too": "2", "tree": "3", "for": "4",
    "fore": "4", "ate": "8", "niner": "9", "fife": "5", "fower": "4",
}

# Spoken-number words for compound numbers
COMPOUND_NUMBERS: dict[str, int] = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000,
}


# ---------------------------------------------------------------------------
#  Helper functions
# ---------------------------------------------------------------------------

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


def _extract_all_numbers(text: str) -> list[int]:
    """
    Pull all numeric values from text, handling both raw digits and
    common Whisper word-to-digit typos.
    """
    # Strip formatting commas: "35,000" → "35000"
    cleaned_text = re.sub(r"(\d),(\d)", r"\1\2", text)

    # Raw digit strings
    results = [int(m) for m in re.findall(r"\d+", cleaned_text)]

    # Word-form numbers
    words = text.lower().split()
    for w in words:
        clean = w.strip(".,;:!?")
        if clean in WHISPER_TYPO_MAP:
            results.append(int(WHISPER_TYPO_MAP[clean]))
        elif clean in SPOKEN_DIGITS.values():
            # Reverse lookup
            for digit, word in SPOKEN_DIGITS.items():
                if word == clean:
                    results.append(int(digit))
                    break
        elif clean in ICAO_DIGITS.values():
            for digit, word in ICAO_DIGITS.items():
                if word == clean:
                    results.append(int(digit))
                    break

    # Compound spoken numbers ("thirty five thousand")
    compound = _parse_compound_number(words)
    results.extend(compound)

    return results


def _parse_compound_number(words: list[str]) -> list[int]:
    """Parse compound spoken numbers like 'thirty five thousand' → [35000]."""
    results: list[int] = []
    current = 0
    in_number = False

    single_map = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    }

    for w in words:
        low = w.lower().strip(".,;:!?")

        if low in single_map:
            current += single_map[low]
            in_number = True
        elif low in COMPOUND_NUMBERS:
            val = COMPOUND_NUMBERS[low]
            if val >= 100:
                current = max(current, 1) * val
            else:
                current += val
            in_number = True
        elif in_number:
            if current > 0:
                results.append(current)
            current = 0
            in_number = False

    if in_number and current > 0:
        results.append(current)

    return results


def fuzzy_number_match(utterance: str, expected_value: str) -> bool:
    """
    Check if any number in the utterance matches the expected value.
    Handles Whisper typos and spoken-word numbers.
    """
    expected_digits = re.sub(r"[^0-9]", "", expected_value)
    if not expected_digits:
        return False

    expected_num = int(expected_digits)
    extracted = _extract_all_numbers(utterance)

    return expected_num in extracted


# ---------------------------------------------------------------------------
#  Variant builder (for strict matching)
# ---------------------------------------------------------------------------

def build_spoken_variants(key: str, value: str) -> list[str]:
    """
    Generate all the ways a value might be spoken by a pilot.
    E.g., runway "28L" → ["28L", "28 left", "two eight left", ...]
    """
    normalized = str(value or "").strip()
    if not normalized:
        return []

    variants: set[str] = set()
    variants.add(normalized)
    variants.add(normalized.upper())
    variants.add(normalized.lower())

    # Hold short
    if key == "hold_short":
        base = re.sub(r"^holding\s+short", "hold short", normalized, flags=re.IGNORECASE)
        variants.add(base)
        if "runway" not in base.lower():
            variants.add(re.sub(r"^(hold short)", r"\1 runway", base, flags=re.IGNORECASE))

    # Takeoff / landing clearance
    if key in ("cleared_takeoff", "cleared_landing"):
        variants.add(normalized.replace("take-off", "takeoff"))
        variants.add(normalized.replace("take-off", "take off"))
        variants.update([
            "cleared for takeoff", "cleared takeoff",
            "cleared to land", "cleared for landing",
        ])

    # ICAO codes
    upper = normalized.upper()
    if re.match(r"^[A-Z]{3,4}$", upper):
        variants.add(to_icao_phonetic(upper))

    # 4-digit squawk codes
    if re.match(r"^\d{4}$", normalized):
        variants.add(" ".join(normalized))
        variants.add(spell_icao_digits(normalized))
        variants.add(spell_digits(normalized))

    # Runways
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

    # Altitudes
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

    # SID / STAR
    if key in ("sid", "star"):
        variants.add(normalized.upper())
        variants.add(normalized.lower())

    # Headings
    if key == "heading":
        digits_only = re.sub(r"[^0-9]", "", normalized)
        if digits_only:
            variants.add(digits_only)
            variants.add(spell_icao_digits(digits_only))
            variants.add(spell_digits(digits_only))
            variants.add(f"heading {digits_only}")

    # Destination / origin ICAO
    if key in ("destination", "origin"):
        upper_val = normalized.upper()
        if re.match(r"^[A-Z]{3,4}$", upper_val):
            variants.add(to_icao_phonetic(upper_val))
            variants.add(upper_val)

    return list(variants)


# ---------------------------------------------------------------------------
#  Readback checking
# ---------------------------------------------------------------------------

def resolve_readback_value(key: str, variables: dict) -> str | None:
    """Resolve the expected value for a readback field from variables."""
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

    Uses strict string matching first, then falls back to fuzzy number
    matching for numeric fields when strict matching fails.

    Returns:
        (status, missing_keys) where status is 'ok' or 'missing'.
    """
    if not readback_keys:
        return ("ok", [])

    sanitized = _sanitize(utterance)
    missing: list[str] = []

    for key in readback_keys:
        expected = resolve_readback_value(key, variables)
        if not expected:
            continue

        # --- Strict match first ---
        variants = build_spoken_variants(key, expected)
        found = any(_sanitize(v) in sanitized for v in variants)

        # --- Fuzzy fallback for numeric fields ---
        if not found and key in (
            "altitude", "cruise_alt", "squawk", "heading",
            "runway", "landing_runway",
        ):
            found = fuzzy_number_match(utterance, expected)

        if not found:
            missing.append(key)

    status = "ok" if not missing else "missing"
    return (status, missing)


# ---------------------------------------------------------------------------
#  Formatting
# ---------------------------------------------------------------------------

def format_missing_fields(missing: list[str]) -> str:
    """Format a list of missing field keys into human-readable ATC phraseology."""
    labels: dict[str, str] = {
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