"""Audited live-feedback behavior using synthetic data, never a network probe."""
import importlib.util
import json
from contextlib import closing
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from creeperman.core import audit_binding, canonical, sha
from creeperman.discovery_policy import DEFAULT, validate_policy
from creeperman.settle import settle
from creeperman.source_frontier import Frontier, resource, spec
from creeperman.source_pages import PageFrontier


_spec = importlib.util.spec_from_file_location(
    "policy_fixture", Path(__file__).resolve().parents[1] / "examples/make_fixture.py")
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)
BASE = "https://library.example.org/catalog/"
COST = {"requests": 2, "bytes": 1200, "wall_millis": 100}


@pytest.fixture
def authority(tmp_path):
    base, audit, model, _ = fixture.make(tmp_path / "fixture")
    return base, audit, model


def reviewed(tmp_path, authority, label, keys):
    """Use the real settle implementation, including source-byte verification."""
    base, audit, model = authority
    root = tmp_path / label
    root.mkdir()
    raw = root / "original.txt"
    raw.write_text("SYNTHETIC reviewed historical directory fixture " + label)
    ledger = root / "decisions.jsonl"
    ledger.write_bytes(b"".join(canonical({
        "hostname": h, "year": year, "authority": audit_binding(audit, model)[0]["id"],
        "rule_version": "fixture-rule-v1", "validation_status": "verified_web_year",
        "reviewer": "synthetic-reviewer", "reason": "fixture only, not competition evidence",
        "evidence_id": label + ":" + h + ":" + str(year),
        "evidence_type": "historical_directory", "record_locator": "line:1",
        "date_semantics": "explicit synthetic issue year", "source_sha256": sha(raw),
        "source_path": raw.name,
    }) for h, year in keys))
    out = root / "settled"
    settle(base, audit, model, ledger, out, rule_version="fixture-rule-v1")
    return out


def bind_prior(f, tmp_path, authority, keys=()):
    return f.policy.import_settlement(reviewed(tmp_path, authority, "prior", keys),
                                     authority[2], prior=True)


def artifact(f, label, parent=None):
    return f.policy.register("artifact:" + label, kind="artifact", family="fixture-corpus",
                             url=BASE + label + ".iso", year=1999,
                             operator="fixture-directory-v1", parent=parent, state="unreviewed")


def import_complete(f, directory, model, node_id, scope_id):
    return f.policy.import_settlement(directory, model, node_id=node_id, complete=True,
                                     scope_id=scope_id, cost=COST)


def init_pages(f, seeds):
    p = PageFrontier(f)
    p.init({"schema": "source-page-scopes-v1", "scopes": [{
        "host": "library.example.org", "paths": ["/catalog"], "family": "fixture-corpus",
        "seeds": [BASE + name for name in seeds],
    }]})
    return p


def test_real_catalog_choose_loads_persistent_policy_and_respects_closed_tasks(tmp_path):
    cfg = {**deepcopy(DEFAULT), "order_by": [{"field": "year", "direction": "asc"}]}
    db = tmp_path / "crawl.sqlite"
    with closing(Frontier(db, policy=cfg)) as f, f.db:
        late = f.enqueue(spec("ia", "detail", "fixture-2001"), "corpus", 0, 100, "seed", "citation")
        early = f.enqueue(spec("ia", "detail", "fixture-1996"), "corpus", 0, 1, "seed", "citation")
        assert f.choose(["ia"], 2)["id"] == early
        f.db.execute("UPDATE tasks SET state='parsed' WHERE id=?", (early,))
        # Re-enqueue is not an implicit retry of a consumed operation.
        f.enqueue(spec("ia", "detail", "fixture-1996"), "corpus", 0, 500, "seed", "same citation")
    with closing(Frontier(db)) as f, f.db:
        assert f.policy.enabled and f.choose(["ia"], 2)["id"] == late
        f.db.execute("INSERT INTO cooldown VALUES('ia',253402300799)")
        assert f.choose(["ia"], 2) is None
        assert f.policy.summary()["reviewed_batches"] == 0


