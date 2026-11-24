"""v0.2 integration and semantics; network calls are replaced by fixed responses."""
import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal
import pytest
from creeperman.core import bit, canonical, jsonl, sha, audit_binding
from creeperman.sources import records
from creeperman.extract import html_clues, unwrap
from creeperman.store import Store
from creeperman.online import ArchiveCollector, request_spec, lookup_result, replay_result, metadata_result
from creeperman.online_plans import publish, followup_rows, routed_jobs, route
from creeperman.execute import execute
from creeperman.catalog import ingest,export_observations,review_export
from creeperman.inventory import census
from creeperman.semantic import signatures
from creeperman.settle import settle

spec=importlib.util.spec_from_file_location("make_fixture",Path(__file__).resolve().parents[1]/"examples/make_fixture.py")
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
META={"state":"received","requests":1,"http_status":200,"truncated":False}

def test_reference_roles_and_base():
    html='<base href="http://cdn.example.com/docs/"><a href="../project">Project Alpha</a><img src="http://assets.example.org/p.gif"><a href="/web/19990101000000/http://actual.example.org/">literal path</a>'
    a=list(html_clues(html,"http://www.example.com/old/",1999,"r1"))
    assert a[0]["original_url"]=="http://cdn.example.com/project"
    assert a[0]["anchor_text"]=="Project Alpha"
    assert a[1]["hostname"]=="assets.example.org"
    assert a[1]["reference_role"]=="embedded_or_form"
    assert a[2]["hostname"]=="cdn.example.com"
    b=list(html_clues('<a href="/web/19990101000000/http://target.example.com/x">X</a>',
        "http://www.example.com/",1999,"r2",replay_provider="ia",
        replay_url="https://web.archive.org/web/19990101000000/http://www.example.com/"))
    assert b[0]["hostname"]=="target.example.com"
    assert b[0]["rewrite"]["replay_timestamp"]=="19990101000000"

def test_mbox_and_deja(tmp_path):
    p=tmp_path/"mail.zip"
    with zipfile.ZipFile(p,"w") as z:
        z.writestr("comp.test.mbox","From 123\nDate: Sat, 1 Jan 2000 12:00:00 +0000\nFrom: A <a@sample.net>\nMessage-ID: <m@sample.net>\n\nFrom ordinary body text\nhttp://site.example.com/p.\nwww.other.example.org\nFrom -456\nDate: Sat, 1 Jan 2000 12:00:00\n\nhttp://unknown.example.org\n")
    a=[r for _,r,e in records(p,"usenet-zip") if r]
    assert {r["hostname"] for r in a}=={"sample.net","site.example.com","www.other.example.org","unknown.example.org"}
    assert next(r for r in a if r["hostname"]=="sample.net")["original_url"] is None
    assert next(r for r in a if r["hostname"]=="unknown.example.org")["observed_year"] is None

def test_webkb_jisc_dmoz(tmp_path):
    p=tmp_path/"webkb.tar.gz"
    with tarfile.open(p,"w:gz") as t:
        b=b'Content-Type: text/html\r\n\r\n<a href="http://outside.example.org/">project</a>'
        info=tarfile.TarInfo("project/misc/http:^^lab.example.com^index.html");info.size=len(b)
        t.addfile(info,io.BytesIO(b))
    a=[r for _,r,e in records(p,"webkb-tar") if r]
    assert {r["hostname"] for r in a}=={"lab.example.com","outside.example.org"}
    assert all(r["observed_year"]==1997 for r in a)
    j=tmp_path/"jisc.tsv";j.write_text("1999|source.example.uk|target.example.com\t2\n")
    a=[r for _,r,e in records(j,"jisc") if r]
    assert [r["kind"] for r in a]==["jisc_source_hint","jisc_target_hint"]
    d=tmp_path/"rdf.xml";d.write_text('<RDF xmlns:r="urn:r"><ExternalPage r:about="http://dmoz.example.com/"/></RDF>')
    a=[r for _,r,e in records(d,"dmoz-rdf") if r]
    assert a[0]["observed_year"] is None

def test_arquivo_and_wrong_replay():
    row={"hostname":"www.example.pt","target_mask":bit(1999),"original_url":"http://www.example.pt/"}
    u,p=request_spec("arquivo","lookup",row)
    assert u=="https://arquivo.pt/wayback/cdx" and p["matchType"]=="exact"
    assert "collapse" not in p and p["filter"]==["status:200","mime:text/html"]
    body=b"\n".join(canonical(r).strip() for r in [
        {"timestamp":"19990101000000","url":"http://example.pt/","status":"200","mime":"text/html"},
        {"timestamp":"19990101000000","url":"http://www.example.pt/","status":"200","mime":"text/html"},
        {"timestamp":"20000101000000","url":"http://www.example.pt/","status":"200","mime":"text/html"}])
    r=lookup_result("arquivo",row,body,META)
    assert len(r["potential_witnesses"])==1 and r["witness_mask"]==bit(1999)
    cap={"hostname":"www.example.pt","original":"http://www.example.pt/","timestamp":"19990101000000"}
    meta={**META,"headers":{"memento-datetime":"Sat, 01 Jan 2000 00:00:00 GMT",
                "link":'<http://www.example.pt/>; rel="original"',"content-type":"text/html"}}
    assert replay_result("arquivo",cap,b"html",meta)["state"]=="replay_identity_unresolved"

