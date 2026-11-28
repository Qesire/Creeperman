"""Bounded, public catalogue-page crawler sharing the source frontier.

Only operator-approved HTTPS host/path scopes are visited. Every GET,
including robots.txt, consumes the run budget. No redirects, credentials,
automatic binary downloads, or historical website verification.
"""
from __future__ import annotations
import argparse
import ipaddress
import json
import re
import socket
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, unquote
from .core import canonical
from .source_frontier import (Frontier, MAX_BYTES, FILE_RE, digest, utc,
    cue_score, http_fetcher, safe_url)
from .locking import collector_lock

SCHEMA="source-page-scopes-v1"
DDL="""
CREATE TABLE IF NOT EXISTS page_scopes(id TEXT PRIMARY KEY,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS page_tasks(url TEXT PRIMARY KEY,scope TEXT NOT NULL,depth INTEGER NOT NULL,
 priority INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'queued',document_id TEXT);
CREATE TABLE IF NOT EXISTS page_edges(parent TEXT,child TEXT,relation TEXT,PRIMARY KEY(parent,child,relation));
CREATE TABLE IF NOT EXISTS page_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,
 url TEXT NOT NULL,host TEXT NOT NULL,scope TEXT NOT NULL,kind TEXT NOT NULL,
 started TEXT NOT NULL,ended TEXT,status TEXT NOT NULL,http_status INTEGER,sha TEXT,headers TEXT,error TEXT);
CREATE TABLE IF NOT EXISTS robots_cache(host TEXT PRIMARY KEY,sha TEXT,code INTEGER NOT NULL,checked REAL NOT NULL);
CREATE TABLE IF NOT EXISTS page_cooldown(host TEXT PRIMARY KEY,until_epoch REAL NOT NULL);
CREATE INDEX IF NOT EXISTS page_task_queue ON page_tasks(state,priority DESC,depth,url);
"""


def page_url(value):
    if not safe_url(value):return None
    try:
        p=urlsplit(value)
        if p.scheme!="https" or p.username or p.password or p.port not in (None,443) or not p.hostname:return None
        h=p.hostname.lower()
        if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,63}",h):return None
        try:ipaddress.ip_address(h);return None
        except ValueError:pass
        path=p.path or "/";dec=unquote(path)
        if "\\" in dec or "%" in dec or re.search(r"%2f|%5c",path,re.I) or any(c.isspace() or ord(c)<32 for c in dec) or any(x in (".","..") for x in dec.split("/")):return None
        return urlunsplit(("https",h,path,p.query,""))
    except ValueError:return None


def in_scope(url,scope):
    u=page_url(url)
    if not u:return False
    p=urlsplit(u)
    if p.hostname!=scope["host"] or (p.query and not scope.get("allow_query",False)):return False
    path=unquote(p.path)
    return any(path==v.rstrip("/") or path.startswith(v.rstrip("/")+"/") for v in scope["paths"])


def validate_scope(s):
    h=s["host"]
    if not isinstance(h,str) or h!=h.lower() or page_url("https://"+h+"/") is None or urlsplit("https://"+h+"/").netloc!=h:
        raise ValueError("scope requires exact public host")
    if h in ("archive.org","www.archive.org","web.archive.org","zenodo.org","api.crossref.org","api.datacite.org"):
        raise ValueError("use dedicated catalog provider")
    if not isinstance(s["paths"],list) or not s["paths"] or any(not isinstance(v,str) or not v.startswith("/") or v=="/" or "?" in v or "#" in v or page_url("https://"+h+v) is None for v in s["paths"]):
        raise ValueError("explicit narrow path prefixes required")
    if not s.get("family") or not s.get("seeds"):raise ValueError("scope family and observed seeds required")
    for u in s["seeds"]:
        if not in_scope(u,s) or FILE_RE.search(u):raise ValueError("seed outside page scope")


def make_fetcher(agent):
    base=http_fetcher(agent,"text/html,application/xhtml+xml,text/plain;q=0.5")
    def fetch(url):
        h=urlsplit(url).hostname
        rows=socket.getaddrinfo(h,443,type=socket.SOCK_STREAM)
        if not rows or any(not ipaddress.ip_address(r[4][0].split("%",1)[0]).is_global for r in rows):
            raise OSError("non-public DNS result")
        return base(url)
    return fetch


