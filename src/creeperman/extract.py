"""Bounded static discovery adapters. Never execute archived code or fetch links.

Every emitted year is a clue date, not evidence that the referenced host
responded in that year. Original files remain the source of truth.
"""
from __future__ import annotations
import gzip
import json
import re
import tarfile
import zipfile
import xml.etree.ElementTree as ET
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime, getaddresses
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from pathlib import Path
from .core import host, url_host

FORMATS = ("mbox","usenet-zip","webkb-tar","jisc","dmoz-rdf","pages-jsonl","text-jsonl","warc")
MAX_BODY = 16 * 1024 * 1024
URL_RE = re.compile(r"""https?://[^\s<>"'\x00-\x1f]+|(?<![\w@.])www\.[a-z0-9][a-z0-9.-]*\.[a-z]{2,63}(?:/[^\s<>"']*)?""", re.I)
REPLAY = {"ia":"web.archive.org","arquivo":"arquivo.pt"}
ATTRS = {
    "a":("href",),"area":("href",),"img":("src","longdesc"),
    "script":("src",),"frame":("src",),"iframe":("src",),"link":("href",),
    "object":("data","codebase"),"embed":("src",),"form":("action",),
    "body":("background",),"input":("src",),"source":("src",),
}

def clean_url(u):
    if not isinstance(u,str) or len(u)>16384 or any(ord(c)<32 or c.isspace() for c in u):
        raise ValueError("unsafe URL spelling")
    url_host(u)
    return u

def clue(url, year, kind, loc, **detail):
    url=clean_url(url)
    return {"hostname":url_host(url),"original_url":url,"observed_year":year,
            "kind":kind,"locator":loc,**detail}

def text_clues(text, year, loc):
    for m in URL_RE.finditer(text):
        raw=m.group()
        u=raw.rstrip(".,;:!?")
        # Only remove unmatched closing punctuation, not valid URL syntax.
        while u.endswith(")") and u.count(")")>u.count("("):
            u=u[:-1]
        if u.lower().startswith("www."):
            # Bare www is observed; the scheme is only a query hypothesis.
            try:
                h=host(u.split("/",1)[0])
            except ValueError:
                continue
            yield {"hostname":h,"original_url":None,"observed_year":year,
                   "kind":"literal_www","locator":loc,"raw_reference":raw,
                   "context":text[max(0,m.start()-100):m.end()+100]}
        else:
            try:
                yield clue(u,year,"text_url",loc,raw_reference=raw,
                           context=text[max(0,m.start()-100):m.end()+100])
            except ValueError:
                pass

def unwrap(value, provider, replay_url=None):
    """Only unwrap recognized archive paths in declared replay context."""
    if not provider or provider not in REPLAY:
        return value, None
    p=urlsplit(value)
    if not p.netloc and value.startswith("/") and replay_url:
        value=urljoin(replay_url,value)
        p=urlsplit(value)
    if p.hostname!=REPLAY[provider]:
        return value,None
    path=p.path
    prefix=r"/web/" if provider=="ia" else r"/(?:wayback/|noFrame/replay/)"
    m=re.match(prefix+r"([0-9]{1,14})([a-z]{2}_)?/(https?://.+)",path,re.I)
    if not m:
        return value,None
    u=m.group(3)+("?" + p.query if p.query else "")
    return u,{"replay_timestamp":m.group(1),"modifier":m.group(2)}

