#!/usr/bin/env bash
# Start (or restart) the DGM dev container.
#
#   ./docker/run-dev.sh          # build image if missing, then (re)start container
#   NAME=dgm-dev ./docker/run-dev.sh
#
# Design notes:
#  * The repo is bind-mounted at its *identical* absolute path. DGM's
#    self_improve_step builds the "dgm" image from that path via the host
#    Docker daemon, so the path must exist on the host as-is.
#  * /var/run/docker.sock is mounted so the in-container DGM code can talk to
#    the host daemon (DGM executes untrusted model-generated code: run this
#    only on a machine you are willing to treat as disposable).
#  * Proxy + API-key env vars are forwarded if set on the host.
set -euo pipefail

REPO_HOST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${NAME:-dgm-dev}"
IMAGE="${IMAGE:-dgm-dev}"

# This host reaches the internet through a proxy bound to 127.0.0.1:7890.
# Containers cannot see 127.0.0.1, so use the docker bridge gateway instead.
# Set DGM_PROXY="" on hosts that have direct internet access (the `-` form
# below keeps an explicit empty value instead of falling back to the default).
DGM_PROXY="${DGM_PROXY-http://172.17.0.1:7890}"
DGM_NO_PROXY="${DGM_NO_PROXY:-localhost,127.0.0.1,::1,172.17.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.local,.internal}"

PROXY_ARGS=()
if [ -n "$DGM_PROXY" ]; then
  PROXY_ARGS=(
    --build-arg http_proxy="$DGM_PROXY" \
    --build-arg https_proxy="$DGM_PROXY" \
    --build-arg HTTP_PROXY="$DGM_PROXY" \
    --build-arg HTTPS_PROXY="$DGM_PROXY" \
    --build-arg no_proxy="$DGM_NO_PROXY" \
    --build-arg NO_PROXY="$DGM_NO_PROXY"
  )
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo ">> building image $IMAGE"
  docker build -f "$REPO_HOST/docker/Dockerfile.dev" -t "$IMAGE" \
    "${PROXY_ARGS[@]}" \
    ${SWE_BENCH_REPO:+--build-arg SWE_BENCH_REPO="$SWE_BENCH_REPO"} \
    ${APT_MIRROR:+--build-arg APT_MIRROR="$APT_MIRROR"} \
    ${PIP_INDEX_URL:+--build-arg PIP_INDEX_URL="$PIP_INDEX_URL"} \
    "$REPO_HOST"
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true

CACHE_DIR="${DGM_CACHE_DIR:-$(cd "$REPO_HOST/.." && pwd)/.dgm-cache}"
mkdir -p "$CACHE_DIR"

DOCKER_GID="$(stat -c %g /var/run/docker.sock 2>/dev/null || echo 0)"

ENV_ARGS=(
  ${DGM_PROXY:+-e http_proxy="$DGM_PROXY" -e https_proxy="$DGM_PROXY" -e all_proxy="$DGM_PROXY"}
  ${DGM_PROXY:+-e HTTP_PROXY="$DGM_PROXY" -e HTTPS_PROXY="$DGM_PROXY" -e ALL_PROXY="$DGM_PROXY"}
  ${DGM_PROXY:+-e no_proxy="$DGM_NO_PROXY" -e NO_PROXY="$DGM_NO_PROXY"}
  -e HOME=/cache -e HF_HOME=/cache/hf -e XDG_CACHE_HOME=/cache/xdg
  -e HF_ENDPOINT
  -e OPENAI_API_KEY -e OPENAI_BASE_URL
  -e ANTHROPIC_API_KEY -e ANTHROPIC_BASE_URL
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_REGION -e AWS_REGION_NAME
  -e HF_TOKEN -e DGM_CONFIG -e SWE_GITHUB_MIRROR
  -e DGM_APT_MIRROR -e DGM_PIP_INDEX_URL
  -e DGM_EMPTY_RETRIES -e DGM_EMPTY_BACKOFF_MAX -e DGM_MAX_NUDGES
)

# Run as the host user so files written into the bind mount stay editable
# from the host; docker socket access comes from --group-add <docker gid>.
docker run -d --name "$NAME" \
  --add-host host.docker.internal:host-gateway \
  --user "$(id -u):$(id -g)" \
  --group-add "$DOCKER_GID" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$REPO_HOST":"$REPO_HOST" \
  -v "$CACHE_DIR":/cache \
  -w "$REPO_HOST" \
  "${ENV_ARGS[@]}" \
  "$IMAGE" sleep infinity

# DGM hardcodes ./swe_bench/SWE-bench; point it at the copy baked into the image.
docker exec "$NAME" bash -lc "ln -sfn /opt/SWE-bench '$REPO_HOST/swe_bench/SWE-bench'"

# docker-py does not forward proxy env vars into `docker build`; make builds work.
docker exec -u 0 "$NAME" python "$REPO_HOST/docker/patch_swebench.py" /opt/SWE-bench

echo ">> container $NAME ready at $REPO_HOST"
echo "   docker exec -it $NAME bash"
