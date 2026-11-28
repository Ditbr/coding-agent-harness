# Coding Agent Harness 总执行计划（Master Plan）

> 最后更新：2026-11-28
>
> 关联文档：[README.md](README.md) · [docs/progress.md](docs/progress.md) · [fix.md](fix.md) · [docs/week1-plan.md](docs/week1-plan.md) · [docs/coding-agent-study-guide.md](docs/coding-agent-study-guide.md) · [learn.md](learn.md) · [result.md](result.md)

---

## 一、8 周总体路线图与当前进度

| 周次 | 阶段目标 | 状态 | 关键里程碑与实测基线 |
| :--- | :--- | :---: | :--- |
| **Week 1** | 理论底座（第 1~3 章）+ V0.0 框架 + 5 题冒烟 + 远端算力解耦 | ✅ 已完成 | 锁死 30/5 题集；Empty 0/5、Gold 5/5；DeepSeek 冒烟 2/5（40%）；远端 Windows x86_64 Docker + ECS 反向隧道 4 并发提速 **2.71×**（`210.9s → 77.7s`）。详见 [docs/week1-plan.md](docs/week1-plan.md)、[docs/devlog-week1.md](docs/devlog-week1.md)。 |
| **Week 2** | 底座全面加固 + 30 题 V0.1 Baseline + 首轮 V0.2~V0.4 消融 | ✅ 已完成 | 30 题 Gold **26/30（86.7%）**，36 步基线 **17/30（56.7%）**，RepoMap **12/30**，Guardrails **16/30**，Compaction **15/30**。四组沿用原 27 题去噪口径。 [评分与消融对比](runs/week2/ablation-36steps.md) |
| **Week 3** | **代码基线固化、Guardrails v2、RepoMap v2 与 V0.2/V0.3 评测** | Day 1 已完成 | 已固化 Week 2 结果与新版网络审计。下一步是 Day 2 Guardrails v2，30 题 Pass@1 目标为 **≥ 20/30（66.7%，去噪 ≥ 70%）**。 |
| **Week 4** | V0.4 验证闭环 + 只读 Explorer Subagent + 50 题完整消融表 | ⬜ 待开始 | 接入只读 Explorer 子 Agent 攻克跨文件 `E1` 难例；在扩展 50 题集上跑出 V0.1 → V0.4 完整消融曲线表（Pass@1 / 步数 / Token / 缓存命中 / E1~E6）。 |
| **Week 5** | 异步并发沙箱池 + 轻量轨迹回放与评测对比看板 | ⬜ 待开始 | 重构并发任务队列与隧道自愈池；落地静态 HTML/轻量 Web 轨迹回放与多版本消融对比看板。 |
| **Week 6** | GitHub Webhook / CI 自愈提 Draft PR 闭环 | ⬜ 待开始 | 对接真实 GitHub 仓库：接收失败 CI 日志 → 沙箱自动复现 → 修复与回归验证 → 自动创建 Draft PR 并附验证证据。 |
| **Week 7** | 极端安全压测 + 跨模型横向评测 | ⬜ 待开始 | OOM / Fork 炸弹 / 路径穿越 / 断网 / 死循环压测；同 Harness 横向对比多档模型（DeepSeek / Qwen / Claude / Gemini）。 |
| **Week 8** | 交付收官、技术报告与面试深挖沉淀 | ⬜ 待开始 | 完善含消融实验曲线与 Demo 录屏的 README；用真实实验数据填实手册第 6.2 节 8 道面试深挖题。 |

---

## 二、Week 2 现状 Review 与核心实证洞察（Week 3 设计依据）

### 1. 当前 36 步 30 题实验对比汇总（`deepseek-flash`，`--thinking disabled`）

