import importlib.util
from pathlib import Path

import pytest

from creeperman.core import audit_binding, canonical, sha
from creeperman.parquet_difference import compare

pytest.importorskip("duckdb")
pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq


def test_frozen_baseline_and_selected_ledger(tmp_path):
    spec = importlib.util.spec_from_file_location("sample", Path(__file__).resolve().parents[1] / "examples/make_fixture.py")
    sample = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sample)
    baseline, audit, model, _ = sample.make(tmp_path / "sample")
    authority, _ = audit_binding(audit, model)
    # The same hostname has different membership across years. Duplicated records in
    # either input and snapshot-local settlement flags must not change the answer.
    source = tmp_path / "observations.parquet"
    pq.write_table(pa.table({"source_year":[1996,1997,1997,1997], "hostname":["example.com","example.com","example.com","new.com"],
                             "locally_settled":[False,True,True,True]}), source)
    baseline_part = baseline / "baseline-1997.parquet"
    pq.write_table(pa.table({"hostname":["same.org"], "year":[1997]}), baseline_part)
    baseline_part.with_suffix(".json").write_bytes(canonical({
        "source_sha256":authority["annual_sha256"]["1997"], "sha256":sha(baseline_part)}))
    ledger = tmp_path / "reviewed.jsonl"
    ledger.write_bytes(b"")
    # Repeated shards with the same label form one source.
    def run():
        return compare([("fixture",source),("fixture",source)],baseline,ledger,model,audit)
    old = run()
    assert [(r["exact_hosts"],r["baseline_hits"],r["unsettled_eed_ceiling"]) for r in old["rows"]] == [
        (1,1,"0.0000"),(2,0,"1.2642")]
    decision = {"authority":authority["id"],"hostname":"new.com","year":1997,"validation_status":"verified_web_year"}
    ledger.write_bytes(canonical(decision) * 2)
    new = run()
    assert new["rows"][1] == {"source":"fixture","year":1997,"exact_hosts":2,"baseline_hits":0,"outside_baseline":2,
                             "already_reviewed_outside":1,"unsettled_candidates":1,"unsettled_eed_ceiling":"0.6321"}
    assert new["qualified_new_eed"] is None and new["reviewed_sha256"] != old["reviewed_sha256"]
    ledger.write_bytes(canonical({**decision,"authority":"wrong"}))
    with pytest.raises(ValueError, match="authority"):
        run()
