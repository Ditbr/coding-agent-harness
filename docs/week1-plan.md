# Week 1（第一阶段）执行计划：环境底座、评测脚手架与 5 题端到端冒烟

> 本阶段目标：**读透底层理论（第 1~3 章）+ 搭好本地容器与评测底座 + 跑通 5 题真实 SWE-bench 端到端冒烟闭环**，为第 2~3 周打磨沙箱/ACI 并产出 30 题 V0.1 Baseline 扫清所有障碍。

---

## 一、本阶段验收标准（Definition of Done）

- [x] **理论吃透**：精读完 [coding-agent-study-guide.md](coding-agent-study-guide.md) 第 1~3 章，并将核心概念与 `src/harness/` 代码模块一一对应。
- [x] **评测集锁死**：生成并固定 **30 题分层评测集**（`data/swebench_verified_30.jsonl`）与 **5 题日常冒烟集**（`data/smoke_5.jsonl`）。
- [x] **评测脚手架双校验通过**：在 `smoke_5.jsonl` 上，**Empty Patch = 0/5（0%）**，**Gold Patch = 5/5（100%）**。
- [x] **真实模型端到端冒烟**：接入后端 LLM 网关，用 `DockerSandboxRuntime` 在 5 题冒烟集上完整跑通 `读取任务 → 容器修复 → 导出 Patch → SWE-bench 评测出分 → JSONL 轨迹落盘`。
- [x] **复盘与同步**：产出 `docs/devlog-week1.md` 踩坑与 Bad Case 初步记录，代码通过测试并同步推送到 GitHub 与 Gitee。

实测结果、题集校验和与 Bad Case 见 [Week 1 开发日志](devlog-week1.md)。

---

## 二、Day 1 ~ Day 7 每日拆解计划

### Day 1：开发环境搭建 + 精读第 1 章（评测体系）
- [x] **阅读（40 min）**：精读 [coding-agent-study-guide.md](coding-agent-study-guide.md) 第 1 章（SWE-bench Full/Lite/Verified 差异、三层 Docker 镜像架构、`FAIL_TO_PASS` / `PASS_TO_PASS` 判定矩阵）。
- [x] **安装容器与工具（30 min）**：
  - Mac 上推荐安装 **OrbStack**（相比 Docker Desktop 更轻省内存、Rosetta 2 跑 `linux/amd64` 镜像更稳），运行 `docker info` 验证正常。
  - 安装 `ripgrep`：`brew install ripgrep`。
- [x] **初始化 Python 虚拟环境（30 min）**：
  ```bash
  uv venv && source .venv/bin/activate
  uv pip install -e ".[dev,eval,docker]"
  pytest -v
  ruff check src tests
  ```
- **当日产出**：本地 Docker、ripgrep、`.venv`、pytest、ruff 全部绿灯。

---

### Day 2：精读第 2 章（三大范式）+ 走读 V0.0 代码骨架
- [x] **阅读（60 min）**：精读第 2 章（SWE-agent ACI 与 Table 3 消融、mini-swe-agent 极简无状态执行、Agentless 三阶段确定性流水线）。
- [x] **源码走读（60 min）**：逐一对照现有模块与论文设计：
  - `src/harness/events/`（`schema.py`、`stream.py`）↔ OpenHands EventStream 事件驱动与 JSONL 落盘
  - `src/harness/runtime/`（`base.py`、`local.py`、`docker.py`）↔ mini-swe-agent 无状态执行 + 容器安全隔离
  - `src/harness/tools/`（`registry.py`、`aci.py`）↔ SWE-agent ACI + Aider 3 级容错编辑与 AST 语法拦截
  - `src/harness/agent/controller.py` ↔ ReAct 主循环、步数/费用熔断、重复调用死循环检测
- [x] 运行 `PYTHONPATH=src python3 -m unittest discover -s tests -v`，熟悉 [test_agent_loop.py](../tests/test_agent_loop.py) 端到端 Mock 流程。
- **当日产出**：能脱稿画出系统模块依赖图并讲清每个设计取舍。

---

### Day 3：构造 30 题分层评测集 + 5 题冒烟集
- [x] **编写抽样脚本（60 min）**：创建 `scripts/sample_swebench.py`，从 HuggingFace 拉取 **SWE-bench Verified（500 题）**。
- [x] **省磁盘分层抽样策略（30 min）**：
  - 优先集中在 **5~6 个主流仓库**（如 `django`、`pytest`、`sympy`、`scikit-learn`、`requests`、`flask`）。
  - 尽量优先选择共享相同/相近 `environment_setup_commit` 的样本，复用 Docker Environment 镜像层（可将 30 题总磁盘占用控制在 ~10~15GB）。
  - 固定随机种子导出并**锁死**两份文件（后续 V0.1 → V0.4 消融实验严禁换题）：
    - `data/swebench_verified_30.jsonl`（30 题标准验证集）
    - `data/smoke_5.jsonl`（5 题跨仓库快速冒烟集）
- **当日产出**：`scripts/sample_swebench.py` + 两份固定评测集文件，提交一次 Commit。

---

