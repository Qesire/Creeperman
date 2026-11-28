"""Real receipt/settle/export plumbing with explicitly synthetic historical keys."""
import json
import os
from contextlib import closing
from pathlib import Path

import pytest

from creeperman.core import canonical,sha
from creeperman.discovery_epoch import DiscoveryEpoch
from creeperman.source_frontier import Frontier
from test_discovery_policy import fixture, reviewed, artifact, bind_prior, COST


RSI = Path(os.environ.get("RSIFORME_ROOT", str(Path(__file__).resolve().parents[2]/"RSIforme")))
needs_rsi = pytest.mark.skipif(not (RSI/"examples/creeperman_replay/prepare.py").is_file(),
                            reason="RSIFORME_ROOT needed for actual cross-repository execution")


@pytest.fixture
def setup(tmp_path):
    baseline,audit,model,_=fixture.make(tmp_path/"fixture")
    rules=tmp_path/"rules.txt";rules.write_text("SYNTHETIC scope and review rules v1")
    source=tmp_path/"source.txt";source.write_text("SYNTHETIC original input")
    operator=tmp_path/"operator.py";operator.write_text("# SYNTHETIC operator revision\n")
    with closing(Frontier(tmp_path/"frontier.sqlite")) as f:
        bind_prior(f,tmp_path,(baseline,audit,model),[("old.com",1999)])
        recorder=DiscoveryEpoch(f,"fixture-epoch")
        recorder.initialize(baseline=baseline,audit=audit,model=model,rules=rules,
            budget={k:v*4 for k,v in COST.items()},data_kind="synthetic_fixture")
        yield f,recorder,(baseline,audit,model),source,operator


def declare(recorder,node,source,operator,label,**kwargs):
    return recorder.declare(label,node_id=node,input_path=source,operator_path=operator,
        record_locator=label+":all",capture_or_edition="1999 synthetic edition",
        cost_bound=COST,**kwargs)


def receipt(tmp_path,label,cost=COST):
    path=tmp_path/(label+"-execution.json")
    path.write_bytes(canonical({"schema":"synthetic-execution-v1","label":label,"cost":cost,
                               "requests_include_failures":True}))
    return path


def finish_batch(f,recorder,tmp_path,authority,label,node,keys):
    settled=reviewed(tmp_path,authority,label,keys)
    batch=f.policy.import_settlement(settled,authority[2],node_id=node,scope_id=label+":all",complete=True,cost=COST)
    path=receipt(tmp_path,label)
    recorder.finish(label,path,batch_id=batch["batch_id"])
    return batch,path


def discovery_receipt(tmp_path,label,plan):
    output=tmp_path/(label+"-members.json")
    output.write_bytes(canonical({"members":["observed-child"],"data":"synthetic"}))
    path=tmp_path/(label+"-discovery.json")
    path.write_bytes(canonical({"cost":COST,"operation":{"kind":"discovery","complete":True,
        "scope_id":plan["coverage"]["record_locator"],
        "input_sha256":plan["coverage"]["input_sha256"],
        "operator_sha256":plan["coverage"]["operator_revision"]},
        "outputs":{output.name:sha(output)}}))
    return path,output


@needs_rsi
def test_completed_discovery_parent_reveals_independently_reviewed_child(tmp_path,setup):
    f,recorder,authority,source,operator=setup
    parent=artifact(f,"listing");child=artifact(f,"body",parent)
    plan=declare(recorder,parent,source,operator,"listing",initial=True,operation_kind="discovery")
    declare(recorder,child,source,operator,"body",revealed_by="listing",requires=["listing"])
    path,output=discovery_receipt(tmp_path,"listing",plan)
    result=recorder.finish("listing",path)
    assert result["state"]=="complete" and result["records"]==[] and result["reveals"]==["body"]
    assert f.policy.summary()["reviewed_batches"]==0
    finish_batch(f,recorder,tmp_path,authority,"body",child,[("new.com",1999)])
    evaluated=recorder.export(tmp_path/"discovery-export",rsiforme_root=RSI,
        evaluate_policy=RSI/"examples/creeperman_replay/policy.json")
    assert evaluated["evaluation"]["valid"]
    assert evaluated["evaluation"]["metrics"]["net_eed_units"]==6321
    assert evaluated["evaluation"]["metrics"]["actions_completed"]==2
    assert f.policy.summary()["reviewed_batches"]==1
    output.write_text("changed output")
    with pytest.raises(ValueError,match="output bytes changed"):
        recorder.export(tmp_path/"changed-export",rsiforme_root=RSI)


