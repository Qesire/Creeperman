"""CLI: offline census, bounded plans, workers and result retrieval."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from .core import canonical
from .inventory import census
from .jobs import discovery_job, verification_jobs
from .store import Store


def main(argv=None):
    p=argparse.ArgumentParser(prog="creeperman")
    s=p.add_subparsers(dest="cmd",required=True)
    c=s.add_parser("census")
    for flag in ("baseline","audit","model","sources","out"):
        c.add_argument("--"+flag,type=Path,required=True)
    d=s.add_parser("discovery-job")
    d.add_argument("--store",required=True)
    d.add_argument("--input",type=Path,required=True)
    d.add_argument("--source-id",required=True)
    d.add_argument("--origin-family",required=True)
    d.add_argument("--format",choices=["hosts","urls","observations","cdxj"],required=True)
    d.add_argument("--allow-source",action="store_true",required=True)
    b=s.add_parser("plan")
    b.add_argument("--store",required=True)
    b.add_argument("--census",type=Path,required=True)
    b.add_argument("--limit",type=int,required=True)
    b.add_argument("--batch-size",type=int,default=50)
    b.add_argument("--include-undated",action="store_true")
    l=s.add_parser("run-local")
    l.add_argument("--store",required=True)
    l.add_argument("--job",type=Path,required=True)
    # local execution intentionally offline only
    w=s.add_parser("worker")
    w.add_argument("--store",required=True)
    w.add_argument("--role",choices=["compute","ia"],required=True)
    w.add_argument("--queue",required=True)
    w.add_argument("--concurrency",type=int,default=2)
    w.add_argument("--allow-online",action="store_true")
    w.add_argument("--interval",type=float,default=2.5)
    w.add_argument("--state",default="work/ia-collector.sqlite")
    w.add_argument("--user-agent")
    u=s.add_parser("submit")
    u.add_argument("--job",type=Path,required=True)
    u.add_argument("--queue",required=True)
    u.add_argument("--wait",action="store_true")
    r=s.add_parser("result")
    r.add_argument("--workflow-id",required=True)
    for x in (w,u,r):
        x.add_argument("--address",default="localhost:7233")
        x.add_argument("--namespace",default="default")
    g=s.add_parser("get")
    g.add_argument("--store",required=True)
    g.add_argument("--ref",required=True,help="JSON object reference")
    g.add_argument("--out",type=Path,required=True)
    a=p.parse_args(argv)
    if a.cmd=="census":
        print(json.dumps(census(a.baseline,a.audit,a.model,a.sources,a.out),ensure_ascii=False,indent=2))
    elif a.cmd=="discovery-job":
        print(canonical(discovery_job(Store(a.store),a.input,source_id=a.source_id,
            origin_family=a.origin_family,fmt=a.format)).decode(),end="")
    elif a.cmd=="plan":
        for envelope in verification_jobs(Store(a.store),a.census,limit=a.limit,
                    batch_size=a.batch_size,include_undated=a.include_undated):
            print(canonical(envelope).decode(),end="")
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
    elif a.cmd=="result":
        from .runtime import get_result
        print(json.dumps(asyncio.run(get_result(a))))


if __name__=="__main__":
    main()