### Day 4：打通 SWE-bench 评测脚手架 + 双基准校验（Eval First）
- [x] **编写评测封装脚本（60 min）**：创建 `scripts/run_swebench_eval.py`，调用官方 `swebench.harness.run_evaluation` 并解析评测日志，生成结构化汇总报告（Pass@1、每题 F2P/P2P 详情、耗时）。
- [x] **执行双基准自检（60 min）**：针对 `data/smoke_5.jsonl` 跑两次强制 Sanity Check：
  1. **空补丁（Empty Patch）**：必须严格 **0/5（0%）通过**，排除假绿。
  2. **官方金标准（Gold Patch）**：使用样本自带 `patch` 字段评测，必须严格 **5/5（100%）通过**，验证本地 Docker 评测链路完全准确。
- **当日产出**：一键评测脚本 + `Empty=0% / Gold=100%` 校验日志记录。

---

### Day 5：精读第 3 章（上下文工程）+ 接入后端 LLM 网关
- [x] **阅读（50 min）**：精读第 3 章（Anthropic《Building Effective Agents》&《Effective Context Engineering》、Cognition《Don't Build Multi-Agents》），重点吃透 Prompt Caching 前缀稳定性与 Context Rot。
- [x] **网关对接与联调（70 min）**：
  - 复制 `.env.example` 为 `.env`，配置你的**后端 LLM 网关**（或 DeepSeek / Qwen / OpenAI 兼容接口）。
  - 在一个本地临时 Git 仓库运行 `PYTHONPATH=src python3 -m harness solve ...`。
  - 核对 [client.py](../src/harness/llm/client.py) 对你网关返回格式中 `tool_calls`、`prompt_tokens`、`cached_tokens`（或 `prompt_cache_hit_tokens`）的解析是否完全准确，并补充单元测试。
- **当日产出**：真实 LLM 网关调通，JSONL 轨迹中的 Token 与费用统计核对无误。

---

### Day 6：`DockerSandboxRuntime` 实战联调 + 5 题端到端冒烟
- [x] **编写批量运行脚本（60 min）**：创建 `scripts/run_agent_batch.py`，实现 `读取 JSONL 任务 → 启动对应 SWE-bench Instance 镜像（/testbed）→ 运行 AgentController → 收集 git diff 写入 predictions.jsonl`。
- [x] **容器真实环境排坑（60 min）**：逐项验证并修复真实 SWE-bench 镜像常见环境问题：
  1. Conda 虚拟环境未激活导致 `pytest` 找不到依赖（自动注入 `/opt/miniconda3/envs/testbed/bin` 到 `PATH` 或 `conda activate testbed`）。
  2. `git diff` 报 `dubious ownership`（执行 `git config --global --add safe.directory /testbed`）。
  3. 容器内字符编码非 UTF-8（显式设置 `LANG=C.UTF-8`、`PYTHONIOENCODING=utf-8`）。
  4. 命令超时后残留孤儿测试子进程未清理。
- [x] **跑通 5 题冒烟并出分（30 min）**：限制 `HARNESS_MAX_STEPS=20`、`HARNESS_MAX_COST_USD=0.15`，跑完 `smoke_5.jsonl` 并喂给 Day 4 评测脚本得出第一份真实冒烟成绩。
- **当日产出**：5 题真实容器端到端闭环 + 加固后的 `DockerSandboxRuntime` + 5 份完整 `.jsonl` 轨迹。

---

### Day 7：轨迹复盘 + 镜像预拉 + 阶段收尾同步
- [x] **人工复盘 5 条真实轨迹（45 min）**：通读 Day 6 产出的 5 份 `.jsonl` 文件，记录第一批真实观察（模型如何定位文件、单步耗时、Token/费用分布、缓存命中率、遇到的首批 Bad Case），整理为 `docs/devlog-week1.md`。
- [x] **预拉剩余镜像（20 min）**：按磁盘余量预拉 `swebench_verified_30.jsonl` 剩余 25 题的 Docker 镜像，减少下周全量跑 V0.1 Baseline 时的等待时间。
- [x] **质量检查与双平台推送（25 min）**：
  - 运行 `pytest -v && ruff check src tests` 确认全部通过。
  - 更新 `README.md` 进度并提交推送至 GitHub（`origin`）与 Gitee（`gitee`）。
- **当日产出**：`docs/devlog-week1.md` + Week 1 里程碑提交。

---

## 三、Mac 本地运行避坑备忘

1. **容器内存与架构**：Apple Silicon（M1~M4）使用 OrbStack 自动通过 Rosetta 2 运行 `linux/amd64` 镜像；建议给容器运行时预留 **6~8 GB 内存**，初期评测并发数设为 `1~2`。
2. **低成本调试原则**：Day 5~6 调通链路时优先用低单价模型（如 DeepSeek / Flash 级模型），严格开启步数上限（`20`）与单题费用熔断（`$0.15`），整周 API 调试成本可控制在几元人民币以内。
3. **锁死评测集不动**：Day 3 确定 `swebench_verified_30.jsonl` 后，后续四个版本迭代全部在同题同环境下评测，保证消融实验曲线严谨可信。
