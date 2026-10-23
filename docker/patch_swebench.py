"""Make SWE-bench image builds inherit the proxy settings of this shell.

SWE-bench calls the Docker API (docker-py) directly, and docker-py does not
forward `http_proxy`/`https_proxy` from the environment the way the docker CLI
does. On hosts that can only reach the internet through a proxy, every build
therefore dies in `apt-get update`.

This script patches the installed SWE-bench checkout (default /opt/SWE-bench)
so `client.api.build(...)` gets those variables as build args. It is
idempotent; run it once per container start (docker/run-dev.sh does).
"""
import os
import sys

TARGET = sys.argv[1] if len(sys.argv) > 1 else "/opt/SWE-bench"
PATH = os.path.join(TARGET, "swebench/harness/docker_build.py")
MARKER = "_dgm_proxy_buildargs"

OLD = """        response = client.api.build(
            path=str(build_dir),
            tag=image_name,
            rm=True,
            forcerm=True,
            decode=True,
            platform=platform,
            nocache=nocache,
        )"""

NEW = """        _dgm_proxy_buildargs = {  # patched by dgm docker/patch_swebench.py
            k: os.environ[k]
            for k in (
                "http_proxy", "https_proxy", "no_proxy", "all_proxy",
                "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
            )
            if os.environ.get(k)
        }
        response = client.api.build(
            path=str(build_dir),
            tag=image_name,
            rm=True,
            forcerm=True,
            decode=True,
            platform=platform,
            nocache=nocache,
            buildargs=_dgm_proxy_buildargs,
        )"""


def main():
    with open(PATH) as f:
        src = f.read()
    if MARKER in src:
        print(f"skip  {PATH} (already patched)")
        return
    if OLD not in src:
        raise SystemExit(f"FAIL: build call not found in {PATH} (SWE-bench layout changed)")
    if "\nimport os\n" not in src:
        src = src.replace("import logging\nimport re\n", "import logging\nimport os\nimport re\n", 1)
    src = src.replace(OLD, NEW, 1)
    with open(PATH, "w") as f:
        f.write(src)
    print(f"patch {PATH} (proxy buildargs)")


if __name__ == "__main__":
    main()