| 实验组 | 30 题 Pass@1 | 27 题去噪 Pass@1 | 非空补丁 | `finished` / `max_steps` | 平均步数 | Prompt Tokens | Cache 命中率 | 相对 Baseline |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`baseline-36steps`** | **17/30 (56.7%)** | **17/27 (63.0%)** | 28/30 | 16 / 13 (`1 loop`) | 28.3 | 5.61M | 66.8% | 基准 |
| **`repomap` (v1)** | 12/30 (40.0%) | 12/27 (44.4%) | 25/30 | 12 / 16 (`2 loop`) | 29.3 | 7.43M (+32%) | 70.6% | **+1 / -6（净跌 5 题）** |
| **`guardrails` (v1)** | 16/30 (53.3%) | 16/27 (59.3%) | **30/30** | **2 / 28** | **35.2** | 7.93M (+41%) | 72.2% | **+1 / -2（净跌 1 题）** |
| **`compaction` (v1)** | 15/30 (50.0%) | 15/27 (55.6%) | 26/30 | 14 / 10 (`6 loop`) | 25.8 | 8.66M (+54%) | 95.9% | **+2 / -4（净跌 2 题）** |

Compaction 组的 30 条轨迹均没有 `compaction` 事件。95.9% 的缓存命中率反映该组的实际请求，尚无证据把变化归因于摘要压缩。Day 5 需要验证实际触发及其影响。 [逐题指标](runs/week2/ablation-36steps.json)

### 2. Baseline 13 道失败题的 E1~E6 归因分布（[逐题归因](runs/week2/baseline-36steps-attribution.md)）

- **`E4`（验证不足）：7 题（占全部非噪声失败的 58%！）** → **当前最大提分杠杆**
- **`E1`（定位偏差）：2 题**（`django-13794`、`django-13112`）
- **`E6`（死循环 / 空补丁）：2 题**（`psf__requests-6028`、`sympy__sympy-13551`）
- **`E5`（回归）：1 题**（`psf__requests-1724`）
- **外网噪声：1 题**（`psf__requests-1766`）；**`E2`（编辑失败）= 0、`E3`（上下文失控）= 0**

### 3. 三条决定 Week 3 方向的关键诊断

1. **为什么 `guardrails` v1 几乎打满步数（28/30 `max_steps`、均步 35.2）却只差 1 题追平基线？**
   - 轨迹统计显示 34 次 `finish` 调用被**拒绝了 32 次**，其中 **18 次**是因为门禁强制要求「必须在修改前通过 `run_test` 录过基线失败，否则先 rollback 回基线重录」。模型已在 `run_command` 跑过复现或已完成修复，被强迫回滚重来导致大量步骤浪费甚至破坏已有正确补丁。
   - 但正收益同样显著：空补丁从 2 降至 **0/30（100% 非空）**、`scikit-learn` 达到 **5/5（100%）**，且精准拦截了约 10 例模型误改官方测试文件的问题。
   - **结论**：放宽“事后强制 `run_test` 基线回滚”的毒规则、保留“非空补丁 + 当前补丁测试通过 + 还原官方测试文件”护栏，预计能直接释放 `E4` 红利。
2. **为什么 `repomap` v1 反而净跌 5 题（`17 → 12`）？**
   - Baseline 仅靠 `search_code` + `view_file` 就已在 **26/30（86.7%）** 题中命中金标准文件，首次命中中位数仅 **第 2 步**（均值 2.7 步）。
   - 在 Step 1 静态前置塞入 ~2,000+ Token 的全仓 RepoMap（总 Prompt 暴涨 **+32%**）带来了早期上下文噪声和锚定偏差（`django` 跌至 `0/5`，`django-13315`、`matplotlib-25311` 退化为空补丁）。
   - **结论**：停止静态前置灌注，改回学习手册设计的**按需 ACI 工具 `get_repo_map(focus_files)`**，并以 `problem_statement` 符号作为 PageRank 个性化种子。
3. **当前工程债务集中且清晰**：
   - Week 2 的代码变更按执行底座与消融框架分批固化，`.env.example` 已去除重复配置（`FIX-010`）。
   - 网关实际费率未核实，Week 3 使用 Token 与缓存命中率比较（`FIX-011`）。Gold 对照中有 4 道 Requests 未通过，Day 1 刷新网络噪声审计（`FIX-012`）。
   - 远端 Docker 隧道偶发闪断导致 `compaction` 多次出现 `0 steps error`（需在容器启动层加健康检查与退避重试）。

---

## 三、Week 3 详细执行计划（Day 1 ~ Day 7）

