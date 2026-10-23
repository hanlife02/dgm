"""Minimal, config-driven model + runtime settings for this DGM checkout.

Everything is read from ``models.json`` next to this file (override the path
with the ``DGM_CONFIG`` environment variable).

If the config file, a role, or an alias is missing, the repo falls back to its
original hard-coded defaults (Bedrock Claude 3.5 Sonnet v2 for the coding
agent, o1-2024-12-17 for the diagnosis step), so upstream behaviour is kept.
"""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(ROOT, "models.json")

_cache = {}


def load_config(path=None):
    path = os.path.abspath(path or os.getenv("DGM_CONFIG") or DEFAULT_CONFIG_PATH)
    if path not in _cache:
        cfg = {}
        if os.path.exists(path):
            with open(path) as f:
                cfg = json.load(f)
        _cache[path] = cfg
    return _cache[path]


def models():
    return load_config().get("models") or {}


def model_entry(alias):
    """Return the config entry for a model alias, or None if it is not one."""
    if not alias:
        return None
    return models().get(alias)


def active_model(role, default=None):
    """Resolve active.<role> to a configured alias, else the given default."""
    alias = (load_config().get("active") or {}).get(role)
    if alias and alias in models():
        return alias
    return default


def coding_model(default="bedrock/us.anthropic.claude-3-5-sonnet-20241022-v2:0"):
    return active_model("coding", default)


def diagnose_model(default="o1-2024-12-17"):
    return active_model("diagnose", default)


def api_key(entry):
    key = (entry or {}).get("api_key") or ""
    if not key and (entry or {}).get("api_key_env"):
        key = os.getenv(entry["api_key_env"], "")
    return key or "EMPTY"


def int_setting(section, key, default):
    try:
        return int((load_config().get(section) or {}).get(key, default))
    except (TypeError, ValueError):
        return default


def subset(name, default):
    """Subset file name used for SWE-bench small/medium task lists."""
    return (load_config().get("swe_bench") or {}).get(name, default)
