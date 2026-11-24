"""Actual batch operations, independent of Temporal for local rehearsal."""
from __future__ import annotations

import json
import tempfile
from collections import Counter
from pathlib import Path
from .core import canonical, host, jsonl
from .jobs import RESULT_SCHEMA, job_id, validate_job
from .sources import records


def execute(store, envelope, role, collector=None, progress=lambda *args:None):
    job=store.get_json(envelope["job_ref"])
    if envelope["job_id"]!=job_id(job) or envelope["operation"]!=job["operation"]:
        raise ValueError("job identity mismatch")
    validate_job(job,role)
    stats=Counter()
    progress("validated_job")
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)
        inp=store.materialize(job["input"],p/("input.gz" if job.get("gzip") else "input"))
        progress("input_verified")
        out=p/"results.jsonl"
        with out.open("wb") as f:
            if role=="compute":
                for n,item,error in records(inp,job["format"]):
                    stats["records"]+=1
                    if item is None:
                        result={"record_line":n,"state":"rejected","reason":error}
                        stats["rejected"]+=1
                    else:
                        result={**item,"record_line":n,"state":"candidate",
                                "source_id":job["source_id"],"origin_family":job["origin_family"]}
                        stats["candidates"]+=1
                    f.write(canonical(result))
                    if stats["records"]%1000==0:
                        progress("records",stats["records"])
            else:
                from .cdx import interpret,query_params
                if collector is None:
                    raise ValueError("verification requires an explicitly enabled collector")
                # Validate entire finite plan before any remote request.
                targets=[]
                seen=set()
                for n,row in jsonl(inp):
                    if len(targets)>=job["max_requests"]:
                        raise ValueError("targets exceed declared budget")
                    params=query_params(row)
                    h=row["hostname"]
                    if h in seen:
                        raise ValueError("duplicate host in batch")
                    seen.add(h)
                    targets.append((n,row,params))
                stop=False
                for n,row,params in targets:
                    progress("target",n)
                    if stop:
                        meta,body={"state":"deferred_cooldown","requests":0},None
                    else:
                        meta,body=collector.request(params)
                    stats["requests"]+=meta["requests"]
                    result=interpret(row,body,meta)
                    result.update(record_line=n,query=params,provider="ia-cdx")
                    if body is not None:
                        raw=p/"response"
                        raw.write_bytes(body)
                        result["response_ref"]=store.put(raw)
                    f.write(canonical(result))
                    stats[result["state"]]+=1
                    if result["state"] in {"provider_cooldown","rate_limited"} or meta.get("http_status")==503:
                        stop=True
        progress("output_ready")
        output=store.put(out)
        # Content-addressed output and manifest: a lost completion response
        # cannot overwrite another attempt's artifacts.
        manifest={"schema":RESULT_SCHEMA,"job_id":envelope["job_id"],
                  "job_ref":envelope["job_ref"],"operation":job["operation"],
                  "authority":job.get("authority"),"policy":job["policy"],
                  "result":output,"stats":dict(stats),
                  "qualified_new_eed":None,"scope":"batch_completed_not_evidence_accepted"}
        return store.put_json(manifest)