> **Week 3 核心目标**：**清零 Week 2 工程债务 → 用数据驱动重构 Guardrails v2 与按需 RepoMap v2 → 完成 30 题 V0.2 & V0.3 正向提分闭环（Pass@1 ≥ 20/30，去噪 ≥ 70%）→ 启动 Explorer Subagent 与 50 题扩展准备。**

### Week 3 验收标准（Definition of Done）

- [x] **代码库收口**。重复模板已清理，`FIX-010`~`012` 已完成。改动分为执行底座、消融框架和文档三笔提交，全量测试与 Ruff 通过。
- [x] **Week 2 消融收尾**：`compaction` 30/30 补齐出分，生成四组对比和基线逐题归因。 [对比报告](runs/week2/ablation-36steps.json)
- [ ] **Guardrails v2 & RepoMap v2 正向提分**：在同 30 题 36 步条件下，至少一组 V0.2/V0.3 配置明确超越 Baseline `17/30 (56.7%)`，目标 **≥ 20/30（66.7%，去噪 ≥ 70%）**，且 `E4` 失败数从 7 题压降至 ≤ 3 题、`finish` 无效拒收率大幅下降。
- [ ] **Compaction 量化闭环**：完成 `FIX-008` 长轨迹缓存命中率、Token 降幅与 Pass@1 的成组量化评估。
- [ ] **稳定性与 V0.4 预备**：`DockerSandboxRuntime.start()` 具备隧道断连自愈重试；只读 Explorer Subagent 原型通过离线单测；锁定 50 题扩展集并启动远端镜像预拉。

---

### Day 1 · Week 2 彻底收口与代码基线固化

- **任务清单**：
  1. **收口 `compaction` 实验（`FIX-013`）**。已补齐 30 题并通过 15 题，四组对比已保存。 [官方评分](runs/week2/compaction-score/summary.json)
  2. **清理并分批提交工作区（`FIX-010`）**：
     - 删除 `.env.example` 末尾重复的 `WIN_DOCKER_*` 配置段；
     - 运行 `.venv/bin/pytest -v && .venv/bin/ruff check src tests scripts && git diff --check`；
     - 按 3 个干净 Commit 提交并推送 `origin` 与 `gitee`：① Infra/Eval 加固与 `FIX-015` 超时保留容器；② V0.2~V0.4 消融特性框架与回归测试；③ `fix.md`、`plan.md`、`docs/progress.md` 与 `README.md` 文档同步。
  3. **统一度量口径（`FIX-011` + `FIX-012`）**：
     - 明确新网关的费率或 Token 对比口径，记录在 `docs/progress.md`；
     - 复核 `gold-30-offline-pip` 中 `psf__requests-2931` 日志，重跑 `scripts/audit_swebench_controls.py` 产出新版 `controls-audit.json`（作为 Week 3 统一噪声基准）。
- **当日产出**。Week 2 四组原始评分已保留，Week 3 使用覆盖 30 题的新版噪声审计，其中 26 题符合默认对照预期。基线在新版去噪子集为 **16/26（61.5%）**。 [新版审计](runs/week3/day1/controls-audit.json)

---

### Day 2 · 重构 Guardrails v2（直击 #1 瓶颈 E4：7/13 失败）

- **设计目标**：保留 v1「0 空补丁 + 防误改官方测试文件」的正收益，彻底消除「32/34 次 `finish` 被拒、28/30 打满 36 步」的过度拦截。
- **代码改造点**（`src/harness/tools/verification.py`、`src/harness/tools/aci.py`、`src/harness/agent/controller.py`）：
  1. **打通 `run_command` 与 `run_test` 的验证证据识别**：不强制要求必须用 `run_test` 才算测试；当模型通过 `run_command` 执行 `pytest` / `runtests.py` / `python -m unittest` / `sympy.test` 时自动解析并记录测试通过/失败证据。
  2. **取消“事后强制回滚补录基线失败”的硬拦截**：若模型已经修改代码且当前补丁下相关测试已通过，缺失修改前的基线失败记录只做一次轻量提示或直接放行，绝不强迫 rollback 已通过的修复。
  3. **保留三条高价值硬门禁**：
     - 最终 `git diff` 必须非空且包含至少 1 个非测试业务源码文件（解决 `psf__requests-1724` 只改测试、`psf__requests-6028` 纯读不改）；
     - 最后一次 `edit_file` 之后必须有至少 1 次退出码为 `0` 的测试运行记录（解决 `E4` 改完不测）；
     - 若改动了既有官方测试文件或新增了临时脚本/changelog，在 `finish` 提示一键清理或提供自动还原选项（解决 `FIX-016`）。
  4. **升级末尾 5 步预算提醒**：当剩余 ≤ 5 步且 `git diff` 仍为空时，注入强制行动提示，引导模型立刻基于已有定位落盘最小修复并验证。
