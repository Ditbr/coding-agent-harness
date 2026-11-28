# Coding Agent Harness 总执行计划（Master Plan · 最高完整度版）

> 最后更新：2026-11-28
>
> 战略定位：**以最高工程完整度、最高评测严谨度与最高通过率为核心目标**（实测网关单价仅 ¥2/1M 未缓存输入与输出、¥0.2/1M 缓存输入，API 成本不再构成瓶颈，不做妥协式缩水）。
>
> 关联文档：[README.md](README.md) · [docs/progress.md](docs/progress.md) · [fix.md](fix.md) · [docs/week3-fix.md](docs/week3-fix.md) · [docs/week1-plan.md](docs/week1-plan.md) · [docs/week3-plan.md](docs/week3-plan.md) · [docs/coding-agent-study-guide.md](docs/coding-agent-study-guide.md) · [learn.md](learn.md) · [result.md](result.md)
>
> **周计划文档约定**：总计划 [plan.md](plan.md) 维护全局路线、阶段汇总与跨周演进；**每一周单独拆出一份详细执行计划 `docs/week<N>-plan.md`**（含每日拆解、验收标准与实测命令），并在本总计划中保持双向同步链接。

---

## 一、8 周旗舰级总路线图与当前进度

| 周次 | 阶段目标 | 详细计划 | 状态 | 关键里程碑与验收标尺 |
| :--- | :--- | :---: | :---: | :--- |
| **Week 1** | 理论底座（第 1~3 章）+ V0.0 框架 + 5 题冒烟 + 远端算力解耦 | [week1-plan.md](docs/week1-plan.md) | ✅ 已完成 | 锁死 30/5 题集；Empty 0/5、Gold 5/5；DeepSeek 冒烟 2/5（40%）；远端 Windows x86_64 Docker + ECS 反向隧道 4 并发提速 **2.71×**（`210.9s → 77.7s`）。 |
| **Week 2** | 底座加固 + 30 题 V0.1 Baseline + 首轮 V0.2~V0.4 消融 | 见 [progress.md](docs/progress.md) | ✅ 已完成 | 30 题 Gold **26/30（86.7%，0 超时）**；36 步 Baseline **17/30（56.7%）**；完成首轮四组消融与逐题 E1~E6 归因，精准定位静态 RepoMap / 过严门禁 / 正则压缩的负收益根因。 |
| **Week 3** | **零泄露固化 + 根因级提分 + 严密拆因 + 按需 RepoMap / Explorer / Best-of-K + 工程底座补全** | [week3-plan.md](docs/week3-plan.md) · [week3-fix.md](docs/week3-fix.md) | 🔄 **进行中（已达 73.3% / 去噪 80.8%）** | **已完成（Day 1~3）**：新版 26 题噪声审计、`FIX-017`/`018` 零泄露工作树门禁、真实 CNY 计费接入、根因级优化（`21/30`），并在 Day 3 完成单因子拆因与零前缀破坏全缓存实验，30 题 Pass@1 再升至 **22/30（73.3%，去噪 21/26 = 80.8%，0 空补丁，0 循环，缓存命中 97.68%，总成本降至 ¥8.02）**。<br>**剩余 Day 4~7**：全前缀默认化 + 按需 `get_repo_map` + LLM 语义级 Compaction → 只读 Explorer Subagent → Best-of-K 择优冲刺 **≥ 85% 去噪通过率**（双采样 Oracle 并集已达 `22/26 = 84.6%`）→ 全功能 CLI + 隧道自愈 + GitHub CI。 |
| **Week 4** | **50 题无外网噪声全量基准 + V0.1→V0.5 完整消融曲线 + 跨模型横向评测** | `docs/week4-plan.md`（待拆） | ⬜ 待开始 | 锁定 50 题 100% Gold / 0% Empty 干净 Verified 集；产出 50 题完整 V0.1→V0.5 消融表（Pass@1 / E1~E6 / 步数 / Token / 缓存 / 人民币成本）；同 Harness 横向对比 3 档模型（`deepseek-flash` / `qwen3.8-reasoner` / `smart/reasoning`）。 |
| **Week 5** | **生产级异步并发沙箱池 + 交互式轨迹回放与消融对比看板** | `docs/week5-plan.md`（待拆） | ⬜ 待开始 | 异步沙箱资源池（并发配额、僵尸容器 GC、隧道自动重连心跳）；落地可视化看板（ReAct 逐步思考/工具/Diff 回放 + 多版本消融对比矩阵）。 |
| **Week 6** | **GitHub Webhook / Actions CI 自愈自动提 Draft PR 端到端闭环** | `docs/week6-plan.md`（待拆） | ⬜ 待开始 | 对接真实 GitHub 仓库：接收失败 CI 日志 → 隔离 Docker 自动复现 → Agent 修复与回归验证 → 自动创建 Draft PR（附根因、验证日志与最小 Diff）。 |
| **Week 7** | **红队安全压测套件 + 大仓库性能压测 + 严格静态检查** | `docs/week7-plan.md`（待拆） | ⬜ 待开始 | 自动化压测 OOM / Fork 炸弹 / 路径与软链接逃逸 / 断网隔离 / 死循环超时强杀 / 10K+ 文件仓库性能；补齐类型检查与高测试覆盖率。 |
| **Week 8** | **旗舰版技术白皮书、演示录屏与面试 8 大深挖题实证沉淀** | `docs/week8-plan.md`（待拆） | ⬜ 待开始 | 旗舰 README（架构图 + 50 题消融曲线 + 跨模型矩阵 + CI 自愈录屏）；撰写《系统架构与基准评测白皮书》；用全部实测数据填实学习手册 8 道面试深挖题。 |

