import hashlib
import hmac
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config import settings
from database import db
from dialogue_service import process_chat

app = FastAPI(title="LifeLine Local Chat and Provider API", version="0.2.0")
WEB_ROOT = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    conversation_id: UUID
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    conversation_id: UUID
    reply: str
    intent: str
    simulated: bool


class ProviderResponse(BaseModel):
    provider_id: str = Field(min_length=1, max_length=80)
    status: Literal["ACCEPTED", "REJECTED"]
    response: str = Field(min_length=1, max_length=1000)
    eta_minutes: int | None = Field(default=None, ge=1, le=1440)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@app.on_event("startup")
def seed():
    db.seed_demo(settings.provider_token)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", include_in_schema=False)
def chat_home():
    return FileResponse(WEB_ROOT / "index.html", media_type="text/html")


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest):
    result = process_chat(str(body.conversation_id), body.message, str(uuid4()))
    return ChatResponse(conversation_id=body.conversation_id, **result)


@app.get("/provider/requests")
def pending_requests(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "provider authentication required")
    token = authorization[7:]
    providers = db.connect().execute("SELECT provider_id,token_hash FROM providers WHERE provider_type='mechanic'").fetchall()
    provider = next((p for p in providers if hmac.compare_digest(p["token_hash"], _hash(f"{settings.provider_token}:{p['provider_id']}")) and hmac.compare_digest(_hash(token), p["token_hash"])), None)
    if not provider:
        raise HTTPException(401, "provider authentication required")
    return [r for r in db.list_pending() if r["selected_provider_id"] == provider["provider_id"]]


@app.post("/provider/requests/{request_id}/response")
def respond(request_id: str, body: ProviderResponse, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer ") or not hmac.compare_digest(_hash(authorization[7:]), _hash(settings.provider_token)):
        raise HTTPException(401, "provider authentication required")
    row = db.connect().execute("SELECT token_hash FROM providers WHERE provider_id=?", (body.provider_id,)).fetchone()
    expected_hash = _hash(f"{settings.provider_token}:{body.provider_id}")
    if not row or not hmac.compare_digest(row[0], expected_hash) or not hmac.compare_digest(row[0], _hash(authorization[7:])):
        raise HTTPException(403, "provider identity is not authorized")
    try:
        return db.respond(request_id, body.provider_id, body.status, body.response, body.eta_minutes)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
