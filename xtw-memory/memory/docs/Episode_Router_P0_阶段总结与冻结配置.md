# Episode Router P0 阶段总结与冻结配置

**日期：2026-09-21**  
**范围：Memory / Episode Router**  
**状态：P0 可用，建议冻结当前配置，停止继续做 Context / Last-N 参数扫描**

---

## 0. 一句话结论

当前 Episode Router 已经达到可以投入 Memory 后续开发的程度。

本阶段建议冻结的输入结构为：

```text
Current Event（当前消息）
+
Previous 5 Raw Events（前 5 条群聊原始消息）
+
Candidate Episode Summary（候选 Episode 摘要）
+
Candidate Episode Last 2 Raw Events（候选 Episode 最近 2 条原始消息）
```

对应核心参数：

```yaml
candidate_limit: 8
local_context_events: 5
candidate_recent_events: 2
use_reply_signal: true
use_episode_summary: true
use_candidate_recent_events: true
```

当前实验已经表明：

> Router 需要的不是尽可能多的 Context（上下文），而是少量、相关、信息密度高的 Context。

公共群聊窗口继续扩大，会引入明显噪声；Candidate Episode 自己最近 2 条消息则能够提供有价值的连续性信息。

因此当前不再继续追求：

```text
More Context
```

而采用：

```text
Short Local Context
+
Relevant Candidate Context
```

---

# 1. Router 在 Memory 模块里的位置

Router 是 Memory 写入路径最前面的“消息分拣器”。

它负责把连续到来的零散 Event（消息事件）组织到不同 Episode（事件线程 / 话题容器）中。

最简单的路径是：

```text
Raw Message（原始消息）
↓
Event Normalization（整理成标准 Event）
↓
Episode Router（消息分拣）
↓
OPEN Episodes（仍在生长的 Episode）
↓
CLOSED Episode（停止继续接收消息）
↓
Final Consolidation（最终长期记忆整理）
```

Router 不是 Memory Recall（记忆读取），也不是 LLM 回复决策。

它只回答一个问题：

> 当前这条消息最应该被放进哪个 Episode，或者是否应该新建一个 Episode？

---

# 2. Episode 的基本理解

Episode 不是固定时间窗口。

它表示：

> 一条语义上连续的事件线程。

因此真实群聊：

```text
A1
A2
B1
B2
A3
A4
```

允许被整理成：

```text
Episode A:
A1 A2 A3 A4

Episode B:
B1 B2
```

也就是说：

> 同一个 Episode 可以被其他话题暂时打断，然后继续。

这也是 Router 不能仅依靠时间间隔分类的原因。

---

# 3. 当前 Router 的基本流程

当前 Router 不是遍历所有历史 Episode。

流程是：

```text
Current Event
↓
Candidate Builder（找少量候选 Episode）
↓
JEV Pointwise Scoring（逐候选打分）
↓
Routing Policy（根据分数决定）
↓
CONTINUE existing Episode
or
NEW Episode
```

Candidate Builder 当前使用：

```text
reply-target Episode first
+
most recent OPEN Episodes
```

最多：

```text
candidate_limit = 8
```

因此实际做法可以理解成：

> 先粗筛出最多 8 个候选，再逐个让 JEV 判断。

当前 benchmark 中：

```text
Candidate Missing = 0
```

说明在现有 300-message 数据上，正确 Episode 基本都能进入候选集合。

所以当前 Candidate Builder 不是主要瓶颈。

---

# 4. JEV 在 Router 里的职责

JEV 在这里不是直接做：

```text
A / B / C / NEW
```

这种一次性多选题。

而是对每个 Candidate Episode 独立评分：

```text
Current Event + Candidate A
→ score A

Current Event + Candidate B
→ score B

Current Event + Candidate C
→ score C
```

这个 score 更适合理解成：

```text
semantic support
```

即：

> 当前证据有多支持“这条消息属于 / 继续这个 Episode”。

而不是严格概率：

```text
P(same episode)
```

---

# 5. 为什么必须给 JEV Local Context

早期 Router 只看 Current Event 和 Candidate Episode 时，很多短消息几乎无法理解：

