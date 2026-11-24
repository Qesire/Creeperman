"""Idempotent import of immutable batch manifests into a local result catalog.

Potential witnesses are NOT adjudicated evidence. This catalog records
attempts separately and can export the unique candidate/witness inventory.
"""
from __future__ import annotations
import json
import sqlite3
import tempfile
from pathlib import Path
from .core import ALL, RULE, bit, canonical, host, jsonl, timestamp_year, url_host
from .jobs import RESULT_SCHEMA, job_id, validate_job

SCHEMA = """
CREATE TABLE IF NOT EXISTS manifests(
  hash TEXT PRIMARY KEY, job_id TEXT NOT NULL, operation TEXT NOT NULL,
  authority TEXT, manifest TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS results(
  manifest_hash TEXT, ordinal INTEGER, record TEXT NOT NULL,
  PRIMARY KEY(manifest_hash,ordinal)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS witnesses(
  authority TEXT, hostname TEXT, year INTEGER, timestamp TEXT, original TEXT,
  provider TEXT, digest TEXT, manifest_hash TEXT, ordinal INTEGER,
  PRIMARY KEY(authority,hostname,timestamp,original,provider,digest)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS discovered(
  hostname TEXT PRIMARY KEY
) WITHOUT ROWID;
"""


def ingest(store, db_path: Path, refs):
    db_path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(db_path)
    try:
        db.executescript(SCHEMA)
        for ref in refs:
            if db.execute("SELECT 1 FROM manifests WHERE hash=?",(ref["sha256"],)).fetchone():
                continue
            m=store.get_json(ref)
            if m["schema"]!=RESULT_SCHEMA or m["policy"]!=RULE:
                raise ValueError("incompatible result manifest")
            job=store.get_json(m["job_ref"])
            if job_id(job)!=m["job_id"] or job.get("authority")!=m["authority"] or job["operation"]!=m["operation"]:
                raise ValueError("result/job binding mismatch")
            validate_job(job,"ia" if m["operation"]=="verify" else "compute")
            with tempfile.TemporaryDirectory() as t:
                p=Path(t)
                inp=store.materialize(job["input"],p/"input")
                targets={}
                if m["operation"]=="verify":
                    from .cdx import query_params
                    for n,row in jsonl(inp):
                        query_params(row)
                        if n in targets or len(targets)>=job["max_requests"]:
                            raise ValueError("invalid target inventory")
                        targets[n]=row
                output=store.materialize(m["result"],p/"results")
                seen=set()
                with db:
                    db.execute("INSERT OR IGNORE INTO manifests VALUES(?,?,?,?,?)",
                               (ref["sha256"],m["job_id"],m["operation"],m["authority"],canonical(m).decode()))
                    for n,r in jsonl(output):
                        db.execute("INSERT INTO results VALUES(?,?,?)",(ref["sha256"],n,canonical(r).decode()))
                        if m["operation"]=="discover":
                            if r["state"]=="candidate":
                                h=host(r["hostname"])
                                if h!=r["hostname"] or (r.get("original_url") and url_host(r["original_url"])!=h):
                                    raise ValueError("invalid discovered identity")
                                db.execute("INSERT OR IGNORE INTO discovered VALUES(?)",(h,))
                            continue
                        ordinal=r["record_line"]
                        target=targets[ordinal]
                        if ordinal in seen or r["hostname"]!=target["hostname"] or r["target_mask"]!=target["target_mask"]:
                            raise ValueError("result target mismatch")
                        seen.add(ordinal)
                        if r.get("response_ref"):
                            # Raw responses remain in content store; readers
                            # verify their SHA/size upon materialization.
                            store.check_ref(r["response_ref"])
                        for w in r["potential_witnesses"]:
                            y=timestamp_year(w["timestamp"])
                            h=url_host(w["original"])
                            if (h!=target["hostname"] or not bit(y)&target["target_mask"]
                                or str(w["statuscode"])!="200" or w["mimetype"]!="text/html"
                                or r["provider"]!="ia-cdx" or not r.get("response_ref")):
                                raise ValueError("witness not supported by target")
                            db.execute("INSERT OR IGNORE INTO witnesses VALUES(?,?,?,?,?,?,?,?,?)",
                                (m["authority"],h,y,w["timestamp"],w["original"],r["provider"],
                                 str(w.get("digest") or ""),ref["sha256"],n))
                    if m["operation"]=="verify" and seen!=set(targets):
                        raise ValueError("verification batch missing target outcomes")
        return summary(db)
    finally:
        db.close()


def summary(db):
    return {
        "imported_manifests":db.execute("SELECT count(*) FROM manifests").fetchone()[0],
        "unique_discovery_hosts":db.execute("SELECT count(*) FROM discovered").fetchone()[0],
        "result_records_including_attempts":db.execute("SELECT count(*) FROM results").fetchone()[0],
        "potential_witness_records":db.execute("SELECT count(*) FROM witnesses").fetchone()[0],
        "potential_host_years_by_authority":dict(db.execute(
            "SELECT authority,count(*) FROM (SELECT DISTINCT authority,hostname,year FROM witnesses) GROUP BY authority")),
        "qualified_new_eed":None,
    }
