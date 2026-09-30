# IRIS Associative Memory Seed Graph v0.1 — 标注说明

**日期：2026-09-21**  
**用途：Attention Diffusion / Memory Emergence Visual Demo P0**  
**数据文件：`iris_associative_memory_seed_graph_v0.1.json`**

## 1. 标注规模

- Nodes: 42
- Directed Edges: 114
- Recall Cases: 9
- Clusters: 5

节点类型包括：

- Person
- Alias
- Self
- Role
- Memory
- Concept
- Activity
- Object
- Location
- Goal

## 2. 五个实验簇

### A. NICEICK
用于测试：
- alias bridge
- 世界计划 / 星乃一歌 / Leo/need 等多入口联想
- multi-path convergence
- context competition

### B. 小天文自身
用于测试：
- “助手 / 小天文喵 / 小天文”之间不做 hard merge 时的跨称呼联想
- Self / Role / Person / Activity / Concept 异构节点共同扩散
- longz creator recall

### C. 不爱记笔记 / 8SE
用于测试：
- 人物 → 器材
- 行星 → 目视观测
- 人物路径与观测路径的跨类型汇聚

### D. 徐汇
用于测试：
- 同一地点连接不同人物
- shared context 不导致 identity collapse
- “走读”Context 对分支的选择

### E. 奉贤校区 / 通海湖
用于测试：
- 简单强一跳 recall
- sanity check

## 3. Association Strength 标注原则

人工只使用五档：

```text
VERY_STRONG = 0.95
STRONG      = 0.80
MEDIUM      = 0.60
WEAK        = 0.35
VERY_WEAK   = 0.15
```

这些值是 **demo prior**：

> 只表示第一版原型中“注意力应该多容易沿这条关系流动”。

它们不是：

- 事实可信度
- IRIS confidence
- 概率
- 最终训练权重

## 4. Identity Policy

本数据集故意不执行 canonical merge。

例如：

```text
心象蜃気楼
NICEICK
2960945437
```

仍然是不同节点，通过：

```text
refers_to
known_as
```

建立关联。

Demo 要测试的是：

> 不依赖强制身份合并，仅靠联想扩散是否还能把相关记忆带起来。

## 5. 为什么显式标双向边

P0 Diffusion Engine 按有向边传播。

因此，如果希望：

```text
Person → Location
```

和：

```text
Location → Person
```

都能够成为认知联想路径，就必须分别存在两条有向边。

这不是说现实中的 relation 本体一定对称，而是显式表示：

> 两个方向是否都允许作为 Recall 通道。

## 6. 核心 Case

### A2_MULTIPATH_PJSK

Context：

```text
NICEICK 世界计划 星乃一歌
```

Seeds：

```text
NICEICK      0.34
世界计划      0.33
星乃一歌      0.33
```

目标：

```text
memory:niceick_pjsk_ichika
```

三条 cue 单独都只是 MEDIUM，但应通过同一步的 incoming Attention 相加，使 Memory 跨过 emergence threshold。

这是 P0 最重要的多路径汇聚演示。

## 7. Dry-run 说明

使用 Demo Spec 的建议参数做过一次非正式 dry-run：

```text
temperature        = 1.0
selfRetention      = 0.35
contextAnchor      = 0.15
propagationFloor   = 0.005
emergenceThreshold = 0.10
```

A2 的三条 cue 若为：

```text
WEAK = 0.35
```

目标 Memory 峰值约：

```text
0.092
```

没有跨过 0.10。

因此这三条 cue 的 **demo prior** 统一调整为：

```text
MEDIUM = 0.60
```

dry-run 峰值约：

```text
0.112
```

可以展示真正的：

```text
多路径汇聚
→ 跨阈值
→ EMERGED
```

这里调整的是 demo 联想先验，不是修改 IRIS 原始事实或置信度。

## 8. 当前 9 个 Recall Cases

1. `A1_ALIAS_BRIDGE`
2. `A2_MULTIPATH_PJSK`
3. `A3_CONTEXT_COMPETITION`
4. `B1_SELF_CREATOR`
5. `B2_SELF_METEOR`
6. `C1_8SE_CONVERGENCE`
7. `D1_XUHUI_SHARED_CONTEXT`
8. `D2_COMMUTING`
9. `E1_TONGHAI_DIRECT`

## 9. 当前标注边界

本轮没有标：

- Truth probability
- 自动 Entity Resolution
- Dream 学习规则
- 最终 decay
- 最终 temperature
- 最终 emergence threshold
- 生产级 ontology
- 全量 IRIS 图

本数据集只服务于：

> 验证有限总注意力在异构联想网络中的扩散、竞争、多路径汇聚和记忆涌现。
