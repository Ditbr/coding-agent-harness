# Week 1 验证结果与踩坑

[技术分析与实现取舍](learn.md) · [执行计划](docs/week1-plan.md) · [开发日志](docs/devlog-week1.md)

## Day 1 · 环境检查

- Apple Silicon 上沿用 Docker Desktop，Docker 守护进程可连接，容器可用内存约 7.75 GiB。用 `docker run --rm --platform linux/amd64 alpine uname -m` 实际得到 `x86_64`。
- Python 3.12.16，ripgrep 15.2.0，SWE-bench 5.0.2。通过 `uv pip install -e ".[dev,eval,docker]"` 安装扩展依赖。

## Day 2 · 离线验证

初始 V0.0 的 12 项单测通过。Mock Agent 验证了复现、编辑、复测、Git diff 和轨迹输出，也覆盖重复调用检测。阶段收尾时，追加的网关测试使总数达到 15 项。

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
pytest -v
ruff check src tests scripts
```

## Day 3 · 题集锁定和冒烟校准

- 上游修订 `78f471bf655a3137b2e8a75af1501690ec009ec3`，种子 `20261126`。[固定的 30 题](data/swebench_verified_30.jsonl) 覆盖 6 个仓库、11 组仓库版本及环境提交。难度分布为 13 道小于 15 分钟、13 道 15 分钟至 1 小时、4 道 1 至 4 小时。
- [最终冒烟集](data/smoke_5.jsonl) 有 5 道题，来自 5 个仓库，每道都在 30 题集合中。
- 运行 `python scripts/sample_swebench.py` 对固定文件做重建校验。30 题 SHA-256 为 `431e03ccc89a7d4cfd6f4867c511e17e334f075ead1acce63fb0345f34569657`，5 题 SHA-256 为 `b8609fd8968d58f70693f474253927435f4c3e75000931609176371309edd7c7`。

**踩坑。** 初选的 `psf__requests-1724` 依赖公网 `httpbin.org`。历史镜像证书导致 TLS 失败，改用系统证书的实验仍出现 HTTP 429。官方 F2P 列表也没有覆盖该题补丁新增的 `test_unicode_method_name`，偶发的空补丁 F2P 失败不足以验证修复。最终冒烟采用同一 30 题集合中的 `matplotlib__matplotlib-25311`，30 题文件仍对应上述校验和。

## Day 4 · 官方评测对照

| 模式 | Pass@1 | 耗时 | 验证证据 |
| --- | ---: | ---: | --- |
| Empty Patch | 0/5（0%） | 210.7 秒 | 五题均观察到预期 F2P 失败，共 16 项，P2P 全过 |
| Gold Patch | 5/5（100%） | 210.9 秒 | 五题均达到官方 F2P/P2P 判定 |

耗时含等待 Matplotlib 镜像首次拉取完成。原始报告保存在本机 `runs/week1/empty-final/summary.json` 和 `runs/week1/gold-final/summary.json`。

**踩坑。** Docker CLI 已连上 Docker Desktop 时，Docker SDK 仍可能找不到正确 socket。脚本从活动 Docker context 读取端点。有镜像缺失时显式拉取 `linux/amd64`，避免 Apple Silicon 默认查找 ARM manifest。

```bash
python scripts/run_swebench_eval.py --mode empty --output-dir runs/recheck/empty
python scripts/run_swebench_eval.py --mode gold --output-dir runs/recheck/gold
```

## Day 5 · 真实网关联调

DeepSeek Flash 在临时 Git 仓库中将错误的减法实现改成加法，完成复现、修复和复测，6 步结束。轨迹记录 8,619 个输入 Token，其中 6,656 个命中缓存，另有 494 个输出 Token。按当次配置逐次复算，估算费用为 $0.001222。

**校验要点。** 网关返回有效的工具调用与缓存命中数。单测核对了 DeepSeek 和 OpenAI 风格的用量字段，以及实际发送的工具定义。成本统一按记录中的费率估算。实测采用的每百万 Token 单价为未缓存输入 $0.30、缓存输入 $0.006、输出 $1.20。

## Day 6 · 真实模型批跑

DeepSeek Flash 通过 **2/5（40%）**，评分耗时 109.2 秒。5 题累计 79 步，估算费用 **$0.052131**。364,964 个输入 Token 中，247,291 个命中缓存（67.8%），输出 12,788 个 Token。成功网关请求的响应耗时中位数为 1.656 秒。计入本地联调和校准，已记录 API 调用的估算费用合计 $0.095312。

| 实例 | 模型步数 | 官方结果 |
| --- | ---: | --- |
| `django__django-13794` | 20 | 空补丁 |
| `matplotlib__matplotlib-25311` | 20 | F2P 0/1，P2P 181/181 |
| `pytest-dev__pytest-7205` | 20 | F2P 1/10，P2P 16/16 |
| `scikit-learn__scikit-learn-14141` | 7 | F2P 1/1，P2P 2/2 |
| `sympy__sympy-13480` | 12 | F2P 1/1，P2P 43/43 |

**容器踩坑与验证。**

- 官方镜像 HEAD 可能是数据集基线之上的 `SWE-bench` 提交。实测核对了父提交，从镜像初始工作树导出了补丁。已检查超过 8,000 字符的完整补丁、UTF-8 大文件往返和指定文件搜索。
- 每次执行注入 Conda 路径，并设置 UTF-8 环境和 Git `safe.directory`。即使使用了正确的环境，SymPy 题的镜像仍缺少 pytest，模型使用独立 Python 复现和 SymPy 自带的测试接口补做验证。
- 旧的逐文件搜索触发大量 `docker exec`。改用容器内一次搜索后，批跑完成。实际启动后台测试子进程验证了超时返回码 124、子进程退出和后续命令可继续运行。

在仓库根目录运行以下命令。 `.env` 需已配置有效网关，输出使用新的目录。

```bash
set -a
source .env
set +a
python scripts/run_agent_batch.py --output-dir runs/recheck/agent
python scripts/run_swebench_eval.py --mode predictions \
  --predictions runs/recheck/agent/predictions.jsonl --output-dir runs/recheck/scored