---

## 二、当前实测基线与真实人民币成本总览（截至 2026-11-28）

> 统一计费标准：未缓存输入 **¥2.0 / 1M**、缓存输入 **¥0.2 / 1M**、输出 **¥2.0 / 1M**；同一锁定 30 题集与同一模型 `deepseek-flash`。

| 实验组 | 30 题 Pass@1 | 26 题去噪 Pass@1 | 非空补丁 | 循环熔断 | Prompt Tokens | Cache 命中率 | 30 题费用 | 每通过 1 题 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Week 2 Baseline (36 步, thinking=off) | 17/30 (56.7%) | 16/26 (61.5%) | 28/30 | 1 | 5.61M | 66.8% | ¥4.74 | ¥0.279 |
| Week 2 RepoMap v1 (静态前置) | 12/30 (40.0%) | 11/26 (42.3%) | 25/30 | 2 | 7.43M | 70.6% | ¥5.66 | ¥0.471 |
| Week 2 Guardrails v1 (含旧提示) | 16/30 (53.3%) | 15/26 (57.7%) | 30/30 | 0 | 7.93M | 72.2% | ¥5.92 | ¥0.370 |
| Week 2 Compaction 60K (0 次触发) | 15/30 (50.0%) | 14/26 (53.8%) | 26/30 | 6 | 8.66M | 95.9% | ¥2.63 | ¥0.176 |
| Week 3 Guardrails v2 (零泄露工作树) | 15/30 (50.0%) | 14/26 (53.8%) | 26/30 | 3 | 5.95M | 71.8% | ¥4.48 | ¥0.299 |
| Week 3 Compaction 18K (12 次正则压缩) | 10/30 (33.3%) | 10/26 (38.5%) | 24/30 | 5 | 7.45M | 94.6% | ¥2.49 | ¥0.249 |
| Week 3 Boost (`boost-30`, 40 步, mask16, thinking=on) | 21/30 (70.0%) | 20/26 (76.9%) | 30/30 | 0 | 22.46M | 84.0% | ¥12.43 | ¥0.592 |
| Week 3 Day 3 Harness 拆因 (`ablation-harness-nothink`, 40 步, thinking=off) | 13/30 (43.3%) | 12/26 (46.2%) | 26/30 | 4 | 14.70M | 80.7% | ¥8.40 | ¥0.646 |
| **Week 3 Day 3 全前缀高缓存 (`ablation-fullprefix`, 40 步, 零遮蔽, thinking=on)** | **22/30 (73.3%)** | **21/26 (80.8%)** | **30/30** | **0** | **27.25M** | **97.7%** | **¥8.02** | **¥0.364** |