def test_discovery_parsed_string_is_not_a_completion_receipt(tmp_path,setup):
    f,recorder,_,source,operator=setup
    node=artifact(f,"directory")
    declare(recorder,node,source,operator,"directory",initial=True,operation_kind="discovery")
    path=receipt(tmp_path,"directory")
    with pytest.raises(ValueError,match="explicit incomplete reason"):
        recorder.finish("directory",path)
    assert recorder.finish("directory",path,reason="parse scope and artifacts not attested")["state"]=="incomplete"


@needs_rsi
def test_actual_export_prepare_evaluate_uses_frozen_prior_and_full_baseline(tmp_path,setup):
    f,recorder,authority,source,operator=setup
    parent=artifact(f,"parent");child=artifact(f,"child",parent)
    declare(recorder,parent,source,operator,"parent",initial=True)
    declare(recorder,child,source,operator,"child",revealed_by="parent",requires=["parent"])
    finish_batch(f,recorder,tmp_path,authority,"parent",parent,
                 [("same.org",1999),("old.com",1999),("new.com",1999)])
    finish_batch(f,recorder,tmp_path,authority,"child",child,
                 [("new.com",1999),("www.new.com",1999),("new.com",2000)])
    out=tmp_path/"export"
    result=recorder.export(out,rsiforme_root=RSI,evaluate_policy=RSI/"examples/creeperman_replay/policy.json")
    raw=json.loads((out/"epoch.json").read_text())
    assert raw["data_kind"]=="synthetic_fixture"
    assert raw["baseline_keys"]==[{"hostname":"same.org","year":1999}]
    assert raw["reviewed_keys"]==[{"hostname":"old.com","year":1999}]
    assert raw["initial_frontier"]==["parent"]
    assert raw["actions"][0]["outcome"]["reveals"]==["child"]
    assert raw["actions"][1]["requires"]==["parent"]
    assert result["evaluation"]["valid"] is True
    assert result["evaluation"]["metrics"]["net_eed_units"]==3*6321
    assert result["evaluation"]["metrics"]["requests"]==COST["requests"]*2
    assert result["production_ledger_written"] is False
    for a in raw["actions"]:
        assert (out/a["outcome"]["receipt_locator"]).is_file()
    # The exporter did not change the real feedback ledger or reuse its current
    # post-execution seen set as A for this historical epoch.
    assert f.policy.summary()["reviewed_batches"]==2


@needs_rsi
def test_parsed_without_review_and_unknown_actions_never_score_zero(tmp_path,setup):
    f,recorder,_,source,operator=setup
    node=artifact(f,"parsed")
    declare(recorder,node,source,operator,"parsed",initial=True)
    unobserved=recorder.export(tmp_path/"unobserved",rsiforme_root=RSI,
        evaluate_policy=RSI/"examples/creeperman_replay/policy.json")
    assert unobserved["evaluation"]["valid"] is False
    assert unobserved["evaluation"]["completion_reason"]=="unobserved_outcome"
    recorder.finish("parsed",receipt(tmp_path,"parsed"),reason="catalog parsed; evidence scope not reviewed")
    result=recorder.export(tmp_path/"incomplete",rsiforme_root=RSI,
        evaluate_policy=RSI/"examples/creeperman_replay/policy.json")
    assert result["evaluation"]["valid"] is False
    assert result["evaluation"]["completion_reason"]=="incomplete_outcome"
    assert "net_eed_units" not in result["evaluation"]["metrics"]
    assert result["evaluation"]["metrics"]["requests"]==COST["requests"]
    assert f.policy.summary()["reviewed_batches"]==0


