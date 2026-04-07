"""
Transcription Correction Layer — sits between raw Whisper STT output
and the ATC decision agent.  Extracts critical aviation entities from
noisy text and validates them against expected values.

The core insight: we don't need *perfect* transcription.  We just need
to correctly extract the numbers (altitude, squawk, runway, heading)
and match them against what ATC expects.  Filler-word hallucinations
("deporture", "effects") are harmless and can be ignored.
"""
from __future__ import annotations

import logging
import re
from typing import Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Word → digit mappings (covers ICAO, casual English, common Whisper typos)
# ---------------------------------------------------------------------------

WORD_TO_DIGIT: dict[str, str] = {
    # ICAO
    "zero": "0", "one": "1", "two": "2", "tree": "3", "three": "3",
    "fower": "4", "four": "4", "fife": "5", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "niner": "9", "nine": "9",
    # Whisper hallucinations / homophones
    "won": "1", "to": "2", "too": "2", "for": "4", "fore": "4",
    "ate": "8",
}

# Multiplier words for compound numbers ("thirty five thousand" → 35000)
MULTIPLIER_WORDS: dict[str, int] = {
    "hundred": 100, "thousand": 1000,
}

TENS_WORDS: dict[str, int] = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}

ONES_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
}

# Runway suffix mappings (spoken → letter)
RUNWAY_SUFFIX: dict[str, str] = {
    "left": "L", "right": "R", "center": "C", "centre": "C",
}

# Common Whisper hallucination patterns that map to runway-related words
HALLUCINATION_RUNWAY_PATTERNS: dict[str, str] = {
    "point": "",       # "point 3 left" — "point" is noise
    "won": "1",
    "to": "2",
    "too": "2",
    "tree": "3",
    "for": "4",
    "fore": "4",
    "fife": "5",
    "ate": "8",
}


# ---- Number Extraction -----------------------------------------------------

def _parse_spoken_number(words: list[str]) -> list[int]:
    """
    Parse a sequence of words into numeric values.
    Handles: "thirty five thousand" → [35000]
             "one two zero zero"   → [1200]
             "5000"                → [5000]
    """
    results: list[int] = []
    accumulator = 0
    current = 0
    in_number = False

    for w in words:
        low = w.lower().strip(".,;:!?")

        # Raw digit string
        if low.isdigit():
            if in_number and current > 0:
                # Check if we're spelling digit-by-digit ("one two zero zero")
                pass
            results.append(int(low))
            in_number = False
            continue

        # Ones place word
        if low in ONES_WORDS:
            current += ONES_WORDS[low]
            in_number = True
            continue

        # Tens word
        if low in TENS_WORDS:
            current += TENS_WORDS[low]
            in_number = True
            continue

        # Multiplier
        if low in MULTIPLIER_WORDS:
            mult = MULTIPLIER_WORDS[low]
            if current == 0:
                current = 1
            current *= mult
            in_number = True
            continue

        # Not a number word — flush accumulator
        if in_number:
            accumulator += current
            if accumulator > 0:
                results.append(accumulator)
            accumulator = 0
            current = 0
            in_number = False

    # Flush at end
    if in_number:
        accumulator += current
        if accumulator > 0:
            results.append(accumulator)

    return results


def extract_numbers(text: str) -> list[int]:
    """
    Extract all numeric values from a transcription string.
    Handles raw digits, spelled-out digits, compound numbers, and
    comma-formatted numbers that Whisper commonly produces.

    Examples:
        "maintain 5000"              → [5000]
        "thirty five thousand feet"  → [35000]
        "squawk 1200"                → [1200]
        "altitude 35,000 feet"       → [35000]
        "squawk 1,200"               → [1200]
    """
    if not text:
        return []

    # Pre-process: strip formatting commas from digit groups.
    # "35,000" → "35000", "1,200" → "1200"
    cleaned = re.sub(r"(\d),(\d)", r"\1\2", text)

    # First pass: extract raw numeric substrings
    raw_nums = [int(m) for m in re.findall(r"\d+", cleaned)]

    # Second pass: parse spoken-word numbers
    words = cleaned.split()
    spoken_nums = _parse_spoken_number(words)

    # Merge, preserving order and deduplicating
    seen: set[int] = set()
    combined: list[int] = []
    for n in raw_nums + spoken_nums:
        if n not in seen:
            seen.add(n)
            combined.append(n)

    return combined


# ---- Runway Extraction (Proximity-Based) -----------------------------------

