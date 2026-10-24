#!/usr/bin/env bash
# dgm-config: run SWE-bench Verified in resumable batches.
#
# For every swe_bench/subsets/batch/batch*.json:
#   1. harness.py  -> run the coding agent on those instances (writes predictions)
#   2. report.py   -> evaluate the patches and write a report
# Both stages are skipped when the batch already produced a report, so the
# script can be stopped and restarted at any time.
#
# Disk stays bounded because eval runs with DGM_CACHE_LEVEL=none: instance and
# env images are removed as soon as they are no longer needed.
#
# Usage: WORKERS=8 EVAL_PROCS=8 CACHE_LEVEL=none bash swe_bench/run_batches.sh
set -uo pipefail
cd "$(dirname "$0")/.."

BATCH_DIR=${BATCH_DIR:-swe_bench/subsets/batch}
OUT=${OUT:-swe_bench/batches_out}
WORKERS=${WORKERS:-8}
EVAL_PROCS=${EVAL_PROCS:-8}
CACHE_LEVEL=${CACHE_LEVEL:-none}
RUN_ID=${RUN_ID:-dgm$(date +%Y%m%d_%H%M%S)}

mkdir -p "$OUT"

for bf in "$BATCH_DIR"/batch*.json; do
  [ -e "$bf" ] || { echo "no batch files in $BATCH_DIR"; exit 1; }
  name=$(basename "$bf" .json)
  bdir="$OUT/$name"
  pred="$bdir/predictions"
  flat="$bdir/preds_flat"

  if ls "$bdir"/*.json >/dev/null 2>&1; then
    echo "== skip $name (report already present)"
    continue
  fi

  mkdir -p "$pred" "$flat"
  rid="${RUN_ID}_${name}"

  # dgm-config: after the first batch, env images from earlier batches are dead
  # weight (~2.8 GB each, 40 unique envs across Verified = ~112 GB). Batches are
  # env-grouped and share almost no envs, so dropping them costs at most one
  # rebuild. Keep the base image.
  if [ "$name" != "batch01" ]; then
    docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^sweb\.env\.' \
      | xargs -r docker rmi -f >/dev/null 2>&1 || true
  fi

  echo "== [$name] harness start $(date -u +%H:%M:%S) workers=$WORKERS"
  python swe_bench/prune_images.py --pred-dir "$pred" --min-free-gb "${MIN_FREE_GB:-25}" &
  PRUNER=$!
  python -m swe_bench.harness \
    --test_task_list "$bf" \
    --max_workers "$WORKERS" \
    --model_name_or_path "$rid" \
    --pred_dname "$pred"
  echo "== [$name] harness done $(date -u +%H:%M:%S)"

  # Stop the pruner before eval: eval needs the instance images (rebuilding them
  # is the expensive part), and it removes them itself afterwards.
  kill "$PRUNER" >/dev/null 2>&1 || true
  wait "$PRUNER" 2>/dev/null || true

  # harness writes predictions into <pred>/<model>_0/*.json; flatten them
  find "$pred" -name '*.json' -exec cp -n {} "$flat"/ \; 2>/dev/null

  echo "== [$name] eval start $(date -u +%H:%M:%S) procs=$EVAL_PROCS cache_level=$CACHE_LEVEL"
  DGM_CACHE_LEVEL="$CACHE_LEVEL" python -m swe_bench.report \
    --dnames "$flat" \
    --run_ids "$rid" \
    --num_eval_procs "$EVAL_PROCS" \
    --output_dir "$bdir"
  echo "== [$name] eval done $(date -u +%H:%M:%S)"

  python swe_bench/merge_batches.py "$OUT" || true
done

echo "== all batches finished $(date -u +%H:%M:%S)"
python swe_bench/merge_batches.py "$OUT"
