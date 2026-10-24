#!/usr/bin/env python3
"""dgm-config: merge the per-batch SWE-bench reports into one cumulative score.

Each batch directory written by swe_bench/run_batches.sh contains an aggregate
report named like `<model_name_or_path>.<run_id>.json` with the keys
resolved_instances / unresolved_instances / error_instances / empty_patch_instances.

Usage: python swe_bench/merge_batches.py swe_bench/batches_out
"""
import glob
import json
import os
import sys


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "swe_bench/batches_out"
    totals = {
        "resolved_instances": 0,
        "unresolved_instances": 0,
        "empty_patch_instances": 0,
        "error_instances": 0,
        "completed_instances": 0,
    }
    ids = {"resolved_ids": [], "unresolved_ids": [], "empty_patch_ids": [], "error_ids": []}
    batches = []

    for path in sorted(glob.glob(os.path.join(root, "*", "*.json"))):
        try:
            with open(path) as fh:
                rep = json.load(fh)
        except Exception:
            continue
        if "resolved_instances" not in rep:
            continue
        batches.append(os.path.basename(os.path.dirname(path)))
        for key in totals:
            totals[key] += rep.get(key, 0)
        for key in ids:
            ids[key].extend(rep.get(key, []) or [])

    submitted = totals["resolved_instances"] + totals["unresolved_instances"]
    accuracy = (totals["resolved_instances"] / submitted) if submitted else 0.0
    summary = {"batches": batches, "submitted": submitted, "accuracy": round(accuracy, 4)}
    summary.update(totals)
    summary.update({k: len(v) for k, v in ids.items()})

    with open(os.path.join(root, "summary.json"), "w") as fh:
        json.dump({"summary": summary, "resolved_ids": ids["resolved_ids"]}, fh, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
