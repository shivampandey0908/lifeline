from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import secrets

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Core database and workflow helpers remain usable without optional env-file loading.
    pass


_SEED_PLACEHOLDERS = {
    "replace-with-a-long-random-private-seed",
    "paste_your_generated_secret_here",
}


def _load_agent_seed(environ: Mapping[str, str] = os.environ) -> str | None:
    """Read a usable stable seed without treating template text as a credential.

    uAgents hashes any string seed; it does not require a mnemonic format. A
    placeholder still creates a valid but predictable identity, so reject the
    examples shipped in this repository.
    """
    value = environ.get("LIFELINE_SEED", "").strip()
    if not value or value in _SEED_PLACEHOLDERS:
        return None
    return value


@dataclass(frozen=True)
class Settings:
    # Agentverse registration requires this identity to remain stable.
    seed: str | None = _load_agent_seed()
    db_path: str = os.getenv("LIFELINE_DB_PATH", "lifeline.db")
    agent_name: str = os.getenv("LIFELINE_AGENT_NAME", "LifeLine Emergency Assistance")
    agent_port: int = int(os.getenv("LIFELINE_AGENT_PORT", "8000"))
    # A random process-local token keeps the local demo usable without shipping
    # a known credential. Set PROVIDER_API_TOKEN for repeatable provider calls.
    provider_token: str = os.getenv("PROVIDER_API_TOKEN") or secrets.token_urlsafe(32)
    provider_host: str = os.getenv("PROVIDER_API_HOST", "127.0.0.1")
    provider_port: int = int(os.getenv("PROVIDER_API_PORT", "8001"))
    booking_timeout_minutes: int = int(os.getenv("BOOKING_TIMEOUT_MINUTES", "30"))


settings = Settings()
Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