- **验证**：补充/更新 `tests/test_fix_regressions.py` 单元测试，并在 `data/smoke_5.jsonl` 跑一轮快速冒烟，确认 `finish` 拒收率明显下降、`finished` 恢复正常。

---

### Day 3 · 重构 RepoMap v2（从静态前置灌注改为按需工具 + 问题词锚定）

- **设计目标**：消除 v1 静态前置 2,000+ Token 带来的 +32% 成本与锚定退化，让 RepoMap 在真正需要跨文件理解（`E1`）时按需发力。
- **代码改造点**（`src/harness/repomap/mapper.py`、`src/harness/tools/aci.py`、`scripts/run_agent_batch.py`）：
  1. **注册为按需 ACI 工具 `get_repo_map(focus_files: list[str] = [], query: str = "", max_tokens: int = 1200)`**：
     - 初始 User Prompt 不再强塞全仓大地图（保持 Step 1 零额外噪声，不污染 Prompt Cache 前缀）；
     - 系统提示词仅用一句话告知模型：在定位跨文件调用关系或找不到入口时调用 `get_repo_map`。
  2. **问题词/焦点文件个性化 PageRank 锚定**：当传入 `focus_files` 或 `query` 时，提升相关模块及直接调用/被调用符号的个性化权重，过滤无关顶层样板文件。
  3. **参数开关兼容**：`--with-repomap-tool`（按需工具模式，Week 3 主推）与原有 `--with-repomap`（静态模式）解耦，方便同条件消融对比。
- **验证**：补充单元测试，并在 Week 2 暴露出的 4 道关键题（`E1` 失败题 `django-13794`、`django-13112` + v1 退化题 `django-13315`、`matplotlib-25311`）上跑定向验证。

---

### Day 4 · 30 题 V0.2 消融实测与归因复盘

- **实验矩阵**（统一 `data/swebench_verified_30.jsonl`、`deepseek-flash`、`--max-steps 36 --thinking disabled`、`--noise-audit runs/week3/day1/controls-audit.json`）：
  1. `runs/week3/guardrails-v2`（单开重构后的验证门禁 v2 + 循环恢复）
  2. `runs/week3/repomap-v2`（单开按需 `get_repo_map` 工具）
  3. `runs/week3/v02-combined`（`guardrails-v2` + `repomap-v2` 组合）
- **分析与验收**：
  - 使用 `scripts/compare_harness_runs.py` 与 `baseline-36steps` 逐题对比（Gained / Lost、平均步数、空补丁数、`finish` 拒收次数、Prompt Token 与缓存命中率）；
  - 对 `v02-combined` 剩余失败题更新 E1~E6 归因表，确认 `E4` 显著下降且 Pass@1 明确超越 `17/30 (56.7%)`；
  - 验收达标后在 `fix.md` 将 `FIX-006`、`FIX-007`、`FIX-016` 更新为 `DONE`。

---

### Day 5 · V0.3 上下文工程与 Compaction 优化闭环（`FIX-008`）

- **任务清单**：
  1. **深度复盘 Day 1 的 `compaction` 30 题数据**：检查实际触发 Compaction 的题数、缓存命中率变化、Prompt Token 节省比例以及 Pass@1 是否有损。
  2. **优化 Compaction 策略与结构化摘要模板**（`src/harness/context/manager.py`、`src/harness/agent/controller.py`）：
     - 确保压缩摘要强制保留 4 个结构化区块：`已确认根因`、`已修改文件与现状`、`已证伪假设（Failed Attempts，避免重踩坑）`、`下一步验证计划`；
     - 结合 36 步实际 Token 分布校准触发阈值（避免 60K 门槛过高从未触发，或过低导致频繁丢细节）。
  3. **跑出 V0.3 组合组**：`runs/week3/v03-compaction`（`v02-combined` + `--with-compaction`），对比 V0.2 与 V0.3 的 Pass@1、Prompt Token 总量与 Cache 命中率，闭环 `FIX-008`。

