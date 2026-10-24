#!/usr/bin/env bash
# dgm-config: keep the batch driver alive on a shared, sometimes unstable box.
#
# A full Verified run takes days, and anything can interrupt it: an SSH drop,
# a container restart, a stray OOM. run_batches.sh already skips finished
# batches, and harness.py skips instances that already have a prediction, so
# simply re-running it is safe. This wrapper does that until `submitted`
# reaches EXPECTED.
#
# Usage: WORKERS=5 EVAL_PROCS=5 nohup bash swe_bench/run_forever.sh &
set -uo pipefail
cd "$(dirname "$0")/.."

LOG=${LOG:-dgm_full500.log}
EXPECTED=${EXPECTED:-500}

submitted_count() {
  python3 - <<'PY'
import json
try:
    with open("swe_bench/batches_out/summary.json") as fh:
        print(json.load(fh)["summary"].get("submitted", 0))
except Exception:
    print(0)
PY
}

for attempt in $(seq 1 1000); do
  # Never run two drivers at once: wait for an already-running one to exit.
  while pgrep -f "bash swe_bench/run_batches.sh" >/dev/null 2>&1; do
    sleep 60
  done
  echo "== watchdog attempt $attempt start $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
  bash swe_bench/run_batches.sh >> "$LOG" 2>&1
  n=$(submitted_count)
  echo "== watchdog attempt $attempt end $(date -u +%Y-%m-%dT%H:%M:%SZ) submitted=$n/$EXPECTED" >> "$LOG"
  if [ "${n:-0}" -ge "$EXPECTED" ]; then
    echo "== watchdog: target reached, stopping" >> "$LOG"
    break
  fi
  sleep 120
done