def test_online_chain(tmp_path,monkeypatch):
    base,audit,model,sources=fixture.make(tmp_path/"fixture")
    authority=audit_binding(audit,model)[0]["id"]
    store=Store(str(tmp_path/"store"))
    db=tmp_path/"catalog.sqlite"
    coll=ArchiveCollector(tmp_path/"ia.sqlite",2.5,"Fixture/1","ia")
    from creeperman.cdx import FIELDS
    target={"hostname":"new.com","target_mask":bit(1999)|bit(2000),"original_url":"http://new.com/"}
    cap=["19990101000000","http://new.com/","200","text/html","-","123"]
    def fake(url,params):
        if "/cdx/" in url:
            return META,json.dumps([FIELDS,cap]).encode()
        if "/metadata/" in url:
            return META,json.dumps({"metadata":{"identifier":"sample-item","collection":["foo"]},
                "files":[{"name":"old.warc.gz","size":"5"},{"name":"other.cdx.gz"}]}).encode()
        assert "/web/" in url
        return {**META,"requested_url":url,"headers":{"memento-datetime":"Fri, 01 Jan 1999 00:00:00 GMT",
            "link":'<http://new.com/>; rel="original"',"content-type":"text/html",
            "x-archive-src":"sample-item/old.warc.gz"}},b'<title>Project Alpha</title><a href="http://new-target.net/">Alpha research</a>'
    monkeypatch.setattr(coll,"fetch",fake)
    j=publish(store,"ia","lookup",[target],authority,"r1")
    a=execute(store,j,"ia",coll);b=execute(store,j,"ia",coll)
    assert store.get_json(b)["stats"]["reused_checkpoint_records"]==1
    s=ingest(store,db,[a,b,a]);assert s["potential_witness_records"]==1
    more=list(followup_rows(db,authority,"expand-host","ia",5))
    assert len(more)==1 and more[0]["target_mask"]==bit(2000)
    rows=list(followup_rows(db,authority,"replay","ia",5))
    assert len(rows)==1 and rows[0]["timestamp"]=="19990101000000"
    j=publish(store,"ia","replay",rows,authority,"r2")
    ingest(store,db,[execute(store,j,"ia",coll)])
    assert not list(followup_rows(db,authority,"replay","ia",5))
    md=list(followup_rows(db,authority,"metadata","ia",5))
    assert md==[{"item":"sample-item","files":["old.warc.gz"]}]
    ingest(store,db,[execute(store,publish(store,"ia","metadata",md,authority,"r3"),"ia",coll)])
    assert not list(followup_rows(db,authority,"metadata","ia",5))
    obs=tmp_path/"observations.jsonl";export_observations(store,db,obs)
    assert any(r["hostname"]=="new-target.net" for _,r in jsonl(obs))
    review=tmp_path/"review.jsonl";review_export(db,review,authority)
    rr=[r for _,r in jsonl(review)]
    assert len(rr)==1 and rr[0]["validation_status"]=="pending_review"
    decisions=tmp_path/"decisions.jsonl"
    reviewed={**rr[0],"evidence_type":"archive_replay","reviewer":"synthetic-reviewer",
              "reason":"fixture response only","rule_version":"fixture-rule",
              "evidence_id":"fixture-evidence","validation_status":"verified_web_year"}
    decisions.write_bytes(canonical(reviewed)+canonical(reviewed))
    out=tmp_path/"settled"
    report=settle(base,audit,model,decisions,out,rule_version="fixture-rule",db_path=db,store=store)
    assert report["new_by_year"]["1999"]==1
    assert Decimal(report["local_reviewed_new_eed"])==Decimal("0.6321")

def test_search_signature_and_route(tmp_path,monkeypatch):
    assert route("x.pt")[0]=="arquivo" and route("x.edu")==["ia","arquivo"]
    store=Store(str(tmp_path/"store"))
    coll=ArchiveCollector(tmp_path/"arquivo.sqlite",2.5,"Fixture/1","arquivo")
    p=tmp_path/"anchors.jsonl"
    p.write_bytes(canonical({"hostname":"x.pt","original_url":"http://x.pt/",
        "observed_year":1999,"source_original_url":"http://y.pt/","anchor_text":"Alpha particle laboratory"}))
    sig=tmp_path/"query.jsonl";signatures(p,sig,1,3)
    rows=[r for _,r in jsonl(sig)]
    assert len(rows)==1
    def fake(url,params):
        assert url.endswith("/textsearch")
        return META,json.dumps({"response_items":[{"originalURL":"http://new.pt/","tstamp":"19990101000000","title":"Alpha"},
            {"originalURL":"http://late.pt/","tstamp":"20090101000000"}]}).encode()
    monkeypatch.setattr(coll,"fetch",fake)
    j=publish(store,"arquivo","search",rows,"fixture-authority","r")
    db=tmp_path/"db.sqlite";ingest(store,db,[execute(store,j,"arquivo",coll)])
    out=tmp_path/"obs";export_observations(store,db,out)
    assert [r["hostname"] for _,r in jsonl(out)]==["new.pt"]
