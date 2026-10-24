"""dgm-config: dump one empty-reply request so it can be replayed offline.

The gateway returns content=null with completion_tokens>0 on roughly a third
of the coding agent's calls. To find out why, capture the exact request the
first time a call comes back empty: the agent container writes the payload to
/dgm/empty_req.json, which we can copy out while the instance is still running.

Replay it with variations (enable_thinking off, logprobs on, etc.) to see what
the server actually did with the generated tokens.
"""
import pathlib
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = root / "llm.py"
src = p.read_text()

MARKER = "dgm-config: dump the first empty reply"
if MARKER in src:
    print("skip  llm.py (empty dump already patched)")
    raise SystemExit(0)

OLD = "                _empty_retries += 1\n"

NEW = OLD + """                if _empty_retries == 1:
                    # dgm-config: dump the first empty reply for offline replay.
                    try:
                        import json as _json, os as _os
                        _u = getattr(response, "usage", None)
                        _dump = {
                            "request": _req,
                            "finish_reason": getattr(_choice, "finish_reason", None),
                            "usage": _u.model_dump() if _u else None,
                            "raw": response.model_dump_json(),
                        }
                        _path = _os.path.join("/dgm", "empty_req.json")
                        with open(_path, "w") as _fh:
                            _json.dump(_dump, _fh)
                        print(f"[dgm-config] dumped empty request to {_path}", flush=True)
                    except Exception as _exc:  # noqa: BLE001
                        print(f"[dgm-config] dump failed: {_exc}", flush=True)
"""

if OLD not in src:
    raise SystemExit("FAIL: retry block not found in llm.py")

p.write_text(src.replace(OLD, NEW, 1))
print("patch llm.py (dump first empty reply)")
