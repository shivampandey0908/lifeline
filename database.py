import sqlite3
import hashlib
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from config import settings
from models import BookingStatus, Provider, TRANSITIONS


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str | None = None):
        self.path = path or settings.db_path
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init(self):
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS providers (
              provider_id TEXT PRIMARY KEY, name TEXT NOT NULL, provider_type TEXT NOT NULL,
              service_area TEXT NOT NULL, services TEXT NOT NULL, contact TEXT NOT NULL,
              available INTEGER NOT NULL, is_demo INTEGER NOT NULL, token_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS service_requests (
              request_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE,
              user_location TEXT NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL,
              selected_provider_id TEXT NOT NULL REFERENCES providers(provider_id),
              status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              provider_response_at TEXT, provider_response TEXT, eta_minutes INTEGER
            );
            CREATE TABLE IF NOT EXISTS conversations (
              conversation_key TEXT PRIMARY KEY, state_json TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """)

    def seed_demo(self, provider_master_token: str):
        providers = [
            ("demo-mech-01", "Yamuna Roadside Motors (SIMULATED)", "mechanic", "Greater Noida, Yamuna Expressway", "engine, battery, tyre, towing", "+91-90000-00001", 1, 1),
            ("demo-mech-02", "Noida Highway Assist (SIMULATED)", "mechanic", "Noida, Greater Noida", "engine, battery, towing", "+91-90000-00002", 1, 1),
            ("demo-mech-03", "Expressway Auto Care (SIMULATED)", "mechanic", "Yamuna Expressway, Jewar", "tyre, fuel, towing", "+91-90000-00003", 1, 1),
            ("demo-blood-01", "Demo Blood Centre — Greater Noida (SIMULATED)", "blood_bank", "Greater Noida", "blood component inquiry", "+91-90000-00011", 1, 1),
            ("demo-blood-02", "Demo District Blood Centre — Noida (SIMULATED)", "blood_bank", "Noida", "blood component inquiry", "+91-90000-00012", 1, 1),
        ]
        with self.connect() as c:
            c.executemany("""INSERT INTO providers
              (provider_id,name,provider_type,service_area,services,contact,available,is_demo,token_hash)
              VALUES (?,?,?,?,?,?,?,?,?)
              ON CONFLICT(provider_id) DO UPDATE SET name=excluded.name,provider_type=excluded.provider_type,
              service_area=excluded.service_area,services=excluded.services,contact=excluded.contact,
              available=excluded.available,is_demo=excluded.is_demo,token_hash=excluded.token_hash""",
              [(*p, hashlib.sha256(f"{provider_master_token}:{p[0]}".encode()).hexdigest()) for p in providers])

    def find_providers(self, location: str, category: str, issue: str = "") -> list[Provider]:
        if not location or not location.strip():
            return []
        category = "blood_bank" if category == "blood" else "mechanic"
        rows = self.connect().execute("SELECT * FROM providers WHERE provider_type=? AND available=1", (category,)).fetchall()
        loc = location.casefold()
        location_terms = {
            token for token in re.findall(r"[a-z0-9]+", loc)
            if token not in {"near", "at", "in", "around", "the", "sector", "road", "highway"}
        }
        issue_words = {w for w in issue.casefold().split() if len(w) > 3}
        result = []
        for row in rows:
            area = (row["service_area"] + " " + row["name"]).casefold()
            area_terms = set(re.findall(r"[a-z0-9]+", area))
            if loc and not any(piece.strip() in area for piece in loc.split(",")) and not location_terms.intersection(area_terms):
                # Greater Noida/Yamuna Expressway should match generic region data.
                if not ("greater" in location_terms and "noida" in location_terms and ("greater noida" in row["service_area"].casefold() or "yamuna" in row["service_area"].casefold())):
                    continue
            services = row["services"].casefold()
            if category == "mechanic" and issue_words and not any(w in services for w in issue_words):
                continue
            result.append(Provider(row["provider_id"], row["name"], row["provider_type"], row["service_area"], row["services"], row["contact"], bool(row["available"]), bool(row["is_demo"])))
        return result

    def create_request(self, location: str, category: str, description: str, provider_id: str, idempotency_key: str):
        request_id, stamp = str(uuid4()), now()
        with self.connect() as c:
            try:
                c.execute("INSERT INTO service_requests(request_id,idempotency_key,user_location,category,description,selected_provider_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                          (request_id,idempotency_key,location,category,description,provider_id,BookingStatus.CREATED,stamp,stamp))
                c.execute("UPDATE service_requests SET status=?,updated_at=? WHERE request_id=?", (BookingStatus.PENDING, now(), request_id))
            except sqlite3.IntegrityError:
                row = c.execute("SELECT * FROM service_requests WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if row:
                    return dict(row)
                raise
        return self.get_request(request_id)

    def get_request(self, request_id: str):
        row = self.connect().execute("SELECT * FROM service_requests WHERE request_id=?", (request_id,)).fetchone()
        if row and row["status"] == BookingStatus.PENDING:
            created = datetime.fromisoformat(row["created_at"])
            if created < datetime.now(timezone.utc) - timedelta(minutes=settings.booking_timeout_minutes):
                with self.connect() as c:
                    c.execute("UPDATE service_requests SET status=?,updated_at=? WHERE request_id=? AND status=?",
                              (BookingStatus.EXPIRED, now(), request_id, BookingStatus.PENDING))
                row = self.connect().execute("SELECT * FROM service_requests WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row else None

    def _expire_stale_pending(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=settings.booking_timeout_minutes)).isoformat()
        with self.connect() as c:
            c.execute("UPDATE service_requests SET status=?,updated_at=? WHERE status=? AND created_at < ?",
                      (BookingStatus.EXPIRED, now(), BookingStatus.PENDING, cutoff))

    def respond(self, request_id: str, provider_id: str, status: str, response: str, eta_minutes: int | None = None):
        try:
            new_status = BookingStatus(status)
        except ValueError as exc:
            raise ValueError("status must be ACCEPTED or REJECTED") from exc
        if new_status not in (BookingStatus.ACCEPTED, BookingStatus.REJECTED):
            raise ValueError("provider may only accept or reject")
        self.get_request(request_id)  # applies the configured pending timeout before provider action
        with self.connect() as c:
            row = c.execute("SELECT * FROM service_requests WHERE request_id=?", (request_id,)).fetchone()
            if not row:
                raise LookupError("request not found")
            if row["selected_provider_id"] != provider_id:
                raise PermissionError("provider does not own this request")
            current = BookingStatus(row["status"])
            if new_status not in TRANSITIONS[current]:
                if current == new_status:
                    return dict(row)
                raise ValueError(f"invalid transition {current} -> {new_status}")
            c.execute("UPDATE service_requests SET status=?,updated_at=?,provider_response_at=?,provider_response=?,eta_minutes=? WHERE request_id=? AND status=?",
                      (new_status,now(),now(),response[:1000],eta_minutes,request_id,current))
        return self.get_request(request_id)

    def list_pending(self):
        self._expire_stale_pending()
        return [dict(r) for r in self.connect().execute("SELECT * FROM service_requests WHERE status='PENDING'").fetchall()]

    def save_conversation(self, key: str, state: dict[str, Any]):
        import json
        with self.connect() as c:
            c.execute("INSERT INTO conversations VALUES(?,?,?) ON CONFLICT(conversation_key) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at", (key,json.dumps(state),now()))

    def get_conversation(self, key: str) -> dict[str, Any]:
        import json
        row = self.connect().execute("SELECT state_json FROM conversations WHERE conversation_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else {}


db = Database()