class References(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs=[]
        self.base=None
        self.anchors=[]
        self.text=""
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="base" and self.base is None and a.get("href"):
            self.base=a["href"]
        if tag=="a" and self.anchors:
            self.anchors.clear()
        for attr in ATTRS.get(tag,()):
            if a.get(attr):
                r={"tag":tag,"attribute":attr,"raw_reference":a[attr],
                   "position":list(self.getpos()),"anchor_text":"",
                   "context_before":self.text[-200:]}
                self.refs.append(r)
                if tag=="a" and attr=="href":
                    self.anchors.append(r)
        if tag in ("img","source") and a.get("srcset") and "data:" not in a["srcset"].lower():
            for part in a["srcset"].split(","):
                p=part.strip().split()
                if p:
                    self.refs.append({"tag":tag,"attribute":"srcset","raw_reference":p[0],
                        "position":list(self.getpos()),"anchor_text":"","context_before":self.text[-200:]})
    def handle_endtag(self,tag):
        if tag=="a":
            self.anchors.clear()
    def handle_data(self,data):
        self.text=(self.text+data)[-400:]
        for r in self.anchors:
            r["anchor_text"]=(r["anchor_text"]+data)[:500]

def html_clues(body, source_url, year, loc, *, replay_provider=None, replay_url=None):
    clean_url(source_url)
    p=References()
    p.feed(body)
    p.close()
    base=source_url
    if p.base:
        try:
            b,_=unwrap(p.base,replay_provider,replay_url)
            base=clean_url(urljoin(source_url,b))
        except ValueError:
            pass
    for r in p.refs:
        raw=r["raw_reference"].strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            value,rewrite=unwrap(raw,replay_provider,replay_url)
            resolved=urljoin(base,value)
            # Unrecognized replay UI and same archive URLs in replay context
            # are not promoted into candidate hosts.
            if replay_provider and urlsplit(resolved).hostname==REPLAY.get(replay_provider):
                continue
            role="navigation" if r["tag"] in ("a","area") else "embedded_or_form"
            yield clue(resolved,year,"html_reference",loc,source_original_url=source_url,
                       source_observed_year=year,reference_role=role,rewrite=rewrite,**r)
        except (ValueError,TypeError):
            continue

def decode_body(b, charset=None):
    for encoding in (charset,"utf-8","windows-1252"):
        if not encoding: continue
        try:
            return b.decode(encoding)
        except (UnicodeDecodeError,LookupError):
            pass
    return b.decode("utf-8",errors="replace")

def message_clues(raw, loc):
    msg=BytesParser(policy=policy.default).parsebytes(raw)
    date=msg.get("Date")
    year=None
    try:
        dt=parsedate_to_datetime(str(date))
        if dt.tzinfo is not None:
            year=dt.year
    except (ValueError,TypeError,OverflowError):
        pass
    mid=str(msg.get("Message-ID") or "")[:512]
    metadata={"message_id":mid,"date_header":str(date or "")[:256],
              "date_semantics":"message_date_header_not_capture"}
    for _,addr in getaddresses([str(msg.get("From",""))]):
        if "@" in addr:
            try:
                h=host(addr.rsplit("@",1)[-1])
            except ValueError:
                continue
            yield {"hostname":h,"original_url":None,"observed_year":year,
                   "kind":"email_domain_hint","locator":loc,**metadata}
    for part in msg.walk():
        if part.get_content_disposition()=="attachment" or part.get_content_type() not in ("text/plain","text/html"):
            continue
        b=part.get_payload(decode=True)
        if not isinstance(b,bytes): continue
        for c in text_clues(decode_body(b,part.get_content_charset()),year,loc):
            yield {**c,**metadata}

def mbox_messages(f, member, *, deja=False):
    # Deja exports have numeric From IDs and unescaped body From lines.
    separator=re.compile(rb"^From -?[0-9]+\s*$") if deja else re.compile(
        rb"^From \S+ (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) ")
    chunks=[]; size=0; n=0; oversized=False
    for line in f:
        if separator.match(line):
            if n or chunks or oversized:
                if oversized:
                    yield (f"{member}:message:{n}",None)
                elif chunks:
                    yield (f"{member}:message:{n}",b"".join(chunks))
            n+=1; chunks=[]; size=0; oversized=False
            continue
        size+=len(line)
        if size>MAX_BODY:
            oversized=True; chunks=[]
        elif not oversized:
            chunks.append(line)
    if chunks or oversized:
        yield (f"{member}:message:{n}",None if oversized else b"".join(chunks))

def page_rows(path, fmt):
    if fmt=="webkb-tar":
        with tarfile.open(path,"r|*") as tf:
            for member in tf:
                if not member.isfile() or member.size>MAX_BODY:
                    continue
                encoded=member.name.rsplit("/",1)[-1]
                url=encoded.replace("^","/")
                try:
                    clean_url(url)
                except ValueError:
                    continue
                f=tf.extractfile(member)
                if f is None: continue
                msg=BytesParser(policy=policy.default).parsebytes(f.read(MAX_BODY+1))
                body=msg.get_payload(decode=True)
                if not isinstance(body,bytes): continue
                yield {"url":url,"year":1997,"locator":member.name,
                       "html":decode_body(body,msg.get_content_charset()),
                       "date_semantics":"CMU_collection_month_1997_01"}
    elif fmt=="warc":
        from warcio.archiveiterator import ArchiveIterator
        with path.open("rb") as f:
            for n,rec in enumerate(ArchiveIterator(f),1):
                if rec.rec_type!="response" or rec.http_headers is None: continue
                url=rec.rec_headers.get_header("WARC-Target-URI")
                date=rec.rec_headers.get_header("WARC-Date")
                try:
                    from datetime import datetime
                    dt=datetime.fromisoformat(date.replace("Z","+00:00"))
                    if dt.tzinfo is None: continue
                    clean_url(url)
                except (ValueError,AttributeError,TypeError): continue
                if "html" not in (rec.http_headers.get_header("Content-Type") or "").lower():
                    continue
                body=rec.content_stream().read(MAX_BODY+1)
                if len(body)>MAX_BODY: continue
                yield {"url":url,"year":dt.year,"locator":f"record:{n}",
                       "html":decode_body(body),"capture_date":date,
                       "date_semantics":"WARC-Date","record_id":rec.rec_headers.get_header("WARC-Record-ID"),
                       "capture_status":rec.http_headers.get_statuscode()}
    else:
        opener=gzip.open if path.suffix==".gz" else open
        with opener(path,"rt",encoding="utf-8") as f:
            for n,line in enumerate(f,1):
                if not line.strip(): continue
                r=json.loads(line)
                y=r.get("observed_year")
                if y is not None and (type(y) is not int or not 1<=y<=9999):
                    raise ValueError(f"invalid observed year at row {n}")
                yield {"url":r["source_original_url"],"year":y,"locator":r.get("locator",f"line:{n}"),
                       "html":r["html"],"date_semantics":r.get("date_semantics","declared_observation"),
                       "replay_provider":r.get("replay_provider"),"replay_url":r.get("replay_url")}

def extract(path:Path,fmt:str):
    if fmt in ("mbox","usenet-zip"):
        def process(f,name,deja):
            for loc,b in mbox_messages(f,name,deja=deja):
                if b is None:
                    yield None,f"oversized message: {loc}"
                else:
                    try:
                        for row in message_clues(b,loc): yield row,None
                    except (ValueError,TypeError,UnicodeError) as exc:
                        yield None,f"message parse: {loc}: {type(exc).__name__}"
        if fmt=="mbox":
            opener=gzip.open if path.suffix==".gz" else open
            with opener(path,"rb") as f:
                yield from process(f,"mbox",False)
        else:
            with zipfile.ZipFile(path) as z:
                for member in z.infolist():
                    if member.is_dir() or not member.filename.lower().endswith((".mbox",".txt")): continue
                    with z.open(member) as f:
                        yield from process(f,member.filename,True)
    elif fmt in ("webkb-tar","pages-jsonl","warc"):
        for p in page_rows(path,fmt):
            try:
                detail={k:p[k] for k in ("capture_date","record_id","capture_status") if p.get(k) is not None}
                yield clue(p["url"],p["year"],"source_page_hint",p["locator"],
                           date_semantics=p["date_semantics"],**detail),None
                for row in html_clues(p["html"],p["url"],p["year"],p["locator"],
                        replay_provider=p.get("replay_provider"),replay_url=p.get("replay_url")):
                    yield row,None
            except (ValueError,TypeError) as exc:
                yield None,f"page {p['locator']}: {exc}"
    elif fmt=="jisc":
        opener=gzip.open if path.suffix==".gz" else open
        with opener(path,"rt",encoding="utf-8") as f:
            for n,line in enumerate(f,1):
                try:
                    key,count=line.strip().split("\t")
                    y,s,t=key.split("|")
                    year=int(y); count=int(count)
                    if not 1996<=year<=2010 or count<1: raise ValueError("invalid JISC row")
                    for role,h in (("source",s),("target",t)):
                        yield {"hostname":host(h),"original_url":None,"observed_year":year,
                               "kind":"jisc_"+role+"_hint","locator":f"line:{n}",
                               "source_hostname":s,"target_hostname":t,"link_count":count,
                               "date_semantics":"source_capture_year"},None
                except ValueError as exc:
                    yield None,f"JISC line {n}: {exc}"
    elif fmt=="dmoz-rdf":
        # Clear completed elements so the RDF need not be held in memory.
        opener=gzip.open if path.suffix==".gz" else open
        with opener(path,"rb") as f:
            stack=[]; n=0
            for event,e in ET.iterparse(f,events=("start","end")):
                if event=="start":
                    stack.append(e); continue
                if e.tag.split("}")[-1]=="ExternalPage":
                    n+=1
                    url=next((v for k,v in e.attrib.items() if k.split("}")[-1]=="about"),None)
                    if url:
                        try: yield clue(url,None,"directory_url_undated",f"ExternalPage:{n}"),None
                        except ValueError as exc: yield None,str(exc)
                stack.pop()
                if stack: stack[-1].remove(e)
                e.clear()
    elif fmt=="text-jsonl":
        opener=gzip.open if path.suffix==".gz" else open
        with opener(path,"rt",encoding="utf-8") as f:
            for n,line in enumerate(f,1):
                if not line.strip(): continue
                r=json.loads(line); y=r.get("observed_year")
                if y is not None and (type(y) is not int or not 1<=y<=9999):
                    raise ValueError(f"invalid date at {n}")
                for row in text_clues(r["text"],y,r.get("locator",f"line:{n}")):
                    yield row,None
    else:
        raise ValueError("unsupported extraction format")
