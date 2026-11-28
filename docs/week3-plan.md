# Week 3（第三阶段）执行计划：零泄露固化、根因提分、严密拆因与核心架构补齐

> 本阶段目标（最高完整度版）：**清零 Week 2 工程债务 → 根因级 Harness 提分并严密拆因 → 落地按需 `get_repo_map` + LLM 语义级 Compaction + 只读 Explorer Subagent + Best-of-3 Verifier 择优 → 补齐全功能 CLI、隧道自愈与 GitHub Actions CI**。
>
> 关联文档：[总执行计划](../plan.md) · [项目进展](progress.md) · [Week 3 修复台账](week3-fix.md) · [全局问题台账](../fix.md) · [Week 1 计划](week1-plan.md)

---

## 一、本阶段验收标准（Definition of Done）

- [x] **Week 2 收口与基线固化**：完成 `FIX-010`~`015`，4 组 36 步消融全员出分，发布新版 30 题网络噪声审计（26/30 默认对照全过，0 环境报错）并接入真实 CNY 计费（¥2 / ¥0.2 / ¥2）。
- [x] **零泄露护栏与根因级通过率突破**：完成 `FIX-017`、`FIX-018`、`FIX-019`、`FIX-016`；同一模型（`deepseek-flash`）30 题官方 Pass@1 从 `17/30 (56.7%)` 跃升至 **21/30（70.0%）**，26 题去噪达 **20/26（76.9%）**，0 空补丁、0 循环、缓存命中 **84.0%**。
- [x] **严密单因子拆因 + 零前缀破坏高缓存**：完成 `thinking=disabled` 新 Harness 拆因组（`13/30`，实证 `Thinking` 贡献 `+8/-0` 题且与重 Harness 强协同）与禁用滑动 Masking 全前缀缓存组（`22/30 = 73.3%`、去噪 `21/26 = 80.8%`、缓存 `97.68%`、总成本 `¥8.02` 降本 `35.5%`）。详情见 [Week 3 修复台账](week3-fix.md)。
- [ ] **按需 `get_repo_map` + LLM 语义级 Compaction**：完成 `FIX-007`、`FIX-008` 架构重构与 30 题实测，彻底消除 v1 负收益。
- [ ] **只读 Explorer Subagent + Best-of-3 Verifier 择优**：落地单写多读探索子 Agent 与多轨迹测试择优，30 题冲刺 **≥ 23/30（76.7%）**、26 题去噪冲刺 **≥ 22/26（84.6%）**。
- [ ] **工程底座封板**：升级全功能 CLI（`src/harness/__main__.py`）、`DockerSandboxRuntime.start()` 隧道自愈重试、上线 `.github/workflows/ci.yml`、产出 `docs/devlog-week2-3.md` 并双端推送。

---

## 二、Day 1 ~ Day 7 每日拆解计划

### Day 1（已完成）：Week 2 彻底收口、新版噪声审计与三笔基线提交

- [x] **补齐 `compaction` 实验（`FIX-013`）**：30 题出分 `15/30`（`compactions=0`，暴露默认 60K 阈值过高），产出完整 [ablation-36steps.json](../runs/week2/ablation-36steps.json)。
- [x] **清理配置并分主题提交（`FIX-010`）**：拆分提交 `4ac719e`（执行底座）、`c19fd02`（消融框架）、`f388d70`（文档与基线），同步 GitHub 与 Gitee。
- [x] **发布新版 30 题网络噪声审计（`FIX-012`）**：产出 [controls-audit.json](../runs/week3/day1/controls-audit.json)，确认 26/30 默认对照全过、0 基础设施报错，明确排除 4 道 `psf__requests` 外网题（`1724 / 1766 / 2317 / 2931`）。

---

### Day 2（已完成）：零泄露工作树门禁、18K 压缩证伪、根因级提分与 CNY 计费接入

- [x] **消除评测泄露与二次误拒（`FIX-017`、`FIX-018`）**：切断 `instance.test_modules` 透传，改用纯工作树零泄露门禁与业务源码 diff 摘要，30 题零泄露护栏实测 `15/30`（去噪 `14/26`）。
- [x] **18K 压缩实测（`FIX-019`）**：30 题触发 12 次正则压缩，官方 `10/30`，实证正则摘录清空已读代码会诱发上下文失忆与循环。
- [x] **根因级 Harness 优化（提交 `144489a`、`ee3634b`）**：
  - `keep_recent_observations` `5 → 16`、`mask_threshold_chars` `600 → 3000`、永不遮蔽 `edit_file` / `git_status_diff`；
  - `MAX_VIEW_LINES` `150 → 300`（默认 250 行）、`MAX_SEARCH_MATCHES` `30 → 40`、默认开启最近似行号反馈；
  - 升级系统工程纪律提示词；支持 `--thinking enabled`（`max_tokens ≥ 16384`、清洗 `raw_message` 保留 `reasoning_content`）；修复 `finish_reason="length"` 误判为 `finished` 的 Bug；新增畸形 tool-call JSON 容错。
