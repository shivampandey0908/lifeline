import argparse

from config import settings
from database import db


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the explicitly simulated LifeLine demo records.")
    parser.add_argument("--reset", action="store_true", help="Clear existing demo requests before seeding")
    args = parser.parse_args()
    if args.reset:
        with db.connect() as conn:
            conn.execute("DELETE FROM service_requests")
            conn.execute("DELETE FROM conversations")
    db.seed_demo(settings.provider_token)
    print("Seeded 3 simulated mechanics and 2 simulated blood centre directory records.")
