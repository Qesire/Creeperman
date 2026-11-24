"""Temporal orchestration: small references only, role-specific queues."""
from __future__ import annotations

import asyncio
import os
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


async def serve(args):
    from pathlib import Path
    from .store import Store
    from .cdx import Collector
    collector=None
    if args.role=="ia":
        if not args.allow_online or not args.user_agent:
            raise ValueError("IA worker requires --allow-online and --user-agent")
        collector=Collector(Path(args.state),args.interval,args.user_agent)
    elif args.allow_online:
        raise ValueError("compute worker never performs external verification")
    client=await connect(args.address,args.namespace)
    act=Activities(Store(args.store),args.role,collector)
    concurrency=1 if args.role=="ia" else args.concurrency
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        worker=Worker(client,task_queue=args.queue,workflows=[BatchWorkflow],
                      activities=[act.run],activity_executor=pool,
                      max_concurrent_activities=concurrency)
        await worker.run()


async def submit(args,envelope):
    client=await connect(args.address,args.namespace)
    handle=await client.start_workflow(BatchWorkflow.run,envelope,
            id="creeperman-v1-"+envelope["job_id"],task_queue=args.queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
    if args.wait:
        return {"workflow_id":handle.id,"manifest_ref":await handle.result()}
    return {"workflow_id":handle.id}


async def get_result(args):
    client=await connect(args.address,args.namespace)
    return {"workflow_id":args.workflow_id,
            "manifest_ref":await client.get_workflow_handle(args.workflow_id).result()}