def test_successful_descendant_changes_next_live_page_fetch(tmp_path, authority):
    with closing(Frontier(tmp_path / "crawl.sqlite", policy=DEFAULT)) as f:
        pages = init_pages(f, ["seed"])
        raw = (b'<a href="a-other1999">neutral catalog</a><p>' + b"separator " * 70
               + b'</p><a href="training1999">vernacular mirror corpus</a>'
                 b'<a href="z-next1999">vernacular mirror corpus</a>')
        with f.db:
            f.import_document_bytes(raw, "html", BASE + "seed", "fixture-corpus")
        assert pages.reuse_local(max_depth=0)["reused_local_this_run"] == 1
        with f.db:
            f.import_document_bytes(b'<a href="result.iso">historical original</a>', "html",
                                    BASE + "training1999", "fixture-corpus")
        assert pages.reuse_local(max_depth=1)["reused_local_this_run"] == 1
        record = f.db.execute("SELECT id FROM resources WHERE json_extract(body,'$.url')=?",
                              (BASE + "result.iso",)).fetchone()
        assert record is not None
        bind_prior(f, tmp_path, authority)
        delta = reviewed(tmp_path, authority, "positive", [("new.com", 1999)])
        result = import_complete(f, delta, authority[2], "artifact:" + record[0], "result-sha:all:v1")
        assert Decimal(result["net_eed"]) == Decimal("0.6321")
        trained = {r[0] for r in f.db.execute("SELECT node_id FROM discovery_training")}
        assert "page:" + BASE + "training1999" in trained
        assert "page:" + BASE + "seed" in trained
        context = f.db.execute("SELECT context FROM discovery_nodes WHERE id=?",
                               ("page:" + BASE + "z-next1999",)).fetchone()[0]
        assert "vernacular" in context
        with f.db:
            f.db.execute("INSERT INTO robots_cache VALUES('library.example.org',NULL,404,253402300799)")
        called = []
        def fetch(url):
            called.append(url)
            return 200, {"content-type": "text/html"}, b"fixture page"
        report = pages.run(1, 3, 2, 3, "fixture-agent", fetch, lambda _: None)
        assert called == [BASE + "z-next1999"]
        assert report["attempted_this_run"] == 1
        # Fetching another HTML page is not another qualified outcome.
        assert report["discovery_policy"]["reviewed_batches"] == 1
        assert f.db.execute("SELECT mode FROM discovery_choices ORDER BY seq DESC LIMIT 1").fetchone()[0] == "exploit"


def test_unique_eed_subtracts_cumulative_prior_and_preserves_host_year(tmp_path, authority):
    with closing(Frontier(tmp_path / "crawl.sqlite", policy=DEFAULT)) as f:
        first, second = artifact(f, "first"), artifact(f, "second")
        bind_prior(f, tmp_path, authority, [("new.com", 1999)])
        keys = [("new.com", 1999), ("www.new.com", 1999), ("new.com", 2000), ("same.org", 1999)]
        delta = reviewed(tmp_path, authority, "first-batch", keys)
        result = import_complete(f, delta, authority[2], first, "first:all:v1")
        assert result["qualified_count"] == 3  # same.org was already in frozen B.
        assert result["new_count"] == 2
        assert Decimal(result["net_eed"]) == Decimal("1.2642")
        assert import_complete(f, delta, authority[2], first, "first:all:v1")["idempotent"]
        again = import_complete(f, delta, authority[2], second, "second:all:v1")
        assert again["new_count"] == 0 and Decimal(again["net_eed"]) == 0
        assert f.policy.summary()["net_eed"] == "1.2642"
        assert {tuple(r) for r in f.db.execute("SELECT hostname,year FROM discovery_seen")} == {
            ("new.com", 1999), ("new.com", 2000), ("www.new.com", 1999)}
        newer = reviewed(tmp_path, authority, "late-prior", [("late.com", 2000)])
        with pytest.raises(ValueError, match="entire cumulative prior"):
            f.policy.import_settlement(newer, authority[2], prior=True)


