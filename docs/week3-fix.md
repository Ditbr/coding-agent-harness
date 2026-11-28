# Week 3 问题修复台账与 Day 3 复盘清单（Week 3 Fix Log）

> 更新日期：2026-11-28
> 关联文档：[总执行计划](../plan.md) · [Week 3 计划](week3-plan.md) · [项目进展](progress.md) · [全局问题台账](../fix.md)

---

## 一、Week 3 问题总览（Day 1 ~ Day 3）

| ID | 优先级 | 类别 | 状态 | 阶段 | 问题与修复摘要 |
| :--- | :---: | :--- | :---: | :---: | :--- |
| `FIX-016` | P2 | Harness / ACI | `DONE` | Day 2 | 上下文失忆修复 + 300 行阅读窗 + 系统提示词升级 + 软循环恢复；空补丁与循环熔断均降至 `0` |
| `FIX-017` | P0 | Eval / Integrity | `DONE` | Day 2 | 推理批跑改用独立 `AgentTask` 投影，切断 `test_patch` / `test_modules` 透传，实现严格零评测泄露 |
| `FIX-018` | P1 | Harness / Verification | `DONE` | Day 2 | `VerificationGate` 仅对业务源码 diff 计算验证摘要，还原测试文件/删除临时脚本后不再触发二次误拒 |
| `FIX-019` | P1 | Harness / Context | `DONE` | Day 2 | 18K 规则正则压缩 30 题实测 `10/30`（证伪）；转用非破坏性全前缀策略，缓存升至 `97.68%` 且 Pass@1 达 `22/30` |
| **`FIX-020`** | P1 | Eval / Reporting | `TODO` | Day 3 收口 | Day 3 报告脚本 `runs/week3/day3/report.py` 将已知外网噪声题（`psf__requests-2317`）300s 超时归为阻塞性「评测中断」，导致自动验收误拦 |
| **`FIX-021`** | P1 | Harness / Context | `TODO` | Day 4 前置 | `ContextConfig.keep_recent_observations` 默认仍为 `16`；Day 3 实证 `0`（全前缀不可变）在质量/缓存/成本上全面占优，需切换默认策略并重定位 LLM Compaction 为超长兜底安全阀 |
| **`FIX-022`** | P2 | Harness / Core | `TODO` | Day 4 ~ 6 | 剩余 4 道双轮未过干净题（`django-13212`、`matplotlib-26466`、`pytest-10356`、`sympy-14248`，均 0 回归）及单次采样波动（`pytest-7324`）的定向攻坚（按需 `get_repo_map` + Explorer + Best-of-3） |

---

## 二、Day 3 四组单因子拆因与全前缀高缓存复盘

> 统一口径：冻结 30 题集（`data/swebench_verified_30.jsonl`）、同模型 `deepseek-flash`、新版 26 题去噪审计（排除 `psf__requests-1724 / 1766 / 2317 / 2931`）、统一 CNY 费率（未缓存输入 ¥2.0 / 1M、缓存输入 ¥0.2 / 1M、输出 ¥2.0 / 1M）。

### 1. 四组实测对比矩阵

| 实验组 | 官方 Pass@1 | 去噪 26 题 Pass@1 | 输入 / 缓存 / 输出 Token | 缓存命中率 | 30 题总成本 | 单题 / 每通过 1 题 | 平均步数 | 空补丁 / 循环 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline-36steps`（36 步, thinking=off） | 17/30 (56.7%) | 16/26 (61.5%) | 5.61M / 3.75M / 131.6K | 66.79% | ¥4.74 | ¥0.158 / ¥0.279 | 28.3 | 2 / 1 |
| **实验 A** `ablation-harness-nothink`（40 步, 新 Harness, thinking=off） | 13/30 (43.3%) | 12/26 (46.2%) | 14.70M / 11.86M / 173.0K | 80.69% | ¥8.40 | ¥0.280 / ¥0.646 | 33.4 | 4 / 4 |
| `boost-30`（40 步, 新 Harness + mask16, thinking=on） | 21/30 (70.0%) | 20/26 (76.9%) | 22.46M / 18.86M / 737.7K | 84.00% | ¥12.43 | ¥0.414 / ¥0.592 | 30.6 | 0 / 0 |
| **实验 B** `ablation-fullprefix`（40 步, 新 Harness + **零遮蔽**, thinking=on） | **22/30 (73.3%)** | **21/26 (80.8%)** | **27.25M / 26.61M / 714.7K** | **97.68%** | **¥8.02** | **¥0.267 / ¥0.364** | **29.9** | **0 / 0** |

### 2. E1 ~ E6 失败分布演变

| 实验组 | PASS | E1 定位偏差 | E2 补丁/编辑失败 | E3 上下文超限 | E4 验证不足/边界漏修 | E5 引入回归 | E6 空补丁/死循环 | 环境噪声 | 噪声题超时 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline-36steps` | 17 | 2 | 0 | 0 | 7 | 1 | 2 | 1 | 0 |
| `ablation-harness-nothink` | 13 | 4 | 0 | 0 | 4 | 4 | 4 | 1 | 0 |
| `boost-30` | 21 | 0 | 0 | 0 | 6 | 0 | 0 | 2 | 1 (`requests-2317`) |
| `ablation-fullprefix` | **22** | **0** | **0** | **0** | 6 | 1 (`requests-1724`) | **0** | 0 | 1 (`requests-2317`) |

