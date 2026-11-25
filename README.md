# coding-agent-harness

Repo-level Coding & CI Self-Healing Agent Harness — 面向真实代码仓库的自主 Issue 修复与 CI 自愈智能体系统（Docker 隔离沙箱、ACI 工具层、Tree-sitter Repo Map、长上下文工程与 SWE-bench 自动化评测闭环）。

## 文档资料

- [深度学习手册（Markdown）](docs/coding-agent-study-guide.md)
- [深度学习手册（Word 版）](docs/coding-agent-study-guide.docx)

## 演进路线（8 周计划）

- **V0.1**：SWE-bench 评测脚手架 + Docker 沙箱 + 正交 ACI 工具 + ReAct Baseline + JSONL 轨迹落盘
- **V0.2**：Failure Taxonomy 失败归因 + Tree-sitter / Personalized PageRank Repo Map 代码定位升级
- **V0.3**：Observation Masking + 结构化 Compaction + Git Checkpoint/Rollback + Prompt Caching
- **V0.4**：Reproduce → Fix → Verify 验证门禁 + 只读 Explorer Subagent + 完整消融实验对比
- **工程化**：异步并发沙箱调度 + GitHub Webhook / CI 自愈闭环 + 轨迹回放看板
