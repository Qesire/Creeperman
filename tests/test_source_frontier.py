"""Source discovery regression fixtures; no network or competition data."""
import json
from pathlib import Path
from urllib.parse import urlsplit
import pytest

from creeperman.source_frontier import Frontier, SCHEMA, endpoint, spec, parsed, route_url, document_links
from creeperman.source_pages import PageFrontier, in_scope, page_url

def body(d):return json.dumps(d).encode()
def seed(f,*items):
    f.init({"schema":SCHEMA,"seeds":[{"family":family,"provider":p,"action":a,"key":k} for family,p,a,k in items]})
def rows(f,table):
    return [dict(r) for r in f.db.execute("SELECT * FROM "+table)]

def test_catalog_to_files(tmp_path):
    f=Frontier(tmp_path/"source.sqlite")
    seed(f,("directory","ia","search","2001 historical web directory"))
    calls=[]
    def fetch(url):
        calls.append(url)
        if "advancedsearch.php" in url:
            return 200,{},body({"response":{"docs":[{"identifier":"fixture-directory","title":"2001 web directory"}]}})
        assert url=="https://archive.org/metadata/fixture-directory"
        return 200,{},body({"metadata":{"identifier":"fixture-directory","title":"directory mirror","date":"2020"},
          "files":[{"name":"content-2001.rdf.gz","size":"123","source":"original","md5":"abc"}]})
    r=f.run(providers=["ia"],limit=2,interval=3,fetch=fetch,sleeper=lambda _:None)
    assert r["attempted_this_run"]==2
    assert r["task_states"]=={"parsed":2}
    f.export(tmp_path/"export")
    x=[json.loads(l) for l in (tmp_path/"export"/"file_review.jsonl").read_text().splitlines()]
    assert x[0]["url"]=="https://archive.org/download/fixture-directory/content-2001.rdf.gz"
    assert x[0]["year_mentions"]==[2001] and x[0]["historical_year_verified"] is False
    assert r["verified_new_eed"] is None
    seed(f,("directory","ia","search","2001 historical web directory"))
    assert f.run(providers=["ia"],limit=2,interval=3,fetch=fetch,sleeper=lambda _:None)["attempted_this_run"]==0
    assert len(calls)==2
    assert len(rows(f,"bodies"))==2
    f.close()

def test_zenodo_doi_and_record_link_share_seed_task(tmp_path):
    f = Frontier(tmp_path / "source.sqlite")
    seed(f, ("public-projection", "zenodo", "detail", "8408539"))
    links = (b'<a href="https://doi.org/10.5281/zenodo.8408539">DOI</a>'
             b'<a href="https://zenodo.org/records/8408539">dataset</a>')
    with f.db:
        f.import_document_bytes(links, "html", "https://library.example.org/paper", "paper")
    tasks = rows(f, "tasks")
    assert [json.loads(task["spec"]) for task in tasks] == [spec("zenodo", "detail", "8408539")]
    assert len([edge for edge in rows(f, "edges") if edge["child"] == tasks[0]["id"]]) == 3
    f.close()

    for doi in ("10.1234/zenodo.8408539", "10.5281/zenodo.8408539a"):
        assert route_url("https://doi.org/" + doi) == [
            spec("datacite", "detail", doi), spec("crossref", "detail", doi)]


def test_four_provider_contracts():
    t=spec("datacite","detail","10.5281/zenodo.123")
    rs,cs,_=parsed(t,{"data":{"id":"10.5281/zenodo.123","attributes":{"doi":"10.5281/zenodo.123",
       "titles":[{"title":"Early web collection 2000"}],"url":"https://zenodo.org/records/123",
       "types":{"resourceTypeGeneral":"Dataset"},"publicationYear":2024,
       "relatedIdentifiers":[{"relatedIdentifierType":"DOI","relationType":"IsSupplementTo","relatedIdentifier":"10.1000/paper"}]}}})
    assert any(r["metadata_date"]==2024 for r in rs if "metadata_date" in r)
    assert any(t["provider"]=="zenodo" and t["key"]=="123" for t,_,_ in cs)
    assert any(t["key"]=="10.1000/paper" for t,_,_ in cs)
    rs,_,_=parsed(spec("zenodo","detail","123"),{"id":123,"metadata":{"title":"web archive 1998","access_right":"open"},
       "files":[{"key":"urls.csv","links":{"self":"https://zenodo.org/api/files/fixture/urls.csv"},"checksum":"md5:abc","size":100}]})
    assert any(r["kind"]=="file_descriptor" and r["declared_checksum"]=="md5:abc" for r in rs)
    rs,cs,_=parsed(spec("crossref","detail","10.1000/paper"),{"message":{"DOI":"10.1000/paper","title":["web crawl 1999"],
       "reference":[{"DOI":"10.1000/other","article-title":"original crawl list 1999"}]}})
    assert any(r["kind"]=="doi_relation" for r in rs)
    assert len(cs)==2
    assert route_url("https://unrelated.example.net/archive/download")==[]
    assert "query.bibliographic" in endpoint(spec("crossref","search","web crawl"))
    with pytest.raises(ValueError):spec("crossref","detail","10.1234/../../admin")

