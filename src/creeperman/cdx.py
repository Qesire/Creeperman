"""IA CDX transport and legacy bounded discovery for observed hostnames.

Not a complete index scan; no result is ever an assertion of absence.
The collector is single active process per provider budget. No IP rotation.
"""
from __future__ import annotations

import email.utils
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .core import ALL, YEARS, bit, host, timestamp_year, url_host

ENDPOINT = "https://web.archive.org/cdx/search/cdx"
MAX_RESPONSE = 2 * 1024 * 1024
FIELDS = ["timestamp","original","statuscode","mimetype","digest","length"]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Collector:
    """Persist request pacing/cooldown across same-state-dir restarts.

    Use one active provider collector in the entire deployment, including
    across regions. This SQLite state is not a distributed limiter.
    """
    def __init__(self, state: Path, interval: float, agent: str):
        if not 2.5 <= interval <= 3600 or not agent or "\r" in agent or "\n" in agent:
            raise ValueError("set a descriptive agent and interval >=2.5 seconds")
        self.state=state
        self.interval=interval
        self.agent=agent
        self.opener=build_opener(NoRedirect)
        state.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(state) as db:
            db.execute("CREATE TABLE IF NOT EXISTS pace (id INTEGER PRIMARY KEY, next REAL NOT NULL)")
            db.execute("INSERT OR IGNORE INTO pace VALUES(1,0)")
            db.execute("""CREATE TABLE IF NOT EXISTS checkpoint(
              job_id TEXT, ordinal INTEGER, state TEXT NOT NULL, record TEXT,
              PRIMARY KEY(job_id,ordinal)) WITHOUT ROWID""")

    def start_target(self, job, ordinal):
        with sqlite3.connect(self.state) as db:
            cur=db.execute("INSERT OR IGNORE INTO checkpoint VALUES(?,?,'inflight',NULL)",(job,ordinal))
            if cur.rowcount==1:
                return None
            state,record=db.execute("SELECT state,record FROM checkpoint WHERE job_id=? AND ordinal=?",(job,ordinal)).fetchone()
            if state=="complete":
                return json.loads(record)
            return {"state":"ambiguous_previous_attempt","requests":0}

    def finish_target(self, job, ordinal, record):
        with sqlite3.connect(self.state) as db:
            db.execute("UPDATE checkpoint SET state='complete',record=? WHERE job_id=? AND ordinal=?",
                       (json.dumps(record,sort_keys=True),job,ordinal))

    def reserve(self):
        # Don't make a task sleep through extended cooldown.
        with sqlite3.connect(self.state, timeout=30, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            nxt=db.execute("SELECT next FROM pace WHERE id=1").fetchone()[0]
            now=time.time()
            if nxt-now>max(5.0,self.interval):
                db.rollback()
                return False
            due=max(now,nxt)
            db.execute("UPDATE pace SET next=? WHERE id=1",(due+self.interval,))
            db.commit()
        time.sleep(max(0,due-time.time()))
        return True

    def cooldown(self, header):
        delay=60.0
        if header:
            try:
                delay=max(delay,float(header))
            except ValueError:
                try:
                    dt=email.utils.parsedate_to_datetime(header)
                    delay=max(delay,dt.timestamp()-time.time())
                except (ValueError,TypeError,OverflowError):
                    pass
        with sqlite3.connect(self.state) as db:
            db.execute("UPDATE pace SET next=max(next,?) WHERE id=1",(time.time()+delay,))

    def request(self, params):
        if not self.reserve():
            return {"state":"provider_cooldown","requests":0},None
        url=ENDPOINT+"?"+urlencode(params,doseq=True)
        req=Request(url,headers={"User-Agent":self.agent,"Accept":"application/json"})
        try:
            with self.opener.open(req,timeout=30) as r:
                body=r.read(MAX_RESPONSE+1)
                return {"state":"received" if r.status==200 else "http_error","requests":1,"http_status":r.status,
                        "truncated":len(body)>MAX_RESPONSE},body[:MAX_RESPONSE]
        except HTTPError as e:
            with e:
                body=e.read(MAX_RESPONSE+1)
                retry=e.headers.get("Retry-After")
                if e.code in {429,503}:
                    self.cooldown(retry)
                return {"state":"rate_limited" if e.code==429 else "http_error",
                        "requests":1,"http_status":e.code,"retry_after":retry,
                        "truncated":len(body)>MAX_RESPONSE},body[:MAX_RESPONSE]
        except (URLError,TimeoutError,OSError) as e:
            return {"state":"transient_failure","requests":1,"error_type":type(e).__name__},None


def query_params(row):
    h=host(row["hostname"])
    if h!=row["hostname"]:
        raise ValueError("noncanonical target")
    mask=row["target_mask"]
    if type(mask) is not int or not 0<mask<=ALL:
        raise ValueError("invalid year mask")
    original=row.get("original_url")
    if original and url_host(original)!=h:
        raise ValueError("original URL does not identify target")
    years=[y for y in YEARS if mask&bit(y)]
    # Canonical keys may merge www, so ask for original-host filtering
    # and still verify original locally. No collapse or subdomain expansion.
    pattern=r"(?i)^https?://"+re.escape(h)+r"(?::[0-9]+)?(?:[/\?#]|$).*"
    return {"url":original or "http://"+h+"/",
            "matchType":"exact" if original else "host",
            "from":f"{min(years)}0101000000","to":f"{max(years)}1231235959",
            "filter":["original:"+pattern,"statuscode:200","mimetype:text/html"],
            "fl":",".join(FIELDS),"output":"json","limit":50,"showResumeKey":"true"}


def annual_params(hostname, year):
    """A single calendar year, every path on one exact hostname, one index block per page."""
    if type(year) is not int or year not in YEARS:
        raise ValueError("expected a core target year")
    params = query_params({"hostname": hostname, "target_mask": bit(year)})
    del params["limit"], params["showResumeKey"]
    return {**params, "pageSize": 1}


def interpret(row, body, meta):
    """Retain a narrow set of metadata witnesses; never auto-qualify."""
    result={"hostname":row["hostname"],"target_mask":row["target_mask"],
            "query_scope_complete":False,"potential_witnesses":[],
            "witness_mask":0,"qualification":"not_evaluated",**meta}
    if meta["state"]!="received":
        return result
    if meta.get("truncated"):
        result["state"]="possibly_truncated"
        return result
    try:
        data=json.loads(body)
        if data==[]:
            result["state"]="unresolved_no_match"
            return result
        if not isinstance(data,list) or not data or not isinstance(data[0],list):
            raise ValueError("missing CDX header")
        header=data[0]
        if not all(k in header for k in FIELDS):
            raise ValueError("unexpected CDX header")
        for vals in data[1:]:
            # Resume marker and malformed rows are not captures.
            if not isinstance(vals,list) or len(vals)!=len(header):
                continue
            r=dict(zip(header,vals))
            try:
                year=timestamp_year(r["timestamp"])
                if url_host(r["original"])!=row["hostname"] or not bit(year)&row["target_mask"]:
                    continue
                if str(r["statuscode"])!="200" or r["mimetype"]!="text/html":
                    continue
            except (ValueError,TypeError,KeyError):
                continue
            result["potential_witnesses"].append(r)
            result["witness_mask"]|=bit(year)
        result["state"]="potential_witness" if result["witness_mask"] else "unresolved_no_match"
    except (ValueError,TypeError,KeyError,AttributeError):
        result["state"]="invalid_response"
    return result
