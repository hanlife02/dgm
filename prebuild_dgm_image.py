"""Pre-build the 'dgm' image the way self_improve_step.py does, then clean up.

Validates that (a) the repo Dockerfile builds with the proxy build args and
(b) the resulting image has the config files DGM needs at runtime.
"""
import os
import sys

import docker

from utils.docker_utils import build_dgm_container, cleanup_container

root = os.path.abspath(os.getcwd())
client = docker.from_env()
container = build_dgm_container(
    client, root, "dgm", "dgm-prebuild-check", force_rebuild=True
)
if container is None:
    sys.exit("build/start failed")

try:
    for path in ("/dgm/models.json", "/dgm/dgm_config.py", "/dgm/coding_agent.py"):
        out = container.exec_run(f"test -f {path}")
        print(f"{path}: {'ok' if out.exit_code == 0 else 'MISSING'}")
    out = container.exec_run(
        ["python", "-c",
         "import sys; sys.path.insert(0,'/dgm'); import dgm_config; "
         "print('coding_model:', dgm_config.coding_model()); "
         "print('diagnose_model:', dgm_config.diagnose_model())"],
        workdir="/dgm",
    )
    print(out.output.decode().strip())
finally:
    cleanup_container(container)
    client.containers.prune()
print("dgm image ready")
