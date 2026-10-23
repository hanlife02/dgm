"""Print the active models.json config with the API key masked."""
import json
import os
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "models.json"
cfg = json.load(open(path))

print("active:", cfg.get("active"))
for alias, m in (cfg.get("models") or {}).items():
    key = m.get("api_key") or ""
    if not key:
        masked = "<empty: falls back to api_key_env=%s>" % m.get("api_key_env")
    elif len(key) > 12:
        masked = key[:6] + "..." + key[-4:]
    else:
        masked = "<short:%d chars>" % len(key)
    print(
        "%s: provider=%s base_url=%s model=%s key=%s temperature=%s max_tokens=%s"
        % (
            alias,
            m.get("provider"),
            m.get("base_url"),
            m.get("model"),
            masked,
            m.get("temperature"),
            m.get("max_tokens"),
        )
    )
print("concurrency:", cfg.get("concurrency"))
print("swe_bench:", cfg.get("swe_bench"))