def test_complete_outcomes_need_predeclared_matching_scope_and_measured_cost(tmp_path,setup):
    f,recorder,authority,source,operator=setup
    node=artifact(f,"a")
    settled=reviewed(tmp_path,authority,"old-completed",[("new.com",1999)])
    old=f.policy.import_settlement(settled,authority[2],node_id=node,scope_id="a:all",complete=True,cost=COST)
    declare(recorder,node,source,operator,"a",initial=True)
    with pytest.raises(ValueError,match="newly reviewed"):
        recorder.finish("a",receipt(tmp_path,"a"),batch_id=old["batch_id"])
    node2=artifact(f,"b");declare(recorder,node2,source,operator,"b",initial=True)
    settled2=reviewed(tmp_path,authority,"new-completed",[("other.com",1999)])
    batch=f.policy.import_settlement(settled2,authority[2],node_id=node2,scope_id="b:all",complete=True,cost=COST)
    with pytest.raises(ValueError,match="costs disagree"):
        recorder.finish("b",receipt(tmp_path,"b",{**COST,"requests":1}),batch_id=batch["batch_id"])
    assert f.db.execute("SELECT count(*) FROM discovery_epoch_actions WHERE outcome IS NOT NULL").fetchone()[0]==0


def test_input_and_execution_receipts_are_immutable(tmp_path,setup):
    f,recorder,authority,source,operator=setup
    node=artifact(f,"a");declare(recorder,node,source,operator,"a",initial=True)
    batch,path=finish_batch(f,recorder,tmp_path,authority,"a",node,[("new.com",1999)])
    first=recorder.finish("a",path,batch_id=batch["batch_id"])
    assert first["state"]=="complete"
    path.write_bytes(canonical({"cost":COST,"tampered":True}))
    with pytest.raises(ValueError,match="cannot be replaced"):
        recorder.finish("a",path,batch_id=batch["batch_id"])
    source.write_text("different bytes")
    with pytest.raises(ValueError,match="asset changed"):
        recorder.finish("a",path,batch_id=batch["batch_id"])


def test_discovery_edges_and_late_initial_roots_are_not_invented(tmp_path,setup):
    f,recorder,_,source,operator=setup
    parent=artifact(f,"parent");unrelated=artifact(f,"unrelated")
    declare(recorder,parent,source,operator,"parent",initial=True)
    with pytest.raises(ValueError,match="observed discovery path"):
        declare(recorder,unrelated,source,operator,"child",revealed_by="parent")
    recorder.finish("parent",receipt(tmp_path,"parent"),reason="review not completed")
    with pytest.raises(ValueError,match="before any recorded outcome"):
        declare(recorder,unrelated,source,operator,"late",initial=True)


def test_new_epoch_requires_bound_prior(tmp_path):
    baseline,audit,model,_=fixture.make(tmp_path/"fixture")
    rules=tmp_path/"rules";rules.write_text("synthetic")
    with closing(Frontier(tmp_path/"f.sqlite")) as f:
        with pytest.raises(ValueError,match="complete current reviewed prior"):
            DiscoveryEpoch(f,"unbound").initialize(baseline=baseline,audit=audit,model=model,
                rules=rules,budget=COST,data_kind="synthetic_fixture")


def test_deleted_review_rows_and_changed_prior_cannot_change_oracle(tmp_path,setup):
    f,recorder,authority,source,operator=setup
    node=artifact(f,"a");declare(recorder,node,source,operator,"a",initial=True)
    delta=reviewed(tmp_path,authority,"reviewed",[("new.com",1999)])
    batch=f.policy.import_settlement(delta,authority[2],node_id=node,scope_id="a:all",complete=True,cost=COST)
    f.db.execute("DELETE FROM discovery_reviewed_records WHERE batch_id=?",(batch["batch_id"],))
    with pytest.raises(ValueError,match="individual evidence changed"):
        recorder.finish("a",receipt(tmp_path,"a"),batch_id=batch["batch_id"])
    f.db.execute("DELETE FROM discovery_epoch_prior WHERE epoch_id=?",(recorder.id,))
    with pytest.raises(ValueError,match="prior snapshot changed"):
        recorder.export(tmp_path/"bad",rsiforme_root=RSI)