**核心实证结论**：
1. **质量与成本双赢（全前缀不可变 > 滑动遮蔽）**：Day 3 禁用滑动 Masking（`HARNESS_KEEP_RECENT_OBSERVATIONS=0`）后，缓存命中率从 `84.0%` 跃升至 **`97.68%`**（未缓存输入仅 `0.63M`），30 题总成本从 `¥12.43` 降至 **`¥8.02`（-35.5%）**，同时 Pass@1 再升至 **22/30（73.3%，去噪 21/26 = 80.8%）**，0 空补丁、0 循环、0 上下文超限、5 道干净未过题全部 0 回归。
2. **模型推理深度 × Harness 复杂度强交互**：关闭 Thinking 时新 Harness 的重上下文（`14.70M`）反而导致 4 例 E5 回归（`13/30`，¥8.40）；开启 Thinking 后带来 **`+8/-0`（零退化）** 跃升，且配合全前缀缓存（¥8.02）反而比关 Thinking（¥8.40）更省钱。
3. **冲刺路径清晰**：`boost-30 ∪ ablation-fullprefix` 双采样 Oracle 并集已达 **`23/30（76.7%）`、去噪 `22/26（84.6%）`**；双轮都未攻克的干净硬骨头仅剩 **4 题**（`django-13212`、`matplotlib-26466`、`pytest-10356`、`sympy-14248`，均为 E4 边界遗漏、0 回归），正是 Day 4~6 **按需 RepoMap + 只读 Explorer + Best-of-3 Verifier** 的精准靶点（详见 [docs/week3-fix.md](docs/week3-fix.md)）。

---

## 三、Week 3 剩余任务详细排期（Day 4 ~ Day 7）

> 完整 Day 1 ~ Day 7 可执行清单与验收命令见独立周计划：[docs/week3-plan.md](docs/week3-plan.md)；Day 3 复盘与 `FIX-020`~`022` 见 [docs/week3-fix.md](docs/week3-fix.md)。
>
> **Week 3 已完成项**：Day 1（Week 2 收口 + 新版 26 题噪声审计）、Day 2（零泄露工作树门禁 `FIX-017`/`018` + 18K 压缩证伪 `FIX-019` + 根因级优化达 `21/30` + CNY 计费）、Day 3（单因子拆因 `13/30` 证成 Thinking `+8/-0` 协同效应 + 全前缀不可变达 **22/30 = 73.3% / 去噪 80.8% / 97.68% 缓存 / ¥8.02**）。

### Day 4 · 按需 `get_repo_map` 工具（闭环 `FIX-007`）+ LLM 语义级 Compaction（闭环 `FIX-008`）

- **目标**：把被 v1 证伪的两项核心模块彻底重构成真正有效的生产级实现。
- **执行任务**：
  1. **按需 ACI 工具 `get_repo_map`（`src/harness/repomap/mapper.py`、`src/harness/tools/aci.py`）**：
     - 取消 Step 1 静态前置灌注（零初始噪声、零缓存前缀污染）；
     - 注册 `get_repo_map(focus_files: list[str] = [], query: str = "", max_tokens: int = 1500)`，结合 Tree-sitter 符号定义/引用图与 `focus_files`/`query` 个性化 PageRank 排序返回结构骨架；
     - 在 `run_agent_batch.py` 增加 `--with-repomap-tool` 并补齐单测。
  2. **LLM 语义级结构化 Compaction（`src/harness/context/manager.py`、`src/harness/agent/controller.py`）**：
     - 摒弃会抹掉代码细节的 230 字符正则拼接；
     - 当上下文真正逼近长窗口阈值（如 45K~60K Token）时，发起一次独立的摘要 LLM 请求，按严格 Schema 输出：`① 已定位关键文件/符号/精确行号`、`② 当前工作树 Diff 摘要`、`③ 已证伪假设（Failed Attempts）`、`④ 剩余待验证边界条件`，同时保留最近 6 轮原始消息不被抹除。
     - 补齐 Mock 单测验证长对话压缩后仍保留关键代码位置与失败假设。
- **验收标准**：单元测试全绿，在 30 题集上验证 `--with-repomap-tool` 与 LLM Compaction 不再出现 v1 负收益，闭环 `FIX-007`、`FIX-008`。

---

### Day 5 · 只读 Explorer Subagent（单写多读解耦）+ 剩余 6 题定向攻关