def extract_runway(text: str, expected_runway: str | None = None) -> str | None:
    """
    Detect runway references from noisy transcription text.

    Uses a proximity-based approach:
    1. Look for explicit patterns: "runway 23 left", "runway 23L"
    2. Look for suffix words (left/right/center) near any digit
    3. If we know the expected runway, validate partial matches

    This handles Whisper hallucinations like "point 3 left" where the
    full number got garbled but the suffix survived.
    """
    lowered = text.lower()

    # --- Pass 1: Explicit runway patterns ---
    # "runway 23 left", "runway 23L", "runway 23, left"
    explicit = re.search(
        r"runway\s+(\d{1,2})[,\s]*(left|right|center|centre|[lrc])\b",
        lowered,
    )
    if explicit:
        num = explicit.group(1)
        suffix = RUNWAY_SUFFIX.get(explicit.group(2), explicit.group(2).upper())
        return f"{num}{suffix}"

    # "runway 23" (no suffix)
    explicit_no_suffix = re.search(r"runway\s+(\d{1,2})\b", lowered)
    if explicit_no_suffix:
        return explicit_no_suffix.group(1)

    # Bare pattern without "runway": "23, left" or "23 left"
    bare = re.search(
        r"\b(\d{1,2})[,\s]+(left|right|center|centre)\b",
        lowered,
    )
    if bare:
        num = bare.group(1)
        suffix = RUNWAY_SUFFIX.get(bare.group(2), bare.group(2)[0].upper())
        return f"{num}{suffix}"
    for suffix_word, suffix_letter in RUNWAY_SUFFIX.items():
        if suffix_word in lowered:
            # Find all digit clusters in the text
            digit_matches = list(re.finditer(r"\d{1,2}", lowered))
            suffix_pos = lowered.index(suffix_word)

            # Find the closest digit cluster to the suffix word
            best_digit = None
            best_dist = 999
            for dm in digit_matches:
                dist = abs(dm.end() - suffix_pos)
                if dist < best_dist:
                    best_dist = dist
                    best_digit = dm.group()

            if best_digit and best_dist < 20:  # within ~20 chars
                return f"{best_digit}{suffix_letter}"

            # No digit found — but if we know the expected runway,
            # check if it has this suffix. "left" + expected "23L" = match.
            if expected_runway:
                expected_upper = expected_runway.upper()
                if expected_upper.endswith(suffix_letter):
                    logger.info(
                        "Runway proximity match: heard '%s', expected '%s' — accepting.",
                        suffix_word, expected_runway,
                    )
                    return expected_runway

    # --- Pass 3: Digit-word substitution for hallucinated numbers ---
    # "point 3 left" → substitue "point" as noise, "3" + "left" = "3L"
    # But if expected is "23L", accept it via the suffix match above.
    # Try spelled-out digits: "two three left"
    words = lowered.split()
    digit_str = ""
    found_suffix = ""
    for w in words:
        clean = w.strip(".,;:!?")
        if clean in WORD_TO_DIGIT:
            digit_str += WORD_TO_DIGIT[clean]
        elif clean in RUNWAY_SUFFIX:
            found_suffix = RUNWAY_SUFFIX[clean]
        elif clean.isdigit() and len(clean) <= 2:
            digit_str += clean

    if digit_str and found_suffix:
        return f"{digit_str}{found_suffix}"
    if digit_str and len(digit_str) <= 2:
        return digit_str

    return None


# ---- Intent Classification -------------------------------------------------

INTENT_PATTERNS: dict[str, list[str]] = {
    "radio_check": ["radio check", "comm check", "how do you read", "how do you hear"],
    "request_clearance": ["request clearance", "request ifr", "ifr clearance"],
    "request_taxi": ["request taxi", "ready to taxi", "taxi to"],
    "request_pushback": ["push back", "pushback", "ready to push", "push and start"],
    "request_takeoff": ["ready for departure", "ready for takeoff", "holding short"],
    "readback": [
        "cleared to", "cleared for", "squawk", "maintain", "climb",
        "descend", "runway", "via", "departure", "approach",
        "hold short", "taxi", "line up",
    ],
    "affirm": ["affirm", "affirmative", "roger", "wilco", "copy"],
    "say_again": ["say again", "repeat", "didn't catch"],
}


def classify_intent(text: str) -> str:
    """
    Simple keyword-based intent classifier.
    Returns the most specific matching intent, or 'unknown'.
    """
    lowered = text.lower()

    # Check specific intents first (most specific → least)
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if pattern in lowered:
                return intent

    return "unknown"


# ---- Readback Validation ---------------------------------------------------

