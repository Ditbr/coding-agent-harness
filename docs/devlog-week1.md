# Week 1 开发日志

## 第 1 至 3 章与代码映射

| 概念 | 代码与实现取舍 |
| --- | --- |
| Full、Lite、Verified 与三层镜像 | `scripts/sample_swebench.py` 从公开的 Verified 500 题抽样。分层优先复用相同仓库版本和 `environment_setup_commit` 的层，任务执行直接使用官方 Instance 镜像。 |
| F2P、P2P 与 Pass@1 | `scripts/run_swebench_eval.py` 调用 SWE-bench 的 `run_instance`。Empty 模式在基线代码上运行官方测试补丁，每题需实际观察到 F2P 失败。Gold 模式用官方补丁校验全部测试。 |
| SWE-agent 的 ACI 与消融 | `tools/registry.py` 固定工具定义与参数，`tools/aci.py` 提供窗口阅读、逐文件聚合搜索、三档匹配和 Python AST 拦截。典型流程是搜索定位、按窗口读文件、编辑和验证。 |
| mini-swe-agent 的无状态执行 | `runtime/base.py` 统一命令和文件接口。`runtime/local.py` 与 `runtime/docker.py` 每次执行独立命令，同一任务保留工作树。 |
| Agentless 的定位、修复、验证 | `repomap/mapper.py` 可先提供 AST 骨架，`tools/aci.py` 支持按需定位，`agent/controller.py` 负责修复循环，官方评测独立验证结果。 |
| OpenHands 的事件流 | `events/schema.py` 定义统一事件，`events/stream.py` 挂载 JSONL 记录器。Controller 直接调用工具，事件流记录每步输入、结果和计费。 |
| Context Rot、Prompt Caching 与单主上下文 | `context/manager.py` 固定系统前缀，对较早的大体积 Observation 使用占位符。Masking 早期消息会改写该位置起的前缀，缓存命中率以实测为准。Compaction 接口可接收结构化摘要，目前由调用方触发。每题使用独立 Controller 和上下文。 |

## 环境和题集

- 本机为 Apple Silicon，沿用 Docker Desktop，容器可用内存约 7.75 GiB。实际运行了 `linux/amd64` 容器。使用 Python 3.12.16、ripgrep 15.2.0 和 SWE-bench 5.0.2。
- 数据使用 SWE-bench Verified 修订 `78f471bf655a3137b2e8a75af1501690ec009ec3`，种子为 `20261126`。30 题覆盖 6 个仓库，每个仓库 5 题。难度为 13 道小于 15 分钟、13 道 15 分钟至 1 小时、4 道 1 至 4 小时，共使用 11 组仓库版本及环境提交。两份 JSONL 直接保留官方字段，批跑只把问题描述和仓库工作区交给模型。 [锁定数据修订](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified/tree/78f471bf655a3137b2e8a75af1501690ec009ec3)
- 30 题 SHA-256 为 `431e03ccc89a7d4cfd6f4867c511e17e334f075ead1acce63fb0345f34569657`。最终 5 题 SHA-256 为 `b8609fd8968d58f70693f474253927435f4c3e75000931609176371309edd7c7`。
- 初次校准发现 `psf__requests-1724` 依赖公网 `httpbin.org`。原镜像证书导致 TLS 失败，换用系统证书的实验仍遇到 HTTP 429。官方 F2P 列表没有包含该题补丁新增的 `test_unicode_method_name`，空补丁的偶发 F2P 失败来自公网调用。最终冒烟从同一 30 题集合改用 `matplotlib__matplotlib-25311`，30 题清单保留原样。

## 运行排查与计费

