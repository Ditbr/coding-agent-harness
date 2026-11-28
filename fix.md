# Coding Agent Harness 待解决问题清单（Fix Log）

> 本文档作为项目**长期维护的问题追踪与修复台账**，统一记录开发、评测、远端算力与 Harness 迭代过程中发现的所有待解决问题。
> 关联文档：[README.md](README.md) · [learn.md](learn.md) · [result.md](result.md) · [docs/devlog-week1.md](docs/devlog-week1.md)

---

## 使用约定

- **编号规则**：全局递增 `FIX-001`, `FIX-002`, ...（已解决项保留编号与修复 Commit，不删除）
- **优先级**：
  - `P0`：阻断主链路 / 影响评测稳定性 / 涉及仓库安全隐私，需立即处理
  - `P1`：影响下一里程碑（如 V0.1 30 题 Baseline）执行效率或数据质量
  - `P2`：Harness 能力增强与提分优化（按 V0.2~V0.4 消融节奏合入）
  - `P3`：低优先观察项 / 备忘
- **状态**：`TODO` · `IN_PROGRESS` · `BLOCKED` · `DONE`
- **消融纪律**：涉及 Agent 行为/提分的修复（如 `pipefail`、Repo Map、Compaction），在 V0.1 30 题 Baseline 出分前不要混入，确保各版本消融对照纯净。

---

## 问题总览