class PageFrontier:
    def __init__(self,f):
        self.f=f;self.db=f.db;self.db.executescript(DDL)
    def enqueue(self,u,sid,depth,priority,parent,context=""):
        u=page_url(u)
        if u is None:raise ValueError("invalid page URL")
        self.db.execute("""INSERT INTO page_tasks(url,scope,depth,priority) VALUES(?,?,?,?)
           ON CONFLICT(url) DO UPDATE SET depth=min(depth,excluded.depth),priority=max(priority,excluded.priority)""",
           (u,sid,depth,priority))
        self.db.execute("INSERT OR IGNORE INTO page_edges VALUES(?,?,?)",(parent,u,"observed_page_link"))
        from .discovery_policy import year_hint
        scope=json.loads(self.db.execute("SELECT body FROM page_scopes WHERE id=?",(sid,)).fetchone()[0])
        state=self.db.execute("SELECT state FROM page_tasks WHERE url=?",(u,)).fetchone()[0]
        self.f.policy.register("page:"+u,kind="page",family=scope["family"],url=u,context=context,
            year=year_hint(u+" "+context),parent=parent,state=state)
    def init(self,cfg):
        if cfg.get("schema")!=SCHEMA:raise ValueError("invalid scope configuration")
        with self.db:
            for s in cfg["scopes"]:
                validate_scope(s);sid=digest(s)
                self.db.execute("INSERT OR IGNORE INTO page_scopes VALUES(?,?)",(sid,canonical(s).decode()))
                for u in s["seeds"]:self.enqueue(u,sid,0,20,"scope:"+sid)
    def index_local_pages(self):
        # Documents can have been imported by an older, independent CLI process.
        # Snapshot metadata once per run; never load or reparse archived bodies.
        self.db.create_function("normalized_page_url", 1, page_url, deterministic=True)
        self.db.execute("""CREATE TEMP TABLE IF NOT EXISTS reusable_pages(
            url TEXT PRIMARY KEY, document_id TEXT NOT NULL)""")
        self.db.execute("DELETE FROM reusable_pages")
        self.db.execute("""INSERT INTO reusable_pages(url,document_id)
            SELECT normalized_page_url(source_url) AS url,min(id)
            FROM documents WHERE format='html'
            GROUP BY normalized_page_url(source_url)
            HAVING url IS NOT NULL AND count(DISTINCT sha)=1
                AND EXISTS (SELECT 1 FROM bodies WHERE bodies.sha=documents.sha)""")
        # A second, different snapshot may have arrived since an earlier run.
        # Keep the previous choice as provenance and release the ambiguous task.
        self.db.execute("""INSERT OR IGNORE INTO page_edges(parent,child,relation)
            SELECT url,document_id,'reused_local_snapshot' FROM page_tasks t
            WHERE state='reused_local' AND NOT EXISTS (SELECT 1 FROM reusable_pages r WHERE r.url=t.url)""")
        self.db.execute("""UPDATE page_tasks SET state='queued',document_id=NULL
            WHERE state='reused_local' AND NOT EXISTS (SELECT 1 FROM reusable_pages r WHERE r.url=page_tasks.url)""")
        return self.db.execute("SELECT 1 FROM reusable_pages LIMIT 1").fetchone() is not None

    def expand_page(self, row, scope, document_id, max_children):
        # The importer already resolved relative URLs against this document's
        # own source URL and HTML base. Keep the original observation intact.
        proposals = {}; contexts = {}
        links = self.db.execute("""SELECT json_extract(body,'$.url'),json_extract(body,'$.description'),
            json_extract(body,'$.surrounding_context')
            FROM observations WHERE parent=?""", (document_id,))
        for link, context, surrounding in links:
            child = page_url(link)
            if child and child != row["url"] and in_scope(child, scope) and not FILE_RE.search(child):
                context = context or ""
                score = cue_score(context + " " + child)
                proposals[child] = max(score, proposals.get(child, -1))
                contexts[child] = (contexts.get(child, "") + " " + context + " " + (surrounding or ""))[:4000]
        self.db.executemany("INSERT OR IGNORE INTO page_edges VALUES(?,?,'unreviewed_page_link')",
                            ((document_id, child) for child in proposals))
        known = {r[0] for r in self.db.execute("""SELECT e.child FROM page_edges e
            JOIN page_tasks t ON t.url=e.child WHERE e.parent=? AND e.relation='unreviewed_page_link'""",
            (document_id,))}
        admitted = 0
        for child, score in sorted(proposals.items(), key=lambda item: (-item[1], item[0])):
            if child not in known:
                if admitted >= max_children:
                    continue
                admitted += 1
            self.enqueue(child, row["scope"], row["depth"] + 1, score, document_id,contexts[child])

    def reuse_queued(self, limit, max_depth, max_children):
        reused = 0
        while reused < limit:
            candidates = self.db.execute("""SELECT t.*,s.body,r.document_id AS local_id
                FROM page_tasks t JOIN reusable_pages r ON r.url=t.url
                JOIN page_scopes s ON s.id=t.scope
                WHERE t.state='queued' AND t.depth<=?
                ORDER BY t.priority DESC,t.depth,t.url""", (max_depth,))
            # Offline reuse remains first, while the optional policy ranks the
            # observed local queue itself. It never schedules a new download.
            with self.db:
                row = self.f.policy.select("page",candidates.fetchall()) if self.f.policy.enabled else candidates.fetchone()
            if row is None:
                break
            scope = json.loads(row["body"])
            if not in_scope(row["url"], scope):
                raise ValueError("persisted task outside scope")
            with self.db:
                self.f.policy.register("document:"+row["local_id"],kind="document",family=scope["family"],
                    url=row["url"],operator="source-document-v1",parent="page:"+row["url"],
                    features={"local_available":True},state="parsed")
                self.expand_page(row, scope, row["local_id"], max_children)
                self.db.execute("INSERT OR IGNORE INTO page_edges VALUES(?,?,'reused_local_snapshot')",
                                (row["url"], row["local_id"]))
                self.db.execute("""UPDATE page_tasks SET state='reused_local',document_id=?
                    WHERE url=?""", (row["local_id"], row["url"]))
                self.f.policy.state("page:"+row["url"],"reused_local")
            reused += 1
        return reused

    def reuse_local(self, max_local_pages=200, max_depth=2, max_children=15):
        if not 1 <= max_local_pages <= 10000 or not 0 <= max_depth <= 8 or not 1 <= max_children <= 100:
            raise ValueError("invalid local bounds")
        with self.db:
            has_local = self.index_local_pages()
        reused = self.reuse_queued(max_local_pages, max_depth, max_children) if has_local else 0
        return {"attempted_this_run": 0, "reused_local_this_run": reused, **self.summary()}

    def fetch_one(self,u,sid,kind,fetch,interval,sleeper):
        h=urlsplit(u).hostname
        last=self.db.execute("SELECT max(started) FROM page_requests WHERE host=?",(h,)).fetchone()[0]
        if last:
            gap=interval-(time.time()-datetime.fromisoformat(last).timestamp())
            if gap>0:sleeper(gap)
        with self.db:
            rid=self.db.execute("INSERT INTO page_requests(url,host,scope,kind,started,status) VALUES(?,?,?,?,?,'started')",
                (u,h,sid,kind,utc())).lastrowid
            if kind=="page":
                self.db.execute("UPDATE page_tasks SET state='started' WHERE url=?",(u,))
                self.f.policy.state("page:"+u,"started")
        code=None;headers={};body=b"";err=None
        try:
            code,headers,body=fetch(u)
            status="truncated" if len(body)>MAX_BYTES else "received" if code==200 else "http_error"
            body=body[:MAX_BYTES]
        except (OSError,TimeoutError) as exc:
            status="transport_error";err=type(exc).__name__
        with self.db:
            sha=self.f.put_body(body) if body else None
            self.db.execute("UPDATE page_requests SET ended=?,status=?,http_status=?,sha=?,headers=?,error=? WHERE id=?",
                (utc(),status,code,sha,canonical(headers).decode(),err,rid))
            if code in (401,403,429,503):
                delay=300;v=headers.get("retry-after")
                if v:
                    try:delay=max(delay,int(v))
                    except (ValueError,TypeError):
                        try:delay=max(delay,parsedate_to_datetime(v).timestamp()-time.time())
                        except (ValueError,TypeError,OverflowError):pass
                until=253402300799 if code in (401,403) else time.time()+delay
                self.db.execute("INSERT INTO page_cooldown VALUES(?,?) ON CONFLICT(host) DO UPDATE SET until_epoch=max(until_epoch,excluded.until_epoch)",(h,until))
        return status,code,headers,body,sha
    def run(self,limit,interval,max_depth,max_children,user_agent,fetch,sleeper=time.sleep,*,max_local_pages=200):
        from protego import Protego
        if not 1<=limit<=200 or not 3<=interval<=3600 or not 0<=max_depth<=8 or not 1<=max_children<=100 or not 1<=max_local_pages<=10000:
            raise ValueError("invalid crawl bounds")
        with self.db:
            has_local = self.index_local_pages()
        used=0;reused=0;excluded=set()
        while used<limit:
            if has_local and reused < max_local_pages:
                reused += self.reuse_queued(max_local_pages - reused, max_depth, max_children)
            candidates=self.db.execute("""SELECT t.*,s.body,coalesce(a.n,0) spent FROM page_tasks t JOIN page_scopes s ON s.id=t.scope
              LEFT JOIN (SELECT scope,count(*) n FROM page_requests GROUP BY scope) a ON a.scope=t.scope
              WHERE t.state='queued' AND t.depth<=?
              AND NOT EXISTS (SELECT 1 FROM reusable_pages r WHERE r.url=t.url)
              ORDER BY spent,priority DESC,depth,url""",(max_depth,))
            eligible=[]
            for r in candidates:
                h=urlsplit(r["url"]).hostname
                cool=self.db.execute("SELECT until_epoch FROM page_cooldown WHERE host=?",(h,)).fetchone()
                if h not in excluded and (not cool or cool[0]<=time.time()):
                    eligible.append(r)
                    if not self.f.policy.enabled:break
            with self.db:
                row=self.f.policy.select("page",eligible)
            if row is None:break
            u=row["url"];sid=row["scope"];s=json.loads(row["body"]);h=urlsplit(u).hostname
            if not in_scope(u,s):raise ValueError("persisted task outside scope")
            robots=self.db.execute("SELECT * FROM robots_cache WHERE host=?",(h,)).fetchone()
            if robots is None or time.time()-robots["checked"]>86400:
                status,code,headers,body,sha=self.fetch_one("https://"+h+"/robots.txt",sid,"robots",fetch,interval,sleeper);used+=1
                if not ((status=="received" and code==200 and "html" not in headers.get("content-type","").lower() and not body.lstrip().lower().startswith((b"<!doctype html",b"<html"))) or (status=="http_error" and code in (404,410))):
                    excluded.add(h);continue
                with self.db:self.db.execute("INSERT OR REPLACE INTO robots_cache VALUES(?,?,?,?)",(h,sha,code,time.time()))
                if used>=limit:break
                robots=self.db.execute("SELECT * FROM robots_cache WHERE host=?",(h,)).fetchone()
            raw=b""
            if robots["code"]==200 and robots["sha"]:
                raw=self.db.execute("SELECT bytes FROM bodies WHERE sha=?",(robots["sha"],)).fetchone()[0]
            rp=Protego.parse(raw.decode("utf-8",errors="replace"))
            if not rp.can_fetch(u,user_agent):
                with self.db:
                    self.db.execute("UPDATE page_tasks SET state='robots_disallowed' WHERE url=?",(u,))
                    self.f.policy.state("page:"+u,"robots_disallowed")
                continue
            rate=rp.request_rate(user_agent)
            delay=max(interval,rp.crawl_delay(user_agent) or 0)
            if rate:
                if rate.start_time is not None or rate.end_time is not None:
                    excluded.add(h);continue
                if rate.requests>0:delay=max(delay,rate.seconds/rate.requests)
            if rp.visit_time(user_agent) or delay>3600:
                excluded.add(h);continue
            status,code,headers,body,sha=self.fetch_one(u,sid,"page",fetch,delay,sleeper);used+=1
            if code in (401,403,429,503):excluded.add(h)
            with self.db:
                state=status;doc=None
                if status=="received":
                    if "html" not in headers.get("content-type","").lower():state="non_html_review"
                    else:
                        self.db.execute("SAVEPOINT page_parse")
                        try:
                            doc=self.f.import_document_bytes(body,"html",u,s["family"])
                            self.expand_page(row, s, doc, max_children)
                            self.db.execute("RELEASE page_parse");state="parsed"
                        except (ValueError,KeyError,TypeError,UnicodeError,AttributeError):
                            self.db.execute("ROLLBACK TO page_parse");self.db.execute("RELEASE page_parse");doc=None;state="invalid_document"
                self.db.execute("UPDATE page_tasks SET state=?,document_id=? WHERE url=?",(state,doc,u))
                self.f.policy.state("page:"+u,state)
        return {"attempted_this_run":used,"reused_local_this_run":reused,"excluded_hosts_this_run":sorted(excluded),**self.summary()}
    def summary(self):
        return {"schema":SCHEMA,"page_states":dict(self.db.execute("SELECT state,count(*) FROM page_tasks GROUP BY state")),
          "request_kinds":dict(self.db.execute("SELECT kind,count(*) FROM page_requests GROUP BY kind")),
          "requests_by_host":dict(self.db.execute("SELECT host,count(*) FROM page_requests GROUP BY host")),
          "provider_cooldowns":dict(self.db.execute("SELECT host,until_epoch FROM page_cooldown")),
          "verified_new_eed":None,"discovery_policy":self.f.policy.summary()}
    def export(self,out):
        out=Path(out);out.mkdir(parents=True,exist_ok=False)
        for table in ("page_scopes","page_tasks","page_edges","page_requests","robots_cache",
                      "discovery_nodes","discovery_edges","discovery_choices","discovery_batches","discovery_training"):
            with (out/(table+".jsonl")).open("wb") as fp:
                for row in self.db.execute("SELECT * FROM "+table):
                    v=dict(row)
                    for k in ("body","headers","features","tokens"):
                        if isinstance(v.get(k),str):v[k]=json.loads(v[k])
                    fp.write(canonical(v))
        (out/"report.json").write_bytes(canonical(self.summary()))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--db",required=True,type=Path)
    sub=p.add_subparsers(dest="cmd",required=True)
    q=sub.add_parser("init");q.add_argument("--scopes",required=True,type=Path)
    r=sub.add_parser("run");r.add_argument("--max-requests",required=True,type=int)
    r.add_argument("--interval",type=float,default=4)
    r.add_argument("--user-agent",required=True);r.add_argument("--allow-public-pages",required=True,action="store_true")
    local=sub.add_parser("reuse-local",help="expand already imported HTML pages offline")
    for parser in (local, r):
        parser.add_argument("--policy",type=Path,help="Load a live ranking policy; local reuse stays ahead of network")
        parser.add_argument("--max-local-pages",type=int,default=200)
        parser.add_argument("--max-depth",type=int,default=2)
        parser.add_argument("--max-children",type=int,default=15)
    e=sub.add_parser("export");e.add_argument("--out",required=True,type=Path)
    sub.add_parser("status")
    a=p.parse_args(argv);f=Frontier(a.db,policy=getattr(a,"policy",None))
    try:
        with collector_lock(a.db):
            pf=PageFrontier(f)
            if a.cmd=="init":pf.init(json.loads(a.scopes.read_text(encoding="utf-8")));result=pf.summary()
            elif a.cmd=="reuse-local":result=pf.reuse_local(a.max_local_pages,a.max_depth,a.max_children)
            elif a.cmd=="run":result=pf.run(a.max_requests,a.interval,a.max_depth,a.max_children,a.user_agent,make_fetcher(a.user_agent),max_local_pages=a.max_local_pages)
            elif a.cmd=="export":pf.export(a.out);result=pf.summary()
            else:result=pf.summary()
        print(canonical(result).decode(),end="")
    finally:f.close()

if __name__=="__main__":main()
