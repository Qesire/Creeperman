"""Verified replay bodies for link discovery. Capture identity stays with each index row."""
import json
import re
import sqlite3


def replay_body(state, store, provider, digest, *, verified=None):
    if not isinstance(digest, str) or not re.fullmatch(r"[A-Z2-7]{32}", digest):
        return None
    namespace = store.root if store.s3 is not None else str(store.path)
    key = (provider, namespace, digest)
    with sqlite3.connect(state) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS verified_html(
            provider TEXT, store TEXT, digest TEXT, sha256 TEXT, record TEXT NOT NULL,
            PRIMARY KEY(provider,store,digest,sha256)) WITHOUT ROWID""")
        if verified is not None:
            db.execute("INSERT OR IGNORE INTO verified_html VALUES(?,?,?,?,?)",
                       (*key, verified["ref"]["sha256"], json.dumps(verified)))
            return None
        found = db.execute("SELECT record FROM verified_html WHERE provider=? AND store=? AND digest=? LIMIT 2", key).fetchall()
    return json.loads(found[0][0]) if len(found) == 1 else None
