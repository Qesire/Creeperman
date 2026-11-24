"""Deterministic orchestration. Only the envelope enters workflow history."""
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class BatchWorkflow:
    @workflow.run
    async def run(self, envelope: dict) -> dict:
        online=envelope["operation"] in ("verify","online")
        # External HTTP activities are not automatically repeated after an
        # ambiguous failure. Offline activities may safely regenerate outputs.
        return await workflow.execute_activity(
            "execute_batch_v1", envelope,
            start_to_close_timeout=timedelta(hours=1),
            schedule_to_close_timeout=timedelta(hours=4),
            heartbeat_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=1 if online else 3))