- **目标**：落地 Cognition 单写多读架构，把高噪声的跨文件探索从主上下文中解耦出去，攻克多点遗漏型难例。
- **执行任务**：
  1. **实现 `src/harness/agent/explorer.py`**：
     - 主 Agent 通过新 ACI 工具 `explore_codebase(question: str, entry_hints: list[str] = [])` 派发只读子 Agent；
     - 子 Agent 拥有独立只读上下文（最多 8 步，仅开放 `search_code`、`view_file`、`get_repo_map`，严禁 `edit_file` 与 `run_command`），强制输出结构化「定位报告（根因候选 + 精确文件路径与行号 + 涉及子类/调用方清单）」；
     - 事件流完整记录子 Agent 轨迹与 Token/费用汇总（可追溯回放）。
  2. **定向验证剩余 6 道干净未过题**（`django-13212`、`django-13401`、`matplotlib-25960`、`matplotlib-26466`、`pytest-10356`、`sympy-14248`），评估 Explorer 对多点遗漏（如 `django-13212` 3/5 F2P、`matplotlib-26466`）的真实提分效果。
- **验收标准**：Explorer Subagent 单测与轨迹记账全通，30 题消融中验证对复杂跨文件定位与总步数的改善。

---

### Day 6 · Best-of-K 并行采样 + 独立 Verifier 补丁择优（冲击去噪 85%+）

- **目标**：彻底解决单次采样随机退化（如 `boost-30` 退化的 3 题）与 P2P 回归（如 `sympy-14248` 6 项 P2P 失败），把系统推向真正 SOTA 级通过率。
- **执行任务**：
  1. **实现 `src/harness/eval/selector.py` 与 `scripts/run_best_of_k.py`**：
     - 对每题生成 `K=3` 条独立候选补丁（如 1 条 `temp=0.0` + 2 条 `temp=0.4` 或策略组合：`boost` / `boost + explorer`）；
     - 独立 **Sandbox Verifier** 在干净容器中对每个非空去重候选补丁执行：
       1. 补丁可干净 `git apply` + 仅修改业务源码（无测试文件/临时文件污染）；
       2. 自动识别并运行与修改文件关联的既有回归测试套件，统计通过数与零回归性；
       3. 由独立 Reviewer/Verifier 模型结合问题描述、候选 Diff 与测试输出，在所有通过回归的候选中选出最完整、最贴合根因的补丁（支持 Majority Voting + Verifier Reranking）。
  2. **在 30 题上实测 `Best-of-3`**（对比单次 `21/30 = 70.0%`）：目标 30 题 **≥ 23/30（76.7%）**，26 题去噪 **≥ 22/26（84.6%）**。
- **验收标准**：`Best-of-3` 产出完整候选日志、择优理由与官方评分报告，净提分明确且可复现。

---

### Day 7 · 工程底座补全（全功能 CLI + 隧道自愈 + GitHub Actions CI + 阶段复盘）

- **目标**：消除一切“实验脚本强、主框架入口弱”的割裂感，让项目达到开箱即用的生产级规范。
- **执行任务**：
  1. **全面升级 `src/harness/__main__.py`**：
     - `coding-harness solve` 支持 `--backend local|docker`、`--image`、`--thinking`、`--max-steps`、`--max-cost`、`--pipefail`、`--with-loop-recovery`、`--with-verification`、`--with-repomap-tool`、`--with-explorer`、`--best-of K`；
     - `coding-harness repomap` 默认使用 Tree-sitter + PageRank `build_ranked_map`（支持 `--query` / `--focus`）。
  2. **远端 Docker 启动自愈加固（`src/harness/runtime/docker.py`）**：
     - 在 `start()` 前增加 `docker info` / 隧道健康探测与指数退避重试（最多 3 次），彻底根治远端隧道瞬断导致的 `0 steps error`；补齐单测。
  3. **上线仓库 CI（`.github/workflows/ci.yml`）**：Push / PR 自动运行 `ruff check src tests scripts` + `pytest -v`。
  4. **撰写 `docs/devlog-week2-3.md`**：完整沉淀从 `10/30 → 17/30 → 负收益教训 → 零泄露修复 → 21/30 → Best-of-K` 的演进证据链，推送双端。

---

## 四、Week 4 ~ Week 8 旗舰级完整规划

### Week 4 · 50 题无外网噪声 Verified 全量基准 & 跨模型横向评测

