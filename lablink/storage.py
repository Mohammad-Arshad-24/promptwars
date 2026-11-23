"""Atomic read-modify-write per workspace, including the approval feasibility check."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from .cloud import client_options

class SQLiteStore:
    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS spaces (id TEXT PRIMARY KEY, body TEXT NOT NULL)")

    def transact(self, key, action, seed):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            entry = db.execute("SELECT body FROM spaces WHERE id=?", (key,)).fetchone()
            state = json.loads(entry[0]) if entry else seed()
            result = action(state)
            encoded = json.dumps(state, separators=(",", ":"))
            if not entry or encoded != entry[0]:
                db.execute("INSERT OR REPLACE INTO spaces VALUES (?,?)", (key, encoded))
            return result

class FirestoreStore:
    def __init__(self):
        from google.cloud import firestore
        self.fs = firestore
        self.db = firestore.Client(**client_options())

    def transact(self, key, action, seed):
        ref = self.db.collection("lablink_spaces").document(key)

        @self.fs.transactional
        def update(tx):
            snap = ref.get(transaction=tx)
            data = snap.to_dict() if snap.exists else {}
            state = json.loads(data["body"]) if snap.exists else seed()
            result = action(state)
            encoded = json.dumps(state, separators=(",", ":"))
            if data.get("body") != encoded:
                document = {"body": encoded}
                if key.startswith("demo-"):
                    document["expiresAt"] = datetime.now(timezone.utc) + timedelta(days=2)
                tx.set(ref, document)
            return result

        return update(self.db.transaction())