- [x] **全量 30 题官方评测突破**：`runs/week3/boost-30` 达到 **21/30（70.0%）**、26 题去噪 **20/26（76.9%）**，0 空补丁、0 循环、缓存命中 **84.0%**，攻克 4 道历史 6 轮全败难题（`django-13112`、`django-13794`、`psf__requests-6028`、`sympy-13551`）。
- [x] **真实 CNY 计费接入（提交 `02764d6`）**：接入 ¥2.0 / ¥0.2 / ¥2.0 每百万 Token 费率与 `compare_harness_runs.py` 自定义币种重算，`boost-30` 30 题实测总费用 **¥12.43**（单题 ¥0.414），全套单测达 **51/51**。

---

### Day 3（已完成）：严密单因子拆因消融 + 零前缀破坏高缓存实验

Day 3 四组官方评测、拆因报告与复盘已完成（26 道干净题 100% 正常出分，仅外网噪声题 `psf__requests-2317` 出现 300s 超时）。复盘与新增待修项（`FIX-020`~`022`）见 [Week 3 修复台账](week3-fix.md)。

- [x] **实验 A · 纯 Harness 增益拆因（关闭 Thinking）**：
  - 固定 `--thinking disabled`，保留全部新 Harness 改动（16/3000 上下文 + 300 行窗 + 新提示词 + 40 步 + `pipefail` + 软循环恢复），完成 30 题官方评测（`runs/week3/ablation-harness-nothink-score`）：**13/30（43.3%）**，去噪 **12/26（46.2%）**，缓存 `80.69%`，成本 `¥8.40`（每通过一题 `¥0.646`），空补丁 4 / 循环 4。
  - **拆因结论**：新 Harness 上下文放大 2.6×（`5.61M → 14.70M`），关闭 Thinking 时模型出现 4 例 E5 回归与过度阅读；同 Harness 下开启 `Thinking`（→ `boost-30`）贡献 **`+8 题 / -0 题`**（零退化），直接清零全部 E1/E5/E6。
- [x] **实验 B · 零前缀破坏全缓存验证**：
  - 设置 `HARNESS_KEEP_RECENT_OBSERVATIONS=0` 关闭滑动 Masking，在 `--thinking enabled` 下完成 30 题官方评测（`runs/week3/ablation-fullprefix-score`）：**22/30（73.3%）**，去噪 **21/26（80.8%）**，0 空补丁、0 循环、0 上下文超限、干净未过题 0 回归。
  - 统一 CNY 费率核算：缓存命中率飙升至 **97.68%**（未缓存输入仅 `0.63M`），30 题总成本从 `¥12.43` 降至 **¥8.02（-35.5%，单通过题 ¥0.364）**，反超关 Thinking 的实验 A（¥8.40）。
  - `boost-30 ∪ ablation-fullprefix` 双采样 Oracle 并集已达 **23/30（76.7%）**、去噪 **22/26（84.6%）**。
- **当日产出**：四组消融矩阵、人民币成本、逐题 E1～E6 归因与 [Week 3 修复台账](week3-fix.md)（`FIX-020`~`022`）。

---

### Day 4：按需 `get_repo_map` 工具（闭环 `FIX-007`）+ LLM 语义级 Compaction（闭环 `FIX-008`）

- [ ] **重构 RepoMap 为按需 ACI 工具（`src/harness/repomap/mapper.py`、`src/harness/tools/aci.py`、`scripts/run_agent_batch.py`）**：
  - 注册按需工具 `get_repo_map(focus_files: list[str] = [], query: str = "", max_tokens: int = 1500)`：基于 Tree-sitter 符号定义/引用图 + `focus_files`/`query` 个性化 PageRank 返回局部结构骨架；
  - Step 1 保持零初始地图污染，系统提示词仅用一句话引导模型在跨文件定位困难时按需调用；
  - 批跑脚本新增 `--with-repomap-tool`（与旧静态 `--with-repomap` 解耦），补充单元测试。
- [ ] **升级 LLM 语义级结构化 Compaction（`src/harness/context/manager.py`、`src/harness/agent/controller.py`）**：
  - 摒弃破坏性正则拼接；当上下文超过长窗口阈值（默认 `45,000` 估算 Token）时，由独立 LLM 请求提炼结构化摘要，强制包含 4 个固定段：`① 关键文件/符号与精确行号`、`② 当前工作树 Diff 摘要`、`③ 已证伪假设（Failed Attempts）`、`④ 剩余待验证边界条件`；
  - 压缩时保留最近 6 轮原始消息不被抹除，防止刚读完代码立刻失忆；
  - 补充 Mock 单元测试覆盖「长对话触发语义压缩 → 保留关键行号与最近 6 轮 → 继续完成修复」。