### 3. 核心实证结论

1. **全前缀不可变（实验 B）实现质量、缓存、成本三赢**：
   - 将 `HARNESS_KEEP_RECENT_OBSERVATIONS` 设为 `0` 关闭滑动 Observation Masking 后，未缓存输入从 `3.59M` 降至 **`0.63M`**，Prompt Cache 命中率从 `84.00%` 跃升至 **`97.68%`**；
   - 30 题总成本从 `¥12.43` 降至 **`¥8.02`（-35.5%，省 ¥4.42）**，每通过 1 题成本从 `¥0.592` 降至 **`¥0.364`（-38.5%）**；
   - 通过率进一步提升至 **22/30（去噪 21/26 = 80.8%）**（新增通过 `django-13401`、`matplotlib-25960`，仅丢 `pytest-7324`），且 **0 空补丁、0 循环、0 上下文超限（E3=0）、干净未过题全部 0 P2P 回归**。
   - **架构定论**：在 10× 缓存价差下，滑动 Observation Masking 同时破坏前缀缓存并引发长轨迹失忆，属于“双输反模式”；保持 append-only 不可变历史前缀是最优默认策略。
2. **揭示「模型推理深度 × Harness 复杂度」强交互效应（实验 A）**：
   - 新 Harness（300 行大窗 + 保留 16 条观察 + 全面排查提示词）将单任务输入膨胀 2.6×（`5.61M → 14.70M`）。关闭 `Thinking` 后快思考模型无法消化更重上下文与高要求指令：失去的 6 题中有 4 题其实目标 F2P 已通过却因过度修补引入 P2P 回归（E5 升至 4：`django-13401`、`matplotlib-25960`、`matplotlib-26342`、`pytest-10356`），另有 `django-13315` 调用 33 次 `view_file` 仅改 1 次即耗尽 40 步。
   - 同一套新 Harness 下开启 `Thinking`（实验 A → `boost-30`）带来 **`+8 题 / -0 题`（零退化）** 的压倒性正收益，一次性清零全部 E1（4→0）、E5（4→0）、E6（4→0）。
   - 更具工程价值的是：**开启 Thinking + 全前缀缓存的实验 B（¥8.02）反而比关闭 Thinking + 滑动遮蔽的实验 A（¥8.40）更便宜**，且多通过 9 题。
3. **验证 Best-of-K 理论上限**：
   - 仅取 `boost-30 ∪ ablation-fullprefix` 两次采样的 Oracle 并集，通过率已达 **`23/30（76.7%）`、去噪 `22/26（84.6%）`**，直接触达 Week 3 Day 6 目标。

---

## 三、Day 3 Review 新增待修复项详情

### <a id="fix-020"></a>FIX-020 · 报告脚本将已知外网噪声题超时误判为阻塞性「评测中断」

- **状态**：`TODO` | **优先级**：`P1` | **类别**：Eval / Reporting | **目标阶段**：Week 3 Day 3 收口 / Day 4
- **相关位置**：`runs/week3/day3/report.py`（L46–L50、L176–L179）、`scripts/compare_harness_runs.py`
- **现象与证据**：
  - Day 3 四组共 120 次评测中，26 道干净题 **100% 正常出分**、零任何基础设施异常；
  - 仅外网噪声题 `psf__requests-2317`（已在 `runs/week3/day1/controls-audit.json` 的 `external_noise_ids` 中）在 `boost-30-rescore` 与 `ablation-fullprefix-score` 中因 `httpbin.org` 挂起触发 300s `timeout`；
  - 报告脚本先判 `grade["status"] == "timeout" -> "评测中断"` 且 `update_week_plan()` 对任意「评测中断」一刀切拦截，导致日志打印 `Score interruptions remain. Kept the Day 3 acceptance boxes open.` 并返回退出码 `1`。
- **根因**：
  - 分类逻辑未结合 `external_noise_ids` 区分「干净题基础设施故障」与「已知外网噪声题网络挂起」。
