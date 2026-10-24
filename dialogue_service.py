"""Reusable conversational workflow shared by ACP and local browser chat."""
import re
from typing import Any

from blood_service import find_blood_centres, format_blood_centres
from database import db
from intent_router import Intent, PromptAnalysis, analyze_prompt, extract_location
from mechanic_service import dispatch, find_mechanics

EMERGENCY_NOTE = (
    "If anyone is hurt or in immediate danger, contact local emergency services or the nearest hospital now. "
)


def _merge_value(state: dict[str, Any], key: str, value: Any) -> None:
    if value not in (None, ""):
        state[key] = value


def _analysis_route(analysis: PromptAnalysis, state: dict[str, Any]) -> str | None:
    if analysis.intent in (Intent.BLOOD_ASSISTANCE, Intent.MECHANIC_ASSISTANCE):
        return "blood" if analysis.intent == Intent.BLOOD_ASSISTANCE else "mechanic"
    if analysis.emergency:
        if analysis.service_type == "blood" or analysis.blood_group or state.get("workflow") == "blood":
            return "blood"
        if analysis.service_type == "mechanic" or analysis.vehicle_type or analysis.mechanic_service or analysis.vehicle_problem:
            return "mechanic"
    return state.get("workflow")


def _mechanic_options(state: dict[str, Any], conversation_key: str, message_id: str) -> tuple[str, bool]:
    location = state.get("location")
    if not location:
        state["phase"] = "mechanic_details"
        state["workflow"] = "mechanic"
        db.save_conversation(conversation_key, state)
        return "Where is the vehicle? Please give a nearby city, road, sector, or landmark.", True

    # Match only against a capability we actually know; a free-form symptom is
    # not itself a reliable provider-service filter.
    search_service = state.get("mechanic_service") or ""
    providers = find_mechanics(location, search_service)
    if not providers:
        state["phase"] = "mechanic_details"
        state["workflow"] = "mechanic"
        db.save_conversation(conversation_key, state)
        return (
            f"I couldn't find a matching registered mechanic for {location} in the available directory. "
            "The directory is simulated and doesn't cover every area. Try a nearby city or contact highway assistance.",
            True,
        )

    state.update(
        phase="choose_provider",
        workflow="mechanic",
        providers=[provider.__dict__ for provider in providers],
        booking_key=f"{conversation_key}:{message_id}",
    )
    db.save_conversation(conversation_key, state)
    lines = [f"Mechanic options near {location} — SIMULATED DIRECTORY:"]
    for index, provider in enumerate(providers, 1):
        service = state.get("mechanic_service") or provider.services
        lines.append(
            f"{index}. {provider.name} — {provider.service_area}; service: {service}; "
            f"contact: {provider.contact}; distance, arrival time, and price: not available. SIMULATED"
        )
    lines.append("Choose an option number. I will ask you to confirm before sending a request.")
    return "\n".join(lines), True


def _provider_selection(text: str, providers: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = text.strip().casefold()
    match = re.fullmatch(r"(?:option(?:\s+number)?|provider|number|choice)?\s*#?\s*(\d+)", normalized)
    if match:
        index = int(match.group(1)) - 1
        return providers[index] if 0 <= index < len(providers) else None
    ordinal = re.fullmatch(r"(?:the\s+)?(first|second|third|1st|2nd|3rd)(?:\s+one)?", normalized)
    if ordinal:
        index = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2}[ordinal.group(1)]
        return providers[index] if index < len(providers) else None
    return next(
        (provider for provider in providers if provider["provider_id"].casefold() == normalized
         or provider["name"].casefold() == normalized),
        None,
    )


def _is_confirmation(text: str) -> bool:
    return text.strip().casefold() in {
        "yes", "yes please", "y", "confirm", "confirmed", "go ahead", "send it", "book it", "dispatch",
    }


