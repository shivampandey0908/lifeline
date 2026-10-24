from uuid import uuid4

from fastapi.testclient import TestClient

from provider_api import app


client = TestClient(app)


def test_local_chat_page_and_health():
    page = client.get("/")
    assert page.status_code == 200
    assert "LifeLine" in page.text
    assert "Type your message" in page.text
    assert client.get("/health").json() == {"ok": True}


def test_free_form_mechanic_followups_and_explicit_confirmation():
    conversation_id = str(uuid4())
    first = client.post("/api/chat", json={
        "conversation_id": conversation_id,
        "message": "My bike has a puncture and needs roadside help.",
    })
    assert first.status_code == 200
    assert first.json()["intent"] == "mechanic_assistance"
    assert "Where is the vehicle" in first.json()["reply"]

    location = client.post("/api/chat", json={
        "conversation_id": conversation_id,
        "message": "Yamuna Expressway",
    }).json()
    assert "SIMULATED DIRECTORY" in location["reply"]
    assert "service: tyre" in location["reply"]

    selection = client.post("/api/chat", json={
        "conversation_id": conversation_id,
        "message": "option number 2",
    }).json()
    assert "Reply YES to confirm" in selection["reply"]

    unconfirmed = client.post("/api/chat", json={
        "conversation_id": conversation_id,
        "message": "maybe",
    }).json()
    assert "Please reply YES" in unconfirmed["reply"]

    booking = client.post("/api/chat", json={
        "conversation_id": conversation_id,
        "message": "yes please",
    }).json()
    assert booking["simulated"] is True
    assert "PENDING" in booking["reply"]
    assert "not an acceptance" in booking["reply"]


def test_vehicle_breakdown_prompt_finds_general_mechanics():
    response = client.post("/api/chat", json={
        "conversation_id": str(uuid4()),
        "message": "My car broke down on the Yamuna Expressway. Find a nearby mechanic.",
    }).json()
    assert response["intent"] == "mechanic_assistance"
    assert "SIMULATED DIRECTORY" in response["reply"]


def test_blood_followup_uses_units_and_marks_demo_stock_unavailable():
    conversation_id = str(uuid4())
    first = client.post("/api/chat", json={
        "conversation_id": conversation_id,
        "message": "I urgently need two units of O-negative blood.",
    }).json()
    assert first["intent"] == "blood_assistance"
    assert "city or nearby area" in first["reply"]

    result = client.post("/api/chat", json={
        "conversation_id": conversation_id,
        "message": "Greater Noida",
    }).json()
    assert result["simulated"] is True
    assert "2 unit(s) of O-" in result["reply"]
    assert "not available from a verified live source" in result["reply"]
    assert "emergency services" in result["reply"]


def test_general_question_and_unknown_prompt_are_supported():
    question = client.post("/api/chat", json={
        "conversation_id": str(uuid4()),
        "message": "What information do you need to arrange roadside assistance?",
    }).json()
    assert question["intent"] == "general_question"
    assert "vehicle problem and location" in question["reply"]

    unknown = client.post("/api/chat", json={
        "conversation_id": str(uuid4()),
        "message": "Tell me a joke.",
    }).json()
    assert unknown["intent"] == "unknown"
    assert "roadside mechanic assistance or blood-centre contacts" in unknown["reply"]


def test_emergency_guidance_is_included_with_mechanic_search():
    response = client.post("/api/chat", json={
        "conversation_id": str(uuid4()),
        "message": "I was in a crash, my car is damaged, and I need towing near Greater Noida.",
    }).json()
    assert response["intent"] == "emergency"
    assert "contact local emergency services" in response["reply"]
    assert "SIMULATED DIRECTORY" in response["reply"]


def test_invalid_chat_payload_is_rejected():
    response = client.post("/api/chat", json={
        "conversation_id": "not-a-uuid",
        "message": "hello",
    })
    assert response.status_code == 422


def test_provider_api_rejects_missing_or_invalid_credentials():
    assert client.get("/provider/requests").status_code == 401
    response = client.post(
        f"/provider/requests/{uuid4()}/response",
        json={
            "provider_id": "demo-mech-01",
            "status": "ACCEPTED",
            "response": "Provider response",
        },
    )
    assert response.status_code == 401
    assert client.get(
        "/provider/requests",
        headers={"Authorization": "Bearer invalid-token"},
    ).status_code == 401