def test_full_zero_requires_explicit_completion_and_empty_scopes_are_distinct(tmp_path, authority):
    with closing(Frontier(tmp_path / "crawl.sqlite", policy=DEFAULT)) as f:
        node = artifact(f, "empty")
        empty = reviewed(tmp_path, authority, "empty-batch", [])
        with pytest.raises(ValueError, match="prior settlement"):
            import_complete(f, empty, authority[2], node, "empty:all:v1")
        bind_prior(f, tmp_path, authority)
        with pytest.raises(ValueError, match="completed bounded"):
            f.policy.import_settlement(empty, authority[2], node_id=node, cost=COST)
        assert f.policy.summary()["trained_path_nodes"] == 0
        first = import_complete(f, empty, authority[2], node, "empty:all:v1")
        other = artifact(f, "other-empty")
        second = import_complete(f, empty, authority[2], other, "other-empty:all:v1")
        assert first["batch_id"] != second["batch_id"]
        assert {r[0] for r in f.db.execute("SELECT label FROM discovery_training")} == {0}
        assert f.policy.summary()["reviewed_batches"] == 2


def test_http_failure_and_parsed_catalog_do_not_train_negative_outcomes(tmp_path):
    with closing(Frontier(tmp_path / "crawl.sqlite", policy=DEFAULT)) as f, f.db:
        f.enqueue(spec("ia", "detail", "fixture"), "first", 0, 20, "seed", "observed")
        f.enqueue(spec("datacite", "search", "historic corpus"), "second", 0, 10, "seed", "observed")
        def fetch(url):
            if "archive.org" in url:
                return 429, {"retry-after": "600"}, b"rate limited"
            return 200, {}, b'{"data":[]}'
        report = f.run(providers=["ia", "datacite"], limit=2, interval=3, fetch=fetch, sleeper=lambda _: None)
        assert report["task_states"] == {"http_error": 1, "parsed": 1}
        assert report["discovery_policy"]["reviewed_batches"] == 0
        assert report["discovery_policy"]["trained_path_nodes"] == 0


def test_exploration_uses_source_year_operator_and_local_reuse_is_policy_ranked(tmp_path):
    cfg = {**deepcopy(DEFAULT), "explore_every": 2}
    with closing(Frontier(tmp_path / "crawl.sqlite", policy=cfg)) as f, f.db:
        a = f.enqueue(spec("ia", "detail", "popular-1999"), "popular", 0, 90, "seed", "observed")
        b = f.enqueue(spec("ia", "detail", "unexplored-1999"), "other", 0, 1, "seed", "observed")
        assert f.choose(["ia"], 0)["id"] == a
        assert f.choose(["ia"], 0)["id"] == b
        assert [r[0] for r in f.db.execute("SELECT mode FROM discovery_choices ORDER BY seq")] == ["exploit", "explore"]
    early = {**deepcopy(DEFAULT), "order_by": [{"field": "year", "direction": "asc"}]}
    with closing(Frontier(tmp_path / "local.sqlite", policy=early)) as f:
        pages = init_pages(f, ["issue2001", "issue1996"])
        with f.db:
            for name in ("issue2001", "issue1996"):
                f.import_document_bytes(b"already local", "html", BASE + name, "fixture-corpus")
        result = pages.reuse_local(max_local_pages=1)
        assert result["reused_local_this_run"] == 1 and result["attempted_this_run"] == 0
        assert f.db.execute("SELECT url FROM page_tasks WHERE state='reused_local'").fetchone()[0] == BASE + "issue1996"


def test_tampered_settlement_rejected_before_reward_and_unobservable_policy_rejected(tmp_path, authority):
    with closing(Frontier(tmp_path / "crawl.sqlite", policy=DEFAULT)) as f:
        node = artifact(f, "original")
        bind_prior(f, tmp_path, authority)
        delta = reviewed(tmp_path, authority, "tamper", [("new.com", 1999)])
        (delta / "1999.txt").write_text("invented.com\n")
        with pytest.raises(ValueError, match="hash mismatch"):
            import_complete(f, delta, authority[2], node, "original:all:v1")
        assert f.policy.summary()["reviewed_batches"] == 0
    cfg = {**deepcopy(DEFAULT), "order_by": [{"field": "request_bound", "direction": "asc"}]}
    with pytest.raises(ValueError, match="unobservable"):
        validate_policy(cfg)
