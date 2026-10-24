#!/usr/bin/env bash
# dgm-config: host-side watchdog for the full 500-instance run.
#
# Guards against the two interruptions that actually happen on this box:
#   * the dev container stops (docker restart / OOM / reboot)
#   * the in-container driver dies (SSH drop, stray kill, python traceback)
#
# Both are repaired here: the container is re-created through docker/run-dev.sh
# (which re-applies the SWE-bench patches), and swe_bench/run_forever.sh is
# restarted inside it. run_batches.sh skips finished batches and harness.py
# skips instances that already have a prediction, so restarting loses at most
# the instances that were mid-flight.
#
# Usage (host, detached):
#   setsid nohup bash swe_bench/watchdog_host.sh >/dev/null 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."
REPO=$(pwd)

LOG=dgm_full500.log
EXPECTED=${EXPECTED:-500}
WORKERS=${WORKERS:-5}
EVAL_PROCS=${EVAL_PROCS:-5}
CACHE_LEVEL=${CACHE_LEVEL:-none}
CONTAINER=${CONTAINER:-dgm-dev}

container_up() {
  docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"
}

driver_up() {
  docker exec "$CONTAINER" pgrep -f "swe_bench/run_forever.sh" >/dev/null 2>&1 \
    || docker exec "$CONTAINER" pgrep -f "bash swe_bench/run_batches.sh" >/dev/null 2>&1
}

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

for attempt in $(seq 1 2000); do
  note="== watchdog_host $attempt $(date -u +%Y-%m-%dT%H:%M:%SZ)"

  if ! container_up; then
    echo "$note container down -> re-creating" >> "$LOG"
    DGM_PROXY="" \
    HF_ENDPOINT=${HF_ENDPOINT:-https://hf-mirror.com} \
    SWE_GITHUB_MIRROR=${SWE_GITHUB_MIRROR:-https://ghfast.top/https://github.com/} \
    DGM_APT_MIRROR=${DGM_APT_MIRROR:-mirrors.ustc.edu.cn} \
    DGM_PIP_INDEX_URL=${DGM_PIP_INDEX_URL:-https://mirrors.ustc.edu.cn/pypi/simple} \
    DGM_EMPTY_RETRIES=${DGM_EMPTY_RETRIES:-60} \
    DGM_EMPTY_BACKOFF_MAX=${DGM_EMPTY_BACKOFF_MAX:-5} \
    DGM_MAX_NUDGES=${DGM_MAX_NUDGES:-10} \
      ./docker/run-dev.sh >> "$LOG" 2>&1
    sleep 30
    continue
  fi

  n=$(submitted_count)
  if [ "${n:-0}" -ge "$EXPECTED" ]; then
    echo "$note done: submitted=$n/$EXPECTED" >> "$LOG"
    break
  fi

  if ! driver_up; then
    echo "$note driver down (submitted=$n/$EXPECTED) -> restarting" >> "$LOG"
    docker exec -d "$CONTAINER" bash -lc \
      "cd $REPO && WORKERS=$WORKERS EVAL_PROCS=$EVAL_PROCS CACHE_LEVEL=$CACHE_LEVEL RUN_ID=full500 nohup bash swe_bench/run_forever.sh >> $REPO/$LOG 2>&1 &"
  fi

  sleep 180
done
