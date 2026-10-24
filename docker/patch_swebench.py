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

# ------------------------------------------------- clone retry (429 handling)
TEST_SPEC = os.path.join(TARGET, "swebench/harness/test_spec.py")
CLONE_MARKER = "_dgm_clone_retry"
OLD_CLONE = (
    '        f"git clone -o origin https://github.com/{repo} {repo_directory}",'
)
NEW_CLONE = '''        # _dgm_clone_retry: GitHub mirrors answer HTTP 429 under parallel load,
        # so retry the clone with backoff instead of failing the image build.
        # cd / first: the Dockerfile sets WORKDIR /testbed, so removing /testbed
        # mid-loop would leave the shell in a deleted directory.
        f"cd / && for _dgm_i in 1 2 3 4 5 6 7 8; do git clone -o origin https://github.com/{repo} {repo_directory} && break; echo \\"clone attempt $_dgm_i failed\\"; rm -rf {repo_directory}; sleep $((_dgm_i * 15)); done",
        f"test -d {repo_directory}",'''

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


def patch_clone_retry():
    """Retry `git clone` in the generated instance setup script.

    GitHub mirrors (ghfast.top et al.) answer HTTP 429 when several image
    builds clone in parallel, which fails the whole instance image with exit
    code 128. A short retry loop with backoff rides that out.
    """
    src = _read(TEST_SPEC)
    if CLONE_MARKER in src:
        print(f"skip  {TEST_SPEC} (clone retry already patched)")
        return
    if OLD_CLONE not in src:
        raise SystemExit(f"FAIL: clone command not found in {TEST_SPEC}")
    src = src.replace(OLD_CLONE, NEW_CLONE, 1)
    with open(TEST_SPEC, "w") as f:
        f.write(src)
    print(f"patch {TEST_SPEC} (clone retry)")


def main():
    if PROXY_ONLY:
        patch_proxy()
    if MIRROR_ONLY:
        patch_git_mirror()
        patch_clone_retry()


if __name__ == "__main__":
    main()
