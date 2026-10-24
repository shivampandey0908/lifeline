from database import Database, db


def find_mechanics(location: str, problem: str, database: Database = db):
    return database.find_providers(location, "roadside", problem)


def dispatch(location: str, problem: str, provider_id: str, idempotency_key: str, database: Database = db):
    return database.create_request(location, "roadside", problem, provider_id, idempotency_key)