| ID | 优先级 | 类别 | 状态 | 目标阶段 | 问题简述 |
| :--- | :---: | :--- | :---: | :---: | :--- |
| [FIX-001](#fix-001) | P0 | Eval / Infra | `DONE` | V0.1 前置 | 远端 Docker 并发评测未捕获 `RequestException`，隧道抖动导致整批崩溃 |
| [FIX-002](#fix-002) | P0 | Security | `DONE` | 推送前 | 远端运维脚本与文档硬编码公网 ECS IP、Tailscale IP 与主机名 |
| [FIX-003](#fix-003) | P0 | Infra | `DONE` | V0.1 前置 | `DockerSandboxRuntime` 调用 `docker` CLI 时未注入 `NO_PROXY`，代理环境下易连不通本地隧道 |
| [FIX-004](#fix-004) | P1 | Eval / Batch | `DONE` | V0.1 | `run_agent_batch.py` 硬编码封顶步数/费用，且缺少 `--resume` 与并发支持 |
| [FIX-005](#fix-005) | P1 | Harness / Runtime | `DONE` | V0.2 | 容器 Shell 执行未启用 `pipefail`，管道命令（如 `pytest ... \| tail`）吞掉测试失败退出码 |
| [FIX-006](#fix-006) | P2 | Harness / ACI | `IN_PROGRESS` | V0.2 / V0.4 | 中等题出现反复改撤空补丁、死循环及局部验证漏回归问题 |
| [FIX-007](#fix-007) | P2 | Harness / RepoMap | `IN_PROGRESS` | V0.2 | `RepoMapper` 仍为 Python AST 基础版且未接入批跑，需升级 Tree-sitter + PageRank |
| [FIX-008](#fix-008) | P2 | Harness / Context | `IN_PROGRESS` | V0.3 | `ContextManager.compact()` 未自动触发；Observation Masking 改写早期消息影响 Prompt Cache 前缀 |
| [FIX-009](#fix-009) | P3 | Dataset / Eval | `DONE` | V0.1 观察 | 30 题中 `psf__requests` 部分用例依赖公网 `httpbin.org`，需核查隔离环境下的噪声影响 |
| [FIX-010](#fix-010) | P0 | Repo / Git | `DONE` | V0.1 收口 | 清理重复配置，按执行底座、消融和文档拆分提交 |
| [FIX-011](#fix-011) | P1 | Eval / Billing | `DONE` | V0.1 收口 | 已核实网关价格（未缓存输入/输出 ¥2/1M、缓存输入 ¥0.2/1M），支持 CNY 环境变量配置与历史对比重算 |
| [FIX-012](#fix-012) | P1 | Dataset / Eval | `DONE` | V0.1 收口 | 已发布 30 题审计，Week 3 同时报全量和去噪 26 题 |
| [FIX-013](#fix-013) | P1 | Eval / Ablation | `DONE` | V0.1 → V0.4 | 补跑 `django-13401`、`baseline-36steps` 官方出分与 E1~E6 归因，并完成同条件成组消融 |
| [FIX-014](#fix-014) | P2 | Docs | `DONE` | V0.1 收口 | 已同步 36 步基线评分、路线图与消融配置 |
| [FIX-015](#fix-015) | P0 | Runtime / Docker | `DONE` | V0.1 收口 / V0.2 | 宿主机侧 `docker exec` 超时保留容器，补丁导出超时重试一次 |
| [FIX-016](#fix-016) | P2 | Harness / ACI | `DONE` | V0.2 | 通过提示词纪律 + 上下文失忆修复 + 300 行窗 + 软循环恢复实现 0 空补丁、0 循环，攻克 `requests-6028`/`sympy-13551` |
| [FIX-017](#fix-017) | P0 | Eval / Integrity | `DONE` | Week 3 Day 4 前 | 推理入口已隔离评测字段，30 题零泄露护栏评测完成（15/30）；后续 `boost-30` 全程零泄露达 21/30 |
| [FIX-018](#fix-018) | P1 | Harness / Verification | `DONE` | Week 3 Day 4 前 | 清理既有测试或新增临时文件后，未变更的业务源码仍保留验证证据 |
| [FIX-019](#fix-019) | P1 | Harness / Context | `DONE` | Week 3 Day 5 | 18K 压缩 30 题实测 10/30（证实规则压缩失忆）；改用 16/3000 非破坏性窗口使缓存达 84.0% 且 Pass@1 达 21/30 |

---

## 问题详情

### <a id="fix-001"></a>FIX-001 · 远端 Docker 并发评测未捕获 `RequestException` 导致整批崩溃

- **状态**：`DONE` | **优先级**：`P0` | **类别**：Eval / Infra | **目标阶段**：V0.1 前置
- **相关位置**：`scripts/run_swebench_eval.py`（L72–L81、L119–L124）
- **现象与证据**：
  - 在远端 Windows Docker 冒烟 `runs/windows-smoke/run.AdjweC/scored.log` 中，并发评测执行 `client.images.get(spec.image)` 时抛出 `requests.exceptions.ConnectionError: RemoteDisconnected`，导致 `ThreadPoolExecutor` 未捕获异常直接退出（`scored.exit=1`），需要人工重跑并手工拼装 `scored-reconciled.json`。
  - 在 `runs/windows-smoke/run.yYfigZ/gold/summary.json` 中，`sympy__sympy-13480` 也曾出现偶发 `evaluation_error`（导致 Gold 4/5）。
- **根因**：
  - `run_swebench_eval.py` 的 `except` 块仅捕获 `docker.errors.DockerException`，遗漏了底层 `requests.exceptions.RequestException`；同时远端 SSH 隧道在高并发短连接下偶发断连且无重试机制。
- **建议修复**：
  1. 在 `evaluate_one` 中同时捕获 `(docker.errors.DockerException, requests.exceptions.RequestException)`，避免单题网络抖动拖垮整个线程池。
  2. 为镜像检查与 `run_instance` 外层增加短暂指数退避重试（仅对明确连接/基础设施错误重试，如最多 2 次）。
  3. 增加 `--resume`（或针对 `summary.json` 中 `evaluation_error` 实例的定向补跑）能力。
- **验收标准**：远端隧道短时闪断时不会导致主进程崩溃，单题记录明确状态或自动重试成功，最终必然产出完整 `summary.json`。

---

### <a id="fix-002"></a>FIX-002 · 远端运维脚本与文档硬编码公网 IP、Tailscale IP 与主机名

- **状态**：`DONE` | **优先级**：`P0` | **类别**：Security | **目标阶段**：下次推送前
- **相关位置**：
  - `scripts/win_docker_tunnel.sh`（L10–L18）
  - `docs/windows-aliyun-tunnel-setup.md`
  - `docs/windows-docker-remote-setup.md`
- **现象与证据**：上述待提交文件中直接写入了个人阿里云 ECS 公网 IP、Tailscale 内网 IP 及本机主机名。
- **建议修复**：
  1. `scripts/win_docker_tunnel.sh` 改为从环境变量（或本地 `.env`）读取 `WIN_DOCKER_HOST`、`WIN_DOCKER_USER` 等配置，脚本内不保留真实 IP 默认值。
  2. 两份 Windows 搭建文档中的真实 IP/主机名替换为 `<ECS_PUBLIC_IP>`、`<WIN_TAILSCALE_IP>` 等占位符，或将个人私有机房运维文档移出公开仓库（加入 `.gitignore`）。
- **验收标准**：`git diff` / 待提交文件中检索不到个人真实公网 IP 与私有主机名后再推送至 GitHub / Gitee。

---

### <a id="fix-003"></a>FIX-003 · `DockerSandboxRuntime` 调用 `docker` CLI 缺少 `NO_PROXY` 保护

- **状态**：`DONE` | **优先级**：`P0` | **类别**：Infra | **目标阶段**：V0.1 前置
- **相关位置**：`src/harness/runtime/docker.py`（L72–L139）
- **现象与证据**：
  - `scripts/run_swebench_eval.py` 已针对 `DOCKER_HOST` 包含 `127.0.0.1/localhost` 自动注入 `NO_PROXY` / `no_proxy`；
  - 但 `DockerSandboxRuntime` 直接通过 `subprocess.run(["docker", ...])` 调用 CLI，未自动注入 `NO_PROXY`。当宿主终端开启 HTTP/SOCKS 代理并指向 `win-docker`（`tcp://127.0.0.1:23750`）时，容易被代理劫持导致容器启动或 `exec` 失败。
- **建议修复**：
  - 在 `DockerSandboxRuntime` 封装统一的 `_docker_env()`，确保传给 `docker` 子进程的环境变量中包含 `NO_PROXY=127.0.0.1,localhost,...` 与 `no_proxy=...`（保留原有值不覆盖），并补充单元测试。
- **验收标准**：宿主设置 `HTTP_PROXY` / `ALL_PROXY` 环境变量时，通过本地回环隧道运行 `run_agent_batch.py` 不受代理干扰。

---

### <a id="fix-004"></a>FIX-004 · `run_agent_batch.py` 预算硬编码封顶且缺少断点续跑与并发控制

- **状态**：`DONE` | **优先级**：`P1` | **类别**：Eval / Batch | **目标阶段**：V0.1
- **相关位置**：`scripts/run_agent_batch.py`（L70–L111）
- **现象与证据**：
  - L78–L79 写死了 `cfg.max_steps = min(cfg.max_steps, 20)` 和 `cfg.max_cost_usd = min(cfg.max_cost_usd, 0.15)`，即使在 `.env` 中调高上限也无法生效；冒烟测试中未通过的 3 题大部分均打满 20 步。
  - L101 为纯串行循环，且 L94 `output.mkdir(parents=True)` 要求新目录，30 题全量跑批若中途发生隧道/API 异常无法断点续跑。
- **建议修复**：
  1. 移除 `min(..., 20)` / `min(..., 0.15)` 的硬编码截断，改为 CLI 参数 `--max-steps`、`--max-cost`（默认沿用 `.env` / `HarnessConfig`）。
  2. 新增 `--resume` 参数：扫描已有 `results.jsonl` 中非 `error` 的 `instance_id` 并跳过，以追加模式续写。
  3. 视远端隧道稳定性补充可选 `--workers`（默认 `1`），注意线程安全写盘。
- **验收标准**：可通过命令行灵活设置步数/费用上限，30 题跑批中途打断后可通过 `--resume` 无损续跑且不重复写入 `instance_id`。

---

### <a id="fix-005"></a>FIX-005 · 容器 Shell 执行未启用 `pipefail`，管道命令吞掉测试失败退出码

- **状态**：`DONE` | **优先级**：`P1` | **类别**：Harness / Runtime | **目标阶段**：V0.2（V0.1 Baseline 完成后合入）
- **相关位置**：`src/harness/runtime/docker.py`（L123–L129）
- **现象与证据**：
  - `docs/devlog-week1.md` 记录：在 `pytest-dev__pytest-7205` 轨迹中，模型运行 `pytest ... | tail` 查看尾部输出，外层 Shell 返回的是 `tail` 的退出码 `0`，导致模型误以为回归测试全部通过而提前结束，实际官方评测 9/10 个参数化 F2P 失败。
- **根因**：`docker exec` 内层调用的是 `bash -c "$2"`，未开启 `pipefail`。
- **建议修复**：
  - 将执行入口改为 `bash -o pipefail -c "$2"`（并同步评估 `LocalWorkspaceRuntime` 是否一致开启），补充单元测试覆盖 `false | true` 返回非零退出码。
- **验收标准**：容器内执行 `false | true` 或 `pytest <failing> | tail` 时，`CommandResult.exit_code != 0`。

---

### <a id="fix-006"></a>FIX-006 · 中等题出现反复改撤空补丁、死循环及局部验证漏回归

- **状态**：`IN_PROGRESS` | **优先级**：`P2` | **类别**：Harness / ACI | **目标阶段**：V0.2 / V0.4
- **相关位置**：`src/harness/agent/controller.py`、`src/harness/tools/aci.py`、`src/harness/runtime/docker.py`（L209–L220）
- **现象与证据**：
  - `django__django-13794`：在多次冒烟中反复出现 20 步反复编辑撤销最终空补丁（E6），或在 12 步触发 `loop_detected` 提前终止。
  - `matplotlib__matplotlib-25311`：模型定位到 `offsetbox.py`，仅用自写局部复现脚本验证通过，漏掉了官方完整反序列化路径（`AttributeError: 'Legend' object has no attribute 'figure'`，E4）。
- **建议修复**：
  1. 待 V0.1 30 题 Baseline 产出完整 E1~E6 分布后，针对性优化 `edit_file` 报错反馈与重复调用恢复提示（而非直接硬停）。
  2. 将 `SandboxRuntime` 已实现的 `checkpoint()` / `rollback()` 暴露为 ACI 能力或在失败分支中自动管理。
  3. 在 V0.4 接入 Reproduce → Fix → Verify 门禁，要求 `finish` 前检查 `git diff` 非空且至少跑过与修改文件关联的官方测试模块。
- **验收标准**：在同 30 题集上，空补丁/死循环（E6）与验证不足（E4）占比显著下降。

---

### <a id="fix-007"></a>FIX-007 · `RepoMapper` 仍为 Python AST 基础版且未接入批跑

- **状态**：`IN_PROGRESS` | **优先级**：`P2` | **类别**：Harness / RepoMap | **目标阶段**：V0.2
- **相关位置**：`src/harness/repomap/mapper.py`、`scripts/run_agent_batch.py`（L40）
- **现象与证据**：
  - 当前 `RepoMapper` 仅基于标准库 `ast` 扫描文件并简单截断，未建立跨文件引用图与 Personalized PageRank 排序；且 `run_agent_batch.py` 调用 `controller.run(...)` 时未传入 `repo_map`。
- **建议修复**：
  1. V0.1 保持不注入 `repo_map`，作为干净 Baseline。
  2. V0.2 升级为 Tree-sitter + 符号引用图 + Personalized PageRank，在 `run_agent_batch.py` 提供 `--with-repomap` 开关以便严格消融。
- **验收标准**：在 30 题评测集上完成 `w/o RepoMap` vs `w/ Tree-sitter PageRank RepoMap` 同条件消融对比，记录定位步数与 Pass@1 变化。

---

### <a id="fix-008"></a>FIX-008 · `ContextManager.compact()` 未自动触发 & Masking 对 Prompt Cache 的影响

- **状态**：`IN_PROGRESS` | **优先级**：`P2` | **类别**：Harness / Context | **目标阶段**：V0.3
- **相关位置**：`src/harness/context/manager.py`（L72–L103）、`src/harness/agent/controller.py`
- **现象与证据**：
  - `ContextManager.compact()` 已定义接口，但 `AgentController` 尚未接入基于 Token 占用的自动触发逻辑。
  - `build_messages()` 每次新工具结果超过 `keep_recent_observations` 时，都会原地替换历史上第 `N - keep` 条工具消息内容，导致从该位置之后的 Prompt Cache 前缀失效（当前 5 题冒烟缓存命中率为 67.8%）。
- **建议修复**：
  1. 在 `AgentController` 中接入基于上下文 Token 阈值的自动 Compaction（提取已验证事实、已修改文件、当前失败假设）。
  2. 在 V0.3 对比「逐轮滑动 Masking」与「分段/按阈值批量 Masking + Compaction」对缓存命中率、单题成本与 Pass@1 的影响。
- **验收标准**：长轨迹（30~40 步）不因上下文膨胀显著劣化，且缓存命中率与单位任务成本可量化改善。

---

### <a id="fix-009"></a>FIX-009 · 核查 30 题中 `psf__requests` 样本的外网依赖噪声

- **状态**：`DONE` | **优先级**：`P3` | **类别**：Dataset / Eval | **目标阶段**：V0.1 观察
- **相关位置**：`data/swebench_verified_30.jsonl`、`result.md`（Day 3）
- **现象与证据**：
  - 冒烟校准阶段发现 `psf__requests-1724` 依赖公网 `httpbin.org`（历史镜像证书 TLS 失败 + HTTP 429），已将其从 5 题冒烟集替换为 `matplotlib__matplotlib-25311`，但 30 题集合保持 SHA-256 锁定未改。
- **建议修复**：
  - 在 30 题集上跑一次 Gold Patch 与 Empty Patch 校验，摸清所有 `psf__requests-*`（共 5 题）在离线/当前网络下的真实可控性；若存在不可复现外网题，在评测汇总中做透明标注（例如同时报告 `30 题总分` 与 `去外网噪声子集分`），避免悄悄换题破坏实验可复现性。
- **验收标准**：明确掌握 30 题中每一题的 Gold/Empty 基线可控状态并归档到评测报告。

---

### <a id="fix-010"></a>FIX-010 · 清理 `.env.example` 重复段并拆分提交当前未提交改动

- **状态**：`DONE` | **优先级**：`P0` | **类别**：Repo / Git | **目标阶段**：V0.1 收口
- **相关位置**：`.env.example`（末尾重复 `WIN_DOCKER_*` 区块）及当前工作区 19 个修改文件 + 7 个新增文件（`+851 / -139` 行）
- **现象与证据**：
  - `.env.example` 末尾同时存在未注释与注释两套 `WIN_DOCKER_*` 配置段。
  - Infra/Eval 加固（`FIX-001`~`005`, `009`）与 V0.2~V0.4 消融特性（`FIX-006`~`008`）全部堆积在未提交工作区，后续继续调优若需回退难以隔离改动。
- **建议修复**：
  1. 删除 `.env.example` 中重复的 `WIN_DOCKER_*` 区块，仅保留脱敏注释模板。
  2. 运行 `pytest -v && ruff check src tests scripts && git diff --check` 复核。
  3. 按主题拆分 Commit（例如：① Infra/Eval 加固与离线 pip 修复；② V0.2~V0.4 消融特性与对比脚本；③ `fix.md` 与文档同步）并推送至 `origin` 与 `gitee`。
- **验收标准**：工作区干净无重复配置，双端分支对齐，本地全量测试与 Ruff 通过。

---

### <a id="fix-011"></a>FIX-011 · 核对新网关费率配置，修复 `$0.0000` 费用统计与预算熔断

- **状态**：`DONE` | **优先级**：`P1` | **类别**：Eval / Billing | **目标阶段**：V0.1 收口
- **相关位置**：`.env`、`src/harness/llm/client.py`、`runs/fix-audit/matched.Tt3ly8/`、`runs/week2/baseline-36steps/`
- **现象与证据**：
  - `matched.Tt3ly8`（baseline/repomap）及正在运行的 `runs/week2/baseline-36steps` 中，所有实例的 `total_cost_usd` 均为 `$0.0000`。
  - 费率为 `0` 会导致 `--max-cost` 预算上限无法触发熔断，也无法与原网关基线（`$0.4539`）直接对比单题成本。
- **建议修复**：
  1. 若使用计费云端网关，在本地 `.env` 补齐 `LLM_INPUT_COST_PER_M`、`LLM_CACHED_INPUT_COST_PER_M`、`LLM_OUTPUT_COST_PER_M` 官方单价。
  2. 若使用本地/免计费网关，在实验记录与对比报告中明确标注为免计费网关，统一以「输入/缓存/输出 Token 数与缓存命中率」作为成本对比指标，并依赖 `--max-steps` 控制预算。
- **验收标准**：后续成组消融实验的费率口径一致、可复算，或明确以 Token 指标替代。
- Week 3 使用输入、缓存、输出 Token 总数和缓存命中率比较各组。保留当前网关配置和 36 步上限。实际费率未经核实，美元字段无法用于评估费用。 [度量口径](docs/progress.md#36-步基线与消融配置)

---

### <a id="fix-012"></a>FIX-012 · 基于 `gold-30-offline-pip` 刷新 30 题外网噪声审计口径

- **状态**：`DONE` | **优先级**：`P1` | **类别**：Dataset / Eval | **目标阶段**：V0.1 收口
- **相关位置**：`scripts/audit_swebench_controls.py`、`runs/week2/gold-30-offline-pip/summary.json`、`runs/fix-audit/run.9xz8O8/controls-audit.json`
- **现象与证据**：
  - 此前 `controls-audit.json` 仅将 3 道 `requests` 题标记为外网噪声（`psf__requests-1724`、`1766`、`2317`）。
  - 修复 `PIP_NO_BUILD_ISOLATION` 后重跑 30 题 Gold（`runs/week2/gold-30-offline-pip/summary.json`）取得 **26/30（86.7%）**、0 评测超时、0 评测错误。未通过的 4 题都来自 Requests。
  - `psf__requests-2931` 的目标用例 `test_binary_put` 通过，两个 P2P 超时用例在私有地址 `10.255.255.1` 上收到了 `ReadTimeout`。这是测试路由行为差异。 [逐题 Gold](runs/week2/gold-30-offline-pip/instances/psf__requests-2931.json)
- **建议修复**：
  1. 复核 `psf__requests-2931` 的测试日志，区分公网服务故障和私有地址路由造成的测试失败。
  2. 基于 `gold-30-offline-pip` 和最新 Empty 对照重跑 `scripts/audit_swebench_controls.py`，产出新版 `controls-audit.json` 作为后续 36 步基线与消融组的统一 `--noise-audit` 输入。
- **验收标准**：新版 `controls-audit.json` 准确覆盖 30 题的 Gold/Empty 可控状态，且所有消融组复用同一份审计文件。
- 30 题默认对照有 26 题符合预期，4 道 Requests 具有网络噪声证据。隔离网络下 `psf__requests-2931` 的 Gold 评分通过。Week 3 统一使用新版审计，Week 2 历史评分保留原口径。 [新版审计](runs/week3/day1/controls-audit.json) · [度量口径](docs/progress.md#week-3-网络噪声审计)

---

### <a id="fix-013"></a>FIX-013 · 完成 36 步 V0.1 Baseline 补跑出分与同条件成组消融（闭环 `FIX-006`~`008`）

- **状态**：`DONE` | **优先级**：`P1` | **类别**：Eval / Ablation | **目标阶段**：V0.1 → V0.4
- **相关位置**：`runs/week2/baseline-36steps/`、`scripts/run_agent_batch.py`、`scripts/run_swebench_eval.py`、`scripts/compare_harness_runs.py`
- **现象与证据**：
  - `runs/week2/baseline-36steps`（`--max-steps 36 --thinking disabled --workers 3`）30 题批跑已完成：主动 `finished` **15/30**、非空补丁 **27/30**、完整覆盖金标准文件 **20/30**（轨迹定位 **26/30**，中位第 2 步）、Prompt Cache 命中率 **67.4%**（3.86M / 5.72M）、`edit_file` 失败率 **8.6%**。
  - 首次批跑中 `django__django-13401` 因 `FIX-015` 报错 `status=error`（空补丁）。
  - `FIX-006`（护栏与验证门禁）、`FIX-007`（Tree-sitter+PageRank RepoMap）、`FIX-008`（自动 Compaction）的代码和回归单测已完成，尚缺同条件 30 题消融数据验收。
- **建议执行步骤**：
  1. 先对 `runs/week2/baseline-36steps` 执行 `--resume --workers 1`，仅补跑 `status=error` 的 `django__django-13401`（1 题）。
  2. 运行 `scripts/run_swebench_eval.py --mode predictions --workers 4 --timeout 300 --docker-timeout 30 --noise-audit ...` 输出 36 步 Baseline 官方 `summary.json`。
  3. 基于 30 题评分与轨迹产出完整 `E1~E6` 失败归因分布（重点核查 5 道未命中金标准文件的非空补丁题与 `psf__requests-6028` / `sympy__sympy-13551`）。
  4. 在**完全相同的题集、模型、36 步与 `--thinking disabled` 条件**下，依次跑完：
     - `repomap`（`--with-repomap`）
     - `guardrails`（`--with-loop-recovery --with-verification`）
     - `compaction`（`--with-compaction`）
  5. 用 `scripts/compare_harness_runs.py` 生成成组对比指标（Pass@1、首次定位金标准文件步数、空补丁数、缓存命中率、Token/成本），并将 `FIX-006`~`008` 更新为 `DONE`。
- **验收标准**：拿到 36 步统一口径下的 4 组完整 30 题评测报告与消融对比表。
- `django__django-13401` 在第 24 步正常结束，导出 3,260 字符补丁并通过官方逐题评分。补跑后的基线有 16/30 题主动结束、28/30 题导出非空补丁、21/30 题覆盖全部金标准文件。30 题官方评分使用原噪声审计。 [Django 逐题评分](runs/week2/baseline-36steps-score/instances/django__django-13401.json) · [当前评分与消融进度](docs/progress.md#36-步基线与消融配置)
- 36 步基线官方 Pass@1 为 **17/30（56.7%）**，按原外网噪声审计为 **17/27（63.0%）**。RepoMap 为 **12/30（40.0%）**，护栏为 **16/30（53.3%）**。四组评测已完成。 [消融对比](runs/week2/ablation-36steps.md) [基线评分](runs/week2/baseline-36steps-score/summary.json) · [逐题归因](runs/week2/baseline-36steps-attribution.md) · [运行日志](runs/week2/fix-013-run.log)

---

### <a id="fix-014"></a>FIX-014 · 同步更新 `README.md` 路线图与 `docs/progress.md` 最新阶段进展

- **状态**：`DONE` | **优先级**：`P2` | **类别**：Docs | **目标阶段**：V0.1 收口
- **相关位置**：`README.md`（L123–L130）、`docs/progress.md`
- **现象与证据**：
  - `README.md` 演进路线中的 V0.1 仍未勾选；`docs/progress.md` 更新日期仍停留在 `2026-11-26`，未反映 30 题 `gold-30-offline-pip`（26/30）、首版 V0.1 Baseline（10/30）及 36 步新基线进展。
- **建议修复**：
  - 待 `FIX-013` 的 36 步 Baseline 出分后，统一勾选 `README.md` 的 V0.1 里程碑并更新 `docs/progress.md` 中的阶段数据、架构改进与消融进展。
- **验收标准**：`README.md`、`docs/progress.md`、`fix.md` 三份文档中的分数、状态与命令完全一致。

---

### <a id="fix-015"></a>FIX-015 · `DockerSandboxRuntime` 命令超时直接销毁容器，导致收尾 `git_diff()` 崩溃丢失补丁

- **状态**：`DONE` | **优先级**：`P0` | **类别**：Runtime / Docker | **目标阶段**：V0.1 收口 / V0.2
- **相关位置**：[Docker Runtime](src/harness/runtime/docker.py) · [ACI 工具](src/harness/tools/aci.py) · [回归测试](tests/test_fix_regressions.py)
- **现象与证据**：
  - 在 `runs/week2/baseline-36steps/trajectories/django__django-13401.jsonl` 中，历史两轮 20 步均 PASS 的 `django__django-13401` 耗时 **1,643 秒**，最终以 `status=error` 收场且补丁归零（`patch_chars=0`）。
  - 轨迹显示模型在容器内后台跑测试后连续用 `sleep 100` / `sleep 90` 轮询结果，Step 36 执行 `git status; git diff` 时因宿主机侧 `subprocess.TimeoutExpired`（71.5s），触发 `docker.py` 中的 `self.stop()` **直接删除了整个容器**；随后 `AgentController.run()` 收尾调用 `self.runtime.git_diff()` 抛出 `RuntimeError: DockerSandboxRuntime is not started.`，彻底丢失前 35 步的全部修改。
- **根因**：
  1. 宿主机侧 `subprocess.TimeoutExpired` 处理过于激进，直接 `self.stop()` 销毁容器并将 `_container_id` 置空，没有区分“远端 `docker exec` 挂起”与“容器不可恢复”。
  2. 缺少对容器内残留后台测试进程（以及模型用 `sleep` 轮询后台输出）的清理/约束机制。
- **建议修复**：
  1. `subprocess.TimeoutExpired` 时优先保留容器（或先尝试仅终止本次超时 exec 的进程/子进程），不要在未导出补丁前直接 `self.stop()`。
  2. 若判定容器确实不可恢复而必须销毁，先做一次受限时长的 `git_diff()` 抢救缓存，或在 `AgentController` 捕获已销毁状态避免覆盖最后已知工作树状态。
  3. 同步在 `run_command` 工具描述或系统提示中明确禁止将耗时测试放到后台并用 `sleep` 轮询。
  4. 补充单元测试覆盖「单步命令触发宿主机 `TimeoutExpired` 后，后续 `git_diff()` 仍能安全导出已有修改」。
- **验收标准**：单条 `run_command` 发生 `TimeoutExpired` 时不再导致整题补丁丢失或 `RuntimeError: DockerSandboxRuntime is not started.`。
- 宿主机 CLI 超时返回 124 并保留已有输出和容器。补丁导出超时后会再尝试一次，沙箱退出时由正常清理流程删除容器。工具说明要求测试在前台限时执行。回归测试覆盖命令超时后直接导出和首次导出超时后重试，两条路径均保留完整补丁。远端 Django 镜像实测在强制 CLI 超时后仍从原容器导出工作树差异。

---

### <a id="fix-016"></a>FIX-016 · 补丁夹带无关测试/changelog 修改，及纯读不改 / 重复复现卡死

- **状态**：`TODO` | **优先级**：`P2` | **类别**：Harness / ACI | **目标阶段**：V0.2
- **相关位置**：`src/harness/tools/aci.py`、`src/harness/tools/verification.py`、`src/harness/context/manager.py`
- **现象与证据**：
  - `runs/week2/baseline-36steps/predictions.jsonl` 中，多道题的最终 patch 混入了模型顺手修改的官方测试文件（`tests/...`、`testing/...`、`test_requests.py`）或新增的 `changelog/*.bugfix.rst`。`psf__requests-1724` 同时修改了 `requests/models.py` 和 `test_requests.py`，Gold 则修改 `requests/sessions.py`。
  - `psf__requests-6028` 在 36 步内持续 `inspect.getsource(urllib3...)` 查看底层库源码，未调用过一次 `edit_file` 即耗尽步数（空补丁）。
  - `sympy__sympy-13551` 在 Step 12~14 连续 3 次执行相同 `python -c` 复现脚本被硬停（`loop_detected`，空补丁）。
  - 另有 5 题（`django-13794`、`django-13112`、`matplotlib-26342`、`psf__requests-1724`、`scikit-learn-25102`）补丁未覆盖金标准文件，待官方出分后复核是等价修法还是定位偏差（E1）。
- **建议修复**：
  1. 在 V0.2 消融中重点验证 `--with-loop-recovery`（缓解 `sympy-13551` 类 3 次硬停）和 `--with-verification`（拦截修改官方测试文件未还原、以及未修改业务源码即提交的问题）。
  2. 考虑在末尾预算提醒（final 5 steps）中附加「若 `git diff` 仍为空且已定位问题，优先提交最小可行修复并验证」的引导，减少 `psf__requests-6028` 类“只看不改”打满步数现象。
- **验收标准**：在 36 步消融组中，空补丁率、测试文件误改导致的 `patch_apply_failed` 及 `loop_detected` 提前终止数明显下降。

---

### <a id="fix-017"></a>FIX-017 · `--with-verification` 透传官方 `test_patch` 文件路径，存在评测数据泄露

- **状态**：`IN_PROGRESS` | **优先级**：`P0` | **类别**：Eval / Integrity | **目标阶段**：Week 3 Day 4（30 题消融前必改）
- **相关位置**：`src/harness/eval/runner.py`（L58–L62）、`scripts/run_agent_batch.py`（L46–L49）、`src/harness/tools/verification.py`（L177–L181、L274–L295）
- **现象与证据**：
  - `load_instances_jsonl()` 从 SWE-bench 数据集的官方评测字段 `raw["test_patch"]` 解析出 `instance.test_modules`；
  - `run_agent_batch.py` 在 `--with-verification` 模式下将 `instance.test_modules` 传给 `VerificationGate`；
  - `VerificationGate.finish_issue()` 直接把这些官方测试文件路径拼进返回给模型的提示消息（如 `For example, run a relevant target from: {targets}.` 以及 `Remove the official test edits...`）。
- **根因**：
  - 推理期工具层读取了仅限评测器使用的 `test_patch` 元数据，违背了 SWE-bench 严格隔离测试补丁的评测纪律（与 `learn.md` / `devlog-week1.md` 中“批跑仅提供问题描述和仓库工作树”的承诺冲突）。
- **建议修复**：
  1. 切断 `run_agent_batch.py` 向 `VerificationGate` 传入 `instance.test_modules`（`EvalInstance.test_modules` 严禁进入 Agent 推理期工具与提示词）。
  2. 将 `VerificationGate` 改为纯基于工作区状态的零泄露设计：
     - 清理检查：拦截工作树中任何被改动的既有测试文件（`_is_test_path(path)`）及新增临时文件（`_is_artifact(path)`），不依赖 `test_patch` 清单；
     - 相关性校验：仅依据 `git_diff()` 实际修改的业务源码路径做启发式关联，或接受任意在最终业务修改之后通过的真实测试命令（`pytest` / `runtests.py` / `unittest` / `bin/test`），不泄露任何官方测试路径。
  3. 补充回归测试，断言 `run_instance` 传给工具层/上下文的输入不包含 `test_patch` 信息。
- **验收标准**：`--with-verification` 完全不读取 `test_patch` / `FAIL_TO_PASS` / `PASS_TO_PASS`，所有单元测试与 30 题消融在严格零泄露口径下通过。
- 推理批跑使用独立的 `AgentTask` 投影。端到端回归覆盖工具 schema、模型消息和轨迹，带标记的评测字段均未进入这些输出。门禁只从工作树识别需恢复的既有测试。30 题验证正在运行。 [后台日志](runs/week3/fix-017-019-eval.log)

---

### <a id="fix-018"></a>FIX-018 · Guardrails v2 还原测试文件后导致 `verified_patch` 哈希失效，触发 `finish` 二次误拒

- **状态**：`DONE` | **优先级**：`P1` | **类别**：Harness / Verification | **目标阶段**：Week 3 Day 4（30 题消融前必改）
- **相关位置**：`src/harness/tools/verification.py`（L209–L231、L269–L295）
- **现象与证据**：
  - 在 `runs/week3/guardrails-v2-smoke` 中，5 题里有 3 题（`django-13794`、`pytest-7205`、`sympy-13480`）在调用 `finish` 时命中「还原测试文件」拦截；
  - 其中 `pytest-dev__pytest-7205` 出现 **2 次连续 `finish` 被拒**：第 1 次模型改业务代码 + 改 `testing/test_setuponly.py` 并跑过测试，调 `finish` 被要求 `git restore` 测试文件；模型照做还原后再次调 `finish`，因完整 `git_diff()` 发生变化导致 `verified_patch` 哈希不匹配，再次被拒要求重跑测试。
- **根因**：
  - `VerificationGate` 使用整个工作树的完整 `git_diff()`（含测试文件与临时脚本改动）计算 `patch_digest`，导致仅清理测试文件/临时文件也会误让已通过验证的业务补丁失效。
- **建议修复**：
  1. 提取只包含**非测试业务源码文件**的 diff（`source_diff`）来计算 `verified_patch` 摘要；
  2. 当模型按提示还原测试文件或删除临时脚本时，只要业务源码 diff 未变，已记录的验证证据保持有效，再次调用 `finish` 直接放行。
  3. 补充回归测试覆盖「修改业务代码 + 修改测试文件 → 跑测试通过 → `finish` 提示清理测试文件 → 清理后再次 `finish` 一次通过」。
- **验收标准**：清理测试文件或临时文件不再使已通过验证的业务补丁失效，消除二次误拒。
- 在真实 Git 工作树中通过 pytest 后，按门禁提示恢复既有测试、删除临时脚本，再次提交直接通过。回归同时覆盖业务源码继续变更时证据失效。

---

### <a id="fix-019"></a>FIX-019 · Compaction 默认 60K 阈值在 36 步内 0 次触发，关闭 Masking 反致 Prompt 膨胀与循环增多

- **状态**：`IN_PROGRESS` | **优先级**：`P1` | **类别**：Harness / Context | **目标阶段**：Week 3 Day 5
- **相关位置**：`src/harness/context/manager.py`、`src/harness/config.py`、`runs/week2/ablation-36steps.json`
- **现象与证据**：
  - Week 2 30 题消融报告 `runs/week2/ablation-36steps.json` 显示：`compaction` 组 30 条轨迹中 **`compactions = 0`（零次触发）**；
  - 与 Baseline 相比，虽然缓存命中率从 `66.8%` 升至 **`95.9%`**（因 `--with-compaction` 关闭了逐轮改写历史的 Observation Masking），但总 Prompt Token 暴涨 **+54%**（`5.61M → 8.66M`），`loop_detected` 从 1 次增至 **6 次**，Pass@1 反跌至 **15/30（50.0%）**。
- **根因**：
  - 默认触发阈值 `--compaction-tokens 60000` 远高于 36 步任务的实际上下文峰值，导致实验组退化为「关闭 Masking 且从未 Compaction」的纯膨胀上下文。
- **建议修复**：
  1. 统计 36 步长轨迹的逐轮估算 Token 分布，将默认/消融阈值下调至合理区间（如 `20,000 ~ 30,000`），确保长轨迹能真实触发 Compaction。
  2. 强化结构化压缩摘要模板，强制保留 `已确认根因`、`已修改文件与现状`、`已证伪假设（Failed Attempts）`、`下一步验证计划`，防止压缩后重复踩坑或丢状态。
  3. 在 Week 3 Day 5 重新跑同条件 30 题消融，验证真实触发 Compaction 后的缓存命中率、Token 降幅、循环次数与 Pass@1 变化。
- **验收标准**：30 题消融中长轨迹实际触发 Compaction，且在不显著损失 Pass@1 的前提下有效抑制总 Prompt Token 膨胀与 `loop_detected`。
- 历史轨迹回放中，默认 18K 阈值触发 12/30 题，估算输入总量减少约 20%。摘要保留根因、当前改动、失败尝试和验证计划。新 30 题消融已入队，实际提分与循环变化待评分。 [回放数据](runs/week3/fix-019-calibration.json) · [后台日志](runs/week3/fix-017-019-eval.log)

---

## 本次修复与验证记录

| 问题 | 实现与当前证据 |
| --- | --- |
| FIX-001 | 官方评测逐题重试连接异常，记录官方已有报告和逐题状态。回归测试覆盖断线重试及续跑。远端首次 30 题 Gold 仍产出完整报告，记录 22 题通过、3 题未通过与 5 题超时。 |
| FIX-002 | 隧道脚本端点读取本地环境，`.env.example` 提供配置字段。两份 Windows 本地文档替换个人端点和主机名，并继续由 Git 忽略。已核查当前可跟踪配置。 |
| FIX-003 | Docker CLI 启动、执行和清理统一合并两种大小写的代理绕行配置。用无效代理配置通过真实 Windows 隧道执行容器命令。 |
| FIX-004 | 预算可由 CLI 覆盖。线程池按题保存原子记录，恢复时跳过已完成实例并生成无重复的 JSONL。真实批跑已从首轮持久化记录继续运行。 |
| FIX-005 | Local 和 Docker Runtime 默认启用 pipefail，批跑实验通过 `--pipefail` 启用。真实 Windows 容器的 `false \| true` 返回 1。 |
| FIX-006 | 已接入可选循环恢复、编辑反馈、checkpoint/rollback 和提交门禁。回归测试覆盖循环后改换工具以及验证证据失效，远端验证了已暂存新增文件的快照恢复。完成验收需对比 30 题的空补丁、循环和验证指标。 |
| FIX-007 | `--with-repomap` 使用 Tree-sitter 和个性化 PageRank。远端验证了 Python 源码批量读取和地图预算。完成验收需拿到同条件的 30 题定位和 Pass@1 对比。 |
| FIX-008 | `--with-compaction` 只在完成的工具调用轮次后按阈值压缩。保留系统与任务前缀，并记录压缩事件。真实单题联调已触发压缩，长轨迹缓存、成本和 Pass@1 仍需成组测量。 |
| FIX-009 | 已归档 30 题的默认网络 Gold/Empty 和 5 道 Requests 的隔离 Gold/Empty。19/30 题的默认对照满足预期，3 道 Requests 题出现外网故障证据。超时和环境错误逐题保留。 [对照审计](runs/fix-audit/run.9xz8O8/controls-audit.json) |

V0.1 批跑的默认行为保留为消融基线。基线和对照产物在本机 `runs/fix-audit/`。固定题集校验和与 Week 1 一致。

V0.1 基线 Pass@1 为 10/30（33.3%）。排除有外网故障证据的样本后为 10/27（37.0%）。 [原始评分](runs/fix-audit/run.9xz8O8/baseline-score/summary.json) · [外网噪声子集](runs/fix-audit/run.9xz8O8/baseline-noise-adjusted.json)

2026-11-27 恢复了 30 题基线评分和对照。RepoMap 尝试遇到网关限流，随后确认当前网关与费率配置和原基线不一致。消融暂停，原基线与对照报告可独立复核。

2026-11-28 完成根因级 Harness 优化（消除 `keep_recent_observations=5` / `mask_threshold=600` 上下文失忆、`view_file` 扩窗至 300 行、升级系统提示词、支持 `--thinking enabled` 安全回放与 `finish_reason="length"` 截断恢复、畸形 JSON 容错、50 项单测全绿）。30 题零泄露官方评分从 **17/30（56.7%）** 提升至 **21/30（70.0%）**，26 题去噪达 **20/26（76.9%）**，空补丁与循环均降至 0，缓存命中率升至 **84.0%**。 [官方评分](runs/week3/boost-30-score/summary.json) · [基线对比](runs/week3/boost-30-comparison.json)

## 新增问题模板（后续直接复制追加）

```markdown
### <a id="fix-xxx"></a>FIX-XXX · <一句话概括问题>

- **状态**：`TODO` | **优先级**：`P1` | **类别**：<Infra / Eval / Harness / Security / Dataset> | **目标阶段**：<V0.1 / V0.2 / ...>
- **相关位置**：`<file_path>`（Lxx–Lyy）
- **现象与证据**：
  - <复现命令、日志路径或实测数据>
- **根因**：
  - <定位到的根因>
- **建议修复**：
  1. <具体改动点>
- **验收标准**：<可验证的完成条件>
```
