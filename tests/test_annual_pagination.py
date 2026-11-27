"""Annual CDX tests use synthetic responses, including through the normal CLI."""
import json
import sqlite3

import pytest

from creeperman.cdx import Collector, FIELDS, query_params
from creeperman.cli import main
from creeperman.core import bit, canonical


OK = {"state": "received", "http_status": 200, "requests": 1, "truncated": False}
TARGET = {"hostname": "history.example.org", "year": 1997, "baseline_mask": 1, "local_qualified_mask": 0,
          "source_locator": "dated-catalog-v1#row=42"}
CAPTURE = ["19970620012345", "http://history.example.org/entry", "200", "text/html", "test-digest", "512"]


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    frame, state = tmp_path / "frame.jsonl", tmp_path / "ia.sqlite"
    frame.write_bytes(canonical(TARGET))
    responses, queries = [], []

    def fetch(self, params):
        queries.append(params)
        return responses.pop(0)

    monkeypatch.setattr(Collector, "request", fetch)

    def cli(cap, *flags):
        main(["annual-cdx", "--input", str(frame), "--state", str(state), "--max-requests", str(cap), *flags])
        return json.loads(capsys.readouterr().out)

    return cli, responses, queries, frame, state


def page(*records):
    return OK, canonical([FIELDS, *records])


def test_pages_budget_and_resume(run):
    cli, responses, queries, _, state = run
    assert cli(3)["state"] == "preflight_only" and not state.exists()
    responses.extend([(OK, b"2"), page(*[CAPTURE] * 53), page(CAPTURE)])
    first = cli(2, "--allow-online")
    assert first["stop_reason"] == "request_budget_exhausted" and first["complete_targets"] == 0
    partial = first["results"][0]
    assert partial["rows_seen"] == 53 and not partial["query_scope_complete"]
    assert cli(2, "--allow-online")["requests_this_run"] == 0
    complete = cli(3, "--allow-online")
    result = complete["results"][0]
    assert complete["requests_this_run"] == 1 and complete["lifetime_requests_including_ambiguous"] == 3
    assert result["query_scope_complete"] and result["rows_seen"] == 54 and result["request_ids"] == [1, 2, 3]
    assert result["first_witness"]["row_ordinal"] == 1 and result["first_witness"]["request_id"] == 2
    assert result["state"] == "potential_witness" and complete["qualification"] == "not_evaluated"
    assert [q.get("page") for q in queries] == [None, 0, 1]
    assert all(q["matchType"] == "host" and q["from"].startswith("1997") and q["to"].startswith("1997")
               and "limit" not in q for q in queries)
    assert queries[0]["showNumPages"] == "true" and "output" not in queries[0] and "fl" not in queries[0]
    assert cli(3, "--allow-online")["requests_this_run"] == 0 and not responses
    with sqlite3.connect(state) as db:
        assert db.execute("SELECT body FROM annual_attempt WHERE id=2").fetchone()[0] == page(*[CAPTURE] * 53)[1]
        saved_frame = db.execute("SELECT frame_json FROM annual_frame WHERE id=?", (complete["frame_sha256"],)).fetchone()[0]
        assert json.loads(saved_frame)[1] == [TARGET]
    assert query_params({"hostname": TARGET["hostname"], "target_mask": bit(1997)})["limit"] == 50


@pytest.mark.parametrize("meta,body,reason", [
    ({"state": "http_error", "http_status": 503, "requests": 1}, b"down", "http_error_503"),
    ({**OK, "truncated": True}, b"[]", "truncated_response"),
    (OK, b"{", "invalid_response"),
    (OK, page([*CAPTURE[:1], "http://other.example.org/entry", *CAPTURE[2:]])[1], "invalid_response"),
    (OK, page(["19980620012345", *CAPTURE[1:]])[1], "invalid_response"),
])
def test_failed_pages_remain_incomplete(run, meta, body, reason):
    cli, responses, queries, _, _ = run
    responses.extend([(OK, b"1"), (meta, body), page(CAPTURE)])
    failed = cli(3, "--allow-online")
    assert failed["complete_targets"] == 0 and failed["stop_reason"].startswith(reason)
    assert failed["results"][0]["rows_seen"] == 0
    assert cli(3, "--allow-online")["requests_this_run"] == 0
    fixed = cli(3, "--allow-online", "--retry-failed")
    assert fixed["complete_targets"] == 1 and fixed["requests_this_run"] == 1
    assert len(queries) == 3 and not responses


def test_zero_count_confirmation_and_local_validation(run):
    cli, responses, queries, frame, _ = run
    responses.extend([(OK, b"0"), (OK, b"[]")])
    result = cli(2, "--allow-online")["results"][0]
    assert result["state"] == "completed_no_filtered_match" and result["query_scope_complete"]
    assert all(k not in queries[1] for k in ("pageSize", "page", "limit"))
    for edits in ({"baseline_mask": 2}, {"local_qualified_mask": 2}, {"source_locator": ""}, {"year": 2002}):
        frame.write_bytes(canonical({**TARGET, **edits}))
        with pytest.raises(ValueError):
            cli(2, "--allow-online")
    frame.write_bytes(canonical(TARGET) * 2)
    with pytest.raises(ValueError, match="duplicate"):
        cli(2, "--allow-online")
    assert len(queries) == 2


def test_ambiguous_reservation_survives_restart(run, monkeypatch):
    cli, responses, _, _, _ = run

    def crash(*args):
        raise RuntimeError("interrupted")

    with monkeypatch.context() as broken:
        broken.setattr(Collector, "request", crash)
        with pytest.raises(RuntimeError, match="interrupted"):
            cli(2, "--allow-online")
    result = cli(2, "--allow-online")
    assert result["stop_reason"] == "ambiguous_previous_attempt"
    assert result["requests_this_run"] == 0 and result["lifetime_requests_including_ambiguous"] == 1
    assert cli(1, "--allow-online", "--retry-failed")["stop_reason"] == "request_budget_exhausted"
    responses.extend([(OK, b"1"), page(CAPTURE)])
    resumed = cli(3, "--allow-online", "--retry-failed")
    assert resumed["complete_targets"] == 1 and resumed["lifetime_requests_including_ambiguous"] == 3
    assert resumed["results"][0]["request_ids"] == [1, 2, 3] and not responses


def test_provider_cooldown_and_inconsistent_zero(run):
    cli, responses, _, _, _ = run
    responses.extend([({"state": "provider_cooldown", "requests": 0}, None), (OK, b"0"),
                      page(CAPTURE), (OK, b"[]")])
    cooling = cli(3, "--allow-online")
    assert cooling["stop_reason"] == "provider_cooldown" and cooling["lifetime_requests_including_ambiguous"] == 0
    failed = cli(3, "--allow-online")
    assert failed["stop_reason"].startswith("invalid_response: zero page count") and failed["complete_targets"] == 0
    assert cli(3, "--allow-online")["requests_this_run"] == 0
    fixed = cli(3, "--allow-online", "--retry-failed")
    assert fixed["requests_this_run"] == 1 and fixed["results"][0]["state"] == "completed_no_filtered_match"
