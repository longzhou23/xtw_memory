Project: xtw-memory
Module: conceptual walkthrough
Version: v0.1
Status: CURRENT
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# How It Works

本文讲当前概念与已验证边界，不承诺每个方框都已在生产系统接通。

## 从聊天到 Episode

原始聊天先规范成 Event（事件：含消息内容、时间、来源等字段）。Episode（事件片段/语义线程）是一组围绕同一件事的事件；它不是固定时间段，同一话题可被别的话题插入后继续。

Episode Router（片段路由器）处理新事件。当前 Router v0.2 用两步 Judgment（判断）：Judge A 先回答 Boundary（边界判断）——应当 `NEW` 开新片段还是 `CONTINUE`；若继续，Judge B 再回答 Ranking（候选排序）——已有候选里 Which Episode（属于哪一个）。当前实现是两个独立的 Laya 322M 模型，不是共享主干。

## Episode 生命周期与临时记忆

Episode 生命周期（Lifecycle）让开放中的 Episode 接收事件，满足关闭/过期条件后停止接收。Working Context（工作上下文）是短期保留的局部事件队列；受容量限制时旧事件会被逐出（spill/eviction）。Temporary Memory Fabric（临时记忆织布层）在实验路径中维护这些临时记忆及 Episode 范围关联。逐出是触发写入检查点，不意味着只总结被逐出的单条消息。

## 写入、usedMemoryIds 与 FORMED_WITH

Memory Write（记忆写入）产生一条新记忆。`injectedMemoryIds` 是模型写入时可看到的旧记忆 ID；`usedMemoryIds` 是模型明确声明本次写入实际依赖的那些 ID，必须是注入集合的子集。它是**写入时 provenance（来源/使用凭据）**，不能根据结果倒推。`FORMED_WITH` 是关联关系，表示新记忆在形成时使用/关联了某个已注入记忆；强度等约束见冻结 schema/报告。有限云探针曾得到空使用列表，不能宣称已证明正向使用能力。

Final Consolidation（最终整合）预期在 Episode 结束后，把多个临时记忆归纳为长期记忆；目前没有完整质量验证的端到端主线。

## Recall 与 Diffusion

Recall（回忆/检索）从记忆中找与当前线索相关的候选；当前历史 Recall P0 不能等同为已证明的长期认知能力。Diffusion（扩散）则是图上的激活传播假设：已有激活沿关联边传递，可能让非直接命中的节点进入工作上下文。二者不同：Recall 选候选，Diffusion 测试关联网络里的激活能否传播。现有 diffusion 报告用的真实 Cognitive Unit 图没有边，故只验证了零边控制与合成不变量，未证明真实关联图收益。

## 为什么需要 JudgmentProvider

JudgmentProvider（判断服务提供者）是模型/规则的接口抽象，让 Router 或记忆任务向不同实现请求结构化评分，而不把某个模型绑死在核心流程。JEV（一个 scoring/judgment 系统）是候选实现之一；Laya、Qwen 等实验是不同 provider/模型证据，不可把某个 benchmark 分数当作通用能力。不同任务（Boundary、Ranking、Recall relevance）也不能混用标签或指标。

## 全链路图

```text
Raw Chat → Event → Router → Lifecycle → Working Context → Temporary Memory
         → Write + provenance/FORMED_WITH → Final Consolidation → Long-Term Memory
         → Recall → optional Diffusion → Agent Working Context → Agent
```

各节点状态见 [PROJECT_MAP.md](PROJECT_MAP.md)；当前唯一主线定义见 [ARCHITECTURE_CURRENT.md](ARCHITECTURE_CURRENT.md)。
