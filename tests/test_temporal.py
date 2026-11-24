"""Offline integration; uses a real local Temporal test server if enabled."""
import asyncio
import os
import uuid
import pytest

pytestmark=pytest.mark.skipif(os.environ.get("RUN_TEMPORAL_SMOKE")!="1",
                              reason="requires Temporal test server binary/download")
def test_temporal_worker(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker
    from creeperman.runtime import Activities
    from creeperman.workflow import BatchWorkflow
    from creeperman.jobs import discovery_job
    from creeperman.store import Store

    async def smoke():
        store=Store(str(tmp_path/"store"))
        p=tmp_path/"input"
        p.write_text("www.example.com\nexample.com\n")
        job=discovery_job(store,p,source_id="synthetic",origin_family="synthetic",fmt="hosts")
        act=Activities(store,"compute")
        q="fixture-"+uuid.uuid4().hex
        async with await WorkflowEnvironment.start_time_skipping() as env:
            with ThreadPoolExecutor(max_workers=1) as pool:
                async with Worker(env.client,task_queue=q,workflows=[BatchWorkflow],
                    activities=[act.run],activity_executor=pool,max_concurrent_activities=1):
                    ref=await env.client.execute_workflow(BatchWorkflow.run,job,
                            id="fixture-"+job["job_id"],task_queue=q)
                    m=store.get_json(ref)
                    assert m["stats"]["candidates"]==2
                    assert m["qualified_new_eed"] is None
    asyncio.run(smoke())


def test_online_temporal_worker(tmp_path):
    """Actual workflow service and fake provider, no archive traffic."""
    from concurrent.futures import ThreadPoolExecutor
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker
    from creeperman.runtime import Activities
    from creeperman.workflow import BatchWorkflow
    from creeperman.online import ArchiveCollector
    from creeperman.online_plans import publish
    from creeperman.store import Store
    from creeperman.core import bit
    async def smoke():
        store=Store(str(tmp_path/"store"))
        collector=ArchiveCollector(tmp_path/"arquivo.sqlite",2.5,"Fixture/1","arquivo")
        collector.fetch=lambda u,p:({"state":"received","requests":1,"http_status":200,"truncated":False},
            b'{"timestamp":"19990101000000","url":"http://example.pt/","status":"200","mime":"text/html"}\n')
        job=publish(store,"arquivo","lookup",[{"hostname":"example.pt","target_mask":bit(1999),"original_url":None}],"fixture","r1")
        act=Activities(store,"arquivo",collector)
        q="fixture-"+uuid.uuid4().hex
        async with await WorkflowEnvironment.start_time_skipping() as env:
            with ThreadPoolExecutor(max_workers=1) as pool:
                async with Worker(env.client,task_queue=q,workflows=[BatchWorkflow],
                    activities=[act.run],activity_executor=pool,max_concurrent_activities=1):
                    ref=await env.client.execute_workflow(BatchWorkflow.run,job,
                            id="fixture-"+job["job_id"],task_queue=q)
                    m=store.get_json(ref)
                    assert m["stats"]["potential_witness"]==1
                    assert m["qualified_new_eed"] is None
    asyncio.run(smoke())