def test_fanout_provenance_and_admission(tmp_path):
    f=Frontier(tmp_path/"f.db")
    seed(f,("research","crossref","search","web collection 2001"))
    f.run(providers=["crossref"],limit=1,interval=3,max_children=1,fetch=lambda u:
          (200,{},body({"message":{"items":[{"DOI":f"10.1000/{n}","title":[f"web archive 2001 {n}"]} for n in range(3)]}})),
          sleeper=lambda _:None)
    assert len(rows(f,"proposals"))==3 and len(rows(f,"tasks"))==2
    assert f.summary()["unadmitted_proposals"]==2
    ids={r["id"] for r in rows(f,"tasks")}
    p=next(r for r in rows(f,"proposals") if r["child"] not in ids)
    f.admit(p["child"]);assert len(rows(f,"tasks"))==3
    f.close()

def test_failure_state_and_no_retry(tmp_path):
    f=Frontier(tmp_path/"f.db")
    seed(f,("a","ia","search","a"),("b","ia","search","b"),("c","datacite","search","c"))
    seen=[]
    def fetch(u):
        seen.append(u)
        if urlsplit(u).hostname=="archive.org":return 503,{"retry-after":"3600"},b"temporarily unavailable"
        return 200,{},body({"data":[]})
    r=f.run(providers=["ia","datacite"],limit=3,interval=3,fetch=fetch,sleeper=lambda _:None)
    assert len(seen)==2
    assert r["blocked_this_run"]==["ia"]
    assert r["task_states"]=={"http_error":1,"parsed":1,"queued":1}
    assert f.run(providers=["ia"],limit=3,interval=3,fetch=fetch,sleeper=lambda _:None)["attempted_this_run"]==0
    f.close()

def test_document_link_import(tmp_path):
    raw=b'<base href="https://library.example.org/catalog/"><a href="old.rdf.gz">2001 web directory</a><a href="https://archive.org/details/fixture">scan</a><a href="https://else.example.org/">external</a><meta name="citation_doi" content="10.1000/paper">'
    p=tmp_path/"doc.html";p.write_bytes(raw)
    f=Frontier(tmp_path/"f.db")
    with f.db:f.import_document(p,"html","https://library.example.org/current","publisher")
    assert len(rows(f,"documents"))==1
    a=[json.loads(r["body"]) for r in rows(f,"resources")]
    assert any(r["url"]=="https://library.example.org/catalog/old.rdf.gz" and r["kind"]=="file_locator_hint" for r in a)
    assert len(rows(f,"tasks"))==3
    assert all(r["historical_year_verified"] is False for r in a)
    f.close()

def scope():
    return {"schema":"source-page-scopes-v1","scopes":[{"host":"library.example.org","paths":["/catalog"],
          "family":"directory","seeds":["https://library.example.org/catalog"]}]}

def test_scoped_pages_and_robots(tmp_path):
    f=Frontier(tmp_path/"f.db");p=PageFrontier(f);p.init(scope())
    seen=[]
    def fetch(u):
        seen.append(u)
        if u.endswith("/robots.txt"):return 200,{"content-type":"text/plain"},b"User-agent: *\nDisallow: /catalog/private\nCrawl-delay: 4\n"
        if u.endswith("/catalog"):
            return 200,{"content-type":"text/html"},b'<a href="/catalog/issue1999">web directory 1999</a><a href="/catalog/private">secret</a><a href="/catalog/file.rdf.gz">2001 dump</a><a href="/outside">outside</a><a href="https://another.example.org/catalog">other</a><a href="https://archive.org/details/item123">item</a>'
        assert u.endswith("/catalog/issue1999")
        return 200,{"content-type":"text/html"},b'<a href="https://library.example.org/catalog">back</a>'
    r=p.run(10,3,2,10,"FixtureBot/1.0",fetch,sleeper=lambda _:None)
    assert len(seen)==3 and r["attempted_this_run"]==3
    assert r["page_states"]=={"parsed":2,"robots_disallowed":1}
    assert r["request_kinds"]=={"page":2,"robots":1}
    assert any(r["spec"].find("item123")>=0 for r in rows(f,"tasks"))
    a=[json.loads(r["body"]) for r in rows(f,"resources")]
    assert any(r["url"].endswith("file.rdf.gz") and r["kind"]=="file_locator_hint" for r in a)
    assert p.run(5,3,2,10,"FixtureBot/1.0",fetch,sleeper=lambda _:None)["attempted_this_run"]==0
    assert not in_scope("https://library.example.org/catalogue",scope()["scopes"][0])
    assert not in_scope("https://library.example.org/catalog/%2e%2e/outside",scope()["scopes"][0])
    f.close()

def test_robots_budget_and_unknown_policy(tmp_path):
    f=Frontier(tmp_path/"f.db");p=PageFrontier(f);p.init(scope())
    seen=[]
    def fail(u):
        seen.append(u);return 503,{"retry-after":"3600"},b"temporarily unavailable"
    r=p.run(10,3,1,4,"FixtureBot",fail,sleeper=lambda _:None)
    assert r["attempted_this_run"]==1 and seen[0].endswith("robots.txt")
    assert r["page_states"]=={"queued":1}
    assert p.run(10,3,1,4,"FixtureBot",fail,sleeper=lambda _:None)["attempted_this_run"]==0
    f.close()

def test_seed_configs(tmp_path):
    root=Path(__file__).resolve().parents[1]
    f=Frontier(tmp_path/"f.db")
    f.init(json.loads((root/"config/source_frontier_seeds.json").read_text(encoding="utf-8")))
    p=PageFrontier(f);p.init(json.loads((root/"config/source_page_scopes.json").read_text(encoding="utf-8")))
    assert f.summary()["task_states"]["queued"]>=10
    assert p.summary()["page_states"]["queued"]>=4
    f.close()
