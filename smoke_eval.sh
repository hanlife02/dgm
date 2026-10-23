#!/usr/bin/env bash
# Validate the DGM -> SWE-bench eval path on a single instance using an
# existing prediction from initial/predictions (no model API calls involved).
set -uo pipefail
cd "$(dirname "$0")"

mkdir -p /tmp/smoke_preds
cp initial/predictions/initial_0/django__django-10880.json /tmp/smoke_preds/
mkdir -p swe_bench/smoke_eval

exec 2>&1
echo "== start $(date -u +%H:%M:%S) =="
time python -m swe_bench.report \
  --dnames /tmp/smoke_preds \
  --run_ids "${RUN_ID:-smoke_0}" \
  --num_eval_procs 1 \
  --output_dir swe_bench/smoke_eval
echo "== done $(date -u +%H:%M:%S) =="