def _process(conversation_key: str, text: str, message_id: str) -> dict[str, Any]:
    prompt = text.strip()
    if not prompt or len(prompt) > 4000:
        return {"reply": "Please enter a message between 1 and 4,000 characters.", "intent": Intent.UNKNOWN.value, "simulated": False}

    state = db.get_conversation(conversation_key)
    analysis = analyze_prompt(prompt)
    lower = prompt.casefold()
    preface = EMERGENCY_NOTE if (analysis.emergency or state.get("emergency")) else ""

    if lower in {"cancel", "stop", "no thanks"} and state.get("phase") in {"choose_provider", "confirm_dispatch", "mechanic_details", "blood_details"}:
        db.save_conversation(conversation_key, {})
        return {"reply": "Okay, I cancelled this assistance conversation. No provider request was sent.", "intent": analysis.intent.value, "simulated": False}

    if lower.startswith("status"):
        parts = prompt.split(maxsplit=1)
        request_id = parts[1].strip() if len(parts) > 1 else state.get("request_id")
        row = db.get_request(request_id) if request_id else None
        if not row:
            return {"reply": "I couldn't find that request. Include its full request ID after ‘status’.", "intent": analysis.intent.value, "simulated": False}
        reply = f"Request {row['request_id']} status: {row['status']}."
        if row["provider_response"]:
            reply += f" Provider response: {row['provider_response']}"
        if row["eta_minutes"]:
            reply += f" Provider supplied ETA: {row['eta_minutes']} minutes."
        return {"reply": reply, "intent": analysis.intent.value, "simulated": bool(row.get("selected_provider_id", "").startswith("demo-"))}

    phase = state.get("phase")
    if phase == "choose_provider":
        provider = _provider_selection(prompt, state.get("providers", []))
        if not provider:
            return {"reply": "Choose one of the listed option numbers or say ‘cancel’.", "intent": Intent.MECHANIC_ASSISTANCE.value, "simulated": True}
        state.update(phase="confirm_dispatch", selected=provider)
        db.save_conversation(conversation_key, state)
        reply = (
            f"You selected {provider['name']} ({provider['contact']}). Send a request near "
            f"{state['location']} for {state.get('vehicle_problem') or state.get('mechanic_service') or 'roadside assistance'}? "
            "Reply YES to confirm or NO to cancel. This provider is simulated."
        )
        if state.get("emergency"):
            reply = EMERGENCY_NOTE + reply
        return {"reply": reply, "intent": Intent.MECHANIC_ASSISTANCE.value, "simulated": True}

    if phase == "confirm_dispatch":
        if lower in {"no", "n", "cancel"}:
            db.save_conversation(conversation_key, {})
            return {"reply": "No provider request was sent.", "intent": Intent.MECHANIC_ASSISTANCE.value, "simulated": True}
        if not _is_confirmation(prompt):
            return {"reply": "Please reply YES to send this provider request, or NO to cancel.", "intent": Intent.MECHANIC_ASSISTANCE.value, "simulated": True}
        if state.get("request_id"):
            row = db.get_request(state["request_id"])
        else:
            row = dispatch(
                state["location"],
                state.get("vehicle_problem") or state.get("mechanic_service") or "roadside assistance",
                state["selected"]["provider_id"],
                state["booking_key"],
            )
            state.update(phase="booking_pending", request_id=row["request_id"])
            db.save_conversation(conversation_key, state)
        reply = (
            f"Request {row['request_id']} is {row['status']}. It was sent to the simulated provider. "
            "This is not an acceptance; only the provider can accept or reject it. Ask for the request status later."
        )
        return {"reply": preface + reply, "intent": Intent.MECHANIC_ASSISTANCE.value, "simulated": True}

    route = _analysis_route(analysis, state)
    if route == "mechanic":
        state.update(workflow="mechanic")
        _merge_value(state, "location", analysis.location)
        _merge_value(state, "destination", analysis.destination)
        _merge_value(state, "vehicle_type", analysis.vehicle_type)
        _merge_value(state, "vehicle_problem", analysis.vehicle_problem)
        _merge_value(state, "mechanic_service", analysis.mechanic_service)
        state["emergency"] = bool(state.get("emergency") or analysis.emergency)
        state["urgent"] = bool(state.get("urgent") or analysis.urgent)
        # During a follow-up the user often answers with just a place name.
        if not state.get("location") and phase == "mechanic_details" and len(prompt.split()) <= 8:
            state["location"] = prompt.removeprefix("near ").removeprefix("at ").strip(" .,!?;")
        reply, simulated = _mechanic_options(state, conversation_key, message_id)
        return {"reply": preface + reply, "intent": analysis.intent.value, "simulated": simulated}

    if route == "blood":
        state.update(workflow="blood")
        _merge_value(state, "location", analysis.location)
        _merge_value(state, "blood_group", analysis.blood_group)
        _merge_value(state, "units", analysis.units)
        state["urgent"] = bool(state.get("urgent") or analysis.urgent)
        if not state.get("location") and phase == "blood_details" and len(prompt.split()) <= 8:
            state["location"] = prompt.removeprefix("near ").removeprefix("in ").strip(" .,!?;")
        missing = []
        if not state.get("blood_group"):
            missing.append("blood group")
        if not state.get("units"):
            missing.append("number of units")
        if not state.get("location"):
            missing.append("city or nearby area")
        if missing:
            state["phase"] = "blood_details"
            db.save_conversation(conversation_key, state)
            reply = "What " + ", ".join(missing) + " should I use?"
            return {"reply": preface + reply, "intent": Intent.BLOOD_ASSISTANCE.value, "simulated": False}
        centres = find_blood_centres(state["location"], state["blood_group"])
        db.save_conversation(conversation_key, {})
        reply = format_blood_centres(centres, state["blood_group"])
        reply = reply.replace("Blood centre contacts near your requested area", f"Blood centre contacts for {state['units']} unit(s) of {state['blood_group']} near {state['location']}")
        if state.get("urgent"):
            reply = EMERGENCY_NOTE + reply
        return {"reply": reply, "intent": Intent.BLOOD_ASSISTANCE.value, "simulated": bool(centres)}

    if analysis.emergency:
        return {
            "reply": EMERGENCY_NOTE + "Tell me whether you need roadside mechanic assistance or blood centre contacts, and share your location if it is safe to do so.",
            "intent": Intent.EMERGENCY.value,
            "simulated": False,
        }

    if analysis.intent == Intent.GENERAL_QUESTION:
        return {
            "reply": (
                "I can help find simulated roadside mechanic options and create a request after you choose a provider "
                "and confirm. I can also list simulated blood-centre contacts, but I cannot verify live stock. "
                "For roadside help, share the vehicle problem and location. For blood assistance, share the blood group, "
                "number of units, and nearby area."
            ),
            "intent": analysis.intent.value,
            "simulated": False,
        }

    return {
        "reply": "I can help with roadside mechanic assistance or blood-centre contacts. What do you need, and where are you located?",
        "intent": Intent.UNKNOWN.value,
        "simulated": False,
    }


def process_chat(conversation_id: str, text: str, message_id: str) -> dict[str, Any]:
    """Process a browser turn using the same SQLite and service workflows as ACP."""
    return _process(f"web:{conversation_id}", text, message_id)


def respond_text(conversation_key: str, text: str, message_id: str) -> str:
    """ACP-facing adapter retaining the existing handle_text() contract."""
    return _process(conversation_key, text, message_id)["reply"]
