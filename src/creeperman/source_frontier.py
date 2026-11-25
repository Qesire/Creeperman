"""Source-object discovery: public catalog metadata, typed edges and bounded frontier.

No candidate-host probing, email, licensed-file access, or automatic evidence decisions.
Raw catalog responses and local document imports remain in the local SQLite ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit, unquote
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

from .core import canonical

SCHEMA = "source-frontier-v1"
PROVIDERS = ("crossref", "datacite", "zenodo", "ia")
ROWS = 20
MAX_BYTES = 8 * 1024 * 1024
DOI = re.compile(r"10\.\d{4,9}/[^\s<>\"?#]+", re.I)
IA_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}")
YEARS = re.compile(r"(?<!\d)(199[6-9]|200[01])(?!\d)")
CUES = (
    "web crawl","web archive","web collection","web corpus","web graph","web directory",
    "website directory","web server survey","url list","url inventory","host list",
    "crawl log","site list","link graph","dmoz","open directory project","wayback",
    "webkb","spirit collection","ntcir","internet scout","internet directory","yellow pages",
    "cdx","warc","rdf","web survey","search engine","seed list",
    "archivage du web","annuaire internet","annuaire web","webarchiv","webkatalog",
    "webverzeichnis","archivo web","directorio web","arquivo da web","diretório",
    "ウェブアーカイブ","ウェブ収集","ウェブサイト","网页归档","网站目录",
)
FILE_RE = re.compile(r"\.(?:cdxj?|warc|arc|rdf|xml|jsonl?|ndjson|csv|tsv|txt|zip|tar|tgz|7z|pdf|mbox|gz|bz2|xz)(?:$|[?#])", re.I)


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def flatten(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(flatten(v) for v in value)
    if isinstance(value, dict):
        return " ".join(flatten(v) for v in value.values())
    return ""


def cue_score(text):
    s = text.casefold()
    # Ordinal ranking, not a probability or an estimated EED.
    return min(12, sum(x in s for x in CUES)) + 3 * bool(YEARS.search(s))


def safe_url(value):
    if not isinstance(value, str) or len(value)>4096 or any(c.isspace() or ord(c)<32 for c in value):
        return None
    try:
        p=urlsplit(value)
        if p.scheme in ("http","https","ftp") and p.hostname and not p.username and not p.password:
            return value
    except ValueError:
        pass
    return None


def normalize_doi(value):
    s = str(value or "").strip()
    for prefix in ("https://doi.org/","http://doi.org/","http://dx.doi.org/","doi:"):
        if s.lower().startswith(prefix):
            s = unquote(s[len(prefix):])
            break
    return s.lower() if len(s)<=512 and DOI.fullmatch(s) and not any(x in (".","..") for x in s.split("/")) else None


def spec(provider, action, key, page=1):
    if provider not in PROVIDERS or action not in ("search","detail"):
        raise ValueError("unsupported catalog operation")
    if not isinstance(key,str) or not key.strip() or len(key)>512 or any(ord(c)<32 for c in key):
        raise ValueError("invalid public metadata key")
    key=key.strip()
    if action=="detail":
        if provider in ("crossref","datacite"):
            key=normalize_doi(key)
            if not key:raise ValueError("detail needs DOI")
        elif provider=="ia" and not IA_ID.fullmatch(key):
            raise ValueError("invalid IA identifier")
        elif provider=="zenodo" and not re.fullmatch(r"\d{1,16}",key):
            raise ValueError("invalid Zenodo record ID")
        page=1
    if type(page) is not int or not 1<=page<=100:
        raise ValueError("invalid page")
    return {"provider":provider,"action":action,"key":key,"page":page}


def endpoint(task):
    t=spec(**task)
    p,a,k,n=(t[x] for x in ("provider","action","key","page"))
    bases={"crossref":"https://api.crossref.org/works","datacite":"https://api.datacite.org/dois",
           "zenodo":"https://zenodo.org/api/records","ia":"https://archive.org/advancedsearch.php"}
    if a=="detail":
        if p=="ia": return "https://archive.org/metadata/"+quote(k,safe="")
        return bases[p]+"/"+quote(k,safe="/" if p in ("crossref","datacite") else "")
    if p=="crossref": params={"query.bibliographic":k,"rows":ROWS,"offset":(n-1)*ROWS}
    elif p=="datacite": params={"query":k,"page[size]":ROWS,"page[number]":n}
    elif p=="zenodo": params={"q":k,"size":ROWS,"page":n}
    else: params={"q":k,"rows":ROWS,"page":n,"output":"json",
                  "fl[]":["identifier","title","description","date","collection","mediatype"]}
    return bases[p]+"?"+urlencode(params,doseq=True)


def route_url(url):
    """Only route documented record identifiers, not arbitrary remote URLs."""
    u=safe_url(url)
    if not u:return []
    p=urlsplit(u); h=p.hostname; path=unquote(p.path)
    if h=="archive.org":
        m=re.match(r"^/(?:details|download|metadata)/([^/]+)(?:/|$)",path)
        if m and IA_ID.fullmatch(m.group(1)): return [spec("ia","detail",m.group(1))]
    if h=="zenodo.org":
        m=re.match(r"^/(?:api/)?records?/(\d+)(?:/|$)",path)
        if m:return [spec("zenodo","detail",m.group(1))]
    if h in ("doi.org","dx.doi.org"):
        d=normalize_doi(path.lstrip("/"))
        if d:
            return [spec("zenodo","detail",d.split(".zenodo.")[-1])] if re.fullmatch(r"10\.5281/zenodo\.\d+",d) else [spec("datacite","detail",d),spec("crossref","detail",d)]
    return []


def resource(kind,identity,*,title="",description="",url=None,**fields):
    s=flatten([title,description,identity,url or ""])
    return {"kind":kind,"identity":identity,"title":flatten(title)[:1000],
            "description":flatten(description)[:4000],"url":safe_url(url),
            "year_mentions":sorted({int(y) for y in YEARS.findall(s)}),
            "rank":cue_score(s)+(8 if kind=="file_descriptor" else 0),
            "historical_year_verified":False, "qualification":"not_evaluated",**fields}


def parsed(task, data):
    """Parse one actual catalog page. Return resources and bounded expansion proposals.

    Metadata publication dates, file mtimes and years in titles are not capture dates.
    Unknown schema raises rather than treating it as an empty result.
    """
    p,a,k,n=(task[x] for x in ("provider","action","key","page"))
    out=[]; children=[]
    def add_task(t, why, rank=0):
        children.append((t,why,int(rank)))
    def add_url(u, why, rank=0):
        u=safe_url(u)
        if u:
            out.append(resource("locator_hint",u,url=u,description=why))
            for t in route_url(u):add_task(t,why,rank)
    def file_item(record_id, name, url, **kw):
        if not isinstance(name,str) or not name or len(name)>2048:return
        out.append(resource("file_descriptor",record_id+"/"+name,title=name,url=url,
                    record_id=record_id,file_name=name,**kw))
    def doi_edge(d, why, title=""):
        d=normalize_doi(d)
        if not d:return
        url="https://doi.org/"+d
        out.append(resource("doi_relation",d,title=title,url=url,description=why))
        # Resolve a finite subset of links. Both DOI registries are possible;
        # prefer data registry for data-like relations; never claim a missing DOI absent.
        rs=route_url(url)
        if len(rs)==2 and p=="crossref" and not cue_score(flatten([title,why])):
            rs=list(reversed(rs))
        for i,t in enumerate(rs):add_task(t,why,cue_score(flatten([title,why]))-i)
    if p=="ia":
        if a=="search":
            r=data["response"]; items=r["docs"]
            if not isinstance(items,list):raise ValueError("invalid IA docs")
            for d in items:
                ident=d.get("identifier")
                if not isinstance(ident,str) or not IA_ID.fullmatch(ident):continue
                x=resource("collection_record",ident,title=d.get("title",""),description=d.get("description",""),
                           url="https://archive.org/details/"+ident,metadata_date=d.get("date"),collection=d.get("collection"))
                out.append(x);add_task(spec(p,"detail",ident),"IA search item identifier",x["rank"])
        else:
            m=data["metadata"]
            if m.get("identifier")!=k:raise ValueError("IA identifier mismatch")
            items=data["files"]
            if not isinstance(items,list):raise ValueError("invalid IA file list")
            out.append(resource("collection_record",k,title=m.get("title",""),description=m.get("description",""),
                     url="https://archive.org/details/"+k,metadata_date=m.get("date"),license_hint=m.get("licenseurl"),
                     collection=m.get("collection")))
            for f in items:
                name=f.get("name")
                if not isinstance(name,str):continue
                # URL is a documented locator only; not a successful GET.
                url="https://archive.org/download/"+quote(k,safe="")+"/"+quote(name,safe="/")
                if any(q in ("","..",".") for q in name.split("/")):url=None
                file_item(k,name,url,size=f.get("size"),declared_sha1=f.get("sha1"),declared_md5=f.get("md5"),
                          format=f.get("format"),file_role=f.get("source"),metadata_mtime=f.get("mtime"),
                          access_hint={"private":f.get("private"),"restricted_item":m.get("access-restricted-item")})
            for u in re.findall(r"https?://[^\s<>\"]+",flatten(m.get("description",""))):
                add_url(u.rstrip(".,);"),"IA item description")
    elif p=="zenodo":
        items=data["hits"]["hits"] if a=="search" else [data]
        if not isinstance(items,list):raise ValueError("invalid Zenodo records")
        for d in items:
            ident=str(d["id"]); m=d["metadata"]
            if not re.fullmatch(r"\d{1,16}",ident) or (a=="detail" and ident!=k):raise ValueError("Zenodo identity mismatch")
            x=resource("dataset_record",ident,title=m.get("title",""),description=m.get("description",""),
                url="https://zenodo.org/records/"+ident,metadata_date=m.get("publication_date"),
                access_hint=m.get("access_right"),license_hint=m.get("license"),doi=m.get("doi"))
            out.append(x)
            if a=="search":add_task(spec(p,"detail",ident),"Zenodo search record",x["rank"])
            for f in d.get("files",[]):
                links=f.get("links") or {}
                file_item(ident,f.get("key"),links.get("content") or links.get("self"),size=f.get("size"),
                          declared_checksum=f.get("checksum"),access_hint=m.get("access_right"))
            for rel in m.get("related_identifiers",[]):
                why="Zenodo relation "+str(rel.get("relation","unknown"))
                if str(rel.get("scheme","")).lower()=="doi":doi_edge(rel.get("identifier"),why)
                else:add_url(rel.get("identifier"),why,x["rank"])
    elif p=="datacite":
        items=data["data"] if a=="search" else [data["data"]]
        if not isinstance(items,list):raise ValueError("invalid DataCite records")
        for d in items:
            m=d["attributes"]; ident=normalize_doi(m.get("doi") or d.get("id"))
            if not ident:continue
            if a=="detail" and ident!=k:raise ValueError("DataCite identity mismatch")
            x=resource("dataset_record" if (m.get("types") or {}).get("resourceTypeGeneral")=="Dataset" else "scholarly_record",
                ident,title=m.get("titles",""),description=m.get("descriptions",""),url=m.get("url"),
                metadata_date=m.get("publicationYear"),date_fields=m.get("dates"),license_hint=m.get("rightsList"),
                resource_type=m.get("types"),doi=ident)
            out.append(x)
            if a=="search":add_task(spec(p,"detail",ident),"DataCite search DOI",x["rank"])
            add_url(m.get("url"),"DataCite landing URL",x["rank"])
            for u in m.get("contentUrl") or []:
                if safe_url(u):file_item(ident,unquote(urlsplit(u).path.rsplit("/",1)[-1]) or "content",u,license_hint=m.get("rightsList"))
            for rel in m.get("relatedIdentifiers") or []:
                why="DataCite relation "+str(rel.get("relationType","unknown"))
                if rel.get("relatedIdentifierType")=="DOI":doi_edge(rel.get("relatedIdentifier"),why)
                elif rel.get("relatedIdentifierType")=="URL":add_url(rel.get("relatedIdentifier"),why,x["rank"])
    elif p=="crossref":
        m=data["message"]; items=m["items"] if a=="search" else [m]
        if not isinstance(items,list):raise ValueError("invalid Crossref records")
        for d in items:
            ident=normalize_doi(d.get("DOI"))
            if not ident:continue
            if a=="detail" and ident!=k:raise ValueError("Crossref identity mismatch")
            x=resource("scholarly_record",ident,title=d.get("title",""),description=d.get("abstract",""),
                       url=d.get("URL"),metadata_date=d.get("published"),license_hint=d.get("license"),doi=ident)
            out.append(x)
            if a=="search":add_task(spec(p,"detail",ident),"Crossref search DOI",x["rank"])
            for l in d.get("link",[]):add_url(l.get("URL"),"Crossref full-text link",x["rank"])
            for typ,rels in (d.get("relation") or {}).items():
                for rel in rels:
                    why="Crossref relation "+typ
                    if rel.get("id-type")=="doi":doi_edge(rel.get("id"),why)
                    elif rel.get("id-type")=="uri":add_url(rel.get("id"),why,x["rank"])
            # On search pages only retain explicit reference expansion from
            # detail calls; avoid exploding the same scholarly result.
            if a=="detail":
                for r in d.get("reference",[]):
                    title=flatten([r.get("article-title"),r.get("volume-title"),r.get("unstructured")])
                    if r.get("DOI"):doi_edge(r["DOI"],"Crossref reference",title)
                    elif title:
                        out.append(resource("unresolved_reference",title[:500],title=title))
    else:raise ValueError("unknown provider")
    full_page=a=="search" and len(items)>=ROWS
    return out,children,full_page


class LinkParser(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base=base;self.links=[];self.active=None
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=="a" and d.get("href"):
            self.active=[d["href"],"",self.getpos()]
            self.links.append(self.active)
        if tag=="meta" and str(d.get("name") or d.get("property") or "").lower() in ("citation_pdf_url","citation_doi","dc.identifier","dcterms.identifier"):
            self.links.append([d.get("content",""),"metadata identifier",self.getpos()])
        if tag=="link" and d.get("href"):
            rel=str(d.get("rel","")).lower()
            if any(x in rel for x in ("alternate","describedby","related","item")):
                self.links.append([d["href"],rel,self.getpos()])
    def handle_data(self,data):
        if self.active:self.active[1]=(self.active[1]+data)[:400]
    def handle_endtag(self,tag):
        if tag=="a":self.active=None


def document_links(raw, fmt, source_url):
    text=raw.decode("utf-8",errors="replace"); result=[]
    if fmt=="html":
        parser=LinkParser(source_url);parser.feed(text);parser.close()
        result=parser.links
    elif fmt=="tei":
        root=ET.fromstring(raw)
        for i,e in enumerate(root.iter()):
            tag=e.tag.rsplit("}",1)[-1]
            target=e.attrib.get("target") or e.attrib.get("ref")
            if tag in ("ref","ptr") and target:
                for u in target.split():result.append([u,"".join(e.itertext())[:400],["element",i]])
            if tag=="idno" and e.attrib.get("type","").lower()=="doi":
                result.append(["".join(e.itertext()),"TEI DOI",["element",i]])
    elif fmt=="text":
        for m in re.finditer(r"(?:https?|ftp)://[^\s<>\"']+|10\.\d{4,9}/[^\s<>\"']+",text):
            result.append([m.group().rstrip(".,);"),text[max(0,m.start()-160):m.start()][:160],["character",m.start()]])
    else:raise ValueError("unsupported document format")
    for raw_url,anchor,position in result:
        if not raw_url or raw_url.startswith(("#","mailto:","javascript:")):continue
        d=normalize_doi(raw_url)
        u="https://doi.org/"+d if d else safe_url(urljoin(source_url,raw_url))
        if u:yield {"url":u,"raw_url":raw_url,"context":anchor,"position":list(position)}


DDL="""
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, provider TEXT NOT NULL, action TEXT NOT NULL,
 spec TEXT NOT NULL, family TEXT NOT NULL, depth INTEGER NOT NULL, priority INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'queued', created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS edges(parent TEXT NOT NULL, child TEXT NOT NULL, relation TEXT NOT NULL,
 PRIMARY KEY(parent,child,relation));
