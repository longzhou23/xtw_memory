Project: xtw-memory
Module: documentation reorganization report
Version: v0.1
Status: PARTIAL
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# Documentation Reorganization Report

## 做了什么

- 为 `memory/` 建立单一入口、状态页、项目地图、浅显流程说明和当前架构页。
- 建立 Router 历史、实验账本、数据/模型 registry、decision log、限制、暂停问题、parking lot、roadmap 与 spec 索引。
- 新建 `memory/benchmark-results/README.md`，只索引原位报告。
- 记录 c_000008 PASS 撤回、HNR gate miss/consumed、Shared Backbone 特定方案失败、Dual 5K 根因未定等纠正后的事实。

## 移动 / 新建 / 归档 / 未动

- **移动：** 无。
- **新建：** `memory/README.md`；`memory/docs/PROJECT_STATUS.md`、`PROJECT_MAP.md`、`HOW_IT_WORKS.md`、`ARCHITECTURE_CURRENT.md`、`EXPERIMENT_LEDGER.md`、`DATASET_REGISTRY.md`、`MODEL_REGISTRY.md`、`DECISION_LOG.md`、`KNOWN_LIMITATIONS.md`、`PAUSED_QUESTIONS.md`、`PARKING_LOT.md`、`ROADMAP.md`、`SPEC_INDEX.md`、`DOCUMENT_INVENTORY.md`、`DUPLICATE_RESOLUTION.md`、`DOCUMENTATION_REORGANIZATION_REPORT.md`、`history/ROUTER_EVOLUTION.md`；`memory/benchmark-results/README.md`。
- **归档：** 无；历史正文未改。
- **未动：** 所有 benchmark 产物、raw data、dataset、checkpoint、源码、测试及相邻 memory-demo 内容。

## 重复 / 冲突 / unresolved

- 未发现可安全确认并解决的精确重复；多份相似文档仍待逐份比对。未删除任何文件。
- 发现并记录 c_000008 replay 的先前 PASS 被撤回为 CONSUMED / INCONCLUSIVE；HNR 原报告中的 PASS/晋级语言被后验证纠正为 PARTIAL、+9.02pp 未达 +10pp、HOLDOUT consumed。
- 5K Boundary failure 的根因未建立；统计分布不能直接当作因果解释。
- 文档 census 为 237 个 Markdown/text 文件（memory 65、memory-demo 172），但仅对关键文档做内容核读；完整逐文件字段 inventory、所有 specs/experiment 文档审阅、checkpoint/dataset SHA 对账及全量历史链接审计仍未完成。因此登记为 PARTIAL，而非 COMPLETE。
- 相对链接做有限核对；未声称对所有既有 Markdown 做了完整 broken-link repair。

## Git / safety audit

- Workspace HEAD at start: `0d21749eda53306c8d2151da76b9f9c967636b6e`。
- 整理前已有大量 dirty/untracked 工作；包括一个已删除的 raw JSON 记录。本轮未恢复、覆盖或清理该状态。
- 整理前后：只新增本报告列出的文档；未运行训练、推理、benchmark、数据重写或 checkpoint 操作。
- 源码修改：NO。模型运行：NO。benchmark 运行：NO。数据/Checkpoint 修改：NO。

## 状态

**DOCUMENTATION_REORGANIZATION_PARTIAL**。项目已经形成单一入口和明确主线/关键实验索引，但全量逐文档审阅、重复判定与链接审计尚未完成，不应宣称完整档案化。