- **建议修复**：
  1. 在归因脚本中对 `iid in noise` 且 `status == "timeout"` 单独归类为「外网噪声超时」（或在阻断验收前过滤 `external_noise_ids`），仅当干净题出现 `evaluation_error` / `timeout` / `missing_prediction` 时阻塞自动验收；
  2. 在通用评测汇总脚本中同样区分 `clean_infra_failures` 与 `noise_infra_failures`。
- **验收标准**：26 道干净题零基础设施失败时，报告脚本正常完成验收流且清晰标注外网噪声题状态。

---

### <a id="fix-021"></a>FIX-021 · 切换默认上下文策略为「全前缀不可变」，并将 LLM Compaction 重定位为超长安全阀

- **状态**：`TODO` | **优先级**：`P1` | **类别**：Harness / Context | **目标阶段**：Week 3 Day 4
- **相关位置**：`src/harness/config.py`（L71–L78、L103–L106）、`src/harness/context/manager.py`（L89–L116）、`.env.example`
- **现象与证据**：
  - 当前 `ContextConfig.keep_recent_observations` 默认值为 `16`（启用滑动 Masking），在 `boost-30` 上缓存命中率仅 `84.00%`、成本 `¥12.43`；
  - Day 3 实验 B 设置 `HARNESS_KEEP_RECENT_OBSERVATIONS=0` 后，缓存命中率跃升至 `97.68%`、成本降至 `¥8.02`（-35.5%）、去噪 Pass@1 升至 `21/26（80.8%）`，且 40 步内零上下文超限（`E3 = 0`）。
- **根因**：
  - 早期默认参数面向无缓存/小窗口模型设计，在支持 10× 前缀缓存的现代网关上会主动触发重复的 KV Cache 失效。
- **建议修复**：
  1. 将默认 `keep_recent_observations`（或独立开关）调整为 `0`（默认保留完整不可变前缀），同时保留 `HARNESS_KEEP_RECENT_OBSERVATIONS > 0` 兼容历史消融复现；
  2. Day 4 的 LLM 语义级 Compaction 默认阈值设为安全高水位（如 `45,000 ~ 60,000` 估算 Token），仅在极端超长轨迹逼近窗口上限时作为兜底触发，平时绝不打断 `97.7%` 前缀缓存，并保留最近 6 轮原始消息。
- **验收标准**：默认配置下前缀 100% 不可变，单测覆盖 `keep=0` 全前缀路径与超长轨迹 LLM 语义压缩兜底路径。

---

### <a id="fix-022"></a>FIX-022 · 剩余 4 道干净硬骨头与单次采样波动的定向攻关

- **状态**：`TODO` | **优先级**：`P2` | **类别**：Harness / Core | **目标阶段**：Week 3 Day 4 ~ Day 6
- **相关位置**：`src/harness/repomap/mapper.py`、`src/harness/agent/explorer.py`（待建）、`src/harness/eval/selector.py`（待建）
- **现象与证据**：
  - `ablation-fullprefix` 中仅剩 5 道干净未过题，且全部 **0 回归（`P2P_fail = 0`）**：
    - **双轮（`boost-30` 与 `fullprefix`）均未攻克的 4 道硬骨头**：
      1. `django__django-13212`（`finished` 38 步，F2P `3/5` — 多 validator / 字段类遗漏）
      2. `matplotlib__matplotlib-26466`（`finished` 34 步，F2P `0/1` — 坐标数组/拷贝生命周期边界遗漏）
      3. `pytest-dev__pytest-10356`（`finished` 38 步，F2P `0/1` — MRO 多继承 mark 合并逻辑偏差）
      4. `sympy__sympy-14248`（`max_steps` 40 步，F2P `1/2` — 多 printer 子类未改全）
    - **单次采样波动 1 题**：
      5. `pytest-dev__pytest-7324`（`boost-30` 通过、`fullprefix` 第 40 步 F2P `1/3`）
- **根因**：
  - 4 道硬骨头均为**多类/多子类遗漏或复杂抽象边界未一次看全**（E4），而非定位完全跑偏（E1=0）或循环卡死（E6=0）；`pytest-7324` 属于单次采样方差。
- **建议修复**：
  1. **Day 4**：落地按需 `get_repo_map(focus_files, query)`，辅助模型在修改父类/基类前快速枚举全部兄弟子类与调用点；
  2. **Day 5**：落地只读 Explorer Subagent（`explore_codebase`），在不污染主上下文的前提下专门排查多子类/MRO/调用链遗漏；
  3. **Day 6**：落地 `Best-of-3` + 独立 Sandbox Verifier 择优，吃掉单次采样波动（仅 2 次采样 Oracle 并集已达 `22/26 = 84.6%`）。
- **验收标准**：30 题官方 Pass@1 **≥ 23/30（76.7%）**，26 题去噪 **≥ 22/26（84.6%）**。
