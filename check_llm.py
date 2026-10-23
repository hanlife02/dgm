"""Smoke-test the model endpoints declared in models.json.

Usage (inside the dev container, repo root):
    python check_llm.py            # test the coding + diagnosis roles
    python check_llm.py coding     # test one role

Makes one tiny call per role, so it costs almost nothing. Use it before
running DGM_outer.py, because a wrong base_url/key/model fails deep inside
the self-improvement loop otherwise.
"""
import sys
import traceback

import dgm_config
from llm import create_client, get_response_from_llm


def test_role(role):
    default = "coding" if role == "coding" else "diagnose"
    alias = dgm_config.coding_model() if role == "coding" else dgm_config.diagnose_model()
    entry = dgm_config.model_entry(alias)
    print(f"\n== role={role} alias={alias}")
    if entry is None:
        print("   not a configured alias -> falls back to the upstream default model")
        return False
    print(f"   provider={entry.get('provider')} base_url={entry.get('base_url')} "
          f"model={entry.get('model')} key={'set' if dgm_config.api_key(entry) != 'EMPTY' else 'EMPTY'}")
    try:
        client, model = create_client(alias)
        response, history = get_response_from_llm(
            msg="Reply with exactly: ok",
            client=client,
            model=model,
            system_message="You are a terse test assistant.",
        )
        print(f"   response: {response!r}")
        return True
    except Exception as e:
        print(f"   FAILED: {type(e).__name__}: {e}")
        traceback.print_exc(limit=3)
        return False


if __name__ == "__main__":
    roles = sys.argv[1:] or ["coding", "diagnose"]
    results = {role: test_role(role) for role in roles}
    print()
    for role, ok in results.items():
        print(f"{role}: {'OK' if ok else 'FAILED'}")
    sys.exit(0 if all(results.values()) else 1)