- **Day 1–2（锁定 50 题干净基准集）**：
  - 扩展 `scripts/sample_swebench.py` 导出并锁定 `data/swebench_verified_50.jsonl`（保留现有 26 道干净题 + 新增 24 道跨仓库分层题，**前置全量离线 Gold 50/50 = 100% 且 Empty 0/50 = 0% 强校验**，彻底消灭外网噪声）；
  - 使用 `scripts/pull_images.py` 在远端 Windows x86_64 节点拉齐全部 50 个镜像并存档 manifest 与 SHA-256。
- **Day 3–5（50 题 V0.1 → V0.4 完整消融曲线）**：
  - 在 50 题严格同条件下跑齐 5 组正式里程碑版本：
    - **V0.1 Baseline**（原始 36 步 `thinking=disabled`）
    - **V0.2 Harness Core**（无失忆上下文 + 300 行窗 + 提示词 + `pipefail` + 软循环恢复 + `get_repo_map`）
    - **V0.3 Reasoning + Stable Prefix**（+ `thinking=enabled` + 全前缀高缓存 + LLM 语义 Compaction）
    - **V0.4 Explorer + Guardrails**（+ 只读 Explorer Subagent + 零泄露工作树门禁）
    - **V0.5 Best-of-3 Verifier**（+ 多轨迹并行采样与回归测试择优）
  - 产出完整 50 题消融矩阵（Pass@1、E1~E6 分布变化、平均步数、Token、缓存命中率、真实人民币费用）。
- **Day 6–7（跨模型横向评测）**：
  - 用同一套最终 Harness（V0.4）在 50 题（或 30 题子集）上横向评测 3 档模型：`deepseek-flash`、`qwen3.8-reasoner`、`smart/reasoning`（或 `qwen3.8-chat`），绘制「模型能力 × Harness 增益」二维对照表。

---

### Week 5 · 生产级异步并发沙箱池 + 交互式轨迹回放与消融看板

- **Day 1–3（异步并发沙箱池 `src/harness/runtime/pool.py`）**：
  - 基于 `asyncio` / 信号量实现并发沙箱调度池，支持最大并发容器上限、内存/CPU 配额预算、容器生命周期追踪、异常退出自动清理与定期僵尸容器 GC（防止远端宿主机泄漏容器）；
  - 集成远端 SSH 隧道健康监控与自动断线重连探针，批跑脚本切换至沙箱池调度。
- **Day 4–7（交互式轨迹回放与消融对比看板 `src/harness/dashboard/`）**：
  - 编写静态 HTML + 轻量前端（零重型构建依赖，可直接浏览器打开或本地 `coding-harness dashboard` 启动）：
    1. **总览页**：多版本消融对比柱状图/折线图（Pass@1、缓存命中率、单题耗时与人民币成本、E1~E6 归因堆叠图、分仓库热力图）；
    2. **逐题对比页**：点击任意 `instance_id` 并排对比 Baseline vs V0.4/V0.5 的最终 Patch Diff 与 F2P/P2P 判定；
    3. **时间线回放页**：逐步展开每轮的 `reasoning_content` 思考过程、工具调用参数、截断前/后观察输出、Token 与缓存命中曲线、子 Agent（Explorer）嵌套轨迹。

---

### Week 6 · GitHub Webhook / Actions CI 自愈提 Draft PR 端到端闭环

- **Day 1–3（CI 自愈引擎 `src/harness/ci/`）**：
  - 实现 GitHub Actions 失败工作流日志抓取与结构化错误提取（`ci_parser.py`）；
  - 实现 `ci_healer.py`：拉取目标 PR/Commit → 启动隔离 Docker 沙箱复现 CI 失败命令 → 运行 Harness 修复并通过全套回归测试 → 生成规范的修复说明（根因、修改点、验证命令与输出、风险提示）；
  - 实现 `github_client.py`：通过 GitHub REST API 自动推修复分支并创建 **Draft PR**（或向失败 PR 发表带可应用 Patch 的 Review Comment），全链路支持 `--dry-run` 安全模式与人工确认闸门。
- **Day 4–5（Webhook 服务与队列对接）**：
  - 提供轻量 FastAPI / 标准库 HTTP Webhook 接收器（校验 `X-Hub-Signature-256` HMAC 签名，仅监听指定仓库的 `workflow_run.completed [failure]` 事件），入队交由 Week 5 异步沙箱池执行。
