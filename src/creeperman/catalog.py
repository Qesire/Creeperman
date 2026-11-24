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
CREATE TABLE IF NOT EXISTS online_attempts(
  manifest_hash TEXT, ordinal INTEGER, authority TEXT NOT NULL, provider TEXT NOT NULL,
  action TEXT NOT NULL, hostname TEXT, timestamp TEXT, original TEXT, item TEXT,
  state TEXT NOT NULL, requests INTEGER NOT NULL,
  PRIMARY KEY(manifest_hash,ordinal)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS attempts_lookup ON online_attempts(authority,provider,action,hostname);
CREATE INDEX IF NOT EXISTS attempts_replay ON online_attempts(authority,provider,action,hostname,timestamp,original);
CREATE INDEX IF NOT EXISTS attempts_item ON online_attempts(authority,action,item);
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
            validate_job(job,job["provider"] if m["operation"]=="online" else
                         "ia" if m["operation"]=="verify" else "compute")
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
                elif m["operation"]=="online":
                    from .online import validate_rows
                    for n,row in jsonl(inp):
                        if n>job["max_requests"]:raise ValueError("oversized online input")
                        targets[n]=row
                    validate_rows(job["provider"],job["action"],list(targets.values()))
                    if len(targets)!=job["max_requests"]:raise ValueError("online input count mismatch")
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
                        if m["operation"]=="online":
                            if ordinal in seen or r["request_input"]!=target or r["provider"]!=job["provider"] or r["action"]!=job["action"]:
                                raise ValueError("online result target mismatch")
                            seen.add(ordinal)
                            for k in ("response_ref","references_ref"):
                                if r.get(k):store.check_ref(r[k])
                            if type(r["requests"]) is not int or not 0<=r["requests"]<=1:
                                raise ValueError("invalid request count")
                            db.execute("INSERT INTO online_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                (ref["sha256"],n,m["authority"],r["provider"],r["action"],
                                 target.get("hostname"),target.get("timestamp"),target.get("original"),
                                 target.get("item"),r["state"],r["requests"]))
                            if r["action"]=="lookup":
                                for w in r["potential_witnesses"]:
                                    y=timestamp_year(w["timestamp"]);h=url_host(w["original"])
                                    if (h!=target["hostname"] or not bit(y)&target["target_mask"] or
                                        str(w["statuscode"])!="200" or w["mimetype"]!="text/html" or not r.get("response_ref")):
                                        raise ValueError("invalid online lookup witness")
                                    db.execute("INSERT OR IGNORE INTO witnesses VALUES(?,?,?,?,?,?,?,?,?)",
                                        (m["authority"],h,y,w["timestamp"],w["original"],r["provider"],
                                         str(w.get("digest") or ""),ref["sha256"],n))
                            elif r["action"]=="search":
                                for o in r.get("observations",[]):
                                    h=url_host(o["original_url"])
                                    if h!=o["hostname"]:raise ValueError("invalid search observation")
                                    db.execute("INSERT OR IGNORE INTO discovered VALUES(?)",(h,))
                            continue
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
                    if m["operation"] in ("verify","online") and seen!=set(targets):
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
        "online_attempt_records":db.execute("SELECT count(*) FROM online_attempts").fetchone()[0],
        "qualified_new_eed":None,
    }


def export_observations(store,db_path:Path,out:Path):
    """Stream original observations and replay-discovered references.
    Output is a new candidate source, not an evidence ledger.
    """
    db=sqlite3.connect(db_path)
    try:
        with out.open("xb") as f,tempfile.TemporaryDirectory() as t:
            for mh,n,raw,op in db.execute("""SELECT r.manifest_hash,r.ordinal,r.record,m.operation
                FROM results r JOIN manifests m ON m.hash=r.manifest_hash
                ORDER BY r.manifest_hash,r.ordinal"""):
                r=json.loads(raw)
                if op=="discover" and r["state"]=="candidate":
                    f.write(canonical({**r,"catalog_manifest":mh,"catalog_ordinal":n}))
                elif op=="online":
                    for o in r.get("observations",[]):
                        f.write(canonical({**o,"catalog_manifest":mh,"catalog_ordinal":n}))
                    if r.get("references_ref"):
                        p=Path(t)/"links.jsonl"
                        store.materialize(r["references_ref"],p)
                        for _,o in jsonl(p):
                            if url_host(o["original_url"])!=o["hostname"]:
                                raise ValueError("invalid reference")
                            f.write(canonical({**o,"catalog_manifest":mh,"catalog_ordinal":n}))
                        p.unlink()
    finally:db.close()


def review_export(db_path:Path,out:Path,authority:str):
    db=sqlite3.connect(db_path)
    try:
        with out.open("xb") as f:
            for mh,n,raw in db.execute("""SELECT r.manifest_hash,r.ordinal,r.record
                FROM results r JOIN manifests m ON m.hash=r.manifest_hash
                WHERE m.authority=? AND m.operation='online'
                AND json_extract(r.record,'$.action')='replay'
                AND json_extract(r.record,'$.state')='replay_review'
                ORDER BY r.manifest_hash,r.ordinal""",(authority,)):
                r=json.loads(raw)
                f.write(canonical({"manifest_hash":mh,"ordinal":n,"authority":authority,
                    "hostname":r["hostname"],"year":r["year"],"original_url":r["actual_original"],
                    "timestamp":r["actual_timestamp"],"provider":r["provider"],
                    "response_ref":r["response_ref"],"title_hint":r.get("title_hint"),
                    "quality_flags":r.get("quality_flags",[]),"archive_digest":r.get("archive_digest"),
                    "source_pointer":r.get("source_pointer"),"validation_status":"pending_review"}))
    finally:db.close()
