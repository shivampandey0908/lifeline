from datetime import datetime, timezone, timedelta
import pytest

from database import Database
from intent_router import analyze_prompt, classify, extract_blood_group, extract_location
from blood_service import find_blood_centres, format_blood_centres


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.seed_demo("test-secret")
    return database


def test_intent_and_entity_extraction():
    assert classify("My car broke down near Yamuna Expressway") == "mechanic_assistance"
    assert classify("Need O-positive blood near Greater Noida") == "blood_assistance"
    assert extract_blood_group("Need O+ urgently") == "O+"
    assert extract_location("Need help near Greater Noida") == "Greater Noida"
    blood = analyze_prompt("I need two units of O-negative blood near Greater Noida.")
    assert blood.units == 2 and blood.blood_group == "O-"
    assert blood.missing_information == ()
    emergency = analyze_prompt("I was in a crash and someone is injured.")
    assert emergency.intent == "emergency" and emergency.emergency


def test_missing_location_and_no_matching_providers(db):
    from mechanic_service import find_mechanics
    assert find_mechanics("", "engine", db) == []
    assert find_mechanics("Mumbai", "engine", db) == []


def test_provider_response_and_rejection(db):
    from mechanic_service import find_mechanics, dispatch
    provider = find_mechanics("Greater Noida", "engine", db)[0]
    request = dispatch("Greater Noida", "engine issue", provider.provider_id, "key-1", db)
    assert request["status"] == "PENDING"
    rejected = db.respond(request["request_id"], provider.provider_id, "REJECTED", "No technician available")
    assert rejected["status"] == "REJECTED"
    with pytest.raises(ValueError):
        db.respond(request["request_id"], provider.provider_id, "ACCEPTED", "duplicate transition")


def test_duplicate_idempotency_and_provider_ownership(db):
    from mechanic_service import find_mechanics, dispatch
    providers = find_mechanics("Greater Noida", "engine", db)
    first = dispatch("Greater Noida", "engine", providers[0].provider_id, "same-key", db)
    retry = dispatch("Greater Noida", "engine", providers[0].provider_id, "same-key", db)
    assert first["request_id"] == retry["request_id"]
    with pytest.raises(PermissionError):
        db.respond(first["request_id"], providers[1].provider_id, "ACCEPTED", "spoof")


def test_invalid_provider_response(db):
    from mechanic_service import find_mechanics, dispatch
    provider = find_mechanics("Greater Noida", "engine", db)[0]
    request = dispatch("Greater Noida", "engine", provider.provider_id, "key-invalid", db)
    with pytest.raises(ValueError):
        db.respond(request["request_id"], provider.provider_id, "PENDING", "not a provider decision")


def test_provider_timeout_expires_request(db):
    from mechanic_service import find_mechanics, dispatch
    provider = find_mechanics("Greater Noida", "engine", db)[0]
    request = dispatch("Greater Noida", "engine", provider.provider_id, "key-timeout", db)
    expired_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with db.connect() as conn:
        conn.execute("UPDATE service_requests SET created_at=? WHERE request_id=?", (expired_at, request["request_id"]))
    assert db.get_request(request["request_id"])["status"] == "EXPIRED"


def test_blood_stock_is_never_claimed_as_live(db):
    centres = find_blood_centres("Greater Noida", "O+", db)
    result = format_blood_centres(centres, "O+")
    assert "not available from a verified live source" in result
    assert "SIMULATED" in result
    assert "not confirmed" in result


def test_stale_or_missing_stock_timestamp_stays_unavailable(db):
    result = format_blood_centres(find_blood_centres("Greater Noida", "O+", db), "O+")
    assert "Last updated" not in result
    assert "call the centre to confirm" in result
