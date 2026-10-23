"""In-container sanity check: imports, config wiring, docker socket, dataset."""
import json
import os
import subprocess
import sys

print("python:", sys.version.split()[0])
print("cwd:", os.getcwd())

import dgm_config

print("models.json:", dgm_config.DEFAULT_CONFIG_PATH,
      "exists" if os.path.exists(dgm_config.DEFAULT_CONFIG_PATH) else "MISSING")
print("coding_model:", dgm_config.coding_model())
print("diagnose_model:", dgm_config.diagnose_model())
print("concurrency:", {k: dgm_config.int_setting("concurrency", k, None)
                       for k in ("harness_workers", "eval_procs", "num_evals_parallel")})
print("swe_bench subsets:", {k: dgm_config.subset(k, None) for k in ("small", "medium")})

import llm
import llm_withtools
import self_improve_step

print("llm_withtools.CLAUDE_MODEL:", llm_withtools.CLAUDE_MODEL)
print("self_improve_step.diagnose_model:", self_improve_step.diagnose_model)

import swebench
print("swebench:", os.path.dirname(swebench.__file__))
print("swe_bench/SWE-bench link ->", os.path.realpath("swe_bench/SWE-bench"))
print("run_evaluation.py exists:",
      os.path.exists("swe_bench/SWE-bench/swebench/harness/run_evaluation.py"))

sub = json.load(open("./swe_bench/subsets/smoke.json"))
print("smoke subset:", sub)

import docker
client = docker.from_env()
print("docker server:", client.version()["Version"])
print("docker socket OK, images visible:", len(client.images.list()))

# configured endpoint reachability (no key needed for a 401/200 probe)
for alias in (dgm_config.coding_model(), dgm_config.diagnose_model()):
    entry = dgm_config.model_entry(alias)
    if not entry:
        print(f"{alias}: not a configured alias (falls back to upstream default)")
        continue
    base = entry.get("base_url")
    print(f"{alias}: base_url={base} model={entry.get('model')} key={'set' if dgm_config.api_key(entry) != 'EMPTY' else 'EMPTY'}")
    try:
        import urllib.request
        req = urllib.request.Request(base.rstrip("/") + "/models",
                                     headers={"Authorization": "Bearer " + dgm_config.api_key(entry)})
        with urllib.request.urlopen(req, timeout=10) as r:
            print("   probe /models ->", r.status)
    except Exception as e:
        print("   probe /models ->", type(e).__name__, str(e)[:120])
