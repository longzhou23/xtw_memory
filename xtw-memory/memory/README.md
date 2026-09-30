Project: xtw-memory
Module: project entry
Version: documentation v0.1
Status: documentation snapshot; experiments paused
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# xtw-memory

`memory/` 是小天文 Memory 研究工作区：包含 Laya Router 训练/评估脚本、实验报告和派生材料。当前工作副本另有 `clean/`、`judgment/` 数据目录（由 `.gitignore` 排除，不随 Git 克隆提供）；`raw massage/`、IRIS 全量备份和身份映射保留在旧 `bot/projects/memory/` 数据区。`../components/memory-demo/` 是 Recall、Temporary Memory、Diffusion 可视化与相关 benchmark 的独立代码仓库；`../components/xtw-memory-fabric/` 是临时记忆 Fabric 的独立仓库。二者各自保留 Git 历史。

## 现在做到哪里

- **Router 主线：** Two-Stage Router v0.2，两个独立 Laya 322M Judgment 模型；2K Refined 是当前稳定基线。详见 [当前状态](docs/PROJECT_STATUS.md) 与[当前架构](docs/ARCHITECTURE_CURRENT.md)。
- **5K Boundary：** FAIL，TRUE_NEW 在固定阈值下完全塌缩到 CONTINUE；150 条 regression catastrophic over-merge。Forensic 后续分析正式 **PAUSED**，禁止自动续跑。
- **Episode Lifecycle / Temporary Memory / 写入 provenance：** memory-demo 有冻结备忘与有限验证；并不等于完整生产级验证。
- **Recall：** P0 baseline 与改进实验已记录；测试集多次使用。**Diffusion：** synthetic invariants 通过，但真实节点图为 zero-edge，真实图扩散收益尚未证明。
- **Final Consolidation / Long-Term Memory：** 尚无已完成的完整主线证明；下一步由用户决定是否转回该主线。

## 当前架构是什么

消息写入的概念路径是 `Raw Chat → Event → Episode Router → Episode Lifecycle → Working Context → Temporary Memory → Memory Write → FORMED_WITH/provenance → Final Consolidation → Long-Term Memory`；读取路径是 `Recall → (可选) Diffusion → Working Context → Agent`。各部分真实成熟度不同，不能把概念图当作已实现能力。Router 当前具体实现为两个独立模型：Judge A 判 Boundary（NEW / CONTINUE），Judge B 对候选 Episode 排名（Which Episode?）。

## 为什么这样设计

Episode 是可被其他话题打断后继续的语义线程，不是固定时间窗。短公共上下文加候选自身摘要/最近消息，为候选判断提供局部证据；Boundary 与 Ranking 分开，避免一个联合决策把“要不要新建”和“选哪个已有 Episode”混成同一题。写入 provenance 用来记录生成记忆时实际使用的注入记忆，而非事后推断。

## 快速阅读顺序

1. [项目状态](docs/PROJECT_STATUS.md) — 当前 DONE/FROZEN/ACTIVE/PAUSED。
2. [怎么运行（概念）](docs/HOW_IT_WORKS.md) — 新读者导览。
3. [当前架构](docs/ARCHITECTURE_CURRENT.md) — 只描述主线。
4. [实验账本](docs/EXPERIMENT_LEDGER.md) — 结果与证据级别入口。
5. [限制](docs/KNOWN_LIMITATIONS.md)、[暂停问题](docs/PAUSED_QUESTIONS.md)、[路线图](docs/ROADMAP.md)。
6. [Router 演进](docs/history/ROUTER_EVOLUTION.md) 与 [Spec 索引](docs/SPEC_INDEX.md)。

权威信息源：当前架构→`ARCHITECTURE_CURRENT.md`；实验→`EXPERIMENT_LEDGER.md`及原始报告；数据→`DATASET_REGISTRY.md`；模型→`MODEL_REGISTRY.md`；状态→`PROJECT_STATUS.md`；后续→`ROADMAP.md`。其他文档应链接这些来源，不复制维护大表。

## 实验安全边界

本次只整理文档。没有运行训练、推理或 benchmark；没有改写数据集、checkpoint 或历史结果；没有移动/删除 checkpoint 或 raw data。5K Boundary forensic 状态为 PAUSED。历史 artifact 原地保留，索引链接到原位置。

## 目录

- `docs/`：项目状态、架构、实验/数据/模型索引、决策、风险、spec 与历史。
- `benchmark-results/`：本仓库的 Router 等 benchmark 原地保存；入口见该目录 README。
- `clean/`, `judgment/`：本机提供的本地数据，Git 忽略；清洗 corpus 和 Judgment 数据集当前在此处实际存在。新 clone 不会包含这些目录，参见 [数据集登记](docs/DATASET_REGISTRY.md)。
- `manifests/`：数据处理清单；`raw massage/` 不在本目录，原始聊天数据保留于旧 `bot/projects/memory/` 兼容/数据区。
- `scripts/`, `tests/`：实现与测试，不属于本轮修改范围。
- `../components/memory-demo/` 与 `../components/xtw-memory-fabric/`：相关源码与实验；各自仍为独立 Git 仓库。

## 文档治理

人工维护文档使用顶部 metadata；实验原始报告是历史证据，不为追求统一而改写。矛盾/撤回须新增更正说明并链接旧记录。此处 Inventory 仍标明尚未逐份内容核读的文件，避免把自动列目录伪装成完整语义审计。
