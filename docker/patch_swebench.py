"""Patch the installed SWE-bench checkout so image builds work on this host.

Two independent fixes, both idempotent, run once per container start
(docker/run-dev.sh does):

1. Proxy build args. SWE-bench calls the Docker API (docker-py) directly and
   docker-py does not forward `http_proxy`/`https_proxy` from the environment
   the way the docker CLI does, so on proxy-only hosts every build dies in
   `apt-get update`.

2. Git mirror. SWE-bench generates setup_repo.sh / setup_env.sh scripts that
   clone from github.com; on networks where github.com is unreachable the
   instance image build fails with exit code 128. Setting SWE_GITHUB_MIRROR
   (e.g. https://ghfast.top/) makes every build configure
   `url.<mirror>.insteadOf https://github.com/` before doing any git work.

Usage: python patch_swebench.py [SWE_BENCH_DIR] [--no-proxy] [--no-mirror]
"""
import os
import sys

TARGET = "/opt/SWE-bench"
PROXY_ONLY = True
MIRROR_ONLY = True
for _arg in sys.argv[1:]:
    if _arg == "--no-proxy":
        PROXY_ONLY = False
    elif _arg == "--no-mirror":
        MIRROR_ONLY = False
    elif not _arg.startswith("-"):
        TARGET = _arg

# ---------------------------------------------------------------- proxy args
PATH = os.path.join(TARGET, "swebench/harness/docker_build.py")
MARKER = "_dgm_proxy_buildargs"
DOCKERFILES = os.path.join(TARGET, "swebench/harness/dockerfiles.py")
MIRROR_MARKER = "_dgm_git_mirror"

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

MIRROR_BLOCK = '''

# dgm-config: route GitHub clones through a mirror when github.com is blocked.
# Set SWE_GITHUB_MIRROR (e.g. https://ghfast.top/) in the harness environment;
# unset means upstream behaviour (clone straight from github.com).
import os as _os  # noqa: E402

_dgm_git_mirror = _os.environ.get("SWE_GITHUB_MIRROR", "")
if _dgm_git_mirror:
    _dgm_git_cfg_run = (
        'RUN git config --global url."%s".insteadOf "https://github.com/"\\n'
        % _dgm_git_mirror
    )
    _dgm_anchors = {
        "_DOCKERFILE_BASE": "\\nRUN apt update",
        "_DOCKERFILE_ENV": "\\nCOPY ./setup_env.sh",
        "_DOCKERFILE_INSTANCE": "\\nCOPY ./setup_repo.sh",
    }
    for _dgm_name, _dgm_anchor in _dgm_anchors.items():
        _dgm_tmpl = globals().get(_dgm_name)
        if _dgm_tmpl and _dgm_anchor in _dgm_tmpl and "insteadOf" not in _dgm_tmpl:
            globals()[_dgm_name] = _dgm_tmpl.replace(
                _dgm_anchor,
                "\\n" + _dgm_git_cfg_run + _dgm_anchor.lstrip("\\n"),
                1,
            )
'''


def _read(path):
    with open(path) as f:
        return f.read()


def patch_proxy():
    src = _read(PATH)
    if MARKER in src:
        print(f"skip  {PATH} (proxy buildargs already patched)")
        return
    if OLD not in src:
        raise SystemExit(f"FAIL: build call not found in {PATH} (SWE-bench layout changed)")
    if "\nimport os\n" not in src:
        src = src.replace("import logging\nimport re\n", "import logging\nimport os\nimport re\n", 1)
    src = src.replace(OLD, NEW, 1)
    with open(PATH, "w") as f:
        f.write(src)
    print(f"patch {PATH} (proxy buildargs)")


def patch_git_mirror():
    src = _read(DOCKERFILES)
    if MIRROR_MARKER in src:
        print(f"skip  {DOCKERFILES} (git mirror already patched)")
        return
    with open(DOCKERFILES, "a") as f:
        f.write(MIRROR_BLOCK)
    print(f"patch {DOCKERFILES} (git mirror)")


def main():
    if PROXY_ONLY:
        patch_proxy()
    if MIRROR_ONLY:
        patch_git_mirror()


if __name__ == "__main__":
    main()
