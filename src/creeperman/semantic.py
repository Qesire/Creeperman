"""Build small query plans from anchor/context or entity metadata.

No network call here. Query words are ranked over distinct source documents,
not raw mention frequency. Preserve the query's target and provenance.
"""
from __future__ import annotations
import math
import re
import sqlite3
import tempfile
from pathlib import Path
from collections import Counter
from .core import canonical,jsonl,host,url_host

STOP=set("the a an and of or to in on for by with from is are was were be as at this that it here home page website web click more link links welcome http https www com org net html index download information about".split())
WORD=re.compile(r"[^\W\d_][\w-]{2,39}",re.UNICODE)

def words(s):
    return {w.casefold() for w in WORD.findall(s) if w.casefold() not in STOP}

def signatures(observations:Path,out:Path,limit:int,nwords:int):
    if not 1<=limit<=100000 or not 1<=nwords<=10:raise ValueError("invalid query budget")
    with tempfile.TemporaryDirectory() as t:
        db=sqlite3.connect(Path(t)/"terms.sqlite")
        db.executescript("""
        CREATE TABLE terms(target TEXT,year INTEGER,doc TEXT,term TEXT,
          PRIMARY KEY(target,year,doc,term)) WITHOUT ROWID;
        CREATE TABLE emitted(query TEXT PRIMARY KEY) WITHOUT ROWID;
        """)
        try:
            for _,r in jsonl(observations):
                h=host(r["hostname"]); u=r.get("original_url") or h
                if r.get("original_url") and url_host(u)!=h:continue
                year=r.get("observed_year")
                if type(year) is not int or not 1996<=year<=2001:continue
                anchor=" ".join(str(r.get(k) or "") for k in ("anchor_text","context_before","context","title","entity_name","project_title","acronym"))
                if not anchor.strip():continue
                doc=str(r.get("source_original_url") or r.get("message_id") or r.get("locator") or "")
                if not doc:continue
                db.executemany("INSERT OR IGNORE INTO terms VALUES(?,?,?,?)",
                               [(u,year,doc,w) for w in words(anchor)])
            db.commit()
            # Document frequency over target/year descriptors, not repeated
            # mentions within the same descriptor.
            db.executescript("""CREATE TEMP TABLE df AS
              SELECT term,count(*) AS n FROM (SELECT DISTINCT target,year,term FROM terms) GROUP BY term;
              CREATE INDEX df_idx ON df(term);""")
            n=db.execute("SELECT count(*) FROM (SELECT DISTINCT target,year FROM terms)").fetchone()[0]
            from itertools import groupby
            q="""SELECT t.target,t.year,t.term,count(*) AS tf,df.n FROM terms t JOIN df USING(term)
                 GROUP BY t.target,t.year,t.term ORDER BY t.target,t.year"""
            emitted=0
            with out.open("xb") as f:
                for (target,year),rows in groupby(db.execute(q),key=lambda r:(r[0],r[1])):
                    ranked=sorted(rows,key=lambda r:(-(1+math.log(r[3]))*(math.log((1+n)/(1+r[4]))+1),r[2]))
                    terms=[r[2] for r in ranked[:nwords]]
                    if len(terms)<2:continue
                    query=" ".join(terms)[:200]
                    if db.execute("INSERT OR IGNORE INTO emitted VALUES(?)",(query,)).rowcount!=1:continue
                    f.write(canonical({"query":query,"target":target,"hint_year":year,
                                       "method":"distinct-document-tfidf-v1","terms":terms}))
                    emitted+=1
                    if emitted>=limit:break
        finally:db.close()
