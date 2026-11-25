"""Temporal orchestration: small references only, role-specific queues."""
from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from temporalio import activity
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.worker import Worker


from .workflow import BatchWorkflow


class Activities:
    def __init__(self, store, role, collector=None):
        self.store,self.role,self.collector=store,role,collector

    @activity.defn(name="execute_batch_v1")
    def run(self,envelope:dict)->dict:
        from .execute import execute
        return execute(self.store,envelope,self.role,self.collector,
                       progress=lambda *args:activity.heartbeat(*args))


async def connect(address,namespace):
    key=os.environ.get("TEMPORAL_API_KEY")
    tls=os.environ.get("TEMPORAL_TLS","").lower() in {"1","true","yes"}
    return await Client.connect(address, namespace=namespace,
                                tls=tls or bool(key), api_key=key)


from .locking import collector_lock

async def serve(args):
    from pathlib import Path
    from .store import Store
    from .online import ArchiveCollector
    from contextlib import nullcontext
    collector=None
    lock=nullcontext()
    if args.role in ("ia","arquivo"):
        if not args.allow_online or not args.user_agent:
            raise ValueError("IA worker requires --allow-online and --user-agent")
        state=Path(args.state or f"work/{args.role}-collector.sqlite")
        lock=collector_lock(state)
    elif args.allow_online:
        raise ValueError("compute worker never performs external verification")
    with lock:
        if args.role in ("ia","arquivo"):
            collector=ArchiveCollector(state,args.interval,args.user_agent,args.role)
        client=await connect(args.address,args.namespace)
        act=Activities(Store(args.store),args.role,collector)
        concurrency=1 if args.role in ("ia","arquivo") else args.concurrency
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            worker=Worker(client,task_queue=args.queue,workflows=[BatchWorkflow],
                          activities=[act.run],activity_executor=pool,
                          max_concurrent_activities=concurrency)
            await worker.run()


async def submit(args,envelope):
    client=await connect(args.address,args.namespace)
    handle=await client.start_workflow(BatchWorkflow.run,envelope,
            id="creeperman-v1-"+envelope["job_id"],task_queue=args.queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,execution_timeout=timedelta(hours=5))
    if args.wait:
        return {"workflow_id":handle.id,"manifest_ref":await handle.result()}
    return {"workflow_id":handle.id}


async def get_result(args):
    client=await connect(args.address,args.namespace)
    return {"workflow_id":args.workflow_id,
            "manifest_ref":await client.get_workflow_handle(args.workflow_id).result()}


async def dispatch(args):
    """Finite inflight workflows, durable JSONL receipts, attach on rerun."""
    import json
    from temporalio.exceptions import WorkflowAlreadyStartedError
    from .core import jsonl, canonical
    if not 1<=args.max_inflight<=16 or not 1<=args.limit_jobs<=10000:
        raise ValueError("invalid dispatch window")
    client=await connect(args.address,args.namespace)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    async def one(e):
        op=e["operation"]
        if op in ("verify","online") and not args.allow_online:
            raise ValueError("online dispatch requires explicit opt-in")
        role="compute" if op=="discover" else "ia" if op=="verify" else e["provider"]
        queue={"compute":args.compute_queue,"ia":args.ia_queue,"arquivo":args.arquivo_queue}[role]
        wid="creeperman-v1-"+e["job_id"]
        try:
            handle=await client.start_workflow(BatchWorkflow.run,e,id=wid,task_queue=queue,
                        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,execution_timeout=timedelta(hours=5))
        except WorkflowAlreadyStartedError:
            handle=client.get_workflow_handle(wid)
        try:
            return {"workflow_id":wid,"manifest_ref":await handle.result()}
        except Exception as exc:
            return {"workflow_id":wid,"state":"workflow_failed_or_unresolved","error_type":type(exc).__name__}
    # Preflight finite cohort before starting any workflow.
    from itertools import islice
    cohort=[e for _,e in islice(jsonl(args.plans),args.limit_jobs)]
    if not args.allow_online and any(e["operation"]!="discover" for e in cohort):
        raise ValueError("online dispatch requires explicit opt-in")
    if args.out.exists():raise FileExistsError(args.out)
    with args.out.open("xb") as f:
        for i in range(0,len(cohort),args.max_inflight):
            for r in await asyncio.gather(*(one(e) for e in cohort[i:i+args.max_inflight])):
                f.write(canonical(r));f.flush()
