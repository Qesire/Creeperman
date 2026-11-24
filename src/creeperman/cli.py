"""CLI: offline census, bounded plans, workers and result retrieval."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from .core import canonical, sha, audit_binding, jsonl
from .inventory import census
from .jobs import discovery_job, verification_jobs
from .store import Store
from .sources import FORMATS, records


def main(argv=None):
    p=argparse.ArgumentParser(prog="creeperman")
    s=p.add_subparsers(dest="cmd",required=True)
    c=s.add_parser("census")
    for flag in ("baseline","audit","model","sources","out"):
        c.add_argument("--"+flag,type=Path,required=True)
    a0=s.add_parser("authority")
    a0.add_argument("--audit",type=Path,required=True)
    a0.add_argument("--model",type=Path,required=True)
    m=s.add_parser("describe-source")
    m.add_argument("--input",type=Path,required=True)
    m.add_argument("--source-id",required=True)
    m.add_argument("--origin-family",required=True)
    m.add_argument("--format",choices=FORMATS,required=True)
    m.add_argument("--role",choices=["discovery","existing_pool"],default="discovery")
    m.add_argument("--allow-source",action="store_true",required=True)
    x=s.add_parser("extract")
    x.add_argument("--input",type=Path,required=True)
    x.add_argument("--format",choices=FORMATS,required=True)
    x.add_argument("--out",type=Path,required=True)
    x.add_argument("--allow-source",action="store_true",required=True)
    d=s.add_parser("discovery-job")
    d.add_argument("--store",required=True)
    d.add_argument("--input",type=Path,required=True)
    d.add_argument("--source-id",required=True)
    d.add_argument("--origin-family",required=True)
    d.add_argument("--format",choices=FORMATS,required=True)
    d.add_argument("--allow-source",action="store_true",required=True)
    b=s.add_parser("plan")
    b.add_argument("--store",required=True)
    b.add_argument("--census",type=Path,required=True)
    b.add_argument("--limit",type=int,required=True)
    b.add_argument("--batch-size",type=int,default=50)
    b.add_argument("--include-undated",action="store_true")
    b.add_argument("--offset",type=int,default=0)
    b.add_argument("--round-id",default="initial")
    rp=s.add_parser("route-plan")
    rp.add_argument("--store",required=True)
    rp.add_argument("--census",type=Path,required=True)
    rp.add_argument("--limit",type=int,required=True)
    rp.add_argument("--batch-size",type=int,default=20)
    rp.add_argument("--offset",type=int,default=0)
    rp.add_argument("--include-undated",action="store_true")
    rp.add_argument("--round-id",required=True)
    op=s.add_parser("online-plan")
    op.add_argument("--store",required=True)
    op.add_argument("--provider",choices=["ia","arquivo"],required=True)
    op.add_argument("--action",choices=["lookup","replay","search","metadata"],required=True)
    op.add_argument("--input",type=Path,required=True)
    op.add_argument("--authority",required=True)
    op.add_argument("--round-id",required=True)
    op.add_argument("--limit",type=int,required=True)
    op.add_argument("--batch-size",type=int,default=20)
    fo=s.add_parser("followup")
    fo.add_argument("--store",required=True)
    fo.add_argument("--db",type=Path,required=True)
    fo.add_argument("--authority",required=True)
    fo.add_argument("--mode",choices=["replay","metadata","fallback"],required=True)
    fo.add_argument("--provider",choices=["ia","arquivo"],required=True)
    fo.add_argument("--round-id",required=True)
    fo.add_argument("--limit",type=int,required=True)
    fo.add_argument("--batch-size",type=int,default=20)
    eo=s.add_parser("export-observations")
    eo.add_argument("--store",required=True)
    eo.add_argument("--db",type=Path,required=True)
    eo.add_argument("--out",type=Path,required=True)
    rv=s.add_parser("review-export")
    rv.add_argument("--db",type=Path,required=True)
    rv.add_argument("--authority",required=True)
    rv.add_argument("--out",type=Path,required=True)
    sig=s.add_parser("signatures")
    sig.add_argument("--observations",type=Path,required=True)
    sig.add_argument("--out",type=Path,required=True)
    sig.add_argument("--limit",type=int,required=True)
    sig.add_argument("--words",type=int,default=5)
    st=s.add_parser("settle")
    for k in ("baseline","audit","model","decisions","out"):
        st.add_argument("--"+k,type=Path,required=True)
    st.add_argument("--rule-version",required=True)
    st.add_argument("--db",type=Path)
    st.add_argument("--store")
    l=s.add_parser("run-local")
    l.add_argument("--store",required=True)
    l.add_argument("--job",type=Path,required=True)
    # local execution intentionally offline only
    w=s.add_parser("worker")
    w.add_argument("--store",required=True)
    w.add_argument("--role",choices=["compute","ia","arquivo"],required=True)
    w.add_argument("--queue",required=True)
    w.add_argument("--concurrency",type=int,default=2)
    w.add_argument("--allow-online",action="store_true")
    w.add_argument("--interval",type=float,default=2.5)
    w.add_argument("--state")
    w.add_argument("--user-agent")
    u=s.add_parser("submit")
    u.add_argument("--job",type=Path,required=True)
    u.add_argument("--queue",required=True)
    u.add_argument("--wait",action="store_true")
    q=s.add_parser("dispatch")
    q.add_argument("--plans",type=Path,required=True)
    q.add_argument("--compute-queue",default="creeperman-compute")
    q.add_argument("--ia-queue",default="creeperman-ia")
    q.add_argument("--arquivo-queue",default="creeperman-arquivo")
    q.add_argument("--max-inflight",type=int,default=2)
    q.add_argument("--limit-jobs",type=int,required=True)
    q.add_argument("--allow-online",action="store_true")
    q.add_argument("--out",type=Path,required=True)
    r=s.add_parser("result")
    r.add_argument("--workflow-id",required=True)
    for x in (w,u,r,q):
        x.add_argument("--address",default="localhost:7233")
        x.add_argument("--namespace",default="default")
    i=s.add_parser("collect")
    i.add_argument("--store",required=True)
    i.add_argument("--db",type=Path,required=True)
    i.add_argument("--refs",type=Path,required=True)
    g=s.add_parser("get")
    g.add_argument("--store",required=True)
    g.add_argument("--ref",required=True,help="JSON object reference")
    g.add_argument("--out",type=Path,required=True)
    a=p.parse_args(argv)
    if a.cmd=="census":
        print(json.dumps(census(a.baseline,a.audit,a.model,a.sources,a.out),ensure_ascii=False,indent=2))
    elif a.cmd=="authority":
        print(canonical(audit_binding(a.audit,a.model)[0]).decode(),end="")
    elif a.cmd=="describe-source":
        print(canonical({"source_id":a.source_id,"origin_family":a.origin_family,
            "role":a.role,"format":a.format,"path":str(a.input.resolve()),
            "sha256":sha(a.input),"allowed_by_competition":True}).decode(),end="")
    elif a.cmd=="extract":
        a.out.parent.mkdir(parents=True,exist_ok=True)
        rejected=a.out.with_suffix(a.out.suffix+".rejected.jsonl")
        if a.out.exists() or rejected.exists(): raise FileExistsError(a.out)
        with a.out.open("xb") as f,rejected.open("xb") as e:
            for n,item,error in records(a.input,a.format):
                if item is None: e.write(canonical({"record":n,"reason":error}))
                else: f.write(canonical(item))
        print(json.dumps({"input_sha256":sha(a.input),"output_sha256":sha(a.out),"format":a.format}))
    elif a.cmd=="discovery-job":
        print(canonical(discovery_job(Store(a.store),a.input,source_id=a.source_id,
            origin_family=a.origin_family,fmt=a.format)).decode(),end="")
    elif a.cmd=="plan":
        for envelope in verification_jobs(Store(a.store),a.census,limit=a.limit,
                    batch_size=a.batch_size,include_undated=a.include_undated,
                    offset=a.offset,round_id=a.round_id):
            print(canonical(envelope).decode(),end="")
    elif a.cmd=="route-plan":
        from .online_plans import routed_jobs
        for j in routed_jobs(Store(a.store),a.census,a.limit,a.batch_size,a.round_id,a.offset,a.include_undated):
            print(canonical(j).decode(),end="")
    elif a.cmd in ("online-plan","followup"):
        from .online_plans import online_jobs,followup_rows
        if a.cmd=="online-plan":
            action=a.action;rows=(r for _,r in jsonl(a.input))
        else:
            action="lookup" if a.mode=="fallback" else a.mode
            rows=followup_rows(a.db,a.authority,a.mode,a.provider,a.limit)
        for j in online_jobs(Store(a.store),rows,a.provider,action,a.authority,a.round_id,a.limit,a.batch_size):
            print(canonical(j).decode(),end="")
    elif a.cmd=="export-observations":
        from .catalog import export_observations
        a.out.parent.mkdir(parents=True,exist_ok=True)
        export_observations(Store(a.store),a.db,a.out)
    elif a.cmd=="signatures":
        from .semantic import signatures
        a.out.parent.mkdir(parents=True,exist_ok=True)
        signatures(a.observations,a.out,a.limit,a.words)
    elif a.cmd=="settle":
        from .settle import settle
        print(json.dumps(settle(a.baseline,a.audit,a.model,a.decisions,a.out,
              rule_version=a.rule_version,db_path=a.db,store=Store(a.store) if a.store else None),
              ensure_ascii=False,indent=2))
    elif a.cmd=="review-export":
        from .catalog import review_export
        a.out.parent.mkdir(parents=True,exist_ok=True)
        review_export(a.db,a.out,a.authority)
    elif a.cmd=="collect":
        from .catalog import ingest
        refs=(r.get("manifest_ref",r) for _,r in jsonl(a.refs) if r.get("manifest_ref") or ("sha256" in r and "bytes" in r))
        print(json.dumps(ingest(Store(a.store),a.db,refs),ensure_ascii=False,indent=2))
    elif a.cmd=="get":
        a.out.parent.mkdir(parents=True,exist_ok=True)
        Store(a.store).materialize(json.loads(a.ref),a.out)
    elif a.cmd=="run-local":
        from .execute import execute
        envelope=json.loads(a.job.read_text())
        ref=execute(Store(a.store),envelope,"compute")
        print(canonical({"manifest_ref":ref}).decode(),end="")
    elif a.cmd=="worker":
        from .runtime import serve
        asyncio.run(serve(a))
    elif a.cmd=="submit":
        from .runtime import submit
        print(json.dumps(asyncio.run(submit(a,json.loads(a.job.read_text())))))
    elif a.cmd=="dispatch":
        from .runtime import dispatch
        asyncio.run(dispatch(a))
    elif a.cmd=="result":
        from .runtime import get_result
        print(json.dumps(asyncio.run(get_result(a))))


if __name__=="__main__":
    main()
