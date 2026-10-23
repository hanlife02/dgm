"""List model ids served by the configured gateway (uses models.json key)."""
import json
import urllib.request

import dgm_config

alias = dgm_config.coding_model()
entry = dgm_config.model_entry(alias)
base = (entry.get("base_url") or "").rstrip("/")
key = dgm_config.api_key(entry)
print(f"gateway: {base}  configured model: {entry.get('model')}\n")

req = urllib.request.Request(base + "/models", headers={"Authorization": "Bearer " + key})
with urllib.request.urlopen(req, timeout=20) as r:
    data = json.load(r)

ids = sorted(m.get("id", "?") for m in data.get("data", []))
print(f"models available: {len(ids)}")
for i in ids:
    print(" ", i)
