"""Run a deterministic end-to-end demo without network calls."""
import tempfile
from pathlib import Path

from database import Database
from mechanic_service import dispatch, find_mechanics


def run_demo():
    with tempfile.TemporaryDirectory() as tmp:
        database = Database(str(Path(tmp) / "demo.db"))
        database.seed_demo("demo-secret")
        providers = find_mechanics("Yamuna Expressway, Greater Noida", "engine won't start", database)
        print("1. User asks for an engine mechanic near Yamuna Expressway, Greater Noida.")
        print(f"2. Found {len(providers)} matching simulated providers.")
        for i, provider in enumerate(providers, 1):
            print(f"   {i}. {provider.name} | {provider.contact} | SIMULATED")
        chosen = providers[0]
        print(f"3. User selects {chosen.name} and confirms dispatch.")
        request = dispatch("Yamuna Expressway, Greater Noida", "engine won't start", chosen.provider_id, "demo-conversation:demo-message", database)
        print(f"4. Created {request['request_id']} with status {request['status']}.")
        print("5. Provider API receives request; simulated provider explicitly responds ACCEPTED.")
        request = database.respond(request["request_id"], chosen.provider_id, "ACCEPTED", "Demo provider accepted; this is a simulation.", 25)
        print(f"6. Persisted provider response: {request['status']} — {request['provider_response']} ETA={request['eta_minutes']}m (simulated).")


if __name__ == "__main__":
    run_demo()
