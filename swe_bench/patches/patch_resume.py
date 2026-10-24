"""dgm-config: make swe_bench/harness.py resume inside a batch.

An interrupted batch (SSH drop, container restart, OOM) should not redo the
instances it already predicted. Skip entries whose prediction json exists.
"""
import pathlib
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = root / "swe_bench/harness.py"
src = p.read_text()

if "already predicted" in src:
    print("skip  swe_bench/harness.py (resume already patched)")
    raise SystemExit(0)

OLD = """        # Process entries in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_entry = {
                executor.submit(process_entry, entry, out_dname, model_name_or_path_inst, model_patch_paths): entry
                for entry in entries
            }"""

NEW = """        # dgm-config: skip instances that already have a prediction file so an
        # interrupted batch resumes instead of restarting from scratch.
        _pending = [
            entry
            for entry in entries
            if not (out_dname / (entry["instance_id"] + ".json")).exists()
        ]
        if len(_pending) != len(entries):
            print(
                f"[dgm-config] resuming {out_dname}: "
                f"{len(entries) - len(_pending)}/{len(entries)} already predicted",
                flush=True,
            )
        # Process entries in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_entry = {
                executor.submit(process_entry, entry, out_dname, model_name_or_path_inst, model_patch_paths): entry
                for entry in _pending
            }"""

if OLD not in src:
    raise SystemExit("FAIL: parallel block not found in swe_bench/harness.py")

p.write_text(src.replace(OLD, NEW, 1))
print("patch swe_bench/harness.py (intra-batch resume)")
