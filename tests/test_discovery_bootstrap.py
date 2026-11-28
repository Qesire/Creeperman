"""Research-backed seed admission; these fixtures make no network requests."""
import copy
import json
from pathlib import Path

import pytest

from creeperman.discovery_bootstrap import initialize, completed, validate
from creeperman.source_frontier import Frontier


def manifest():
    return {"schema": "discovery-bootstrap-v1", "seeds": [{
        "id": "disc-1997", "origin_family": "publisher-disc", "next_step": "inspect original URL map",
        "citations": ["https://publisher.example.org/discs/1997"],
        "date_claims": [{"value": "1997", "meaning": "edition label, not page capture",
                         "source": "https://publisher.example.org/discs/1997"}],
        "page_scopes": [{"host": "publisher.example.org", "paths": ["/discs/1997"],
                         "seeds": ["https://publisher.example.org/discs/1997"]}],
        "catalog_tasks": [],
        "artifacts": [{"url": "https://publisher.example.org/discs/disc97.iso",
                       "observed_on": "https://publisher.example.org/discs/1997",
                       "version": "1997", "operator": "url-map-v1", "coverage_scope": "whole-edition"}]
    }], "completed_operations": []}


def test_unknown_inventory_stays_unknown_and_initialization_is_idempotent(tmp_path):
    f = Frontier(tmp_path / "f.sqlite")
    try:
        a = initialize(f, manifest())
        b = initialize(f, manifest())
        assert a == b
        assert a["inventory_bound"] is False and a["verified_new_eed"] is None
        assert a["operation_states"] == {"needs_inventory_match": 1}
        assert f.db.execute("SELECT count(*) FROM page_tasks").fetchone()[0] == 1
        f.export(tmp_path / "export")
        row = json.loads((tmp_path / "export" / "precheck.jsonl").read_text().splitlines()[0])
        assert row["reason"] == "inventory_unbound"
        original = json.loads(f.db.execute("SELECT body FROM resources").fetchone()[0])
        assert original["historical_year_verified"] is False
        assert original["date_claims"][0]["meaning"] == "edition label, not page capture"
    finally:
        f.close()


def test_only_exact_bytes_operation_and_scope_close_work(tmp_path):
    cfg = manifest()
    art = cfg["seeds"][0]["artifacts"][0]
    art["declared_sha256"] = "a" * 64
    receipt = {"artifact_sha256": "a" * 64, "operator": "url-map-v1",
               "coverage_scope": "whole-edition", "audit": "published-receipt.json"}
    cfg["completed_operations"] = [receipt]
    assert completed(art, [receipt])
    assert not completed({**art, "coverage_scope": "unrecovered-tail"}, [receipt])
    assert not completed({**art, "operator": "extract-resource-domains-v2"}, [receipt])
    assert not completed({**art, "declared_sha256": "b" * 64}, [receipt])
    f = Frontier(tmp_path / "f.sqlite")
    try:
        r = initialize(f, cfg)
        assert r["operation_states"] == {"closed_exact_operation": 1}
        assert f.db.execute("SELECT count(*) FROM page_tasks").fetchone()[0] == 0
        assert f.db.execute("SELECT count(*) FROM resources").fetchone()[0] == 0
    finally:
        f.close()


def test_real_manifest_is_narrow_and_does_not_restart_exhausted_sources(tmp_path):
    root = Path(__file__).resolve().parents[1]
    cfg = json.loads((root / "config/discovery_bootstrap.json").read_text())
    f = Frontier(tmp_path / "f.sqlite")
    try:
        result = initialize(f, cfg)
        assert result["seed_count"] == 4
        assert result["operation_states"] == {"needs_inventory_match": 7}
        assert f.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 3
        assert f.db.execute("SELECT count(*) FROM page_tasks").fetchone()[0] == 4
        assert all(s["action"] == "detail" for x in cfg["seeds"] for s in x.get("catalog_tasks", []))
        assert not any("dmoz" in r[0] or "webbase" in r[0] for r in f.db.execute("SELECT spec FROM tasks"))
        assert all(json.loads(r[0])["historical_year_verified"] is False
                   for r in f.db.execute("SELECT body FROM resources"))
        editions = dict(f.db.execute("SELECT url,year FROM discovery_nodes WHERE kind='artifact' AND family='iucr-nexus'"))
        assert editions['https://www.iucr.org/__data/iucr/nexus/nexus_oct2001.iso'] == 2001
        assert editions['https://www.iucr.org/__data/iucr/nexus/nexus_jul2000.iso'] == 2000
        # Citation-only parents are retained but never inserted into the crawl
        # queue unless an actual reviewed page scope admitted that exact URL.
        assert f.db.execute("SELECT count(*) FROM page_tasks WHERE url LIKE 'https://archive.org/%'").fetchone()[0] == 0
    finally:
        f.close()


def test_missing_citation_or_broad_search_is_rejected():
    cfg = manifest()
    cfg["seeds"][0]["citations"] = []
    with pytest.raises(ValueError, match="citations"):
        validate(cfg)
    cfg = manifest()
    cfg["seeds"][0]["catalog_tasks"] = [{"provider": "ia", "action": "search", "key": "1997 web"}]
    with pytest.raises(ValueError, match="observed records"):
        validate(cfg)
