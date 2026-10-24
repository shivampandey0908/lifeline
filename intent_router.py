"""Local prompt understanding with validated, deterministic extraction.

The parser deliberately does not treat a user's text as executable instructions. It
returns a small typed analysis which downstream workflows validate before acting.
"""
from dataclasses import dataclass
from enum import StrEnum
import re


class Intent(StrEnum):
    MECHANIC_ASSISTANCE = "mechanic_assistance"
    BLOOD_ASSISTANCE = "blood_assistance"
    GENERAL_QUESTION = "general_question"
    EMERGENCY = "emergency"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PromptAnalysis:
    intent: Intent
    service_type: str | None = None
    location: str | None = None
    destination: str | None = None
    vehicle_type: str | None = None
    vehicle_problem: str | None = None
    mechanic_service: str | None = None
    blood_group: str | None = None
    units: int | None = None
    urgent: bool = False
    emergency: bool = False
    missing_information: tuple[str, ...] = ()


_BLOOD_GROUP = re.compile(
    r"\b(AB|A|B|O)\s*-?\s*(positive\b|negative\b|\+|-)(?=$|[\s,.;!?])", re.I
)
_LOCATION = re.compile(
    r"\b(?:near|at|in|around|close\s+to|on|along)\s+(?:the\s+)?"
    r"(?P<place>[a-z0-9#-]+(?:\s+[a-z0-9#-]+){0,7})"
    r"(?=\s*[,.;!?]|\s+(?:and|but|because|where|while|near|at|in|close\s+to)\b|$)",
    re.I,
)
_DESTINATION = re.compile(r"\b(?:to|towards)\s+(?:the\s+)?([a-z0-9#-]+(?:\s+[a-z0-9#-]+){0,5})", re.I)
_UNITS = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:units?|bags?)\b", re.I
)
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def extract_blood_group(text: str) -> str | None:
    match = _BLOOD_GROUP.search(text)
    if not match:
        return None
    sign = "-" if match.group(2).casefold() in ("negative", "-") else "+"
    return f"{match.group(1).upper()}{sign}"


def extract_location(text: str) -> str | None:
    for match in _LOCATION.finditer(text):
        place = re.sub(r"\s+", " ", match.group("place")).strip(" .,!?;:")
        if place.casefold() not in {
            "me", "nearby", "my area", "my location", "current location", "here", "there",
            "a crash", "an accident", "a breakdown", "trouble", "a hurry",
        }:
            return place
    return None


def _vehicle_type(text: str) -> str | None:
    match = re.search(r"\b(car|bike|motorcycle|scooter|truck|van|bus|suv)\b", text, re.I)
    if not match:
        return None
    value = match.group(1).strip().casefold()
    return "bike" if value == "motorcycle" else value


def _blood_units(text: str) -> int | None:
    match = _UNITS.search(text)
    if not match:
        return None
    raw = match.group(1).casefold()
    try:
        units = int(raw)
    except ValueError:
        units = _NUMBER_WORDS[raw]
    return units if 1 <= units <= 10 else None


def analyze_prompt(text: str) -> PromptAnalysis:
    """Classify a free-form prompt and extract supported service parameters."""
    normalized = re.sub(r"\s+", " ", text).strip()
    t = normalized.casefold()
    blood_group = extract_blood_group(normalized)
    blood_signal = bool(blood_group) or any(
        word in t for word in ("blood", "blood bank", "platelet", "transfusion", "donor")
    )
    mechanic_signal = any(
        word in t for word in (
            "mechanic", "roadside", "breakdown", "broke down", "won't start",
            "wont start", "will not start", "flat tyre", "flat tire", "puncture",
            "towing", "tow truck", "engine", "battery", "car", "bike", "motorcycle",
            "scooter", "vehicle", "fuel",
        )
    )
    emergency = any(
        phrase in t for phrase in (
            "emergency", "accident", "crash", "injured", "unconscious", "trapped",
            "not breathing", "severe bleeding", "bleeding heavily", "life threatening",
            "life-threatening", "someone is hurt", "people are hurt",
        )
    )
    urgent = emergency or any(word in t for word in ("urgent", "urgently", "asap", "immediately", "quickly"))

    meta_question = any(
        phrase in t for phrase in ("what information", "what info", "what details", "what do you need", "what should i provide", "what can you do")
    )
    if emergency:
        intent = Intent.EMERGENCY
    elif meta_question:
        intent = Intent.GENERAL_QUESTION
    elif blood_signal:
        intent = Intent.BLOOD_ASSISTANCE
    elif mechanic_signal:
        intent = Intent.MECHANIC_ASSISTANCE
    elif any(word in t for word in ("what", "how", "can you", "could you", "explain", "information", "help")):
        intent = Intent.GENERAL_QUESTION
    elif normalized:
        intent = Intent.UNKNOWN
    else:
        intent = Intent.UNKNOWN

    vehicle = _vehicle_type(normalized)
    problem = None
    service = None
    service_patterns = (
        ("flat tyre", "tyre"), ("flat tire", "tyre"), ("puncture", "tyre"),
        ("engine", "engine"), ("battery", "battery"), ("towing", "towing"),
        ("tow truck", "towing"), ("out of fuel", "fuel"), ("ran out of fuel", "fuel"),
        ("fuel", "fuel"), ("won't start", "engine"), ("wont start", "engine"),
        ("will not start", "engine"), ("brake", "brakes"), ("locked out", "lockout"),
    )
    for phrase, capability in service_patterns:
        if phrase in t:
            problem, service = phrase, capability
            break
    if not problem and any(word in t for word in ("broke down", "breakdown")):
        problem = "vehicle breakdown"

    units = _blood_units(normalized)
    destination_match = _DESTINATION.search(normalized)
    destination = destination_match.group(1).strip(" .,!?;:") if destination_match else None
    # A location specified with a location preposition takes priority over a destination.
    location = extract_location(normalized)

    missing: list[str] = []
    service_intent = Intent.BLOOD_ASSISTANCE if blood_signal else Intent.MECHANIC_ASSISTANCE if mechanic_signal else None
    if service_intent == Intent.BLOOD_ASSISTANCE:
        if not location:
            missing.append("location")
        if not blood_group:
            missing.append("blood_group")
        if units is None:
            missing.append("units")
    elif service_intent == Intent.MECHANIC_ASSISTANCE:
        if not location:
            missing.append("location")
        if not vehicle and not service:
            missing.append("vehicle_or_service")

    return PromptAnalysis(
        intent=intent,
        service_type=("blood" if blood_signal else "mechanic" if mechanic_signal else None),
        location=location,
        destination=destination,
        vehicle_type=vehicle,
        vehicle_problem=problem,
        mechanic_service=service,
        blood_group=blood_group,
        units=units,
        urgent=urgent,
        emergency=emergency,
        missing_information=tuple(missing),
    )


def classify(text: str) -> str:
    """Compatibility helper returning the public intent label as a string."""
    return analyze_prompt(text).intent.value
