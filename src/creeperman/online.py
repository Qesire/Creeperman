"""Provider-bound online operations; one HTTP attempt per validated target.

Uses documented public interfaces, no live-site fetching, no redirects or
browser execution. Every result is pending qualification. Same provider
worker/state must cover lookup, replay, search, metadata and retries.
"""
from __future__ import annotations
import base64
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request
from pathlib import Path
from .cdx import Collector, query_params, interpret
from .core import YEARS, ALL, bit, host, timestamp_year, url_host, canonical
from .extract import clean_url, html_clues, decode_body

PROVIDERS=("ia","arquivo")
ACTIONS={"ia":{"lookup","replay","metadata"},"arquivo":{"lookup","replay","search"}}
ORIGINS={"ia":"https://web.archive.org","arquivo":"https://arquivo.pt"}
MAX_RESPONSE=8*1024*1024
ITEM=re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}\Z")
SAFE_HEADERS={"content-type","content-encoding","content-length","memento-datetime",
              "link","location","content-location","retry-after","x-archive-src",
              "x-archive-orig-content-type","x-archive-orig-date",
              "x-archive-orig-content-encoding","x-archive-orig-status"}

def capture_row(row):
    h=host(row["hostname"])
    u=clean_url(row["original"])
    ts=row["timestamp"]
    y=timestamp_year(ts)
    if h!=row["hostname"] or url_host(u)!=h or y not in YEARS:
        raise ValueError("capture identity/year mismatch")
    return h,u,ts,y

def source_pointer(value):
    if not isinstance(value,str) or "/" not in value: return None
    item,file=value.split("/",1)
    if not ITEM.fullmatch(item) or not file or len(file)>4096 or any(x in file.split("/") for x in ("..",".")):
        return None
    return {"item":item,"file":file,"raw":value}

def request_spec(provider,action,row):
    if action not in ACTIONS.get(provider,set()): raise ValueError("unsupported provider/action")
    if action=="lookup":
        if row.get("original_url"):clean_url(row["original_url"])
        params=query_params(row)
        if row.get("same_host"):
            params["url"]="http://"+row["hostname"]+"/"
            params["matchType"]="host"
        if provider=="ia":
            return ORIGINS[provider]+"/cdx/search/cdx",params
        # Arquivo uses pywb field names and newline-delimited JSON.
        params.pop("showResumeKey",None)
        params.pop("fl",None)
        params["filter"]=["status:200","mime:text/html"]
        return ORIGINS[provider]+"/wayback/cdx",params
    if action=="replay":
        _,u,ts,_=capture_row(row)
        # The original URL is nested inside a fixed archive path; do not follow
        # redirects or use a returned URI as the next request.
        prefix="/web/" if provider=="ia" else "/noFrame/replay/"
        return ORIGINS[provider]+prefix+ts+"id_/"+quote(u,safe=":/?&=%+;,@!$'()*[]~-._"),{}
    if action=="metadata":
        item=row["item"]
        if not ITEM.fullmatch(item): raise ValueError("invalid item identifier")
        if not isinstance(row.get("files"),list) or not row["files"] or len(row["files"])>500:
            raise ValueError("explicit finite file candidates required")
        return "https://archive.org/metadata/"+quote(item,safe=""),{}
    q=row["query"]
    if not isinstance(q,str) or not 1<=len(q)<=200 or "://" in q or any(ord(c)<32 for c in q):
        raise ValueError("invalid historical text query")
    return ORIGINS[provider]+"/textsearch",{"q":q,"from":"19960101000000",
        "to":"20011231235959","maxItems":25,"dedupValue":3,
        "fields":"title,originalURL,tstamp,collection,digest,linkToArchive,linkToOriginalFile"}

def validate_rows(provider,action,rows):
    if not 1<=len(rows)<=50:
        raise ValueError("online batch requires 1..50 operations")
    seen=set()
    for row in rows:
        request_spec(provider,action,row)
        if action=="lookup": key=(row["hostname"],row["target_mask"],bool(row.get("same_host")))
        elif action=="replay": key=capture_row(row)[:3]
        elif action=="search": key=row["query"].strip().casefold()
        else: key=row["item"]
        if key in seen: raise ValueError("duplicate online operation")
        seen.add(key)