- Docker SDK 读取活跃 Docker context 的 socket。Apple Silicon 同时显式拉取官方 `linux/amd64` Instance 镜像，避免 SDK 尝试获取 ARM manifest。
- 官方镜像的 HEAD 可以是基线之上的 `SWE-bench` 提交。批跑检查基线关系，从镜像原始 HEAD 导出补丁。临时 Git index 收集新增和已暂存文件，导出的补丁保留完整内容。
- 批跑每条容器命令设置 Conda `testbed` 路径和 UTF-8，并在启动时配置 Git `safe.directory`。真实容器验证过 UTF-8 大文件往返、超过 8,000 字符的完整补丁和命令超时后的子进程清理。容器 ACI 搜索在一次 Docker exec 中完成。
- DeepSeek Flash 在临时 Git 仓库跑完复现、修复和复测，6 步结束。轨迹记录了 8,619 个输入 Token，其中 6,656 个命中缓存，另有 494 个输出 Token，逐次复算合计 $0.001222。费用使用官方高峰单价做上限估算，每百万 Token 分别为未缓存输入 $0.30、缓存输入 $0.006、输出 $1.20，非高峰账单按服务商实际费率结算。 [DeepSeek 官方模型与定价](https://api-docs.deepseek.com/quick_start/pricing/)

## 最终对照

| 对照组 | Pass@1 | 评测耗时 | 核对结果 |
| --- | --- | --- | --- |
| Empty Patch | 0/5（0%） | 210.7 秒 | 五题都实际出现预期 F2P 失败，共 16 项，P2P 全过 |
| Gold Patch | 5/5（100%） | 210.9 秒 | F2P 和 P2P 均达到官方判定 |

本机结构化报告在 `runs/week1/empty-final/summary.json` 和 `runs/week1/gold-final/summary.json`。评测耗时包含 Matplotlib 镜像在本机拉取完成前的等待。

## 真实模型冒烟与 Bad Case

DeepSeek Flash 官方评测为 **2/5（40%）**，评测耗时 109.2 秒。5 题共 79 步，逐次复算的估算费用为 **$0.052131**。共输入 364,964 个 Token，其中 247,291 个命中缓存（67.8%），输出 12,788 个 Token。网关单次成功响应的中位耗时为 1.656 秒。连同临时仓库和中途校准，所有已记录 API 调用的估算费用为 $0.095312。

| 实例 | 结果 | 步数 | 批跑耗时 | 估算费用 | 输入 / 缓存 / 输出 Token | 轨迹观察 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `django__django-13794` | 空补丁 | 20 | 42.9 秒 | $0.009737 | 72,008 / 52,480 / 2,970 | E6。很早找到 `defaultfilters.py`，多个编辑和撤销操作耗尽步数，最终 Git 工作树无差异。 |
| `matplotlib__matplotlib-25311` | F2P 0/1，P2P 181/181 | 20 | 99.8 秒 | $0.020441 | 122,500 / 72,064 / 4,065 | E4。通过 `set_draggable` 找到 `offsetbox.py`，复现脚本中的序列化成功后，反序列化仍失败。官方日志记录 `AttributeError: 'Legend' object has no attribute 'figure'`。 |
| `pytest-dev__pytest-7205` | F2P 1/10，P2P 16/16 | 20 | 47.5 秒 | $0.012250 | 113,893 / 85,376 / 2,652 | E4。找到了 `setuponly.py`，并处理了新增的 bytes 用例。用 `pytest … | tail` 查看验证结果时，Shell 返回的是 `tail` 的退出码。官方评分显示 9 个已有参数化 F2P 用例仍失败。 |
| `scikit-learn__scikit-learn-14141` | F2P 1/1，P2P 2/2 | 7 | 24.2 秒 | $0.003908 | 19,331 / 11,259 / 1,182 | 搜索 `show_versions` 直达依赖列表，编辑后运行定向测试并检查 diff。 |
| `sympy__sympy-13480` | F2P 1/1，P2P 43/43 | 12 | 50.8 秒 | $0.005795 | 37,232 / 26,112 / 1,919 | 定位到 `Coth.eval`。镜像的 testbed 环境缺少 pytest，模型通过独立 Python 复现和 SymPy 的测试接口补做验证，官方评分通过。 |

本机保留 `runs/week1/agent-final/predictions.jsonl`、`runs/week1/agent-final/results.jsonl`、`runs/week1/agent-final/trajectories/` 下的 5 份轨迹和 `runs/week1/scored-final/summary.json`。

## 阶段验收

- 30 个官方 Instance 镜像均已缓存，并逐个核对 `linux/amd64` 架构和仓库摘要。本机镜像清单在 `runs/week1/image-manifest.json`。
- Docker 的 Images 统计从 3.685 GB 增至 77.32 GB，实际增加约 73.6 GB，高于计划中的 10～15 GB 估算。
- `pytest -v` 通过 15 项测试，`ruff check src tests scripts` 和 `git diff --check` 通过。