```

## Day 7 · 失败案例、镜像与同步

| 失败案例 | 轨迹和日志证据 |
| --- | --- |
| Django · E6 | 早期定位到 `defaultfilters.py`，反复编辑和撤销耗尽步数，最终 Git 工作树无差异。 |
| Matplotlib · E4 | 定位到 `offsetbox.py`，修复只覆盖局部序列化路径。官方反序列化验证仍出现 `AttributeError: 'Legend' object has no attribute 'figure'`。 |
| pytest · E4 | 找到 `setuponly.py` 并使新增 bytes 用例通过。验证命令使用 `pytest … \| tail`，外层 Shell 报告了 `tail` 的退出码。官方评测确认 9 项参数化 F2P 仍失败。 |

- 30/30 个实例镜像逐个核对为 `linux/amd64`，本机清单记录镜像仓库摘要。Docker 镜像统计从 3.685 GB 增至 77.32 GB，增加约 73.6 GB，高于计划的 10～15 GB 估算。
- `pytest -v` 通过 15 项测试，`ruff check src tests scripts` 和 `git diff --check` 通过。Week 1 实现提交为 `176c49c`，GitHub 与 Gitee 的 `main` 均核对到同一提交。

| 本机证据 | 路径 |
| --- | --- |
| 临时仓库的网关轨迹 | `runs/week1/local-trajectories/deepseek-local.jsonl` |
| 预测和逐题结果 | `runs/week1/agent-final/predictions.jsonl`、`runs/week1/agent-final/results.jsonl` |
| 五份逐题轨迹 | `runs/week1/agent-final/trajectories/` |
| 真实模型评分 | `runs/week1/scored-final/summary.json` |
| 30 个镜像的平台与摘要 | `runs/week1/image-manifest.json` |