- [ ] **30 题验证**：在 `boost` 基础上单测 `--with-repomap-tool` 与 LLM Compaction，确认零负收益并闭环 `FIX-007`、`FIX-008`。

---

### Day 5：只读 Explorer Subagent（单写多读解耦）+ 剩余 6 题定向攻关

- [ ] **实现 `src/harness/agent/explorer.py`**：
  - 遵循 Cognition 单写多读架构：主 Agent 通过 `explore_codebase(question: str, entry_hints: list[str] = [])` 派发只读子 Agent；
  - 子 Agent 使用独立上下文（上限 8 步），仅注册 `search_code`、`view_file`、`get_repo_map` 三个只读工具（严禁写文件与执行命令），输出结构化定位报告（根因候选 + 精确文件与行号 + 涉及子类/调用方清单）；
  - 子 Agent 的 Token / 费用与步骤事件完整归入主轨迹 `EventStream`（支持独立审计与回放）。
- [ ] **补齐单元测试**：Mock 测试验证只读权限边界、子 Agent 独立上下文不污染主对话、Token 计费汇总准确。
- [ ] **定向攻关剩余 6 道干净失败题**：在 `django-13212`、`django-13401`、`matplotlib-25960`、`matplotlib-26466`、`pytest-10356`、`sympy-14248` 上实测 Explorer 带来的定位完整度提升，并跑全量 30 题消融（`--with-explorer`）。

---

### Day 6：Best-of-3 并行采样 + 独立 Verifier 补丁择优（冲击去噪 85%+）

- [ ] **实现 `src/harness/eval/selector.py` 与 `scripts/run_best_of_k.py`**：
  - 对每道题运行 `K=3` 条独立候选轨迹（如 1 条 `temp=0.0` + 2 条 `temp=0.4` 或混合策略：`boost` / `boost+explorer`）；
  - 独立 **Sandbox Verifier** 对去重后的非空候选补丁在干净容器中执行：
    1. 补丁可干净应用且仅改动业务源码（自动过滤测试/临时文件污染）；
    2. 推断并运行与改动文件关联的模块既有测试套件，淘汰引发 P2P 回归的候选（如 `sympy-14248` 的 6 项回归）；
    3. 由独立 Verifier LLM 结合问题描述、各候选 Diff 与回归测试输出进行投票/打分，选出最完整且最极简的最终补丁。
- [ ] **30 题全量实测 `Best-of-3`**：
  - 产出完整候选池日志、择优决策记录与官方 `summary.json`；
  - 验收目标：30 题 Pass@1 **≥ 23/30（76.7%）**，26 题去噪 **≥ 22/26（84.6%）**。

---

### Day 7：工程底座封板（全功能 CLI + 隧道自愈 + GitHub CI + 阶段复盘）

- [ ] **升级全功能 CLI（`src/harness/__main__.py`）**：
  - `coding-harness solve` 支持 `--backend local|docker`、`--image`、`--thinking`、`--max-steps`、`--max-cost`、`--pipefail`、`--with-loop-recovery`、`--with-verification`、`--with-repomap-tool`、`--with-explorer`、`--best-of K`；
  - `coding-harness repomap` 默认使用 Tree-sitter + PageRank `build_ranked_map`（支持 `--query` / `--focus`），补充 CLI 单元测试。
- [ ] **远端 Docker 启动自愈（`src/harness/runtime/docker.py`）**：
  - `start()` 前加入 `docker info` 隧道健康探测与指数退避重试（3 次：5s/10s/20s），彻底解决远端隧道瞬断导致的 `0 steps error`，补充单测。
- [ ] **上线 GitHub Actions CI（`.github/workflows/ci.yml`）**：Push / PR 自动执行 `ruff check src tests scripts` + `pytest -v`。
- [ ] **阶段复盘与双端交付**：
  - 撰写 `docs/devlog-week2-3.md`（完整沉淀 `10/30 → 17/30 → 负收益复盘 → 零泄露修复 → 21/30 → 拆因与 Best-of-3` 全链路数据）；
  - 同步更新 `plan.md`、`docs/progress.md`、`fix.md`、`README.md`，全套测试 + lint 绿灯后推送 GitHub 与 Gitee。

---

## 三、本阶段实验与工程纪律

1. **零评测数据泄露**：所有新工具（`get_repo_map`、`explore_codebase`、Best-of-3 Verifier）严禁接触数据集中的 `patch`、`test_patch`、`FAIL_TO_PASS`、`PASS_TO_PASS`。
2. **统一度量口径**：所有 30 题实验统一使用 `--noise-audit runs/week3/day1/controls-audit.json` 并列报告 `30 题全量` 与 `26 题去噪`，统一按 `--input-price 2.0 --cached-price 0.2 --output-price 2.0 --currency CNY` 核算真实人民币成本。
3. **每日可回溯**：每组实验使用独立输出目录，保留 `inputs.json`、`results.jsonl`、`predictions.jsonl`、`trajectories/` 与官方 `summary.json`。
