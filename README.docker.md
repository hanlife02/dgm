# DGM 本地可运行版（Docker + 可配置模型网关）

在原始 `jennyzzt/dgm` 上做的**最小改动**，目标是「先跑通」，之后可以直接搬到正式算力服务器。

## 1. 改了什么

| 文件 | 改动 | 目的 |
|---|---|---|
| `dgm_config.py` | **新增**，读取 `models.json` | 模型/并发/子集全部可配 |
| `models.json` | **新增** | 网关 `base_url` / `api_key` / `model`、并发、SWE 子集 |
| `llm.py` | `create_client()` + `get_response_from_llm()` 各加一个 config 分支 | 支持任意 OpenAI 兼容 / Anthropic 兼容端点 |
| `llm_withtools.py` | `CLAUDE_MODEL = coding_model()` | 编码 agent 的模型来自 json |
| `self_improve_step.py` | `diagnose_model` 来自 json；`max_workers` / `num_evals_parallel` / `dnames_workers` / `num_eval_procs` 读 `concurrency` | 并发降到 1–2 |
| `DGM_outer.py` | small/medium 子集文件名读 `swe_bench` 段 | 用 3 题 smoke 子集 |
| `swe_bench/harness.py`, `swe_bench/report.py` | 默认并发 4/5 → 2 | 7 GB 内存机器不 OOM |
| `swe_bench/harness.py` | 见 §8 的 4 处健壮性补丁（clone 攀爬边界、pip 代理、传 config 文件） | 评测阶段真正能跑完 |
| `llm.py` / `llm_withtools.py` | 空响应退避重试 + 原生 tool_calls / reasoning 归一化 + 无工具调用时 nudge | 网关抖动/prompt 不合规时不再静默出空 patch |
| `utils/docker_utils.py` | `images.build(..., buildargs=proxy)` | docker-py 不会自动转发代理 |
| `utils/eval_utils.py` | 兼容纯字符串 message content | 非 Claude 模型的工具结果解析 |
| `docker/*` | **新增** dev 镜像、启动脚本、SWE-bench 代理补丁 | 依赖 + SWE-bench 装在镜像里 |
| `swe_bench/subsets/smoke.json` | **新增** 3 题（同 1 个 env 镜像） | 最小评测集 |
| `.dockerignore` | 加 `!requirements_dev.txt` | 原作者把 dev 依赖排除在 build context 外 |

仓库根目录的 `apply_patch.py` 是幂等打补丁脚本（本次改动已全部落在代码里，重复执行只会 skip：`python apply_patch.py .`），源码改动都带 `# dgm-config` 标记，方便跟上游 diff。

## 2. 起容器

```bash
cd ~/data/agent-rsi/01-DGM-2505.22954/repo
./docker/run-dev.sh            # 首次会 build dgm-dev 镜像（约 5 分钟）
docker exec -it dgm-dev bash
```

要点（脚本已处理，改动前请先读）：

* **仓库以相同绝对路径 bind mount**。`self_improve_step.py` 用宿主 docker daemon 以 `root_dir` 为 build context 构建 `dgm` 镜像，路径必须宿主可见。
* 挂载 `/var/run/docker.sock`（容器内调宿主 daemon）。**等于把宿主机 root 权限交给容器**，DGM 本身会执行模型生成的不可信代码，请只在可弃机器上跑。
* 容器以宿主 uid 运行（`--user 1000:1000` + `--group-add 988`），避免挂载目录里出现 root 文件。
* 代理：宿主 `127.0.0.1:7890` 容器看不见，脚本改写为 `172.17.0.1:7890`；`/opt/SWE-bench` 的 `docker_build.py` 由 `docker/patch_swebench.py` 注入 buildargs，否则 `apt-get` 全挂。
* 缓存目录：`01-DGM-2505.22954/.dgm-cache`（HF 数据集等），容器重启不丢。

## 3. 配置模型（唯一必须做的事）

```bash
cp models.json.example models.json   # models.json 被 .gitignore 忽略, 里面放真实 key
```

编辑 `models.json`：

```json
{
  "active": { "coding": "coding_main", "diagnose": "diagnose_main" },
  "models": {
    "coding_main": {
      "provider": "openai_compatible",
      "base_url": "http://172.17.0.1:8090/v1",
      "api_key": "sk-xxx",
      "model": "claude-sonnet-4-5"
    }
  }
}
```

