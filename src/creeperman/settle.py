"""Score externally reviewed, explicit website-year decisions against frozen B.

A decision is not inferred from CDX, an anchor, a digest or registration.
Replay decisions must bind to an actual catalog replay and stored bytes;
other evidence types need a local reviewed ledger with source locator/hash.
"""
from __future__ import annotations
import json,sqlite3,tempfile,re
from pathlib import Path
from collections import Counter
from decimal import Decimal
from .core import (YEARS,bit,host,url_host,timestamp_year,sha,weights,audit_binding,
                   annual_masks,canonical,jsonl,write_json)

def settle(baseline,audit,model,decisions,out,*,rule_version,db_path=None,store=None):
    if out.exists():raise FileExistsError(out)
    binding,authority_rows=audit_binding(audit,model)
    if baseline.name!=binding["baseline_id"]:raise ValueError("baseline name mismatch")
    w=weights(model)
    decision_hash=sha(decisions)
    checked_sources={}
    out.parent.mkdir(parents=True,exist_ok=True)
    catalog=sqlite3.connect(db_path) if db_path else None
    try:
        with tempfile.TemporaryDirectory(prefix=".settle-",dir=out.parent) as t:
            p=Path(t);db=sqlite3.connect(p/"keys.sqlite")
            try:
                db.execute("CREATE TABLE q(h TEXT,y INTEGER, PRIMARY KEY(h,y)) WITHOUT ROWID")
                with (p/"reviewed_decisions.jsonl").open("wb") as f:
                    for n,r in jsonl(decisions):
                        if r.get("validation_status")!="verified_web_year":continue
                        if r.get("authority")!=binding["id"] or r.get("rule_version")!=rule_version:
                            raise ValueError(f"decision version mismatch at {n}")
                        h=host(r["hostname"]);y=r["year"]
                        if h!=r["hostname"] or type(y) is not int or y not in YEARS or not r.get("reviewer") or not r.get("reason") or not r.get("evidence_id"):
                            raise ValueError(f"incomplete reviewed decision {n}")
                        if r.get("original_url") and url_host(r["original_url"])!=h:raise ValueError("decision identity mismatch")
                        if r.get("evidence_type")=="archive_replay":
                            if catalog is None or store is None:raise ValueError("replay decisions require catalog and store")
                            row=catalog.execute("""SELECT r.record,m.authority FROM results r JOIN manifests m ON m.hash=r.manifest_hash
                              WHERE r.manifest_hash=? AND r.ordinal=?""",(r["manifest_hash"],r["ordinal"])).fetchone()
                            if not row or row[1]!=binding["id"]:raise ValueError("unbound replay")
                            a=json.loads(row[0])
                            if a["state"]!="replay_review" or a["hostname"]!=h or a["year"]!=y or url_host(a["actual_original"])!=h or timestamp_year(a["actual_timestamp"])!=y:
                                raise ValueError("reviewed replay does not bind host/year")
                            tmp=p/"verify-body"
                            store.materialize(a["response_ref"],tmp)
                            if sha(tmp)!=a["body_sha256"]:raise ValueError("body digest mismatch")
                            tmp.unlink()
                        else:
                            if r.get("evidence_type") not in ("historical_directory","historical_graph","original_archive_record","reviewed_original_material"):
                                raise ValueError("unsupported evidence type")
                            if not r.get("record_locator") or not r.get("date_semantics") or not re.fullmatch(r"[0-9a-f]{64}",r.get("source_sha256","")):
                                raise ValueError("offline reviewed decision missing locator/date/hash")
                            source=(decisions.parent/Path(r["source_path"])).resolve()
                            if source not in checked_sources:
                                checked_sources[source]=sha(source)
                            if checked_sources[source]!=r["source_sha256"]:
                                raise ValueError("offline source hash mismatch")
                        db.execute("INSERT OR IGNORE INTO q VALUES(?,?)",(h,y))
                        f.write(canonical(r))
                db.commit()
                cur=iter(db.execute("SELECT h,y FROM q ORDER BY h,y"))
                current=next(cur,None)
                counts=Counter();overlap=Counter();tld=Counter()
                from contextlib import ExitStack
                with ExitStack() as stack:
                    fs={y:stack.enter_context((p/f"{y}.txt").open("w",encoding="ascii",newline="\n")) for y in YEARS}
                    def emit(h,y):
                        fs[y].write(h+"\n");counts[y]+=1;tld[h.rsplit(".",1)[-1]]+=1
                    for h,mask in annual_masks(baseline,authority_rows):
                        while current and current[0]<h:
                            emit(*current);current=next(cur,None)
                        while current and current[0]==h:
                            _,y=current
                            if mask&bit(y):overlap[y]+=1
                            else:emit(h,y)
                            current=next(cur,None)
                    while current:
                        emit(*current);current=next(cur,None)
                if sha(decisions)!=decision_hash:raise ValueError("decision ledger changed")
                for source,digest in checked_sources.items():
                    if sha(source)!=digest:raise ValueError("reviewed source changed")
                eed=sum((Decimal(n)*w.get(t,Decimal(0)) for t,n in tld.items()),Decimal(0))
                report={"schema":"reviewed-delta-v1","authority":binding,"rule_version":rule_version,
                        "scope":"locally adjudicated core-year delta; not organizer acceptance",
                        "new_by_year":{str(y):counts[y] for y in YEARS},
                        "baseline_overlap_by_year":{str(y):overlap[y] for y in YEARS},
                        "local_reviewed_new_eed":str(eed),
                        "minimum_increment":str(Decimal(binding["baseline_eed"])*Decimal(".01")),
                        "meets_reference_minimum":eed>=Decimal(binding["baseline_eed"])*Decimal(".01"),
                        "decisions_sha256":decision_hash,"files":{str(y):sha(p/f"{y}.txt") for y in YEARS}}
                write_json(p/"report.json",report)
            finally:db.close()
            (p/"keys.sqlite").unlink()
            p.rename(out)
        return report
    finally:
        if catalog:catalog.close()
