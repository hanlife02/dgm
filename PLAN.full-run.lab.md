# 在 `lab`（80 核 / 503 GB / 8×4090）上跑 DGM 的方案

本文是 `new-ethan` 上跑通后的迁移说明。`new-ethan`（8 vCPU / 7 GB / 数据盘 120 MB/s）只够跑 3 题 smoke，
全量必须换机器；`lab` 是候选。

## 1. 机器实测

| 项 | 值 | 对 DGM 的意义 |
|---|---|---|
| CPU | 2× Xeon Gold 6248，80 线程 | 评测并发可开到 8–16 |
| 内存 | 503 GiB（可用 ~470） | 不再是瓶颈 |
| GPU | 8× RTX 4090，其中 6 张空闲 | DGM harness 不用 GPU；可用于自建 vLLM |
| `/` | SSD 894 GB，剩 **85 GB**（90% 已用） | Docker `data-root` 默认在这，全量不够 |
| `/data` | 63.7 TB RAID，剩 14 TB，写速 **71 MB/s** | 镜像适合放这，但比 SSD 慢 |
| Docker | 25.0.5，overlay2，**已给 `yanghan` docker 组** | 评测容器可用 |
| 网络 | pypi/conda/`archive.ubuntu.com` 通；**github / huggingface / docker.io 直连不通** | 用 `ghfast.top`、`hf-mirror.com`、`mirrors.ustc.edu.cn` |

## 2. 已验证可用（本次会话实测）

- `docker run` / `docker pull`：通（国内加速源 `docker.m.daocloud.io` 对普通镜像有效）
- `docker-py` 从 dev 容器访问宿主 daemon：`ping: True`
- 网关 `http://8.130.71.10:12034/v1`：容器内 38 ms，`check_llm.py` 两角色都返回 `ok`
- HF 数据集 `princeton-nlp/SWE-bench_Verified`：`HF_ENDPOINT=https://hf-mirror.com`，500 条，47 s
- `dgm-dev` 镜像：Python 3.11.17 + SWE-bench `dc4c087c`，构建通过

## 3. 为这台机器新增的补丁（都已带 `# dgm-config` / 文档化）

| 文件 | 改动 | 原因 |
|---|---|---|
| `docker/Dockerfile.dev` | `ARG SWE_BENCH_REPO`（镜像 clone）、`ARG APT_MIRROR`、`ARG PIP_INDEX_URL` | GitHub 不通 → `ghfast.top`；`deb.debian.org` 不通 → `mirrors.ustc.edu.cn` |
| `docker/run-dev.sh` | `DGM_PROXY=""` 表示"无代理"（`${VAR-}` 而非 `${VAR:-}`）；透传 `HF_ENDPOINT` / `DGM_APT_MIRROR` / `DGM_PIP_INDEX_URL` | 用 `:-` 时空值会被替换成默认代理，导致 apt 全挂 |
| `Dockerfile`（仓库根，DGM 运行时镜像） | 固定 `python:3.10-slim-bookworm`，加 `APT_MIRROR` / `PIP_INDEX_URL` 构建参数 | 同上：容器内 `apt-get update` 需要镜像源 |
| `utils/docker_utils.py` | 把 `DGM_APT_MIRROR` / `DGM_PIP_INDEX_URL` 作为 build args 传给 `client.images.build` | docker-py 不会自动透传 |
| `docker/patch_swebench.py` | 新增 git 镜像注入：给 SWE-bench 生成的 base/env/instance Dockerfile 加 `url.<mirror>.insteadOf https://github.com/` | `setup_repo.sh` 里的 `git clone github.com/...` 在 lab 上退出码 128 |
| `swe_bench/subsets/verified.json` | 新增，Verified 全部 500 条 id | 全量评测用 |

启动命令（lab 专用）：

```bash
cd /data/ckpt/yanghan/agent-rsi/01-DGM-2505.22954/repo
DGM_PROXY="" \
HF_ENDPOINT=https://hf-mirror.com \
SWE_GITHUB_MIRROR=https://ghfast.top/https://github.com/ \
DGM_APT_MIRROR=mirrors.ustc.edu.cn \
DGM_PIP_INDEX_URL=https://mirrors.ustc.edu.cn/pypi/simple \
SWE_BENCH_REPO=https://ghfast.top/https://github.com/SWE-bench/SWE-bench.git \
./docker/run-dev.sh
```

> `SWE_GITHUB_MIRROR` 必须是**前缀保留式**（`https://ghfast.top/https://github.com/`），
> 因为 `insteadOf` 是纯字符串前缀替换。写成 `https://ghfast.top/` 会得到
> `https://ghfast.top/django/django/` → 403。

## 4. 存储：全量前必须解决

