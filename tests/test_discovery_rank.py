"""Equivalent ranking features with a bounded number of database round trips."""
import json

from creeperman.core import canonical
from creeperman.discovery_policy import DEFAULT
from creeperman.discovery_rank import batch_features
from creeperman.source_frontier import Frontier, spec


def candidates(f, count=30):
    for i in range(count):
        task = spec("ia", "search", f"synthetic 1999 mapping shared term{i}")
        f.enqueue(task, "fixture-" + str(i % 3), 0, i % 5, "synthetic", "synthetic anchor")
    rows = f.db.execute("SELECT * FROM tasks ORDER BY created").fetchall()
    return [(row, f.policy._register_row("catalog", row)) for row in rows]


def test_batch_features_match_reference_including_shared_ancestry(tmp_path):
    f = Frontier(tmp_path / "f.sqlite", policy=DEFAULT)
    try:
        pairs = candidates(f)
        child = pairs[0][1]
        f.policy.register("document:parent", kind="document", family=child["family"],
                          year=child["year"], operator=child["operator"], context="mapping")
        # These are synthetic database statistics, not admitted production
        # settlements. One batch reaches two ancestors in the same source arm.
        for bid, prior, eed, requests in [("one", 0, "1.7", 5), ("two", 0, "0", 2), ("old", 1, "999", 1)]:
            f.db.execute("""INSERT INTO discovery_batches
                (id,node_id,prior,receipt_sha,requests,bytes,wall_millis,net_eed,qualified_count,new_count)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (bid, child["id"], prior, "fixture", requests, 200, 1, eed, 1, 1))
            f.db.execute("INSERT INTO discovery_training VALUES(?,?,?,?,?)",
                         (bid, child["id"], 1, 1.0, "[]"))
        f.db.execute("INSERT INTO discovery_training VALUES(?,?,?,?,?)",
                     ("one", "document:parent", 1, 0.5, "[]"))
        f.db.executemany("INSERT INTO discovery_terms VALUES(?,?,?)",
                         [("mapping", 3, 1), ("shared", 0, 2), ("term7", 10, 0)])
        expected = [f.policy._features(n, r) for r, n in pairs]
        actual = [v for _, _, v in batch_features(f.policy, pairs)]
        assert actual == expected
        assert actual[0]["arm_yield"] == 1.7 / 7
        assert actual[0]["arm_attempts"] == 2
        # Every call sees newly arrived training; no stale score cache.
        f.db.execute("UPDATE discovery_terms SET pos=50 WHERE term='mapping'")
        changed = [v for _, _, v in batch_features(f.policy, pairs)]
        assert changed[0]["path_score"] > actual[0]["path_score"]
    finally:
        f.close()


def test_batch_lookups_replace_per_candidate_queries(tmp_path):
    f = Frontier(tmp_path / "f.sqlite", policy=DEFAULT)
    try:
        pairs = candidates(f, 120)
        before = []
        f.db.set_trace_callback(before.append)
        expected = [f.policy._features(n, r) for r, n in pairs]
        f.db.set_trace_callback(None)
        after = []
        f.db.set_trace_callback(after.append)
        actual = [v for _, _, v in batch_features(f.policy, pairs)]
        f.db.set_trace_callback(None)
        assert actual == expected
        assert len(after) == 2  # One source aggregate; one bounded token batch.
        assert len(before) > 120 * 5
        assert batch_features(f.policy, []) == []
    finally:
        f.close()


def test_observation_adapter_preserves_media_identity(tmp_path):
    from creeperman.sources import records

    row = {"original_url": "http://www.example.org/project/", "observed_year": None,
           "kind": "source_page_hint", "extraction_version": "media-map-v1",
           "media_provenance": {"member_path": "SITE/INDEX.HTM", "member_sha256": "a" * 64,
                                "container": {"partial": True},
                                "date_claims": [{"value": "1997", "meaning": "edition"}]}}
    p = tmp_path / "observations.jsonl"
    p.write_bytes(canonical(row))
    _, parsed, error = next(records(p, "observations"))
    assert error is None and parsed["observed_year"] is None
    assert parsed["hostname"] == "www.example.org"
    assert parsed["media_provenance"] == row["media_provenance"]
    assert parsed["extraction_version"] == row["extraction_version"]
