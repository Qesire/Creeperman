"""Turn researched, edition-specific originals into the existing source frontier.

This command does not fetch data or declare historical website evidence. It
preserves the seed's citation and date claims, queues only observed catalogue
pages/records, and exposes original file descriptors to the local precheck.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import canonical
from .discovery_policy import year_hint
from .locking import collector_lock
from .source_frontier import Frontier, digest, resource, safe_url, spec
from .source_pages import PageFrontier, validate_scope
from .source_precheck import checksum, claims

SCHEMA = "discovery-bootstrap-v1"
DDL = """
CREATE TABLE IF NOT EXISTS bootstrap_seeds(
 id TEXT PRIMARY KEY, manifest_sha TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bootstrap_operations(
 id TEXT PRIMARY KEY, seed_id TEXT NOT NULL, artifact_url TEXT NOT NULL,
 operator TEXT NOT NULL, coverage_scope TEXT NOT NULL, state TEXT NOT NULL,
 body TEXT NOT NULL);
"""


def validate(cfg):
    if cfg.get("schema") != SCHEMA or not isinstance(cfg.get("seeds"), list):
        raise ValueError("invalid bootstrap manifest")
    ids = set()
    for seed in cfg["seeds"]:
        if not seed.get("id") or seed["id"] in ids or not seed.get("origin_family"):
            raise ValueError("unique seed ID and origin family required")
        ids.add(seed["id"])
        if not seed.get("citations") or not all(safe_url(u) for u in seed["citations"]):
            raise ValueError("seed requires observed public citations")
        if not seed.get("date_claims") or not seed.get("artifacts"):
            raise ValueError("date claims and exact original objects required")
        for claim in seed["date_claims"]:
            if not all(claim.get(k) for k in ("value", "meaning", "source")) or not safe_url(claim["source"]):
                raise ValueError("date claims require meaning and source")
        for scope in seed.get("page_scopes", []):
            validate_scope({**scope, "family": seed["origin_family"]})
        for task in seed.get("catalog_tasks", []):
            if task.get("action") != "detail":
                raise ValueError("bootstrap uses observed records, not broad searches")
            spec(task["provider"], task["action"], task["key"])
            if not safe_url(task.get("observed_on")):
                raise ValueError("catalogue record requires observed parent")
        for artifact in seed["artifacts"]:
            if not all(artifact.get(k) for k in ("url", "observed_on", "operator", "coverage_scope", "version")):
                raise ValueError("artifact identity, edition, operation and coverage required")
            if not safe_url(artifact["url"]) or not safe_url(artifact["observed_on"]):
                raise ValueError("invalid artifact or observation URL")
            claims(artifact)
    for receipt in cfg.get("completed_operations", []):
        checksum(receipt["artifact_sha256"], "sha256")
        if not all(receipt.get(k) for k in ("operator", "coverage_scope", "audit")):
            raise ValueError("completed operation requires exact scope and audit")


def completed(artifact, receipts):
    """A family/URL/date match never closes work; match bytes AND operation."""
    sha = artifact.get("declared_sha256")
    return bool(sha) and any(
        r["artifact_sha256"] == sha and r["operator"] == artifact["operator"]
        and r["coverage_scope"] == artifact["coverage_scope"]
        for r in receipts
    )


def initialize(frontier, cfg):
    validate(cfg)
    db = frontier.db
    db.executescript(DDL)
    pages = PageFrontier(frontier)
    manifest_sha = digest(cfg)
    receipts = cfg.get("completed_operations", [])
    with db:
        for seed in cfg["seeds"]:
            family = seed["origin_family"]
            # Keep the complete citation and conflicting date assertions. The
            # derived file descriptor is deliberately not a historical verdict.
            db.execute("INSERT OR REPLACE INTO bootstrap_seeds VALUES(?,?,?)",
                       (seed["id"], manifest_sha, canonical(seed).decode()))
            active = [a for a in seed["artifacts"] if not completed(a, receipts)]
            if active:
                pages.init({"schema": "source-page-scopes-v1", "scopes": [
                    {**s, "family": family} for s in seed.get("page_scopes", [])]})
                for task in seed.get("catalog_tasks", []):
                    frontier.enqueue(spec(task["provider"], task["action"], task["key"]),
                                     family, 0, seed.get("priority", 20),
                                     "observed:" + task["observed_on"], "researched seed citation")
            for ordinal, artifact in enumerate(seed["artifacts"]):
                oid = digest([artifact["url"], artifact.get("declared_sha256"),
                              artifact["version"], artifact["operator"], artifact["coverage_scope"]])
                state = "closed_exact_operation" if completed(artifact, receipts) else "needs_inventory_match"
                db.execute("""INSERT INTO bootstrap_operations VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET body=excluded.body,
                    state=CASE WHEN excluded.state='closed_exact_operation' THEN excluded.state
                               ELSE bootstrap_operations.state END""",
                    (oid, seed["id"], artifact["url"], artifact["operator"],
                     artifact["coverage_scope"], state, canonical(artifact).decode()))
                if state == "closed_exact_operation":
                    continue
                record = resource("file_descriptor", artifact["url"], url=artifact["url"],
                    title=seed["id"] + " " + artifact["version"],
                    description=artifact.get("next_step", seed["next_step"]),
                    origin_family=family, version=artifact["version"],
                    date_claims=seed["date_claims"], citations=seed["citations"],
                    coverage_status="needs_inventory_match", operation_id=oid,
                    **{k: artifact[k] for k in ("size", "declared_sha256", "declared_sha1", "declared_md5") if k in artifact})
                # Page/catalogue nodes are registered by their normal enqueue
                # paths. This edge is the actually observed file relationship.
                policy = getattr(frontier, "policy", None)
                source_node = "page:" + artifact["observed_on"]
                if policy is not None:
                    policy.register(source_node, kind="page", family=family,
                                    url=artifact["observed_on"],
                                    context="research citation; not a fetched page",
                                    state="researched_reference")
                    rid = digest(["researched_original", "file_descriptor", artifact["url"]])
                    policy.register("artifact:" + rid, kind="artifact", family=family,
                                    url=artifact["url"], context=record["description"],
                                    year=year_hint(artifact["version"]),
                                    operator=artifact["operator"],
                                    parent=source_node, state=state)
                frontier.observe(source_node, "researched_original", record, ordinal)
                if policy is not None:
                    # Correct an earlier generic year hint from a family-wide
                    # date assertion; this is still only an edition hint.
                    db.execute("UPDATE discovery_nodes SET year=? WHERE id=?",
                               (year_hint(artifact["version"]), "artifact:" + rid))
                db.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?)",
                           ("seed:" + seed["id"], source_node, "cited original listing"))
    return status(frontier)


def status(frontier):
    db = frontier.db
    db.executescript(DDL)
    bound = bool(db.execute("SELECT 1 FROM settings WHERE key='inventory_root'").fetchone())
    return {"schema": SCHEMA,
            "seed_count": db.execute("SELECT count(*) FROM bootstrap_seeds").fetchone()[0],
            "operation_states": dict(db.execute("SELECT state,count(*) FROM bootstrap_operations GROUP BY state")),
            "inventory_bound": bound,
            "historical_qualification": "not_evaluated",
            "verified_new_eed": None,
            "network_requests": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    frontier = Frontier(args.db)
    try:
        with collector_lock(args.db):
            result = initialize(frontier, json.loads(args.manifest.read_text(encoding="utf-8")))
        print(canonical(result).decode(), end="")
    finally:
        frontier.close()


if __name__ == "__main__":
    main()