```text
“不是”
“？”
“我也是”
“笑死”
```

加入最近 5 条原始群聊消息后，Scorer Misrank（JEV 把错误候选排到正确候选前面）曾从：

```text
35
↓
2
```

说明 JEV 本身并不是完全不能判断，而是非常依赖当前聊天现场。

因此 Local Context 是 Router 的必要输入。

---

# 6. Context 实验的核心问题

在 Local Context 已经证明有效之后，我们继续测试：

> 给 JEV 看更多 Context，会不会继续提高 Router？

主要测试了：

```text
A. 5 + Summary
B. 8 + Summary + Last 2
C. 5 + Summary + Last 2
D. 5 + Summary + Last 3
```

其中：

- `5` / `8`：Current Event 之前最近的公共群聊消息数量。
- `Summary`：Candidate Episode 整体摘要。
- `Last 2 / Last 3`：Candidate Episode 最近 2 / 3 条原始消息。

---

# 7. Benchmark A — 5 + Summary

这是 Context 增强前的主要基线。

输入：

```text
Current Event
+
Previous 5 Raw Events
+
Candidate Episode Summary
```

主要结果：

| Metric | Result |
|---|---:|
| Pairwise Precision | 0.574913 |
| Pairwise Recall | 0.514821 |
| Pairwise F1 | 0.543210 |
| False Split | 0.485179 |
| False Merge | 0.023921 |
| NEW Precision | 0.277778 |
| NEW Recall | 0.468750 |
| NEW F1 | 0.348837 |
| Predicted Episodes | 54 |
| Mean Episode Size | 5.555556 |
| Max Episode Size | 40 |

Failure：

| Failure | Count |
|---|---:|
| Candidate Missing | 0 |
| Threshold Reject | 38 |
| Scorer Misrank | 4 |
| Cascade Error | 1 |
| False Continue | 17 |

这版已经可以工作，但仍存在较多：

```text
Threshold Reject
```

即：

> JEV 已经把正确 Episode 排在第一，但分数仍然不够高，最终错误 NEW。

---

# 8. Benchmark B — 8 + Summary + Last 2

第一次尝试同时增加两类 Context：

```text
Current Event
+
Previous 8 Raw Events
+
Candidate Episode Summary
+
Candidate Episode Last 2
```

结果：

| Metric | Result |
|---|---:|
| Pairwise Precision | 0.391199 |
| Pairwise Recall | 0.565133 |
| Pairwise F1 | 0.462348 |
| False Split | 0.434867 |
| False Merge | 0.055268 |
| NEW Precision | 0.340000 |
| NEW Recall | 0.531250 |
| NEW F1 | 0.414634 |
| Predicted Episodes | 52 |
| Mean Episode Size | 5.769231 |
| Max Episode Size | 76 |

Failure：

| Failure | Count |
|---|---:|
| Candidate Missing | 0 |
| Threshold Reject | 32 |
| Scorer Misrank | 9 |
| Cascade Error | 1 |
| False Continue | 15 |

这一版虽然：

```text
Recall ↑
False Split ↓
```

但是：

```text
Precision ↓↓↓
False Merge ↑↑
Scorer Misrank ↑
Max Episode Size 40 → 76
```

说明 Router 更容易找到“某个看起来相关的旧 Episode”，但也更容易把不同话题错误粘在一起。

因此：

```text
8 + Summary + Last 2
```

不能作为默认配置。

---

# 9. 为什么需要拆分实验变量

上一轮同时修改了：

```text
Local Context:
5 → 8
```

以及：

```text
Candidate Context:
+ Last 2
```

所以无法知道性能下降究竟来自哪一个改动。

因此下一轮保持：

```text
Local Context = 5
```

只加入：

```text
Candidate Last 2
```

---

# 10. Benchmark C — 5 + Summary + Last 2

输入：

```text
Current Event
+
Previous 5 Raw Events
+
Candidate Episode Summary
+
Candidate Episode Last 2 Raw Events
```

结果：