* `provider`：`openai_compatible`（默认，`/chat/completions`）或 `anthropic`（`/v1/messages`）。
* `base_url`：**从容器看宿主的地址是 `172.17.0.1:<port>`，不是 127.0.0.1**。网关若在别的 docker 网络里，填宿主发布的端口地址即可。
* `api_key` 留空时读 `api_key_env` 指定的环境变量（默认 `OPENAI_API_KEY`）。
* `model` 是发给网关的真实模型 id；`active` 里的值只是别名。
* `temperature` / `max_tokens` 可写 `null` 表示不发送（推理模型常需要这样）。
* 别名不要含 `claude`、不要以 `o3-` 开头 —— 走「手写 `<tool_use>` 标签」的通用工具调用路径，任何 chat 模型可用。想用原生 tool-use 就把别名起成 `claude-*` 并配 `anthropic` provider。

验证：

```bash
docker exec -it dgm-dev python check_llm.py          # 两个角色各发一次 "ok"
docker exec -it dgm-dev python check_env.py          # 环境/依赖/子集/网关可达性
```

**改完 `models.json` 必须删除旧的 `dgm` 镜像**，否则 DGM 复用旧镜像里的旧配置：

```bash
docker rmi dgm
```

## 4. 跑起来

```bash
docker exec -it dgm-dev bash
cd /home/ubuntu/data/agent-rsi/01-DGM-2505.22954/repo

# 最小：1 代、1 次自我改进、只评 smoke 的 3 题
python DGM_outer.py --max_generation 1 --selfimprove_size 1 \
  --selfimprove_workers 1 --shallow_eval --no_full_eval
```

产出：`output_dgm/<run_id>/`（`dgm_metadata.jsonl`、每个 attempt 的 `self_evo.md` / `model_patch.diff` / 评测报告）。

`initial/` 自带的 60 题评测结果直接复用，**不需要重跑基线**。

## 5. 只验证评测链路（不花钱、不调 API）

```bash
bash smoke_eval.sh     # 用 initial/predictions 里已有的 patch 评 smoke 的 3 题
```

已实测通过：`Instances completed: 1, errors: 0`（单题 2 分钟，env 镜像已缓存时）。

## 6. 实测磁盘 / 内存

**宿主机 Docker 存储已迁到数据盘**（这是本机唯一的一次系统级改动）：

| 项 | 位置 | 说明 |
|---|---|---|
| Docker `data-root` | `/home/ubuntu/data/docker` | `daemon.json` 里 `"data-root"`，同时开了 `"live-restore": true` |
| containerd `root`（真正的镜像层） | `/home/ubuntu/data/containerd` | Docker 29 用 containerd 快照器，这 25G 才是大头，`/etc/containerd/config.toml` 里 `root = ...` |

迁移前根盘 48G 只剩 2.9G；迁移后根盘 **22G 空闲**，数据盘 196G 用 37G（**150G 空闲**）。
代价：数据盘写速 **120 MB/s** vs 根盘 **619 MB/s**，所以单个实例镜像构建从约 1 分钟变成 **约 13 分钟**（含 `setup_repo.sh` 里的 pip 安装）。

> ⚠️ **docker daemon 重启后必须重新 `./docker/run-dev.sh`**：容器挂的是 `/var/run/docker.sock` 这个文件，daemon 重启会新建 socket，旧 bind mount 指向失效 inode，DGM 会报 `Connection refused`。

| 组件 | 磁盘 |
|---|---|
| `dgm-dev` 镜像（python3.11 + 全部依赖 + SWE-bench） | **2.2 GB** |
| `sweb.base.x86_64`（SWE-bench 基础镜像） | **2.2 GB** |
| `sweb.env.x86_64.<hash>` 每个 distinct django 版本 | **4.0 GB** |
| `dgm` 镜像（DGM 运行时自建，与 dev 镜像同 base） | **1.4 GB** |
| 每份输出/日志 | < 100 MB |

* 3 题 smoke 子集（`10880/10999/11087`）**共用同一个 env 镜像** → 总计约 **11 GB**。
* 官方 `small.json` 的 10 题跨 4 个 django 版本 → 4 个 env 镜像 ≈ **+12 GB**（合计约 23 GB），数据盘完全放得下。
* 实测环境：8 vCPU / 7 GB RAM。
  * 第一次构建 env 镜像时 **内存不足被 SIGKILL（exit 137）**，加 4 GB swap 后通过（`/swapfile`，已写入 `/etc/fstab`）。
  * 建议正式跑时 ≥16 GB RAM，或保持 `harness_workers=1` + swap。

## 7. 一次完整跑的实测结果（1 代 / 1 次自我改进 / smoke 3 题）