class ArchiveCollector(Collector):
    def __init__(self,state,interval,agent,provider):
        super().__init__(state,interval,agent)
        if provider not in PROVIDERS: raise ValueError("unknown provider")
        self.provider=provider
        import sqlite3
        with sqlite3.connect(self.state) as db:
            db.execute("CREATE TABLE IF NOT EXISTS collector_binding(id INTEGER PRIMARY KEY, provider TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO collector_binding VALUES(1,?)",(provider,))
            if db.execute("SELECT provider FROM collector_binding WHERE id=1").fetchone()[0]!=provider:
                raise ValueError("state file bound to another provider")

    def fetch(self,url,params):
        p=urlsplit(url)
        expected={"web.archive.org","archive.org"} if self.provider=="ia" else {"arquivo.pt"}
        if p.scheme!="https" or p.netloc not in expected:
            raise ValueError("outside fixed provider endpoints")
        if not self.reserve():
            return {"state":"provider_cooldown","requests":0},None
        if params: url+="?"+urlencode(params,doseq=True)
        req=Request(url,headers={"User-Agent":self.agent,"Accept-Encoding":"identity"})
        try:
            with self.opener.open(req,timeout=30) as r:
                body=r.read(MAX_RESPONSE+1)
                return {"state":"received" if r.status==200 else "http_error",
                        "requests":1,"http_status":r.status,"requested_url":url,
                        "retrieved_at":datetime.now(timezone.utc).isoformat(),
                        "headers":{k.lower():v for k,v in r.headers.items() if k.lower() in SAFE_HEADERS},
                        "truncated":len(body)>MAX_RESPONSE},body[:MAX_RESPONSE]
        except HTTPError as e:
            with e:
                h={k.lower():v for k,v in e.headers.items() if k.lower() in SAFE_HEADERS}
                if e.code in (429,503): self.cooldown(h.get("retry-after"))
                body=e.read(MAX_RESPONSE+1)
                return {"state":"rate_limited" if e.code==429 else "http_error",
                        "requests":1,"http_status":e.code,"requested_url":url,
                        "retrieved_at":datetime.now(timezone.utc).isoformat(),"headers":h,
                        "truncated":len(body)>MAX_RESPONSE},body[:MAX_RESPONSE]
        except (URLError,TimeoutError,OSError) as e:
            return {"state":"transient_failure","requests":1,"error_type":type(e).__name__,
                    "requested_url":url,"retrieved_at":datetime.now(timezone.utc).isoformat()},None

def lookup_result(provider,row,body,meta):
    if provider=="ia":
        return interpret(row,body,meta)
    result={"hostname":row["hostname"],"target_mask":row["target_mask"],"witness_mask":0,
            "potential_witnesses":[],"query_scope_complete":False,
            "qualification":"not_evaluated",**meta}
    if meta["state"]!="received": return result
    if meta.get("truncated"):
        result["state"]="possibly_truncated";return result
    try:
        for line in body.splitlines():
            if not line.strip(): continue
            v=json.loads(line)
            ts,u=v["timestamp"],v["url"]
            y=timestamp_year(ts)
            if url_host(u)!=row["hostname"] or not bit(y)&row["target_mask"]: continue
            if str(v.get("status"))!="200" or v.get("mime")!="text/html": continue
            result["potential_witnesses"].append({"timestamp":ts,"original":u,"statuscode":"200",
                "mimetype":"text/html","digest":v.get("digest"),"filename":v.get("filename"),
                "offset":v.get("offset"),"length":v.get("length"),
                "source_collection":v.get("source-coll")})
            result["witness_mask"]|=bit(y)
        result["state"]="potential_witness" if result["witness_mask"] else "unresolved_no_match"
    except (ValueError,TypeError,KeyError,AttributeError):
        result["state"]="invalid_response"
        result["potential_witnesses"]=[];result["witness_mask"]=0
    return result

def original_link(header):
    for m in re.finditer(r'<([^>]+)>\s*;\s*([^<]+)',header or ""):
        if re.search(r'\brel\s*=\s*(?:"original"|original)(?:\s|;|,|$)',m.group(2),re.I):
            return m.group(1)
    return None

def replay_result(provider,row,body,meta):
    h,u,ts,y=capture_row(row)
    r={"hostname":h,"original":u,"requested_timestamp":ts,"year":y,
       "archive_digest":row.get("digest"),"qualification":"review_required",**meta}
    if meta["state"]!="received": return r
    if meta.get("truncated"):
        r["state"]="possibly_truncated";return r
    headers=meta.get("headers",{})
    try:
        dt=parsedate_to_datetime(headers["memento-datetime"])
        if dt.tzinfo is None:raise ValueError("missing timestamp timezone")
        actual=dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
        actual_url=original_link(headers.get("link"))
        if actual!=ts or not actual_url or url_host(actual_url)!=h:
            raise ValueError("replay identity/time differs")
        # Preserve returned original, not the URL chosen by the caller.
        clean_url(actual_url)
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError):
        r["state"]="replay_identity_unresolved";return r
    r.update(actual_timestamp=actual,actual_original=actual_url,
             body_sha256=hashlib.sha256(body).hexdigest())
    if provider=="ia":
        r["source_pointer"]=source_pointer(headers.get("x-archive-src"))
    digest=row.get("digest")
    if isinstance(digest,str) and re.fullmatch(r"[A-Z2-7]{32}",digest):
        r["archive_digest_matches_received_body"]=(base64.b32encode(hashlib.sha1(body).digest()).decode()==digest)
    if headers.get("content-encoding","identity").lower() not in ("","identity"):
        r["state"]="replay_encoded_body_review";return r
    ctype=headers.get("content-type","").lower()
    if "html" not in ctype:
        r["state"]="replay_non_html_review";return r
    text=decode_body(body)
    title=re.search(r"<title[^>]*>(.*?)</title>",text,re.I|re.S)
    r["title_hint"]=title.group(1)[:300] if title else ""
    r["quality_flags"]=[]
    if re.search(r"domain (?:for sale|has expired)|buy this domain|apache.*test page|future home of",text[:100000],re.I):
        r["quality_flags"].append("possible_placeholder_or_parking")
    r["state"]="replay_review"
    return r

