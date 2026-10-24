from database import Database, db


def find_blood_centres(location: str, blood_group: str, database: Database = db):
    # The public portal offers a human-facing stock search but no verified public API
    # is configured here. Never present seeded samples as actual inventory.
    return database.find_providers(location, "blood")


def format_blood_centres(centres, blood_group: str) -> str:
    if not centres:
        return "I couldn't find a listed centre for that location. Please contact a nearby hospital directly."
    lines = [f"Blood centre contacts near your requested area for {blood_group}:"]
    for c in centres:
        tag = "SIMULATED DIRECTORY RECORD" if c.is_demo else "directory listing"
        lines.append(f"• {c.name} — {c.service_area}; {c.contact} ({tag}). Stock: not available from a verified live source; call the centre to confirm.")
    lines.append("For an emergency, contact the treating hospital or emergency services directly. No unit or donor is confirmed; availability is not confirmed by this lookup.")
    return "\n".join(lines)