---

### Day 6 · 远端沙箱自愈加固 + 只读 Explorer Subagent 原型（V0.4 先导）

- **任务清单**：
  1. **彻底根治远端隧道闪断导致的 `0 steps error`**：
     - 在 `DockerSandboxRuntime.start()` 及 `run_agent_batch.py` 题目启动阶段增加 `docker` 连接健康探测 + 指数退避重试（如 3 次，5s/10s/20s），避免隧道瞬断把整批未跑题目瞬间打成 `error`。
     - 补充单元测试模拟首连失败后退避恢复。
  2. **实现只读 Explorer Subagent 原型**（`src/harness/agent/explorer.py`）：
     - 遵循 Cognition 单写多读原则：主 Agent 可通过新 ACI 工具 `explore_codebase(question: str)` 派发只读子 Agent（最多 6~8 步，仅开放 `search_code` / `view_file` / `get_repo_map`，无写文件和命令权限），返回精炼的「定位结论 + 关键文件路径与行号」；
     - 避免主上下文被大量探索性 `search_code`/`view_file` 噪声污染，为 Week 4 攻克复杂跨文件 `E1` 难例做好准备。
     - 补齐 Mock 端到端单元测试。

---

### Day 7 · 50 题扩展集锁定、阶段复盘与双端交付

- **任务清单**：
  1. **构建 50 题扩展评测集**：
     - 扩展 `scripts/sample_swebench.py` 导出并锁定 `data/swebench_verified_50.jsonl`（严格包含现有 30 题中的无外网噪声部分 + 新增 20 题分层样本，排除依赖 `httpbin.org` 的外网脆弱题，记录 SHA-256）；
     - 调用 `scripts/pull_images.py` 在远端 Windows x86_64 节点预拉新增 20 个镜像并校验 Gold Patch。
  2. **产出 Week 2~3 阶段复盘文档**：
     - 撰写 `docs/devlog-week2-3.md`，汇总完整的 **V0.1 (20步) → V0.1 (36步) → V0.2 (v1 负收益教训 → v2 重构提分) → V0.3** 消融实验表与轨迹案例（这段“发现负收益 → 根因定位 → 重构反转”的过程是极具含金量的工程证据）；
     - 同步更新 `README.md`、`docs/progress.md`、`fix.md` 与 `plan.md` 进度勾选。
  3. **质量门禁与双端推送**：
     - 全量 `pytest -v`、`ruff check src tests scripts`、`git diff --check` 全绿；
     - 推送最新代码与文档至 GitHub（`origin`）与 Gitee（`gitee`）。

---

## 四、关键风险与管控对策

| 风险项 | 影响 | 管控措施 |
| :--- | :--- | :--- |
| **远端 SSH 隧道并发抖动** | 批跑出现连续 `0 steps error`（如 `compaction` 首轮全挂） | Day 6 在 `DockerSandboxRuntime.start()` 加退避重试；批跑并发保守控制在 `--workers 2~3`，异常时依赖 `--resume` 补跑。 |
| **LLM 网关限流 / 费率漂移** | 不同消融组成本或延迟不可比 | 整个 Week 3 锁定同一网关、同一模型（`deepseek-flash`）、同一 `--thinking disabled` 与 36 步上限；统一记录 Token 总量与 Cache 命中率。 |
| **外网脆弱题干扰 Pass@1 结论** | `psf__requests` 3~4 题因 `httpbin.org` 偶发挂掉造成统计抖动 | 30 题全量始终同时报告 `Raw (30题)` 与 `Noise-Adjusted` 两列指标；Week 3 Day 7 构造 50 题集时提前用离线 Gold 校验把关。 |
| **多变量同时改动污染消融** | 无法归因单个模块的真实增益 | 严格单变量控制：先单独测 `guardrails-v2`、`repomap-v2`，验证各自正向收益后再合入 `v02-combined` 与 `v03-compaction`。 |