def search_result(row,body,meta):
    r={"query":row["query"],"observations":[],"qualification":"not_evaluated",**meta}
    if meta["state"]!="received": return r
    if meta.get("truncated"):
        r["state"]="possibly_truncated";return r
    try:
        for i,v in enumerate(json.loads(body)["response_items"]):
            try:
                y=timestamp_year(v["tstamp"]);u=clean_url(v["originalURL"])
                if y not in YEARS:continue
                r["observations"].append({"hostname":url_host(u),"original_url":u,"observed_year":y,
                    "kind":"historical_fulltext_hit","locator":f"result:{i}","capture_timestamp":v["tstamp"],
                    "title":str(v.get("title",""))[:500],"collection":v.get("collection")})
            except (ValueError,TypeError,KeyError):continue
        r["state"]="search_hits" if r["observations"] else "unresolved_no_match"
    except (ValueError,TypeError,KeyError,AttributeError):
        r["state"]="invalid_response";r["observations"]=[]
    return r

def metadata_result(row,body,meta):
    r={"item":row["item"],"requested_files":row["files"],"qualification":"not_evaluated",**meta}
    if meta["state"]!="received":return r
    if meta.get("truncated"):
        r["state"]="possibly_truncated";return r
    try:
        v=json.loads(body);m=v["metadata"]
        if m.get("identifier")!=row["item"]:raise ValueError("metadata identifier mismatch")
        names={x.get("name"):x for x in v["files"] if isinstance(x,dict)}
        r["matched_files"]=[{k:names[n].get(k) for k in ("name","size","sha1","format","source")}
                            for n in row["files"] if n in names]
        r["file_inventory"]=[{k:x.get(k) for k in ("name","size","sha1","format","source")}
                             for x in names.values() if isinstance(x.get("name"),str) and
                             x["name"].lower().endswith((".arc",".arc.gz",".warc",".warc.gz",".cdx",".cdx.gz",".cdxj",".cdxj.gz"))][:2000]
        r["collection"]=m.get("collection");r["contributor"]=m.get("contributor")
        r["state"]="source_binding" if r["matched_files"] else "source_binding_unresolved"
    except (ValueError,TypeError,KeyError,AttributeError):r["state"]="invalid_response"
    return r

def interpret_action(provider,action,row,body,meta):
    if action=="lookup":return lookup_result(provider,row,body,meta)
    if action=="replay":return replay_result(provider,row,body,meta)
    if action=="search":return search_result(row,body,meta)
    return metadata_result(row,body,meta)

def run_online(store,envelope,job,inp,out,collector,progress):
    from collections import Counter
    from .core import jsonl
    from tempfile import TemporaryDirectory
    from itertools import islice
    rows=[r for _,r in islice(jsonl(inp),51)]
    provider,action=job["provider"],job["action"]
    validate_rows(provider,action,rows)
    if len(rows)!=job["max_requests"] or collector is None or collector.provider!=provider:
        raise ValueError("online job/collector/budget mismatch")
    stats=Counter();stop=False
    with TemporaryDirectory() as t,out.open("wb") as f:
        p=Path(t)
        for n,row in enumerate(rows,1):
            progress("target",n)
            previous=collector.start_target(envelope["job_id"],n)
            if previous and previous.get("record_line")==n:
                r=previous;stats["reused_checkpoint_records"]+=1
            else:
                url,params=request_spec(provider,action,row)
                meta,body=(previous,None) if previous else (
                    ({"state":"deferred_cooldown","requests":0},None) if stop else collector.fetch(url,params))
                r=interpret_action(provider,action,row,body,meta)
                r.update(record_line=n,provider=provider,action=action,
                         request_input=row)
                if body is not None:
                    raw=p/"response";raw.write_bytes(body)
                    r["response_ref"]=store.put(raw)
                if action=="replay" and r["state"]=="replay_review":
                    links=p/"references.jsonl"
                    count=0
                    with links.open("wb") as l:
                        for clue in html_clues(decode_body(body),r["actual_original"],r["year"],
                            r["actual_timestamp"],replay_provider=provider,replay_url=meta.get("requested_url")):
                            l.write(canonical(clue));count+=1
                    r["references_ref"]=store.put(links);r["reference_count"]=count
                collector.finish_target(envelope["job_id"],n,r)
                stats["requests"]+=meta["requests"]
            f.write(canonical(r));stats[r["state"]]+=1
            if r["state"] in {"provider_cooldown","rate_limited"} or r.get("http_status")==503:stop=True
    return dict(stats)
