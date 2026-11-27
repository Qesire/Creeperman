"""Resumable exact-host/year metadata collection from a locally reconciled frame."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import urlencode

from .cdx import Collector, ENDPOINT, FIELDS, annual_params
from .core import ALL, bit, canonical, jsonl, timestamp_year, url_host
from .locking import collector_lock


class Unfinished(Exception):
    """A reason the index scope could not be completed."""


def read_frame(path):
    rows, seen = [], set()
    for line, row in jsonl(path):
        h, year = row["hostname"], row["year"]
        annual_params(h, year)
        for key in ("baseline_mask", "local_qualified_mask"):
            mask = row[key]
            if type(mask) is not int or not 0 <= mask <= ALL or mask & bit(year):
                raise ValueError(f"line {line}: invalid mask or already accepted hostname-year")
        if not isinstance(row.get("source_locator"), str) or not row["source_locator"].strip():
            raise ValueError(f"line {line}: supply the independently observed exact-host record location")
        if (h, year) in seen:
            raise ValueError(f"line {line}: duplicate hostname-year")
        seen.add((h, year))
        rows.append(row)
    if not rows:
        raise ValueError("empty annual validation frame")
    return rows


def page_count(body):
    value = json.loads(body)
    if type(value) is not int or value < 0:
        raise ValueError("expected a non-negative CDX page count")
    return value


def read_page(body, hostname, year, expect_empty=False):
    data = json.loads(body)
    if data == []:
        return 0, None
    if not isinstance(data, list) or not data or data[0] != FIELDS:
        raise ValueError("unexpected CDX field names")
    if expect_empty and len(data) > 1:
        raise ValueError("zero page count inconsistent with returned rows")
    first = None
    for ordinal, values in enumerate(data[1:], 1):
        if not isinstance(values, list) or len(values) != len(FIELDS) or not all(isinstance(v, str) for v in values):
            raise ValueError("malformed CDX row")
        row = dict(zip(FIELDS, values))
        if (url_host(row["original"]) != hostname or timestamp_year(row["timestamp"]) != year
                or row["statuscode"] != "200" or row["mimetype"] != "text/html"):
            raise ValueError("capture outside exact-host/year/status/MIME scope")
        if first is None:
            first = {**row, "row_ordinal": ordinal}
    return len(data) - 1, first


class Requests:
    """SQLite holds query URLs, raw responses and durable pre-request reservations."""

    def __init__(self, db, collector, frame_id, budget, retry_failed):
        self.db, self.collector = db, collector
        self.frame_id, self.budget, self.retry_failed = frame_id, budget, retry_failed
        self.sent = 0
        db.execute("""CREATE TABLE IF NOT EXISTS annual_attempt (
            id INTEGER PRIMARY KEY, frame TEXT NOT NULL, url TEXT NOT NULL, started TEXT NOT NULL,
            requests INTEGER, meta TEXT, body BLOB, sha256 TEXT)""")
        db.execute("CREATE INDEX IF NOT EXISTS annual_lookup ON annual_attempt(frame,url,id)")
        self.used = db.execute("SELECT COALESCE(SUM(COALESCE(requests,1)),0) FROM annual_attempt WHERE frame=?",
                               (frame_id,)).fetchone()[0]

    @staticmethod
    def decode(meta, body, parser):
        if meta.get("truncated"):
            raise Unfinished("truncated_response")
        if meta["state"] != "received" or meta.get("http_status") != 200 or body is None:
            raise Unfinished(meta["state"] + (f"_{meta['http_status']}" if "http_status" in meta else ""))
        try:
            return parser(body)
        except (ValueError, TypeError, RecursionError) as exc:
            raise Unfinished(f"invalid_response: {exc}") from exc

    def get(self, params, parser, ids):
        url = ENDPOINT + "?" + urlencode(params, doseq=True)
        previous = self.db.execute("""SELECT id,requests,meta,body,sha256 FROM annual_attempt
            WHERE frame=? AND url=? ORDER BY id DESC LIMIT 1""", (self.frame_id, url)).fetchone()
        if previous:
            index, requests, metadata, body, digest = previous
            if metadata is None:
                ids.append(index)
                if not self.retry_failed:
                    raise Unfinished("ambiguous_previous_attempt")
                # The old reservation still consumes a request. An explicit
                # retry takes a new slot after the budget check below.
            else:
                if body is not None and hashlib.sha256(body).hexdigest() != digest:
                    raise ValueError("cached CDX body fingerprint mismatch")
                try:
                    value = self.decode(json.loads(metadata), body, parser)
                except Unfinished:
                    if requests and not self.retry_failed:
                        ids.append(index)
                        raise
                else:
                    ids.append(index)
                    return value
        if self.used >= self.budget:
            raise Unfinished("request_budget_exhausted")
        with self.db:
            index = self.db.execute("INSERT INTO annual_attempt(frame,url,started) VALUES(?,?,?)",
                                    (self.frame_id, url, datetime.now(timezone.utc).isoformat())).lastrowid
        ids.append(index)
        meta, body = self.collector.request(params)
        digest = hashlib.sha256(body).hexdigest() if body is not None else None
        with self.db:
            self.db.execute("UPDATE annual_attempt SET requests=?,meta=?,body=?,sha256=? WHERE id=?",
                            (meta["requests"], json.dumps(meta), body, digest, index))
        self.used += meta["requests"]
        self.sent += meta["requests"]
        return self.decode(meta, body, parser)


def collect_year(requests, row, result):
    hostname, year = row["hostname"], row["year"]
    params = annual_params(hostname, year)
    ids = result["request_ids"]
    count_params = {k: v for k, v in params.items() if k not in ("fl", "output")}
    pages = requests.get({**count_params, "showNumPages": "true"}, page_count, ids)
    result["reported_pages"] = pages
    for page in range(max(1, pages)):
        # Double-check scalar zero using the unpaged, uncapped exact-host filter.
        query = {**params, "page": page} if pages else {k: v for k, v in params.items() if k != "pageSize"}
        count, witness = requests.get(query, lambda b: read_page(b, hostname, year, expect_empty=not pages), ids)
        result["completed_pages"] += 1
        result["rows_seen"] += count
        if witness and "first_witness" not in result:
            result["first_witness"] = {**witness, "request_id": ids[-1]}
    result["query_scope_complete"] = True
    result["state"] = "potential_witness" if result["rows_seen"] else "completed_no_filtered_match"


def run(input_path, state, max_requests, interval, agent, allow_online, retry_failed=False):
    if type(max_requests) is not int or max_requests < 1:
        raise ValueError("a positive cumulative physical request budget is required")
    rows = read_frame(input_path)
    frame_data = canonical(["annual-exact-v1", rows])
    frame_id = hashlib.sha256(frame_data).hexdigest()
    report = {"frame_sha256": frame_id, "targets": len(rows), "budget": max_requests,
              "requests_this_run": 0, "complete_targets": 0, "qualification": "not_evaluated"}
    if not allow_online:
        return {**report, "state": "preflight_only"}
    results, stop = [], None
    with collector_lock(state):
        collector = Collector(state, interval, agent)
        with closing(sqlite3.connect(state)) as db:
            with db:
                db.execute("CREATE TABLE IF NOT EXISTS annual_frame(id TEXT PRIMARY KEY, frame_json BLOB NOT NULL)")
                db.execute("INSERT OR IGNORE INTO annual_frame VALUES(?,?)", (frame_id, frame_data))
            requests = Requests(db, collector, frame_id, max_requests, retry_failed)
            for row in rows:
                result = {"hostname": row["hostname"], "year": row["year"], "source_locator": row["source_locator"],
                          "state": "not_started", "query_scope_complete": False, "completed_pages": 0,
                          "rows_seen": 0, "request_ids": []}
                results.append(result)
                if stop:
                    continue
                try:
                    collect_year(requests, row, result)
                except Unfinished as exc:
                    stop = str(exc)
                    result.update(state="index_unfinished", reason=stop)
    return {**report, "state": "incomplete" if stop else "complete", "stop_reason": stop,
            "requests_this_run": requests.sent, "lifetime_requests_including_ambiguous": requests.used,
            "response_ledger": str(state), "response_table": "annual_attempt",
            "complete_targets": sum(r["query_scope_complete"] for r in results), "results": results}
