"""Bounded routing, follow-up and manifest publication.

No default broadcast. PANDORA/Webarchiv remain manual routes until a
machine-access contract is bound. The second archive is a separate plan.
"""
from __future__ import annotations
import json
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path
from .core import ALL, RULE, VERSION, canonical, host, jsonl, sha, url_host, bit, timestamp_year
from .jobs import JOB_SCHEMA, job_id
from .online import ACTIONS, validate_rows, source_pointer

def publish(store,provider,action,rows,authority,round_id):
    if not isinstance(round_id,str) or not 1<=len(round_id)<=64 or not authority:
        raise ValueError("explicit authority and round required")
    validate_rows(provider,action,rows)
    with tempfile.TemporaryDirectory() as t:
        p=Path(t)/"targets.jsonl"
        p.write_bytes(b"".join(canonical(r) for r in rows))
        job={"schema":JOB_SCHEMA,"operation":"online","version":VERSION,"policy":RULE,
             "provider":provider,"action":action,"authority":authority,"round_id":round_id,
             "max_requests":len(rows),"input":store.put(p)}
        return {"job_id":job_id(job),"operation":"online","provider":provider,
                "action":action,"job_ref":store.put_json(job)}

def online_jobs(store,rows,provider,action,authority,round_id,limit,batch_size):
    if not 1<=batch_size<=50 or not 1<=limit<=100000:
        raise ValueError("batch size 1..50, explicit limit 1..100000")
    batch=[]
    for i,row in enumerate(rows):
        if i>=limit:break
        batch.append(row)
        if len(batch)==batch_size:
            yield publish(store,provider,action,batch,authority,round_id);batch=[]
    if batch:yield publish(store,provider,action,batch,authority,round_id)

def route(h):
    if h.endswith(".pt"):return ["arquivo","ia"]
    # .au and .cz are meaningful manual leads, not fabricated API adapters.
    return ["ia"]

def routed_jobs(store,census_dir,limit,batch_size,round_id,offset=0,include_undated=False):
    if not 1<=batch_size<=50 or not 1<=limit<=100000 or offset<0:
        raise ValueError("invalid bounded window")
    report=json.loads((census_dir/"report.json").read_text(encoding="utf-8"))
    p=census_dir/"opportunities.jsonl"
    if report["schema"]!="census-v1" or sha(p)!=report["output_sha256"]["opportunities.jsonl"]:
        raise ValueError("invalid census snapshot")
    authority=report["authority"]["id"]
    batches=defaultdict(list);accepted=skipped=0
    for dated in ((True,False) if include_undated else (True,)):
        for _,r in jsonl(p):
            hinted=r["hinted_missing_mask"]
            if bool(hinted)!=dated:continue
            mask=hinted if dated else r["missing_mask"]
            if not mask:continue
            if skipped<offset:skipped+=1;continue
            h=host(r["hostname"])
            if h!=r["hostname"] or type(mask) is not int or mask&~ALL or mask&(r["baseline_mask"]|r.get("local_qualified_mask",0)):
                raise ValueError("invalid census target")
            original=next((s["sample_url"] for s in r["sources"] if s.get("sample_url") and url_host(s["sample_url"])==h),None)
            primary=route(h)[0]
            target={"hostname":h,"target_mask":mask,"original_url":original,
                    "census_sha256":sha_value(report),
                    "manual_route_hint":"PANDORA" if h.endswith(".au") else "Webarchiv.cz" if h.endswith(".cz") else None}
            batches[primary].append(target);accepted+=1
            if len(batches[primary])==batch_size:
                yield publish(store,primary,"lookup",batches[primary],authority,round_id);batches[primary]=[]
            if accepted>=limit:break
        if accepted>=limit:break
    for provider,rows in sorted(batches.items()):
        if rows:yield publish(store,provider,"lookup",rows,authority,round_id)

def sha_value(data):
    import hashlib
    return hashlib.sha256(canonical(data)).hexdigest()

def followup_rows(db_path,authority,mode,provider,limit):
    """Generate new explicitly bounded plans from completed catalog results.

    The catalog retains attempts; a previous ambiguous or failed action is
    NOT automatically repeated. Explicit new round/manual plans are needed.
    """
    if not 1<=limit<=100000:raise ValueError("invalid limit")
    db=sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro",uri=True)
    try:
        # All prior attempts for the authority are examined once. For large
        # production inventories use bounded cohorts per authority/run.
        # SQLite handles joins; output dedup is bounded by the requested limit.
        if mode=="replay":
            query="""SELECT w.hostname,w.timestamp,w.original,w.digest,w.provider
                FROM witnesses w
                WHERE w.authority=? AND w.provider IN (?,?)
                AND NOT EXISTS(SELECT 1 FROM online_attempts a
                   WHERE a.authority=w.authority AND a.provider=?
                   AND a.action='replay' AND a.hostname=w.hostname
                   AND a.timestamp=w.timestamp AND a.original=w.original)
                ORDER BY w.hostname,w.year,w.timestamp,w.original"""
            seen=set()
            for h,ts,u,d,prov in db.execute(query,(authority,provider,provider+"-cdx",provider)):
                key=(h,timestamp_year(ts))
                if key in seen:continue
                seen.add(key)
                yield {"hostname":h,"timestamp":ts,"original":u,"digest":d}
                if len(seen)>=limit:return
        elif mode=="metadata":
            seen=set()
            for (raw,) in db.execute("""SELECT r.record FROM results r JOIN manifests m ON m.hash=r.manifest_hash
                WHERE m.authority=? AND m.operation='online' AND json_extract(r.record,'$.action')='replay'
                AND json_extract(r.record,'$.provider')='ia'
                AND json_extract(r.record,'$.source_pointer.item') IS NOT NULL ORDER BY r.manifest_hash,r.ordinal""",(authority,)):
                s=json.loads(raw)["source_pointer"];item=s["item"]
                if item in seen:continue
                if db.execute("SELECT 1 FROM online_attempts WHERE authority=? AND action='metadata' AND item=? LIMIT 1",(authority,item)).fetchone():continue
                files=[x[0] for x in db.execute("""SELECT DISTINCT json_extract(r.record,'$.source_pointer.file') FROM results r JOIN manifests m ON m.hash=r.manifest_hash
                    WHERE m.authority=? AND json_extract(r.record,'$.source_pointer.item')=? LIMIT 500""",(authority,item)) if x[0]]
                seen.add(item);yield {"item":item,"files":files}
                if len(seen)>=limit:return
        elif mode=="fallback":
            seen=set()
            for (raw,) in db.execute("""SELECT r.record FROM results r JOIN manifests m ON m.hash=r.manifest_hash
                WHERE m.authority=? AND m.operation='online' AND json_extract(r.record,'$.action')='lookup'
                AND json_extract(r.record,'$.provider')!=? ORDER BY r.manifest_hash,r.ordinal""",(authority,provider)):
                r=json.loads(raw);h=r["hostname"]
                # Only a documented TLD route warrants default fallback.
                if provider not in route(h)[1:] or r["state"] not in ("potential_witness","unresolved_no_match"):continue
                missing=r["target_mask"]&~r["witness_mask"]
                if not missing or h in seen:continue
                if db.execute("SELECT 1 FROM online_attempts WHERE authority=? AND provider=? AND action='lookup' AND hostname=? LIMIT 1",(authority,provider,h)).fetchone():continue
                seen.add(h)
                yield {"hostname":h,"target_mask":missing,"original_url":r["request_input"].get("original_url")}
                if len(seen)>=limit:return
        else:raise ValueError("unknown follow-up")
    finally:db.close()