| Metric | 5 + Summary | 5 + Summary + Last 2 | Change |
|---|---:|---:|---:|
| Pairwise Precision | 0.574913 | **0.604897** | +0.029984 |
| Pairwise Recall | 0.514821 | **0.558892** | +0.044071 |
| Pairwise F1 | 0.543210 | **0.580985** | +0.037775 |
| False Split | 0.485179 | **0.441108** | -0.044071 |
| False Merge | 0.023921 | **0.022941** | -0.000980 |
| NEW Precision | 0.277778 | **0.386364** | +0.108586 |
| NEW Recall | 0.468750 | **0.531250** | +0.062500 |
| NEW F1 | 0.348837 | **0.447368** | +0.098531 |
| Predicted Episodes | 54 | **46** | -8 |
| Mean Episode Size | 5.555556 | 6.521739 | +0.966183 |
| Max Episode Size | 40 | 42 | +2 |

Failure：

| Failure | Baseline | Last 2 | Change |
|---|---:|---:|---:|
| Candidate Missing | 0 | 0 | 0 |
| Threshold Reject | 38 | **26** | -12 |
| Scorer Misrank | 4 | 6 | +2 |
| Cascade Error | 1 | 1 | 0 |
| False Continue | 17 | **15** | -2 |

这一轮是目前最重要的 Context 实验。

因为 A 与 C 只有一个主要变量：

```text
Candidate Last 2
```

结果表现为：

```text
Precision ↑
Recall ↑
F1 ↑
False Split ↓
False Merge 略↓
Threshold Reject 明显↓
False Continue ↓
```

虽然：

```text
Scorer Misrank
4 → 6
```

出现了很小的退化，但整体结构明显改善。

因此结论：

> Candidate Episode Last 2 是有效上下文。

---

# 11. Last 2 为什么有效

Episode Summary 与 Episode Last 2 提供的是两种不同的信息。

## Summary

回答：

> 这个 Episode 整体在讲什么？

例如：

```text
今晚木星观测计划与设备准备
```

## Last 2

回答：

> 这个 Episode 最近具体讲到哪里？

例如：

```text
B：十一点应该可以
A：那我带赤道仪
```

因此：

```text
Summary
+
Last 2
```

可以同时给 JEV：

```text
长期主题
+
最近对话落点
```

这很可能是 Threshold Reject 从 38 降到 26 的重要原因。

---

# 12. Benchmark D — 5 + Summary + Last 3

为了检查 Candidate Context 是否还能继续增加，我们测试：

```text
Current Event
+
Previous 5 Raw Events
+
Candidate Episode Summary
+
Candidate Episode Last 3 Raw Events
```

主要比较 Last 2 与 Last 3：

| Metric | Last 2 | Last 3 | Change |
|---|---:|---:|---:|
| Pairwise Precision | **0.604897** | 0.515400 | -0.089497 |
| Pairwise Recall | **0.558892** | 0.489470 | -0.069422 |
| Pairwise F1 | **0.580985** | 0.502100 | -0.078885 |
| False Split | **0.441108** | 0.510530 | +0.069422 |
| False Merge | **0.022941** | 0.028921 | +0.005980 |
| NEW Precision | **0.386364** | 0.295455 | -0.090909 |
| NEW Recall | **0.531250** | 0.406250 | -0.125000 |
| NEW F1 | **0.447368** | 0.342105 | -0.105263 |
| Predicted Episodes | 46 | 46 | 0 |
| Max Episode Size | 42 | 42 | 0 |

Failure：

| Failure | Last 2 | Last 3 | Change |
|---|---:|---:|---:|
| Candidate Missing | 0 | 0 | 0 |
| Threshold Reject | **26** | 30 | +4 |
| Scorer Misrank | **6** | 10 | +4 |
| Cascade Error | 1 | 1 | 0 |
| False Continue | **15** | 19 | +4 |

结论非常明确：

```text
Last 3 < Last 2
```

第三条旧消息没有继续增加有效信息，反而开始增加噪声。

特别是：

```text
Threshold Reject 26 → 30
Scorer Misrank    6 → 10
False Continue   15 → 19
```