- **Day 6–7（真实仓库端到端闭环验证与录屏）**：
  - 在独立 Demo GitHub 仓库构造 3 类真实 CI 故障（逻辑 Bug、依赖/边界回归、多文件接口破坏），跑通「Push 触发 CI 红灯 → Webhook 自动拉起 Harness → 自动修复验证 → 自动提 Draft PR 且 CI 转绿」全流程并录制演示视频/GIF。

---

### Week 7 · 红队安全压测套件 + 大仓库性能压测 + 代码质量封板

- **Day 1–3（自动化安全红队压测 `tests/test_security_stress.py`）**：
  - 逐项编写可重复执行的真实容器压测用例并输出安全审计报告：
    1. **内存炸弹（OOM）**：分配 4GB 内存验证被 `--memory=2g --memory-swap=2g` 秒杀且宿主机无感；
    2. **Fork 炸弹**：验证被 `--pids-limit=256` 阻断；
    3. **路径穿越 & 软链接逃逸**：测试 `../../etc/passwd`、容器/本地软链接指向工作区外文件全部被 `LocalWorkspaceRuntime` / `DockerSandboxRuntime` 拦截；
    4. **网络隔离（SSRF / 数据外泄）**：验证 `--network=none` 下 `curl` / `socket` 外联 100% 阻断；
    5. **命令死循环与孤儿进程**：验证 `timeout --signal=KILL` 杀净整个进程组且宿主机超时保留容器可安全导出 diff；
    6. **权限降级**：验证 `--cap-drop=ALL` + `no-new-privileges` 阻止特权操作。
- **Day 4–5（大仓库性能基准与工程收紧）**：
  - 在 10K+ 文件级仓库压测 `RepoMapper`（Tree-sitter + PageRank）、`search_code` 与事件流写入延迟，优化瓶颈并记录 P50/P95 延迟；
  - 接入 `mypy` 严格类型检查与 `pytest --cov=harness`（核心模块测试覆盖率目标 **≥ 85%**），纳入 `.github/workflows/ci.yml`。
- **Day 6–7（端到端全回归）**：跑通全套单测 + 安全压测 + 看板生成 + CI 自愈 Dry-Run，确保零缺陷。

---

### Week 8 · 旗舰级交付收官、技术白皮书与面试深挖沉淀

- **Day 1–3（技术白皮书与旗舰 README）**：
  - 撰写 `docs/architecture-and-benchmark-report.md`：完整呈现系统架构、控制面/执行面异构解耦、ACI 与安全沙箱设计、**负收益踩坑与根因反转案例研究**（静态 RepoMap / 过严门禁 / 正则压缩 / 评测泄露排查 / 上下文失忆）、50 题 V0.1→V0.5 完整消融曲线、跨模型矩阵、人民币成本 ROI 分析；
  - 升级根目录 `README.md`：嵌入核心架构图、关键消融成果表、看板截图、CI 自愈 Demo GIF 与一键复现指南。
- **Day 4–5（面试深挖题库实证化）**：
  - 产出 `docs/interview-prep-evidence.md`：用本项目真实数据、代码行号、失败轨迹与对比表逐题填实 [docs/coding-agent-study-guide.md](docs/coding-agent-study-guide.md) 第 6.2 节全部 8 道面试官高频深挖题（外加「如何防止 Benchmark Data Leakage」「如何做单因子消融归因」2 道加分题）。
- **Day 6–7（最终封板发布）**：
  - 打正式 Release Tag（`v1.0.0`），同步 GitHub 与 Gitee，清理所有临时分支与过期产物。

---

## 五、质量与工程红线（全程强制执行）

| 红线 | 具体约束 |
| :--- | :--- |
| **零评测数据泄露** | 推理期严禁读取 `patch`、`test_patch`、`FAIL_TO_PASS`、`PASS_TO_PASS`；由回归单测 `test_batch_does_not_expose_grading_inputs_to_verification` 强制守护。 |
| **单变量消融纪律** | 每次新增模块必须先跑单因子对照，验证真实净收益后再合入组合版本；如实记录负收益案例（绝不挑选性汇报）。 |
| **全链路可复现** | 锁定题集 SHA-256、容器镜像 Digest、批跑指纹 `inputs.json`、逐题 `.jsonl` 轨迹与官方 `summary.json` 完整可溯源。 |
| **安全与隐私底线** | 绝不提交密钥、真实公网/内网 IP 与主机名；所有安全隔离边界必须有自动化压测用例验证。 |
