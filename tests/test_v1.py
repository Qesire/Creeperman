from pathlib import Path
import importlib.util
import json
from decimal import Decimal

import pytest

from creeperman.core import ALL, bit, host, sha, url_host, jsonl, canonical, write_json, audit_binding
from creeperman.inventory import census
from creeperman.sources import records
from creeperman.store import Store
from creeperman.jobs import discovery_job, verification_jobs
from creeperman.execute import execute
from creeperman.cdx import Collector, FIELDS, interpret, query_params
from creeperman.catalog import ingest

spec=importlib.util.spec_from_file_location("make_fixture",Path(__file__).resolve().parents[1]/"examples/make_fixture.py")
fixture=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.fixture
def data(tmp_path):
    return fixture.make(tmp_path/"sample")


def test_exact_identity():
    assert host(" WWW.Example.COM ")=="www.example.com"
    assert url_host("http://example.com:80/path")=="example.com"
    for invalid in ("www.com","http://example.com/","127.0.0.1","a_b.com","example.com."):
        with pytest.raises(ValueError): host(invalid)


def test_census(data,tmp_path):
    out=tmp_path/"out"
    r=census(*data,out)
    assert r["union"]["unique_hosts"]==8
    assert r["union"]["already_in_candidate_pool"]==2
    assert r["union"]["discovery_hosts_new_to_pool_and_core"]==3
    assert r["union"]["new_to_core_baseline_hosts"]==5
    assert r["union"]["hinted_missing_host_years"]==4
    assert r["union"]["all_missing_host_years_ceiling"]==39
    assert Decimal(r["hinted_missing_eed_ceiling_not_score"])==Decimal("2.5284")
    assert r["qualified_new_eed"] is None
    rows={v["hostname"]:v for _,v in jsonl(out/"opportunities.jsonl")}
    assert "same.org" not in rows
    assert rows["example.com"]["baseline_mask"]==bit(1996)|bit(1998)
    assert rows["example.com"]["hinted_missing_mask"]==bit(1997)
    assert rows["www.example.com"]["hinted_missing_mask"]==0
    assert rows["new.com"]["hinted_missing_mask"]==bit(1998)|bit(1999)
    assert rows["late.uk"]["hint_mask"]==0
    assert (out/"core_new_candidates.txt").read_text().splitlines()==["a.new.com","late.uk","unknown.uk"]
    assert len(list(jsonl(out/"rejected.jsonl")))==1
    again=tmp_path/"again"
    r2=census(*data,again)
    assert r2==r
    assert (out/"report.json").read_bytes()==(again/"report.json").read_bytes()


def test_local_qualified(data,tmp_path):
    base,audit,model,sources=data
    q=tmp_path/"sample"/"qualified.jsonl"
    q.write_bytes(canonical({"hostname":"new.com","year":1998,
        "validation_status":"verified_web_year","evidence_id":"synthetic-witness"}))
    cfg=json.loads(sources.read_text())
    cfg["local_qualified"]={"path":q.name,"sha256":sha(q),
        "authority":audit_binding(audit,model)[0]["id"],"rule_version":"synthetic"}
    write_json(sources,cfg)
    r=census(*data,tmp_path/"out")
    assert r["union"]["hinted_missing_host_years"]==3
    assert r["union"]["all_missing_host_years_ceiling"]==38
    assert r["union"]["already_local_qualified_host_years"]==1


def test_hash_mismatch_is_not_published(data,tmp_path):
    (data[0]/"2001.txt").write_text("different.org\n")
    out=tmp_path/"out"
    with pytest.raises(ValueError): census(*data,out)
    assert not out.exists()


def test_cdxj_original_not_surt(tmp_path):
    p=tmp_path/"raw.cdxj"
    p.write_text('com,example)/ 19990101000000 {"url":"http://www.example.com/"}\n'
                 'com,example)/ 19991301000000 {"url":"http://example.com/"}\n')
    rs=list(records(p,"cdxj"))
    assert rs[0][1]["hostname"]=="www.example.com"
    assert rs[0][1]["observed_year"]==1999
    assert rs[1][1] is None


def test_discovery_and_catalog(data,tmp_path):
    store=Store(str(tmp_path/"objects"))
    inp=data[3].parent/"source-a.jsonl"
    job=discovery_job(store,inp,source_id="a",origin_family="synthetic",fmt="observations")
    ref=execute(store,job,"compute")
    assert ref==execute(store,job,"compute")
    m=store.get_json(ref)
    assert m["stats"]=={"records":8,"rejected":1,"candidates":7}
    r=ingest(store,tmp_path/"catalog.sqlite",[ref,ref])
    assert r["imported_manifests"]==1
    assert r["unique_discovery_hosts"]==6
    assert r["qualified_new_eed"] is None


def test_plan_and_cdx(data,tmp_path):
    out=tmp_path/"out"
    census(*data,out)
    store=Store(str(tmp_path/"objects"))
    jobs=list(verification_jobs(store,out,limit=3,batch_size=2))
    assert len(jobs)==2
    job=store.get_json(jobs[0]["job_ref"])
    inp=store.materialize(job["input"],tmp_path/"targets")
    rows=[x for _,x in jsonl(inp)]
    assert [r["hostname"] for r in rows]==["a.new.com","example.com"]
    assert rows[1]["target_mask"]==bit(1997)
    row=rows[1]
    params=query_params(row)
    assert params["matchType"]=="exact"
    assert "collapse" not in params
    raw=json.dumps([FIELDS,
        ["19970101000000","http://www.example.com/","200","text/html","abc","99"],
        ["19970102000000","http://example.com/history","200","text/html","abc","99"],
        ["19980102000000","http://example.com/history","200","text/html","abc","99"]]).encode()
    meta={"state":"received","requests":1,"http_status":200,"truncated":False}
    r=interpret(row,raw,meta)
    assert r["witness_mask"]==bit(1997)
    assert len(r["potential_witnesses"])==1
    assert r["qualification"]=="not_evaluated"
    assert r["query_scope_complete"] is False
    assert interpret(row,b"[]",meta)["state"]=="unresolved_no_match"


def test_checkpoint_and_verify_import(data,tmp_path,monkeypatch):
    out=tmp_path/"out"
    census(*data,out)
    store=Store(str(tmp_path/"objects"))
    envelope=next(verification_jobs(store,out,limit=1,batch_size=1))
    collector=Collector(tmp_path/"collector.sqlite",2.5,"SyntheticTest/1")
    calls=[]
    def fake(params):
        calls.append(params)
        raw=json.dumps([FIELDS,["19980101000000","http://a.new.com/","200","text/html","abc","99"]]).encode()
        return {"state":"received","requests":1,"http_status":200,"truncated":False},raw
    monkeypatch.setattr(collector,"request",fake)
    a=execute(store,envelope,"ia",collector)
    b=execute(store,envelope,"ia",collector)
    assert len(calls)==1
    r=ingest(store,tmp_path/"catalog.sqlite",[a,b,a])
    assert r["imported_manifests"]==2
    assert r["potential_witness_records"]==1
    assert list(r["potential_host_years_by_authority"].values())==[1]
    assert r["qualified_new_eed"] is None


def test_store_rejects_corruption(tmp_path):
    store=Store(str(tmp_path/"store"))
    p=tmp_path/"x"
    p.write_text("hello")
    ref=store.put(p)
    (store.path/store.key(ref)).write_text("hullo")
    with pytest.raises(ValueError): store.materialize(ref,tmp_path/"out")
    assert not (tmp_path/"out").exists()