DGM 的评测镜像 ≈ `sweb.base` 2.2 GB + 每个 env 版本 4.0 GB + 每个实例增量 0.6 GB。
（实测 new-ethan：3 题 smoke 共 1 个 env 镜像，合计 11 GB。）

| 规模 | 实例数 | 估计镜像占用 |
|---|---|---|
| smoke | 3 | ~11 GB |
| 上游默认 small+medium+big | 10+50+140 = 200 | **300–500 GB** |
| Verified 全量 | 500 | **600–1000 GB** |

`/` 只剩 85 GB → 全量必须把镜像放 `/data`。三种做法：

1. **独立 daemon（推荐，需要 root 一次）**
   ```bash
   sudo dockerd --data-root /data/ckpt/yanghan/docker \
                --host unix:///run/yanghan-docker.sock --group docker \
                --registry-mirror https://docker.m.daocloud.io
   export DOCKER_HOST=unix:///run/yanghan-docker.sock
   ```
   不影响系统 daemon / 别人的 14 个容器。
2. 改系统 `data-root`（影响所有人，不推荐）。
3. 只跑 smoke/小规模时直接留在 `/`（85 GB 够 20 个实例左右）。

## 5. 规模与时间估算

分三档，按需选：

| 档 | 参数 | 实例评测量 | 估算 |
|---|---|---|---|
| A. smoke（已验证） | `--max_generation 1 --selfimprove_size 1 --shallow_eval` | 3 | ~1 小时（含首次建镜像） |
| B. 论文口径 | `--max_generation 80 --selfimprove_size 2`，small=10 / medium=50 / big=140 | 80 代 × 2×10 + 偶发 50/140 | **数天～两周**（和论文"约两周"一致） |
| C. 单轮全量评测 | `swe_bench/subsets/verified.json`（500） | 500 | **10–25 小时**（8–16 并发） |

时间瓶颈是镜像构建（新建一次）+ 每个实例的 agent 交互与测试执行，不是 CPU。

> ⚠️ SWE-bench 官方的预构建镜像（`swebench/sweb.eval.x86_64.*`）在国内加速源上
> **拉不到**（实测 daocloud 白名单拒绝、hub.rat.dev / docker.1ms.run 报 manifest unknown），
> 只能在 lab 上本地构建。首次全量会有一大段构建时间。

## 6. 配置要点

`models.json`（`concurrency` 段）：

```json
{
  "concurrency": { "harness_workers": 8, "eval_procs": 4, "num_evals_parallel": 1 },
  "swe_bench":   { "small": "smoke.json", "medium": "smoke.json" }
}
```

- `harness_workers`：lab 上 8–16 合理；`new-ethan` 是 1。
- 全量评测：把 `swe_bench.small` 改成 `verified.json`（或 `big.json` 140 题）。
- 换配置后必须 `docker rmi dgm`（`dgm` 镜像烘焙了 `models.json`）。
- 共享机器：构建/评测期间建议 `nice -n 10` + 并发不超过 12，避免拖慢别人的训练数据读取。

## 7. 执行清单

```bash
# 0. 环境（一次性）
DGM_PROXY="" HF_ENDPOINT=https://hf-mirror.com \
DGM_APT_MIRROR=mirrors.ustc.edu.cn \
DGM_PIP_INDEX_URL=https://mirrors.ustc.edu.cn/pypi/simple \
SWE_BENCH_REPO=https://ghfast.top/https://github.com/SWE-bench/SWE-bench.git \
./docker/run-dev.sh

# 1. 冒烟
docker exec -d dgm-dev bash -lc "cd <repo> && python DGM_outer.py \
  --max_generation 1 --selfimprove_size 1 --selfimprove_workers 1 \
  --shallow_eval --no_full_eval > dgm_run1.log 2>&1"

# 2. 全量（切 verified.json 后）
docker rmi -f dgm
docker exec -d dgm-dev bash -lc "cd <repo> && python DGM_outer.py \
  --max_generation 1 --selfimprove_size 1 --selfimprove_workers 1 \
  --shallow_eval --no_full_eval > dgm_full.log 2>&1"
```

## 8. 已知风险

1. 部分 env 规格的 `setup_env.sh` 会从 github / pyenv 拉资源 → 这些实例会报错（按 error 计，不影响其他实例）。
2. `files.pythonhosted.org` 偶发不稳 → 用 `PIP_INDEX_URL` 指向 ustc 可绕过。
3. `/data` 是机械 RAID（71 MB/s），`data-root` 放这里会让构建慢于放 SSD；并行构建数量要控制。
4. 共享机器 18 人在线，2 张 4090 已被别人占满；我们只用 CPU/磁盘，不碰 GPU。