CREATE TABLE IF NOT EXISTS resources(id TEXT PRIMARY KEY, body TEXT NOT NULL, rank INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS observations(parent TEXT NOT NULL, resource_id TEXT NOT NULL,
 locator TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(parent,resource_id,locator));
CREATE TABLE IF NOT EXISTS bodies(sha TEXT PRIMARY KEY, bytes BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(task_id TEXT PRIMARY KEY, started TEXT NOT NULL,
 ended TEXT, status TEXT NOT NULL, http_status INTEGER, url TEXT NOT NULL, sha TEXT, headers TEXT,
 error TEXT, family TEXT NOT NULL, provider TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cooldown(provider TEXT PRIMARY KEY, until_epoch REAL NOT NULL);
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, sha TEXT NOT NULL, source_url TEXT NOT NULL, format TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proposals(parent TEXT NOT NULL, child TEXT NOT NULL, spec TEXT NOT NULL, family TEXT NOT NULL, depth INTEGER NOT NULL, priority INTEGER NOT NULL, relation TEXT NOT NULL, PRIMARY KEY(parent,child,relation));
"""


class Frontier:
    def __init__(self, path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,timeout=30)
        self.db.row_factory=sqlite3.Row
        self.db.executescript(DDL)
        self.db.execute("INSERT OR IGNORE INTO settings VALUES('schema',?)",(SCHEMA,))
        self.db.commit()
        if self.db.execute("SELECT value FROM settings WHERE key='schema'").fetchone()[0]!=SCHEMA:
            raise ValueError("incompatible source frontier")
    def close(self):self.db.close()
    def put_body(self,body):
        h=hashlib.sha256(body).hexdigest()
        self.db.execute("INSERT OR IGNORE INTO bodies VALUES(?,?)",(h,body))
        return h
    def enqueue(self, t, family, depth, priority, parent, reason):
        t=spec(**t); i=digest(t)
        self.db.execute("""INSERT INTO tasks(id,provider,action,spec,family,depth,priority,created)
          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET depth=min(depth,excluded.depth),
          priority=max(priority,excluded.priority)""",
          (i,t["provider"],t["action"],canonical(t).decode(),family,depth,priority,time.time_ns()))
        self.db.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?)",(parent,i,reason))
        return i
    def init(self,cfg):
        if cfg.get("schema")!=SCHEMA:raise ValueError("bad seed schema")
        with self.db:
            for s in cfg["seeds"]:
                family=s["family"]
                if not isinstance(family,str) or not family:raise ValueError("missing family")
                t=spec(s["provider"],s.get("action","search"),s["key"])
                self.enqueue(t,family,0,5 if t["action"]=="search" else 20,"seed:"+family,"configured public seed")
    def observe(self,parent,p,record,ordinal):
        # Record entity identity is separate from the full observation. Preserve
        # all versioned claims, even when record IDs coincide.
        rid=digest([p,record["kind"],record["identity"]])
        body={**record,"provider":p,"resource_id":rid}
        self.db.execute("""INSERT INTO resources VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,rank=excluded.rank WHERE excluded.rank>=resources.rank""",(rid,canonical(body).decode(),record["rank"]))
        self.db.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?)",
                        (parent,rid,str(ordinal),canonical(body).decode()))
        self.db.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?)",(parent,rid,record["kind"]))
    def import_document(self, path, fmt, source_url, family):
        if not safe_url(source_url):raise ValueError("explicit public original document URL required")
        path=Path(path)
        if path.stat().st_size>MAX_BYTES:raise ValueError("document exceeds metadata cap; split locally")
        return self.import_document_bytes(path.read_bytes(),fmt,source_url,family)
    def import_document_bytes(self,raw,fmt,source_url,family):
        if not safe_url(source_url) or not family:raise ValueError("public source URL and family required")
        if len(raw)>MAX_BYTES:raise ValueError("document exceeds metadata cap; split locally")
        # Caller may be within the scoped page crawl's transaction.
        h=self.put_body(raw); doc=digest([h,source_url,fmt])
        self.db.execute("INSERT OR IGNORE INTO documents VALUES(?,?,?,?)",(doc,h,source_url,fmt))
        for i,l in enumerate(document_links(raw,fmt,source_url)):
            r=resource("file_locator_hint" if FILE_RE.search(l["url"]) else "locator_hint",
                l["url"],url=l["url"],description=l["context"],**{"raw_url":l["raw_url"],"position":l["position"]})
            self.observe(doc,"local_document",r,i)
            for t in route_url(l["url"]):
                self.enqueue(t,family,0,20+r["rank"],doc,"document link at "+str(l["position"]))
        return doc
    def propose(self,parent,t,family,depth,priority,reason):
        cid=digest(t)
        self.db.execute("INSERT OR IGNORE INTO proposals VALUES(?,?,?,?,?,?,?)",
           (parent,cid,canonical(t).decode(),family,depth,priority,reason))
        return cid
    def admit(self,cid):
        rows=self.db.execute("SELECT * FROM proposals WHERE child=? ORDER BY priority DESC,depth,parent",(cid,)).fetchall()
        if not rows:raise ValueError("unknown proposal ID")
        with self.db:
            for r in rows:
                self.enqueue(json.loads(r["spec"]),r["family"],r["depth"],r["priority"],r["parent"],r["relation"])
    def choose(self, providers, max_depth, excluded=()):
        ps=[p for p in providers if p not in excluded]
        if not ps:return None
        placeholders=",".join("?" for _ in ps)
        # Explicit exploration: rotate source families by attempted task count;
        # within each family select concrete details before generic search.
        rows=self.db.execute(f"""SELECT t.*,coalesce(a.n,0) AS spent FROM tasks t
          LEFT JOIN (SELECT family,count(*) n FROM attempts GROUP BY family) a ON a.family=t.family
          LEFT JOIN cooldown c ON c.provider=t.provider
          WHERE t.state='queued' AND t.depth<=? AND t.provider IN ({placeholders})
          AND coalesce(c.until_epoch,0)<=?
          ORDER BY spent ASC, priority DESC, depth ASC, created ASC, id ASC LIMIT 1""",
          (max_depth,*ps,time.time())).fetchone()
        return rows
    def run(self, *, providers, limit, interval, max_depth=3, max_pages=2, max_children=6, fetch, sleeper=time.sleep):
        if not providers or any(p not in PROVIDERS for p in providers):raise ValueError("invalid providers")
        if type(limit)is not int or not 1<=limit<=200 or not 3<=interval<=3600 or not 0<=max_depth<=8 or not 1<=max_pages<=5 or not 1<=max_children<=30:
            raise ValueError("invalid crawl bounds")
        used=0; blocked=set()
        # Single controller lock is enforced by the CLI. Claim persists before
        # network; after crash a started task is never automatically resent.
        while used<limit:
            with self.db:
                row=self.choose(providers,max_depth,blocked)
                if row is None:break
                t=json.loads(row["spec"]);tid=row["id"];p=t["provider"];url=endpoint(t)
                changed=self.db.execute("UPDATE tasks SET state='started' WHERE id=? AND state='queued'",(tid,)).rowcount
                if not changed:continue
                last=self.db.execute("SELECT max(started) FROM attempts WHERE provider=?",(p,)).fetchone()[0]
                self.db.execute("INSERT INTO attempts(task_id,started,status,url,family,provider) VALUES(?,?,?,?,?,?)",
                    (tid,utc(),"started",url,row["family"],p))
            # Enforce a persistent lower bound even when commands are restarted.
            if last:
                delay=interval-(time.time()-datetime.fromisoformat(last).timestamp())
                if delay>0:sleeper(delay)
                with self.db:
                    self.db.execute("UPDATE attempts SET started=? WHERE task_id=?",(utc(),tid))
            used+=1
            status="transport_error"; code=None; headers={}; body=b""; err=None
            try:
                code,headers,body=fetch(url)
                if len(body)>MAX_BYTES:status="truncated";body=body[:MAX_BYTES]
                elif code==200:status="received"
                else:status="http_error"
            except (OSError,URLError,TimeoutError) as exc:err=type(exc).__name__
            with self.db:
                h=self.put_body(body) if body else None
                if status=="received":
                    self.db.execute("SAVEPOINT parse_result")
                    try:
                        rs,cs,full=parsed(t,json.loads(body))
                        for i,r in enumerate(rs):self.observe(tid,p,r,i)
                        # Deduplicate proposals before applying fan-out. All
                        # resource observations survive even if not scheduled.
                        seen=set(); admitted=0
                        for child,why,rank in sorted(cs,key=lambda c:(-c[2],digest(c[0]),c[1])):
                            cid=digest(child)
                            if cid==tid:continue
                            self.propose(tid,child,row["family"],row["depth"]+1,20+rank,why)
                            existing=self.db.execute("SELECT 1 FROM tasks WHERE id=?",(cid,)).fetchone()
                            if existing or (cid not in seen and admitted<max_children):
                                self.enqueue(child,row["family"],row["depth"]+1,20+rank,tid,why)
                                if not existing:admitted+=1
                                seen.add(cid)
                        if full and t["page"]<max_pages:
                            child=spec(t["provider"],"search",t["key"],t["page"]+1)
                            self.enqueue(child,row["family"],row["depth"],4,tid,"bounded next search page")
                        self.db.execute("RELEASE parse_result")
                        status="parsed"
                    except (ValueError,KeyError,TypeError,AttributeError,UnicodeError) as exc:
                        self.db.execute("ROLLBACK TO parse_result")
                        self.db.execute("RELEASE parse_result")
                        status="invalid_response";err=type(exc).__name__
                if code in (401,403,429,503):
                    blocked.add(p)
                    delay=300
                    v=headers.get("retry-after")
                    if v:
                        try:delay=max(delay,int(v))
                        except (ValueError,TypeError):
                            try:delay=max(delay,parsedate_to_datetime(v).timestamp()-time.time())
                            except (ValueError,TypeError,OverflowError):pass
                    until=253402300799 if code in (401,403) else time.time()+delay
                    self.db.execute("INSERT INTO cooldown VALUES(?,?) ON CONFLICT(provider) DO UPDATE SET until_epoch=max(until_epoch,excluded.until_epoch)",(p,until))
                self.db.execute("UPDATE attempts SET ended=?,status=?,http_status=?,sha=?,headers=?,error=? WHERE task_id=?",
                    (utc(),status,code,h,canonical(headers).decode(),err,tid))
                self.db.execute("UPDATE tasks SET state=? WHERE id=?",(status,tid))
            if used<limit:sleeper(interval)
        return {"attempted_this_run":used,"blocked_this_run":sorted(blocked),**self.summary()}
    def summary(self):
        counts=lambda q:dict(self.db.execute(q).fetchall())
        return {"schema":SCHEMA,"task_states":counts("SELECT state,count(*) FROM tasks GROUP BY state"),
                "attempts_by_provider":counts("SELECT provider,count(*) FROM attempts GROUP BY provider"),
                "attempts_by_family":counts("SELECT family,count(*) FROM attempts GROUP BY family"),
                "resource_kinds":counts("SELECT json_extract(body,'$.kind'),count(*) FROM resources GROUP BY 1"),
                "unadmitted_proposals":self.db.execute("SELECT count(DISTINCT p.child) FROM proposals p LEFT JOIN tasks t ON t.id=p.child WHERE t.id IS NULL").fetchone()[0],
                "provider_cooldowns":counts("SELECT provider,until_epoch FROM cooldown"),
                "verified_new_eed":None}
    def export(self,out):
        out=Path(out);out.mkdir(parents=True,exist_ok=False)
        queries={
          "frontier.jsonl":"SELECT * FROM tasks ORDER BY id",
          "attempts.jsonl":"SELECT * FROM attempts ORDER BY started,task_id",
          "edges.jsonl":"SELECT * FROM edges ORDER BY parent,child,relation",
          "observations.jsonl":"SELECT parent,resource_id,locator,body FROM observations ORDER BY parent,locator",
          "resources.jsonl":"SELECT body FROM resources ORDER BY rank DESC,id",
          "file_review.jsonl":"SELECT body FROM resources WHERE json_extract(body,'$.kind') IN ('file_descriptor','file_locator_hint') ORDER BY rank DESC,id",
          "documents.jsonl":"SELECT * FROM documents ORDER BY id",
          "proposals.jsonl":"SELECT p.*,CASE WHEN t.id IS NULL THEN 0 ELSE 1 END AS admitted FROM proposals p LEFT JOIN tasks t ON t.id=p.child ORDER BY p.priority DESC,p.parent,p.child"}
        for name,q in queries.items():
            with (out/name).open("wb") as f:
                for r in self.db.execute(q):
                    d=dict(r)
                    for k in ("spec","body","headers"):
                        if isinstance(d.get(k),str):d[k]=json.loads(d[k])
                    if name in ("resources.jsonl","file_review.jsonl"):d=d["body"]
                    f.write(canonical(d))
        (out/"report.json").write_bytes(canonical(self.summary()))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def http_fetcher(user_agent):
    if not user_agent or any(c in user_agent for c in "\r\n"):raise ValueError("descriptive User-Agent required")
    opener=build_opener(NoRedirect)
    def fetch(url):
        r=Request(url,headers={"User-Agent":user_agent,"Accept":"application/json","Accept-Encoding":"identity"})
        try:response=opener.open(r,timeout=30)
        except HTTPError as exc:response=exc
        with response:
            headers={k.lower():v for k,v in response.headers.items() if k.lower() in ("content-type","content-length","retry-after","location","etag","last-modified")}
            return int(response.code),headers,response.read(MAX_BYTES+1)
    return fetch


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",required=True,type=Path)
    sub=p.add_subparsers(dest="cmd",required=True)
    init=sub.add_parser("init");init.add_argument("--seeds",type=Path,required=True)
    imp=sub.add_parser("import-document");imp.add_argument("--input",type=Path,required=True)
    imp.add_argument("--format",choices=("html","tei","text"),required=True);imp.add_argument("--source-url",required=True);imp.add_argument("--family",required=True)
    run=sub.add_parser("run");run.add_argument("--providers",choices=PROVIDERS,nargs="+",required=True)
    run.add_argument("--max-requests",type=int,required=True);run.add_argument("--interval",type=float,default=4)
    run.add_argument("--max-depth",type=int,default=3);run.add_argument("--max-pages",type=int,default=2);run.add_argument("--max-children",type=int,default=6)
    run.add_argument("--user-agent",required=True);run.add_argument("--allow-public-catalog",action="store_true",required=True)
    ex=sub.add_parser("export");ex.add_argument("--out",type=Path,required=True)
    raw=sub.add_parser("raw");raw.add_argument("--sha256",required=True);raw.add_argument("--out",type=Path,required=True)
    admit=sub.add_parser("admit");admit.add_argument("--proposal-id",required=True)
    sub.add_parser("status")
    a=p.parse_args(argv)
    f=Frontier(a.db)
    try:
        if a.cmd=="init":f.init(json.loads(a.seeds.read_text(encoding="utf-8")));result=f.summary()
        elif a.cmd=="import-document":
            with f.db:
                doc=f.import_document(a.input,a.format,a.source_url,a.family)
            result={"document_id":doc,**f.summary()}
        elif a.cmd=="admit":f.admit(a.proposal_id);result=f.summary()
        elif a.cmd=="run":
            # Reuse the existing OS-level lock used by the archive worker;
            # run with the worker extra installed.
            from .runtime import collector_lock
            with collector_lock(a.db):
                result=f.run(providers=a.providers,limit=a.max_requests,interval=a.interval,
                    max_depth=a.max_depth,max_pages=a.max_pages,max_children=a.max_children,fetch=http_fetcher(a.user_agent))
        elif a.cmd=="export":f.export(a.out);result=f.summary()
        elif a.cmd=="raw":
            row=f.db.execute("SELECT bytes FROM bodies WHERE sha=?",(a.sha256,)).fetchone()
            if row is None:raise ValueError("unknown body hash")
            with a.out.open("xb") as out:out.write(row[0])
            result={"sha256":a.sha256,"bytes":len(row[0])}
        else:result=f.summary()
        print(canonical(result).decode(),end="")
    finally:f.close()


if __name__=="__main__":main()