def validate_readback(
    text: str,
    expected_vars: dict[str, str],
    required_fields: Sequence[str] | None = None,
) -> tuple[bool, list[str]]:
    """
    Validate a pilot readback by extracting critical numbers and matching
    against expected values.  Ignores hallucinated filler words entirely.

    Args:
        text:             Raw Whisper transcription of the pilot's readback.
        expected_vars:    Dict of expected template variables (altitude, squawk, etc.).
        required_fields:  Which fields must be present. Defaults to all numeric fields.

    Returns:
        (passed, missing_fields) — passed is True if all critical numbers match.
    """
    if required_fields is None:
        required_fields = [
            k for k in expected_vars
            if k in ("altitude", "cruise_alt", "squawk", "runway", "heading",
                      "landing_runway")
        ]

    numbers = extract_numbers(text)
    lowered = text.lower()
    missing: list[str] = []

    for field in required_fields:
        expected = expected_vars.get(field, "")
        if not expected:
            continue

        matched = False

        # --- Runway fields: use proximity-based detection ---
        if field in ("runway", "landing_runway"):
            detected_rwy = extract_runway(text, expected_runway=expected)
            if detected_rwy:
                # Normalize for comparison
                exp_digits = re.sub(r"[^0-9]", "", expected)
                det_digits = re.sub(r"[^0-9]", "", detected_rwy)
                exp_suffix = re.sub(r"[0-9]", "", expected).upper()
                det_suffix = re.sub(r"[0-9]", "", detected_rwy).upper()

                if exp_digits == det_digits:
                    if not exp_suffix or exp_suffix == det_suffix:
                        matched = True

            # Also check if runway number appears as a raw number
            if not matched:
                rwy_num = int(re.sub(r"[^0-9]", "", expected) or "0")
                if rwy_num and rwy_num in numbers:
                    # Check suffix if needed
                    exp_suffix = re.sub(r"[0-9]", "", expected).upper()
                    if not exp_suffix:
                        matched = True
                    else:
                        suffix_word = {
                            "L": "left", "R": "right", "C": "center"
                        }.get(exp_suffix, "")
                        if suffix_word in lowered:
                            matched = True

        # --- Numeric fields: simple number comparison ---
        elif field in ("altitude", "cruise_alt", "squawk", "heading"):
            expected_num = int(re.sub(r"[^0-9]", "", expected) or "0")
            if expected_num and expected_num in numbers:
                matched = True

            # For squawk: also check individual digits (Whisper may separate them)
            if not matched and field == "squawk" and len(expected) == 4:
                digits = list(expected)
                if all(int(d) in numbers for d in digits):
                    matched = True

        # --- Text fields: keyword matching ---
        elif field in ("destination", "origin"):
            if expected.lower() in lowered:
                matched = True
            # Try spoken ICAO phonetic (e.g., KORD → "kilo oscar romeo delta")
            # Partial match: just the airport name
            airport_names = {
                "KORD": ["o'hare", "ohare", "chicago", "kord", "cord", "code"],
                "KJFK": ["jfk", "kennedy", "john f"],
                "KLAX": ["lax", "los angeles"],
                "KATL": ["atlanta", "hartsfield"],
                "EGLL": ["heathrow"],
                "KIND": ["indianapolis", "indy", "kind"],
            }
            for name_variant in airport_names.get(expected.upper(), []):
                if name_variant in lowered:
                    matched = True
                    break

        elif field in ("sid", "star"):
            # SID/STAR names are tricky — just check substring
            sid_lower = expected.lower().replace("_", " ").replace("-", " ")
            if sid_lower in lowered or expected.lower() in lowered:
                matched = True
            # Accept "radar vectors" for the default SID
            if expected.lower() == "radar vectors" and "radar" in lowered:
                matched = True

        elif field in ("cleared_takeoff", "cleared_landing"):
            takeoff_phrases = ["cleared for takeoff", "cleared takeoff", "cleared to take off"]
            landing_phrases = ["cleared to land", "cleared for landing", "cleared landing"]
            phrases = takeoff_phrases if "takeoff" in field else landing_phrases
            if any(p in lowered for p in phrases):
                matched = True

        else:
            # Fallback: substring match
            if expected.lower() in lowered:
                matched = True

        if not matched:
            missing.append(field)

    passed = len(missing) == 0
    if passed:
        logger.info("Readback validation PASSED (all critical fields matched).")
    else:
        logger.info("Readback validation: missing fields %s", missing)

    return passed, missing


# ---- Transcription Cleaning ------------------------------------------------

def clean_transcription(text: str, context_vars: dict[str, str]) -> str:
    """
    If the raw transcription contains the right numbers but garbled words,
    produce a cleaned version for display purposes.

    This does NOT change the decision logic — just makes the UI log readable.
    """
    # For now, just strip common Whisper noise phrases
    noise_phrases = [
        "um", "uh", "ah", "like", "you know", "basically",
        "so", "okay so", "alright so",
    ]

    cleaned = text
    for noise in noise_phrases:
        cleaned = re.sub(
            rf"\b{re.escape(noise)}\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

    # Collapse multiple spaces
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

    return cleaned if cleaned else text