```
python DGM_outer.py --max_generation 1 --selfimprove_size 1 \
  --selfimprove_workers 1 --shallow_eval --no_full_eval
```

`output_dgm/20261022140230_258458/dgm_metadata.jsonl`：

```json
{"generation": 0,
 "selfimprove_entries": [["initial", "solve_contextlength"]],
 "children": ["20261022_140238_377296"],
 "children_compiled": ["20261022_140238_377296"],
 "archive": ["initial", "20261022_140238_377296"]}
```

子节点 `metadata.json` 的 `overall_performance`：

| 指标 | 值 |
|---|---|
| accuracy_score | 0.333 |
| resolved | `django__django-10880` |
| unresolved | `django__django-10999` |
| empty patch | `django__django-11087` |
| errors | 0 |

即：**自改进 → 编译检查 → 打补丁 → 评测 → 报告 → 归档** 全链路走通，分数无意义（smoke 3 题、便宜模型）。

**耗时 79 分钟**，其中约 40 分钟是 3 个实例镜像构建（数据盘 120 MB/s 的代价）、约 20 分钟 agent 交互、其余是 pip / 测试。根盘跑会快 5 倍左右。

### 为跑通加的 4 处 harness 补丁

1. `harness.py` 的「跳转到 `/dgm` 目录」逻辑在 `/` 上 `os.chdir('..')` 永不前进 → 无限循环，5 分钟写 6.8 GB 日志。改成最多 8 跳 / 见 `coding_agent.py` 就停 / 到 `/` 就停（`# dgm-config: bounded climb`）。
2. eval 容器里 `pip install -r /dgm/requirements.txt` 没有代理 → `ConnectTimeoutError` → 每个实例 `Script failed with exit code 1`。给该 `exec_run` 传 `environment=_proxy_env`（`# dgm-config: proxy for pip in the eval container`）。
3. harness 往 eval 容器拷文件是硬编码列表，漏了新加的 `dgm_config.py` / `models.json` → `ModuleNotFoundError: dgm_config`。补两条 `copy_to_container`。
4. `--max_workers` 默认 4 → 2。

### 为网关抖动加的补丁（`llm.py` / `llm_withtools.py`）

模型网关（vLLM 后端）会**成分钟地**返回 `content: null`（`completion_tokens` 非 0，内容被丢弃），偶发十几次全是空。因此：

* `llm.py`：空内容时指数退避重试（20 次、1s→30s 封顶、累计约 7 分钟），从第 3 次起轻微改写 prompt 以免复现同一个确定性空生成；原生 `tool_calls` 与 `reasoning` 字段归一化成 DGM 的 `<tool_use>` 文本格式；最终还是空则把原始响应 dump 出来。
* `llm_withtools.py`：`except Exception: pass` 改为打印 traceback；回复里没有工具调用时最多 nudge 3 次（`# dgm-config: nudge when a reply has no tool call`）。

> 网关抖动是上游问题，重试只是兜底；同一现象影响所有客户端，值得让网关方查。

## 8. 已知坑

1. 上游 README 的 SWE-bench commit `dc4c087c2b9e4cefebf2e3d201d27e36` 只有 32 位，**git 会失败**；完整是 `dc4c087c2b9e4cefebf2e3d201d27e362d899e0f`（镜像里已 checkout 好）。
2. `swebench.run_evaluation` 按 `run_id` 去重：同一个 `run_id` 复跑会跳过已完成实例。
3. `report.py` 用 `ThreadPoolExecutor.map` 且不消费结果，**评测异常会被静默吞掉**（只会打印 “All reports generated”）；看 `swe_bench/<out>/logs/run_evaluation/...` 判断真实结果。
4. 宿主 docker 若重启代理配置，SWE-bench 的 buildargs 补丁需重跑一次（`run-dev.sh` 每次启动都会执行）。
5. 论文口径：SWE-bench 完整一轮约 2 周、约 $22k 模型成本；本 smoke 配置只为跑通链路。
6. 评测时 `run_id` 复用会跳过已完成实例；`report.py` 也会静默吞掉评测异常，判断结果请看 `swe_bench/<out>/logs/run_evaluation/<run_id>/` 下的 `run_instance.log` / `report.json`。
7. 系统级改动只有两处，已在本次会话完成并验证：`/swapfile`（4G，写进 `/etc/fstab`）、Docker `data-root` + containerd `root` 迁到数据盘（`daemon.json` / `config.toml` 均有 `.bak-*` 备份）。
