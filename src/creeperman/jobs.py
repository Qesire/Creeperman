"""Small job/manifest contracts and bounded batch admission."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from .core import ALL, RULE, VERSION, canonical, host, jsonl, sha, url_host
from .store import Store

JOB_SCHEMA = "creeperman-job-v1"
RESULT_SCHEMA = "creeperman-result-v1"


def job_id(job):
    return hashlib.sha256(canonical(job)).hexdigest()


def discovery_job(store: Store, path: Path, *, source_id: str, origin_family: str, fmt: str):
    if not source_id or not origin_family:
        raise ValueError("source and historical observation family required")
    if "commoncrawl" in origin_family.lower().replace(" ", "").replace("-", ""):
        raise ValueError("Common Crawl candidate corpus excluded")
    if fmt not in {"hosts","urls","observations","cdxj"}:
        raise ValueError("unsupported source format")
    job = {"schema":JOB_SCHEMA, "operation":"discover", "version":VERSION,
        "policy":RULE, "source_id":source_id,"origin_family":origin_family,
        "format":fmt,"gzip":path.suffix==".gz","input":store.put(path)}
    return {"job_id":job_id(job), "operation":"discover", "job_ref":store.put_json(job)}


def verification_jobs(store: Store, census_dir: Path, *, limit: int, batch_size: int,
                      include_undated=False):
    """Admit a bounded cohort; one possible CDX request per exact host.
    Input is produced by the offline census; never expands a domain subtree.
    """
    if not 1 <= batch_size <= 500 or limit < 1:
        raise ValueError("positive limit and batch size 1..500 required")
    report = json.loads((census_dir/"report.json").read_text(encoding="utf-8"))
    if report["schema"] != "census-v1":
        raise ValueError("incompatible census")
    path = census_dir/"opportunities.jsonl"
    if sha(path) != report["output_sha256"]["opportunities.jsonl"]:
        raise ValueError("census opportunity fingerprint mismatch")
    authority = report["authority"]["id"]
    snapshot = sha(census_dir/"report.json")
    emitted, batch = 0, []
    def publish(rows):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"targets.jsonl"
            with p.open("wb") as f:
                for row in rows:
                    f.write(canonical(row))
            job={"schema":JOB_SCHEMA,"operation":"verify","version":VERSION,
                 "policy":RULE,"provider":"ia-cdx","authority":authority,"census_snapshot":snapshot,
                 "input":store.put(p),"max_requests":len(rows)}
            return {"job_id":job_id(job),"operation":"verify","job_ref":store.put_json(job)}
    # Two passes avoid giving undated clues precedence over dated ones.
    for dated in ((True,False) if include_undated else (True,)):
        for _, row in jsonl(path):
            hinted = row["hinted_missing_mask"]
            mask = hinted if dated else row["missing_mask"]
            if bool(hinted) != dated or not mask:
                continue
            h=host(row["hostname"])
            if h != row["hostname"] or type(mask) is not int or mask & ~ALL or mask & (row["baseline_mask"] | row.get("local_qualified_mask",0)):
                raise ValueError("invalid census identity/mask")
            original=None
            for s in row["sources"]:
                u=s.get("sample_url")
                if u and url_host(u)==h:
                    original=u
                    break
            batch.append({"hostname":h,"target_mask":mask,"original_url":original})
            emitted+=1
            if len(batch)==batch_size:
                yield publish(batch)
                batch=[]
            if emitted==limit:
                break
        if emitted==limit:
            break
    if batch:
        yield publish(batch)


def validate_job(job, role):
    if job.get("schema")!=JOB_SCHEMA or job.get("version")!=VERSION or job.get("policy")!=RULE:
        raise ValueError("unsupported job version")
    op=job.get("operation")
    if (role,op) not in {("compute","discover"),("ia","verify")}:
        raise ValueError("job routed to wrong worker role")
    Store.check_ref(job["input"])
    if op=="verify":
        if job.get("provider")!="ia-cdx" or type(job.get("max_requests")) is not int or not 1<=job["max_requests"]<=500:
            raise ValueError("invalid verification budget")
        if not job.get("authority"):
            raise ValueError("authority required")
    elif not job.get("source_id") or not job.get("origin_family"):
        raise ValueError("source identity required")
    elif "commoncrawl" in job["origin_family"].lower().replace(" ", "").replace("-", ""):
        raise ValueError("Common Crawl candidate corpus excluded")