说明第三条信息甚至开始直接干扰正确候选的判断。

因此不支持继续增加 Candidate Recent Events。

---

# 13. 四组实验放在一起

| Version | Input | Pairwise F1 | False Merge | Predicted Episodes | 结论 |
|---|---|---:|---:|---:|---|
| A | 5 + Summary | 0.543210 | 0.023921 | 54 | 可用 Baseline |
| B | 8 + Summary + Last 2 | 0.462348 | 0.055268 | 52 | 公共 Context 过长，明显退化 |
| C | **5 + Summary + Last 2** | **0.580985** | **0.022941** | **46** | **当前最佳 / 建议冻结** |
| D | 5 + Summary + Last 3 | 0.502100 | 0.028921 | 46 | Candidate Context 开始过长 |

这组结果形成了非常清晰的规律：

```text
公共 Context：
5 条合适
8 条开始明显增加群聊噪声
```

以及：

```text
Candidate Recent Context：
2 条有明显价值
3 条开始明显增加噪声
```

所以当前“甜点位”是：

```text
5 + Summary + Last 2
```

---

# 14. 当前最重要的设计结论

## 14.1 Context 不是越多越好

错误方向：

```text
More Context
→ Better Router
```

当前实验不支持这个结论。

更合理的是：

```text
Relevant Context
→ Better Router
```

即：

> Router 应优先获得与当前判断最相关的信息，而不是获得更多原始文本。

---

## 14.2 公共上下文应该短

群聊中同时可能存在多个交错话题。

因此：

```text
Previous 5
```

目前比：

```text
Previous 8
```

表现更稳定。

公共窗口过长，会把其他话题一起带入 JEV。

---

## 14.3 Candidate 专属上下文有价值

相比增加整个群聊窗口：

```text
Candidate Episode Last 2
```

提供的信息更加集中。

它告诉 JEV：

> 这个 Candidate 最近具体停在哪里。

因此当前更推荐：

```text
短公共 Context
+
Candidate 专属 Context
```

---

## 14.4 Candidate 专属 Context 也不能无限增加

Last 3 明显退化说明：

> 即使是 Candidate 自己的历史，也不是越多越好。

超过某个长度以后，旧消息同样会成为噪声。

当前数据支持：

```text
Last 2
```

而不支持：

```text
Last 3
```

---

# 15. 当前冻结的 Router 输入 Contract

每次 JEV 对一个 Candidate Episode 评分时，输入可以固定为：

```text
LOCAL CONVERSATION CONTEXT

Previous Event -5
Previous Event -4
Previous Event -3
Previous Event -2
Previous Event -1


CURRENT EVENT

Current Event


CANDIDATE EPISODE

Summary:
<episode summary>

Recent Events:
<second last raw event>
<last raw event>
```

其中 Raw Event 尽量保留：

```text
event_id
sender
timestamp
content
reply_to
message_type
```

---

# 16. 当前冻结配置

建议冻结：

```yaml
candidate_limit: 8

local_context_events: 5
candidate_recent_events: 2

use_reply_signal: true
use_episode_summary: true
use_candidate_recent_events: true
```

当前 Routing Policy 继续保持既有配置：

```yaml
high_threshold: 0.55
low_floor: 0.25
min_margin: 0.15
```

本阶段不再继续做：

```text
Local Context 5 / 8 / 10 / 15 sweep

Candidate Last 1 / 2 / 3 / 4 / 5 sweep

threshold sweep

low_floor sweep

margin sweep

candidate_limit sweep
```

---

# 17. 当前 Router 的限制

冻结并不等于 Router 已经完美。

仍然存在：

```text
Threshold Reject
Scorer Misrank
False Continue
False Split
False Merge
```

也仍然受到：

```text
短消息歧义
图片内容缺失
Teacher Silver 边界歧义
已有 Episode state 污染
JEV Provider Error
```

等因素影响。

但是：

> P0 的目标不是得到完美 Episode 分类器，而是得到一个足够稳定、足够简单、能够支撑后续 Memory 工作的 Router。

从当前实验结果看，这个目标已经达到。

---

