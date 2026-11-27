"""Offline archive replay through the planner, worker and evidence catalog."""
import base64
import hashlib
import json
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from runpy import run_path
from unittest.mock import Mock

import pytest

from creeperman.catalog import ingest, review_export
from creeperman.cdx import FIELDS
from creeperman.cli import main
from creeperman.core import audit_binding, bit, canonical, jsonl
from creeperman.execute import execute
from creeperman.online import ArchiveCollector
from creeperman.online_plans import publish
from creeperman.payloads import replay_body
from creeperman.settle import settle
from creeperman.store import Store


BODY = b'<base href="assets/"><a href="doc.html">Doc</a><img src="/icon.gif">'
DIGEST = base64.b32encode(hashlib.sha1(BODY).digest()).decode()


def capture(name, year, path):
    return {"hostname":name, "original":f"http://{name}/{path}", "timestamp":f"{year}0101000000", "digest":DIGEST}


def response(row):
    stamp = datetime.strptime(row["timestamp"], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    return {"state":"received", "requests":1, "http_status":200, "truncated":False, "headers":{
        "memento-datetime":format_datetime(stamp, usegmt=True), "link":f'<{row["original"]}>; rel="original"',
        "content-type":"text/html; charset=UTF-8", "x-archive-orig-status":"200 OK"}}


def test_followup_cache_hit_then_direct_after_restart(tmp_path, monkeypatch, capsys):
    store = Store(str(tmp_path / "objects"))
    catalog = tmp_path / "catalog.sqlite"
    state = tmp_path / "ia.sqlite"
    fixture = run_path(str(Path(__file__).resolve().parents[1] / "examples/make_fixture.py"))
    baseline, audit, model, _ = fixture["make"](tmp_path / "fixture")
    authority = audit_binding(audit, model)[0]["id"]
    original = capture("a.example.com", 1999, "old/index.html")
    second = capture("b.example.com", 2001, "dept/portal.html")
    calls = []

    def fetch(self, url, params):
        calls.append(url)
        if "/cdx/" in url:
            row = second
            cdx = [row["timestamp"], row["original"], "200", "text/html", DIGEST, str(len(BODY))]
            return response(row), json.dumps([FIELDS, cdx]).encode()
        row = next(row for row in (original, second) if url.endswith(row["original"]))
        return response(row), BODY

    monkeypatch.setattr(ArchiveCollector, "fetch", fetch)

    def run(job):
        # Open a new collector for every worker run, including checkpoint recovery.
        return execute(store, job, "ia", ArchiveCollector(state, 3, "OfflineFixture", "ia"))

    def followup(reuse):
        options = ["--reuse-payloads"] if reuse else []
        main(["followup", "--db", str(catalog), "--store", store.root, "--provider", "ia",
              "--mode", "replay", "--authority", authority, "--round-id", "next", "--limit", "5", *options])
        return [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    first_ref = run(publish(store, "ia", "replay", [original], authority, "warm"))
    ingest(store, catalog, [first_ref])
    lookup = {"hostname":second["hostname"], "target_mask":bit(2001), "original_url":second["original"]}
    ingest(store, catalog, [run(publish(store, "ia", "lookup", [lookup], authority, "cdx"))])
    job, = followup(True)
    cached_ref = run(job)
    cached_manifest = store.get_json(cached_ref)
    assert cached_manifest["stats"]["requests"] == 0
    assert cached_manifest["qualified_new_eed"] is None
    cached = store.get_json(cached_manifest["result"])
    assert cached["state"] == "cached_payload_discovery"
    assert cached["payload_original"] == original["original"]
    assert cached["payload_timestamp"] == original["timestamp"]
    assert cached["qualification"] == "not_evaluated"
    assert {"response_ref", "actual_timestamp", "http_status", "body_sha256"}.isdisjoint(cached)
    for ref, row, directory in ((first_ref, original, "old"), (cached_ref, second, "dept")):
        result = store.get_json(store.get_json(ref)["result"])
        file = store.materialize(result["references_ref"], tmp_path / directory)
        clues = [item for _, item in jsonl(file)]
        assert [clue["original_url"] for clue in clues] == [
            f'http://{row["hostname"]}/{directory}/assets/doc.html', f'http://{row["hostname"]}/icon.gif']
        assert all(clue["source_original_url"] == row["original"] for clue in clues)
    replayed_manifest = store.get_json(run(job))
    assert replayed_manifest["result"] == cached_manifest["result"]
    assert replayed_manifest["stats"]["reused_checkpoint_records"] == 1
    assert len(calls) == 2
    assert ingest(store, catalog, [cached_ref, cached_ref])["qualified_new_eed"] is None
    review = tmp_path / "review.jsonl"
    review_export(catalog, review, authority)
    assert [r["hostname"] for _, r in jsonl(review)] == [original["hostname"]]
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_bytes(canonical({
        "hostname":second["hostname"], "year":2001, "evidence_type":"archive_replay",
        "validation_status":"verified_web_year", "authority":authority, "rule_version":"fixture",
        "reviewer":"fixture", "reason":"cache-only replay", "evidence_id":"cached",
        "manifest_hash":cached_ref["sha256"], "ordinal":1,
    }))
    with pytest.raises(ValueError, match="does not bind host/year"):
        settle(baseline, audit, model, decisions, tmp_path / "settled", rule_version="fixture",
               db_path=catalog, store=store)
    assert followup(True) == []
    direct, = followup(False)
    assert direct["job_id"] != job["job_id"]
    result_ref = run(direct)
    direct_result = store.get_json(store.get_json(result_ref)["result"])
    assert len(calls) == 3 and calls[-1].endswith(second["original"])
    assert direct_result["state"] == "replay_review" and direct_result["requests"] == 1
    assert direct_result["actual_timestamp"] == second["timestamp"]
    assert direct_result["response_ref"] == cached["cached_payload_ref"]
    ingest(store, catalog, [result_ref])
    assert followup(False) == [] and followup(True) == []


@pytest.mark.parametrize("invalid", [
    "429", "original-404", "digest", "mime", "original-mime", "encoded", "wrong-path", "truncated",
])
def test_only_verified_responses_populate_cache(tmp_path, monkeypatch, invalid):
    store = Store(str(tmp_path / "objects"))
    collector = ArchiveCollector(tmp_path / "ia.sqlite", 3, "OfflineFixture", "ia")
    first = capture("a.example.com", 1999, "index.html")
    second = capture("b.example.com", 2000, "other.html")
    calls = []

    def fetch(url, params):
        calls.append(url)
        meta = response(first if len(calls) == 1 else second)
        body = BODY
        if len(calls) == 1:
            if invalid == "429":
                meta.update(state="rate_limited", http_status=429)
            elif invalid == "original-404":
                meta["headers"]["x-archive-orig-status"] = "404 Not Found"
            elif invalid == "digest":
                body += b"changed"
            elif invalid == "mime":
                meta["headers"]["content-type"] = "text/plain"
            elif invalid == "original-mime":
                meta["headers"]["x-archive-orig-content-type"] = "application/pdf"
            elif invalid == "encoded":
                meta["headers"]["content-encoding"] = "gzip"
            elif invalid == "wrong-path":
                meta["headers"]["link"] = '<http://a.example.com/another>; rel="original"'
            elif invalid == "truncated":
                meta["truncated"] = True
        return meta, body

    monkeypatch.setattr(collector, "fetch", fetch)
    for row in (first, {**second, "reuse_payload":True}):
        job = publish(store, "ia", "replay", [row], "test-baseline", "check")
        manifest = store.get_json(execute(store, job, "ia", collector))
        assert manifest["stats"]["requests"] == 1
    assert len(calls) == 2


@pytest.mark.parametrize("code,status", [
    ("NoSuchKey", 404), ("404", 404), ("NotFound", 404),
    ("AccessDenied", 403), ("NoSuchBucket", 404), ("corrupt", 200),
])
def test_missing_s3_cached_payload_falls_back_to_direct_replay(tmp_path, monkeypatch, code, status):
    store = Store(str(tmp_path / "objects"))
    state = tmp_path / "ia.sqlite"
    collector = ArchiveCollector(state, 3, "OfflineFixture", "ia")
    first = capture("a.example.com", 1999, "index.html")
    second = {**capture("b.example.com", 2001, "page.html"), "reuse_payload": True}
    cached = {"sha256": hashlib.sha256(BODY).hexdigest(), "bytes": len(BODY)}
    replay_body(state, store, "ia", DIGEST, verified={
        "ref": cached, "original": first["original"], "timestamp": first["timestamp"]})
    job = publish(store, "ia", "replay", [second], "test-baseline", "check")

    # Keep job artifacts local; only the cached body is materialized from simulated S3.
    s3_store = Store(str(tmp_path / "cache"))
    s3_store.bucket = "fixture"
    s3_store.s3 = Mock()
    class ClientError(Exception):
        pass
    s3_store.s3.exceptions.ClientError = ClientError
    if code == "corrupt":
        stream = Mock()
        stream.iter_chunks.return_value = [b"x" * len(BODY)]
        s3_store.s3.get_object.return_value = {"Body": stream, "ContentLength": len(BODY)}
    else:
        error = ClientError(code)
        error.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
        s3_store.s3.get_object.side_effect = error
    local_read = store.materialize
    def read(ref, dst):
        return s3_store.materialize(ref, dst) if ref == cached else local_read(ref, dst)
    monkeypatch.setattr(store, "materialize", read)
    fetch = Mock(return_value=(response(second), BODY))
    monkeypatch.setattr(collector, "fetch", fetch)

    if code in {"AccessDenied", "NoSuchBucket", "corrupt"}:
        with pytest.raises(ValueError if code == "corrupt" else ClientError):
            execute(store, job, "ia", collector)
        fetch.assert_not_called()
    else:
        manifest = store.get_json(execute(store, job, "ia", collector))
        result = store.get_json(manifest["result"])
        assert result["state"] == "replay_review" and result["requests"] == 1
        assert result["actual_original"] == second["original"]
        fetch.assert_called_once()
    s3_store.s3.get_object.assert_called_once_with(Bucket="fixture", Key=store.key(cached))
