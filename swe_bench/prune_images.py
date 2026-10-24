#!/usr/bin/env python3
"""dgm-config: keep the Docker disk bounded during long SWE-bench runs.

Instance images (sweb.eval.*) are ~0.35 GB each and pile up while the agent
phase runs: 100 instances is ~35 GB that is only needed later, at eval time.
Env images (sweb.env.*) are ~2.8 GB each and, with cache_level=none and
clean=False, are *kept* because they existed before the eval run - across 40
unique envs that reaches ~112 GB.

This pruner reclaims the first group. It only deletes instance images whose
prediction file already exists (so the agent's work is safely on disk) and that
no container is using. Eval simply rebuilds them (2-3 min each) when needed.

Run it alongside the agent phase and stop it before eval:

    python swe_bench/prune_images.py --pred-dir <dir> --min-free-gb 25

Nothing is deleted while free space is above --min-free-gb, so a roomy disk
keeps the fast path (eval finds images already built).
"""
import argparse
import pathlib
import shutil
import subprocess
import sys
import time


def sh(*args, check=False):
    return subprocess.run(args, capture_output=True, text=True, check=check)


def free_gb(path="/"):
    return shutil.disk_usage(path).free / 1e9


def images():
    out = sh("docker", "images", "--format", "{{.Repository}}:{{.Tag}}|{{.CreatedAt}}")
    rows = []
    for line in out.stdout.splitlines():
        name, _, created = line.partition("|")
        if name.startswith("sweb.eval."):
            rows.append((created, name))
    rows.sort()  # oldest first
    return rows


def in_use():
    out = sh("docker", "ps", "-a", "--format", "{{.Image}}")
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def instance_id(image_name):
    # sweb.eval.x86_64.<instance_id>:latest
    parts = image_name.split(".")
    if len(parts) < 4:
        return None
    return parts[3].split(":")[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred-dir", required=True, help="directory holding <instance_id>.json")
    ap.add_argument("--min-free-gb", type=float, default=25.0)
    ap.add_argument("--interval", type=int, default=120)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    pred_dir = pathlib.Path(args.pred_dir)
    print(f"[prune] watching {pred_dir}, threshold {args.min_free_gb:.0f} GB free", flush=True)

    while True:
        have = free_gb()
        if have < args.min_free_gb:
            known = {p.stem for p in pred_dir.rglob("*.json")}
            busy = in_use()
            removed = 0
            reclaimed = 0.0
            for _created, name in images():
                if free_gb() >= args.min_free_gb:
                    break
                iid = instance_id(name)
                if not iid or iid not in known:
                    continue
                if name in busy or f"{name}" in busy:
                    continue
                # keep at least one image per instance is not required; eval rebuilds
                before = free_gb()
                if sh("docker", "rmi", "-f", name).returncode == 0:
                    removed += 1
                    reclaimed += free_gb() - before
            if removed:
                print(
                    f"[prune] removed {removed} instance images "
                    f"(~{reclaimed:.1f} GB), free now {free_gb():.1f} GB",
                    flush=True,
                )
            else:
                print(
                    f"[prune] low on space ({have:.1f} GB) but nothing safe to remove",
                    flush=True,
                )
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
