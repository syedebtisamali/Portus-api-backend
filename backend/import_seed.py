"""
One-time helper to load backend/seed_data.json into PORTUS.USERS.

Usage:
    cd backend
    pip install -r requirements.txt
    python import_seed.py

Reads MONGO_URI from backend/.env automatically. Skips any document whose
USERNAME already exists in the collection, so it's safe to re-run.
"""
import os
import json
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
SEED_FILE = os.path.join(os.path.dirname(__file__), "seed_data.json")

def main():
    client = MongoClient(MONGO_URI)
    db = client["PORTUS"]
    col = db["USERS"]

    with open(SEED_FILE, "r", encoding="utf-8") as f:
        docs = json.load(f)

    inserted, skipped = 0, 0
    for doc in docs:
        username = doc.get("USERNAME")
        if col.find_one({"USERNAME": username}):
            print(f"  skip  {username} (already exists)")
            skipped += 1
            continue
        col.insert_one(doc)
        print(f"  add   {username}")
        inserted += 1

    print(f"\nDone. Inserted {inserted}, skipped {skipped}.")
    print(f"Collection now has {col.count_documents({})} document(s) total.")

if __name__ == "__main__":
    main()