# 18. 关于 Reconciliation 的当前决定

之前曾考虑加入：

```text
Episode Reconciliation
```

用于：

```text
merge
split
detach
reassign
repair
```

但这会明显增加：

```text
运行成本
系统状态复杂度
历史修改逻辑
调试难度
错误传播路径
```

当前 Router 在 `5 + Summary + Last 2` 下已经获得了可接受的结构质量。

因此当前阶段建议：

```text
不把 Reconciliation 放入 P0 主路径
```

而是保留为未来可选能力。

只有后续 Memory Recall 或 Consolidation 的真实使用证明：

```text
Episode fragmentation / contamination
确实已经成为下游系统的主要瓶颈
```

再考虑引入 Reconciliation。

也就是说：

> 不为尚未证明的问题提前增加系统复杂度。

---

# 19. 当前 Memory Write Path 建议

因此现阶段可以把写入路径保持得很简单：

```text
Raw Message
↓
Normalized Event
↓
Episode Router
↓
OPEN Episode Store
↓
TTL / Explicit Close
↓
CLOSED Episode
↓
Final Consolidation
```

Router 本身：

```text
Current Event
↓
Candidate Builder
↓
JEV Candidate Scoring
↓
Routing Policy
↓
CONTINUE / NEW
```

暂时不增加持续的 OPEN Episode 重组层。

---

# 20. 当前阶段判断

当前可以正式将 Episode Router P0 判断为：

```text
USABLE
```

更完整地说：

```text
Episode Router P0
≈ DONE / USABLE

Candidate Builder
≈ SUFFICIENT FOR P0

Local Context
≈ 5 EVENTS FROZEN

Candidate Recent Context
≈ LAST 2 FROZEN

JEV Pointwise Scoring
≈ VALIDATED

Relative Margin Policy
≈ VALIDATED

Further Context Sweep
≈ STOP

Reconciliation
≈ DEFERRED
```

---

# 21. 当前阶段最值得保留的结论

```text
1.
Episode 是 semantic thread，而不是时间窗口。

2.
Episode 可以 non-contiguous。

3.
Candidate Builder 当前不是主要瓶颈。

4.
Local Context 对 JEV 判断非常重要。

5.
公共 Local Context 不是越长越好。

6.
Previous 5 当前比 Previous 8 更稳定。

7.
Episode Summary 和 Episode Last 2 提供互补信息。

8.
Candidate Last 2 有明确正收益。

9.
Candidate Last 3 已开始明显退化。

10.
当前最佳 Context 是：
Previous 5 + Summary + Last 2。

11.
当前 Router 已经足够支撑下一阶段 Memory 开发。

12.
暂时没有必要为了追求完美分类引入复杂 Reconciliation。
```

---

# 22. 下一步

Router 本阶段停止继续优化。

下一阶段不再问：

```text
“Context 应该再多一条吗？”
```

也不再问：

```text
“还能不能把 Episode 数继续压低？”
```

而应该开始使用当前 Router 产生的 Episode，继续验证 Memory 后面的模块。

最重要的问题变成：

> 当前这种“并不完美但已经可用”的 Episode 结构，是否足够支撑后续 Consolidation、Semantic Memory 和 Recall？

只有当真实下游使用证明 Router 的错误已经成为主要瓶颈时，才重新打开 Router / Reconciliation 设计。

---

# 23. 最终冻结结论

```text
Episode Router P0

INPUT:
Current Event
+ Previous 5 Raw Events
+ Candidate Episode Summary
+ Candidate Episode Last 2 Raw Events

CANDIDATES:
reply-target Episode first
+ recent OPEN Episodes
max 8

SCORING:
JEV pointwise scoring

POLICY:
high threshold
+ low floor
+ relative margin

OUTPUT:
CONTINUE existing Episode
or
NEW Episode

STATUS:
USABLE / FREEZE FOR NOW
```

当前阶段的目标已经不再是让 Router 变得完美，而是：

> **用一个简单、可解释、成本可控的 Router，把零散消息稳定地整理成足够可用的 Episode，随后让 Memory 的其他部分继续向前发展。**

