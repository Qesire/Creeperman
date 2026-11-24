#!/usr/bin/env python3
"""Offline capacity arithmetic for Creeperman; inputs are labelled scenarios.

Uses exact Decimal arithmetic for EED thresholds. No network calls, source
sampling, deployment, or attribution of measured yields are performed.
Fractions and means must describe the same globally deduplicated population.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

D = Decimal
DAY = D(86400)


def number(value, *, minimum=None, maximum=None):
    x = D(str(value))
    if not x.is_finite():
        raise ValueError(f"nonfinite value: {value}")
    if minimum is not None and x < D(str(minimum)):
        raise ValueError(f"below minimum: {value}")
    if maximum is not None and x > D(str(maximum)):
        raise ValueError(f"above maximum: {value}")
    return x


def positive(value):
    x = number(value, minimum=0)
    if x == 0:
        raise ValueError("denominator must be positive")
    return x


def fraction(value):
    return number(value, minimum=0, maximum=1)


def ceil_int(value):
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def threshold(baseline_eed, percentage):
    exact = positive(baseline_eed) * positive(percentage) / 100
    return exact, exact.quantize(D("0.0001"), rounding=ROUND_CEILING)


def required_units(gap, unit_yield):
    if gap == 0:
        return 0
    return ceil_int(gap / unit_yield) if unit_yield > 0 else None


def days_needed(gap, request_rate, marginal_yield):
    if gap == 0:
        return D(0)
    rate = request_rate * marginal_yield
    return gap / (DAY * rate) if rate > 0 else None


def calculate(config):
    a, b = config["assumptions"], config["baseline"]
    w = fraction(a["mean_weight_of_qualified_novel_pairs"])
    achieved = number(a["achieved_qualified_novel_eed"], minimum=0)
    rates = [number(v, minimum=0) for v in a["effective_all_request_rates_per_second"]]
    source_bytes = positive(config["observed_source"]["identity_object_bytes"])
    output = {"schema_version": 1, "as_of": config["as_of"],
              "status": config["status"], "baseline_id": b["id"],
              "null_semantics": {
                  "required_units_or_days": "Positive target with zero throughput or yield is unreachable under that scenario",
                  "fraction_of_remaining_gate": "Undefined when the remaining gap is zero"
              },
              "targets": []}
    for pct in a["target_percentages"]:
        exact, attainable = threshold(b["eed"], pct)
        gap = max(D(0), attainable - achieved)
        result = {"target_percent": D(pct), "exact_threshold_eed": exact,
                  "minimum_four_decimal_eed": attainable, "remaining_attainable_gap_eed": gap,
                  "qualified_novel_pairs_required_at_assumed_mean_weight": required_units(gap, w),
                  "source_inventory": [], "contributing_hosts": [], "request_scenarios": [],
                  "host_query_scenarios": [], "bulk_scenarios": [], "worker_scaling": [],
                  "review_effort": []}
        for q0 in a["joint_qualified_novel_fractions"]:
            q = fraction(q0)
            result["source_inventory"].append({"joint_qualified_novel_fraction": q,
                "candidate_host_years_required": required_units(gap, q*w)})
        for k0 in a["mean_novel_years_per_contributing_host"]:
            k = number(k0, minimum=1, maximum=len(b["core_years"]))
            result["contributing_hosts"].append({"mean_new_years": k,
                "contributing_hosts_required": required_units(gap, k*w)})
        for g0 in a["marginal_eed_per_all_request"]:
            g = number(g0, minimum=0)
            for r in rates:
                result["request_scenarios"].append({"effective_requests_per_second": r,
                    "eed_per_all_request": g, "days": days_needed(gap, r, g),
                    "requests_required": required_units(gap, g)})
        result["horizon_requirements"] = [{"days": positive(t),
            "required_eed_per_day": gap/positive(t),
            "required_eed_per_second": gap/(DAY*positive(t))} for t in a["horizon_days"]]
        for item in a["host_query_scenarios"]:
            p = fraction(item["contributing_host_fraction"])
            k = number(item["mean_novel_years_if_contributing"], minimum=1, maximum=len(b["core_years"]))
            requests = positive(item["mean_requests_per_attempted_host"])
            host_yield = p*k*w
            g = host_yield/requests
            result["host_query_scenarios"].append({**item,
                "eed_per_attempted_host": host_yield, "eed_per_all_request": g,
                "attempted_hosts_required": required_units(gap, host_yield),
                "requests_required": required_units(gap, g),
                "days_at_each_effective_rate": [{"rps": r, "days": days_needed(gap,r,g)} for r in rates]})
        for item in a["bulk_scenarios"]:
            rows = source_bytes/positive(item["mean_identity_bytes_per_row"])
            pairs = rows*fraction(item["valid_target_row_fraction"])*fraction(item["global_unique_pairs_per_valid_target_row"])
            eed = pairs*fraction(item["joint_qualified_novel_fraction"])*w
            result["bulk_scenarios"].append({**item, "scenario_raw_rows": rows,
                "scenario_distinct_target_candidate_pairs": pairs,
                "scenario_novel_qualified_eed": eed,
                "fraction_of_remaining_gate": eed/gap if gap else None,
                "scenario_inventory_reaches_remaining_gate": eed >= gap})
        scale = a["worker_scaling"]
        for n in scale["homogeneous_workers"]:
            active = number(scale["active_requests_per_worker_second"], minimum=0)
            workers = number(n, minimum=1)
            duty = fraction(scale["duty_fraction"])
            budget = number(scale["project_provider_rate_budget"], minimum=0)
            offered = workers*active*duty
            r_upper = min(offered, budget)
            r_synchronized = duty*min(workers*active, budget)
            g = number(scale["eed_per_all_request"], minimum=0)
            result["worker_scaling"].append({"workers": n, "offered_average_rps": offered,
                "ideal_staggered_upper_bound_rps": r_upper,
                "ideal_staggered_lower_bound_days": days_needed(gap,r_upper,g),
                "synchronized_downtime_average_rps": r_synchronized,
                "synchronized_downtime_conditional_days": days_needed(gap,r_synchronized,g),
                "scope": scale["scope"]})
        pairs = required_units(gap,w)
        for f0 in a["manual_review_fractions"]:
            f = fraction(f0)
            count = ceil_int(D(pairs)*f) if pairs is not None else None
            result["review_effort"].append({"review_fraction":f,"pairs_to_review":count,
                "hours": D(count)*positive(a["seconds_per_manually_reviewed_pair"])/3600 if count is not None else None})
        output["targets"].append(result)
    output["ideal_identity_transfer_minutes"] = []
    for mbps0 in a["ideal_wire_megabits_per_second"]:
        mbps = positive(mbps0)
        denominator = mbps*1000000*60
        output["ideal_identity_transfer_minutes"].append({"mbps":mbps,
            "source_minutes":source_bytes*8/denominator,
            "baseline_minutes":positive(b["annual_text_bytes"])*8/denominator})
    output["index_task_logical_mib"] = positive(a["index_task_logical_mib"])
    output["source_index_task_count"] = ceil_int(source_bytes/(output["index_task_logical_mib"]*1024*1024))
    p = config["price_snapshot"]
    output["list_price_examples"] = [{"regional_workers":n,
        "probe_monthly_usd":D(p["control_2gib_1vcpu_monthly"])+D(n)*D(p["probe_worker_1gib_1vcpu_monthly"])+D(p["shared_object_storage_base_monthly"]),
        "processing_monthly_usd":D(p["control_2gib_1vcpu_monthly"])+D(n)*D(p["regional_worker_4gib_2vcpu_monthly"])+D(p["shared_object_storage_base_monthly"])} for n in p["worker_counts"]]
    output["price_snapshot"] = p
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,default=Path(__file__).with_name("capacity_scenarios_20261124.json"))
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    raw=args.config.read_bytes()
    result=calculate(json.loads(raw))
    result["config_sha256"]=hashlib.sha256(raw).hexdigest()
    result["estimator_sha256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    encoded=json.dumps(result,ensure_ascii=False,indent=2,default=str)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(encoded,encoding="utf-8")
        print(f"Wrote scenario arithmetic to {args.output}")
    else:
        print(encoded,end="")


if __name__=="__main__":
    main()
