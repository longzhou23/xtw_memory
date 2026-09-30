# 小天文 Memory — Recall P0 完整实验备忘录
## 从 Astra Recall 优化阶段到 Recall P0 冻结

**日期：2026-09-22**  
**项目：小天文记忆 / Agent Memory**  
**覆盖时间范围：** 从上一份阶段备忘录  
`小天文_Memory_Recall_Astra优化与Benchmark_阶段备忘录_2026-09-22.md`  
结束的位置开始，至当前 Recall P0 冻结决策与归档 Spec 发出为止。

---

# 0. 本备忘录的目的

这份备忘录不是新的算法 Spec，也不是只记录“最后分数”的结果摘要。

它的目的，是把这一阶段 Recall 子系统从：

```text
强 lexical baseline
↓
冻结 benchmark
↓
正式 Recall / Agent / Oracle 测试
↓
发现 MULTI_UNIT 系统性失败
↓
提出 Recall Temperature 假设
↓
Astra 诊断 whole-query coverage
↓
multi-emergence-recall
↓
Luna 本地 Temperature sweep
↓
发现实验变量根本未触发
↓
Aspect Extraction failure diagnosis
↓
quoted-list parser 窄修复
↓
DEV Recall 重新验证
↓
FREEZE_PARSER
↓
Recall P0 Freeze & Archive
```

整个实验过程、实验纪律、原始数据、失败路径、解释变化和最终边界一次性记录下来。

本阶段最重要的不是“把 Recall 做到了 100%”，而是：

> **通过一系列可证伪实验，定位出 MULTI_UNIT Recall 的主要失败来自 Recall Target 的表达/分解，而不是简单的阈值、Temperature 或相对竞争参数。**

---

# 1. 上一份备忘录结束时的起点

上一阶段结束时，已经完成 Astra 对 Recall baseline 的一次较大优化。

冻结强 baseline：

```text
provider:
improved-recall

config:
1.0.0-final-candidate

provider fingerprint:
035bb4f78f6031a7fb99d2625d42bc0874f8f6c02101128e451d5a2238da4659

provider implementation commit:
ec485a69872b48360678e33aa8e8058398ac0579
```

它的核心结构为：

```text
Query
↓
Normalize
↓
Detect Subject
↓
Remove Subject + Question Scaffolding
↓
Extract Topical Content
↓
IDF-weighted Coverage
↓
Subject Gate
↓
Topic Coverage Gate
↓
Phrase / Type / Temporal / Negation bonuses
↓
Absolute Score Floor
↓
Relative-to-best Threshold
↓
0..8 Cognitive Units
```

最终配置：

```text
minContentCoverage = 0.36
noSubjectCoverage  = 0.55
relativeThreshold  = 0.78

subjectWeight = 2.0
mentionWeight = 1.2
typeWeight    = 1.0
contentWeight = 4.0
phraseWeight  = 0.6
cueWeight     = 0.35

minimumScore = 1.5
cleanOnly    = true
limit        = 8
```

这时已经确立一条重要原则：

> `limit=8` 是最大 Context Budget，而不是要求一定返回 8 条。

相比早期 `lexical-top8`，`improved-recall` 的设计目标从：

```text
尽可能保证 gold 在 Top-8
```

变成：

```text
只有真正有足够 evidence 的 Cognitive Unit 才进入 context
```

---

# 2. Benchmark v0.2.0 人工审计与正式冻结

上一阶段的自动生成 benchmark 存在明显 annotation / query 质量问题，因此在进行新的正式测试前，先完成 benchmark 审计。

## 2.1 冻结数据

```text
file:
memory_benchmark_v0.2.0.json

version:
0.2.0

frozen:
true

total:
200

DEV:
50

TEST:
150
```

SHA256：

```text
14be135076979992d9043553585f9f2290c6155937b3cba56dff5b24ce228ca9
```

Benchmark freeze commit：

```text
c831fd9f6eaed996a1f22c290c7112ba799af8bd
```

Cognitive Unit Store 保持不变：

```text
SHA256:
92f5b405b10f00ba82c05f5f8197fc277966853d70499cbcd949d3ece7e34ef8
```

---

## 2.2 Category 分布

总计 200 cases：

| Category | Cases |
|---|---:|
| DIRECT | 35 |
| MULTI_UNIT | 35 |
| ALIAS | 25 |
| TEMPORAL | 20 |
| NEGATION | 20 |
| DISTRACTOR_HEAVY | 20 |
| DIRTY_OR_AMBIGUOUS | 15 |
| INSUFFICIENT_MEMORY | 15 |
| NO_MEMORY_NEEDED | 15 |

---

## 2.3 Audit 结果

```text
PASS              = 45
FIXED_ANNOTATION  = 153
INVALID_CASE      = 2
```

主要修订原因：

```text
natural / clear / topic-specific query rewrite      153
typeHints aligned to gold type                       15
duplicate-semantic expected → acceptableUnitIds       3
distractor semantically duplicate → acceptable        7
category lacked real negative semantics → invalid      2
```

两条 INVALID NEGATION case 被替换，但保留：

```text
case ID
split
category
```

替换内容：

```text
bench_119_negation
→ 小瑾没有游泳经历，之前表示自己没下过水

bench_126_negation
→ NICEICK不喜欢角色保登心爱
```

---

## 2.4 冻结后的纪律

从 benchmark v0.2.0 freeze 开始：

> **TEST 只负责测，不负责教。**

禁止：

```text
看到 TEST
→ 调 threshold
→ 改 scoring
→ 改 gold
→ 再把结果叫 holdout
```

后续正式评估冻结输入：

```text
benchmark SHA256:
14be...ca9

store SHA256:
92f5...4ef8

improved provider fingerprint:
035b...4659

provider config:
1.0.0-final-candidate
```

---

# 3. Frozen Final Benchmark 设计

最终评估设计为三层。

## 3.1 Recall-only

```text
Query
→ MemoryProvider
→ recalled Unit IDs
→ compare gold
```

对比：

```text
lexical-top8
vs
improved-recall
```

目的：

> 单独测检索，不混入 LLM 工具判断和回答能力。

---

## 3.2 Agent E2E

```text
User Query
↓
Tool Decision
↓
improved-recall
↓
Answer
↓
Judge
```

目的：

> 测真实 Agent 是否决定调用记忆、是否召回正确内容、是否正确使用召回内容。

---

## 3.3 Oracle

```text
User Query
↓
直接注入 Gold expected / acceptable Units
↓
Answer
↓
Judge
```

目的：

> 把 Retrieval 从链路中拿掉，估计“如果正确记忆已经进入 Context，LLM 能做到什么”。

这样可分离：

```text
Tool Decision Failure
Recall Failure
Answer-use Failure
Hallucination
Abstention Failure
```

---

# 4. 为什么需要 Parallel Frozen Benchmark Runner

原始 runner 完全串行。

150 个 TEST case 中，每个 Agent case 最多可能产生：

```text
1. Tool Decision
2. Answer Generation
3. Judge
```

因此理论上：

```text
150 × 3 ≈ 450 次 CLI/model calls
```

实际串行正式运行时间过长。

之前两次正式尝试都被正确判定为 INVALID：

```text
Attempt 1:
模型调用完成
但 runner 写 report 时变量错误
→ INVALID

Attempt 2:
外部中断
→ INVALID
```

第三次串行 run 启动后，决定不在运行中修改实验条件，而是另写 Parallel Runner Spec。

---

# 5. Parallel Frozen Benchmark Runner v0.3

## 5.1 并发原则

只并行不同 case。

同一个 case 内保持严格：

```text
Tool Decision
→ Answer
→ Judge
```

即：

```text
Case 1: D → A → J
Case 2: D → A → J
Case 3: D → A → J
...
```

不同 case 之间使用 bounded worker pool。

配置：

```text
concurrency = 5
```

不允许：

```text
Promise.all(150)
无限并发
自动重试
结果驱动重跑
动态换模型
同一正式 run 中偷偷改 concurrency
```

---

## 5.2 Run-level provenance

正式 run：

```text
run_id:
frozen-v0.2.0-final-parallel-20260922T094715Z

runner commit:
aeeb80c7e62f86dc7cf599ab3782bd0a4df49f78

runner source SHA256:
6147bf3dde1ab5301d2eb9d85d6261b4533d26934bf68ddaec01803d631af32a

configured concurrency:
5

max observed workers:
5

smoke test:
PASS
```

执行结果：

```text
recall cases = 150
agent cases  = 150
oracle cases = 150

case errors:
0

automatic retries:
0
```

---

## 5.3 Runtime

Agent：

```text
wall_clock_ms:
1,390,476.767

≈ 23.17 min

throughput:
0.107877 cases/s

case latency p50:
40,107.142 ms

case latency p95:
81,532.455 ms
```

Oracle：

```text
wall_clock_ms:
830,764.366

≈ 13.85 min

throughput:
0.180557 cases/s

case latency p50:
23,643.594 ms

case latency p95:
49,974.418 ms
```

说明：

> 并行化降低的是 wall-clock，不降低 quota / model calls。

---

# 6. Frozen v0.2.0 Recall Final Results

## 6.1 lexical-top8 baseline

```text
expected_unit_recall:
1.000000

exact_core_recall:
1.000000

useful_context_rate:
0.173491

distractor_rate:
0.022158

false_positive_rate:
0.738921

false_positives_per_memory_case:
5.557971

negative_rejection:
0.000000

no_memory_rejection:
0.583333

returned_units_mean:
7.186667

returned_units p50/p95/p99:
8 / 8 / 8

latency mean:
12.996 ms

latency p50/p95/p99:
11.888 / 23.517 / 27.261 ms
```

这一结果说明：

```text
Recall = 极高
Context cleanliness = 极差
Negative rejection = 几乎不存在
```

v0.2 审计后 query 更明确，因此粗 lexical matcher + 强制 Top-8 很容易把正确答案包含进去。

但代价是：

> 每条 query 平均返回 7.19 条，约 74% false-positive rate。

因此它代表的是：

> **“宁可全部搬进来，也不要漏答案。”**

而不是生产可用的高质量 Ambient Recall。

---

## 6.2 improved-recall

```text
expected_unit_recall:
0.727273

exact_core_recall:
0.775862

useful_context_rate:
0.851852

distractor_rate:
0.014815

false_positive_rate:
0.148148

false_positives_per_memory_case:
0.144928

negative_rejection:
1.000000

no_memory_rejection:
0.833333

returned_units_mean:
0.913333

returned_units p50/p95/p99:
1 / 2 / 3

latency mean:
1.402 ms

latency p50/p95/p99:
1.175 / 2.834 / 4.719 ms
```

相比 lexical-top8：

```text
expected recall          -27.27 pp
exact core recall        -22.41 pp

useful-context           +67.84 pp
false-positive rate      -59.08 pp
FP / memory case         -5.41
negative rejection       +100 pp
returned units mean      -6.27
latency mean             -11.59 ms
```

这说明 `improved-recall` 成功把 Recall 从：

```text
“固定装满”
```

变成：

```text
“有 evidence 才返回”
```

---

# 7. Frozen Agent E2E / Oracle Results

## 7.1 Agent Tool Decision

```text
TP = 134
FP = 0
TN = 12
FN = 4

precision:
1.000000

recall:
0.971014

F1:
0.985294

accuracy:
0.973333
```

说明 Tool Decision 本身已经不是主要瓶颈。

---

## 7.2 Agent E2E

```text
answer_fact_accuracy:
0.600000

forbidden_fact_violation_cases:
0

unsupported_claim_rate:
0.316832

abstention_accuracy:
1.000000

e2e_success:
0.613333

judge_errors:
3
```

Failure breakdown：

```text
recall_fail:
26 positive cases missed exact core

answer_use_fail:
41 cases

hallucination_fail:
32 cases

abstention_fail:
0

tool_decision_fail:
4

judge_error:
3

case_execution_error:
0
```

---

## 7.3 Oracle

```text
tool decision:
138 TP
0 FP
12 TN
0 FN

precision:
1.0

recall:
1.0

F1:
1.0

accuracy:
1.0
```

回答：

```text
answer_fact_accuracy:
0.973856

unsupported_claim_rate:
0.102564

abstention_accuracy:
1.000000

e2e_success:
0.873333

judge_errors:
3
```

Oracle 与 Normal Agent 完全独立：

```text
无共享 conversation state
无共享 Agent answer
无共享 recall result
直接注入 gold context
```

---

# 8. Final Benchmark 暴露出的真正结构性问题

最重要的发现不是 overall Recall 72.7%，而是：

> `improved-recall` 的失败高度集中在 `MULTI_UNIT`。

后续 artifact 诊断显示，除 MULTI_UNIT 外，正例主要类别：

```text
DIRECT               expected recall = 1.0
ALIAS                expected recall = 1.0
TEMPORAL             expected recall = 1.0
NEGATION             expected recall = 1.0
DISTRACTOR_HEAVY     expected recall = 1.0
```

对应 exact core 同样为：

```text
1.0
```

Negative 类：

```text
DIRTY_OR_AMBIGUOUS rejection:
1.0

INSUFFICIENT_MEMORY rejection:
1.0
```

但：

```text
MULTI_UNIT expected-unit recall:
≈ 0.34375（正式 TEST 诊断）

MULTI_UNIT exact core recall:
0
```

因此 overall 下降不是系统“普遍找不到”，而是：

> **单目标 Recall 已很强，多目标 Recall 出现系统性 collapse。**

---

# 9. MULTI_UNIT 与 Agent E2E 的关系

后续 artifact 分解发现：

```text
Agent overall fact accuracy:
60%
```

但去掉 MULTI_UNIT 后，非 MULTI expected facts：

```text
73 / 89
≈ 82.0%
```

而 MULTI_UNIT：

```text
17 / 61
≈ 27.9%
```

Oracle 中 MULTI_UNIT：

```text
64 / 64
= 100%
```

这给出一条非常明确的链：

```text
Multi-unit query
↓
Recall 只返回其中部分 Unit
↓
LLM Context 缺少其他 expected Unit
↓
Answer 缺事实
↓
Agent fact accuracy 降低
```

而 Oracle 证明：

> 当正确 Cognitive Units 全部进入 Context 后，LLM 对 MULTI_UNIT 的使用能力本身不是主要问题。

---

# 10. 一个重要的 Agent 语义问题

典型 case：

```text
“1kingsl 喜欢巧克力，
以及喜欢《东方Project》的角色灵梦，
相关内容有哪些？”
```

Gold 包含：

```text
喜欢巧克力
喜欢灵梦
```

当 Recall 只返回：

```text
喜欢灵梦
```

LLM 曾回答类似：

```text
“未提到他喜欢巧克力。”
```

这是一个危险的语义升级：

```text
“我没想起来 X”
↓
“记忆中不存在 X”
```

但 Recall 的正确语义只能是：

```text
本次 Recall 没返回 X
≠
Memory Store 中没有 X
```

因此得到产品层原则：

> **Absence from recalled results is not evidence that the memory store contains no such information.**

这对未来 Ambient Recall / Deep Recall 的 Prompt 设计很重要。

---

# 11. Oracle 结果中的两个评估设计问题

## 11.1 Oracle failure report contamination

某些 Oracle case：

```text
gold context 全部注入
answer 正确
oracle.failure = PASS
```

但顶层 failure 仍可能写：

```text
RECALL_METRIC_FAIL
```

原因是顶层 failure 字段继承了 Normal Recall metric。

因此后续 runner 应区分：

```text
normalRecallFailure
oracleAnswerFailure
```

Oracle failure report 不应继承 Normal Recall failure。

---

## 11.2 NO_MEMORY_NEEDED Oracle 语义

例如：

```text
“请解释牛顿第一定律？”
```

case：

```text
requiresMemory = false
shouldAbstain = false
```

但 Oracle 如果强制：

```text
“只能根据 injected memory 回答”
```

会错误回答：

```text
“提供的记忆中没有相关信息，因此无法回答。”
```

所以：

```text
Oracle E2E = 87.33%
```

不能简单理解为 LLM 理论上限。

更正确的 Oracle：

```text
requiresMemory = true
→ gold memory injection

requiresMemory = false
→ 正常 general-knowledge LLM path
```

---

# 12. 初始假设：Recall Temperature

观察到 `improved-recall` 使用：

```text
absolute floor
+
relative-to-best threshold
```

最初提出：

> 是否可以加入类似 Temperature 的参数控制 Recall breadth？

定义直觉：

```text
T < 1
→ competition 更尖
→ 更聚焦

T = 1
→ 当前 baseline

T > 1
→ competition 变平
→ 次强相关 Unit 更容易 emerge
```

候选公式：

\[
r_i = score_i / bestScore
\]

\[
r'_i = r_i^{1/T}
\]

保留：

\[
r'_i \ge relativeThreshold
\]

---

# 13. Astra 对 Temperature 假设的第一轮诊断

Astra 指出两个关键问题。

## 13.1 Temperature 公式并不是新的自由度

因为：

\[
(score/best)^{1/T} \ge \theta
\]

严格等价于：

\[
score \ge best \cdot \theta^T
\]

因此：

> 这个 Temperature 在纯 relative-threshold 层，本质上是另一种参数化方式。

它可以作为“认知 breadth”接口，但不能自动解决更早的 eligibility failure。

---

## 13.2 更早还有 whole-query coverage gate

旧 provider 在 relative competition 之前就要求：

> 一条 Memory 必须覆盖整条 Query 足够多的内容。

如果 Query 同时包含：

```text
A
B
C
```

而一条 Memory 只对应：

```text
A
```

则其 whole-query coverage 可能只有约 1/3。

于是：

```text
Coverage Gate
↓
Candidate 被过滤
↓
根本进不到 relative competition
```

此时哪怕：

```text
T = 20
```

也救不回来。

---

# 14. Astra 提交 multi-emergence-recall

为验证“多个 Recall Target 应独立评分”，Astra 创建新 provider：

```text
multi-emergence-recall
```

旧：

```text
improved-recall
```

保持完全冻结。

初始候选：

```text
version:
0.1.0-candidate

temperature:
1

intentMode:
explicit-clauses

maxAspects:
8

maxReturnedUnits:
8

fingerprint:
b325c632b4e7391cf0721490ff4e8370dc50580ae08ccccef8368af3736d8ab0
```

---

# 15. multi-emergence 初始机制

明确分隔的 query：

```text
A ; B ; C
```

或：

```text
A；B
A以及B
A另外B
```

被拆成独立 aspects。

每个 aspect：

```text
subject
topic
coverage
score
relative competition
```

独立计算。

然后：

```text
Aspect A strongest candidate
Aspect B strongest candidate
Aspect C strongest candidate
↓
round-robin / fair merge
↓
supporting context
↓
dedup
↓
max 8
```

重要：

> 一个 aspect 不允许先把整个 budget 填满，再让其他 aspect 没机会出现。

---

# 16. Astra Synthetic Tests

Astra 没有立即跑 DEV / TEST，而先做机制验证。

早期交付：

```text
new provider synthetic tests:
12 passed

frozen provider contract tests:
9 passed

build:
PASS
```

关键 synthetic case：

```text
Query:
Mira orchard mango;
satellite orbit;
violin sonata
```

三个独立 Memory：

```text
orchard
space
music
```

结果：

```text
old provider:
[]

whole-query + T=20:
[]

multi-emergence T=1:
[orchard, space, music]
```

这个实验非常关键：

> Temperature 无法救回在 Coverage 之前已死掉的 candidate；local aspect scoring 可以。

---

# 17. Temperature 本地 Sweep 设计

Astra 负责算法机制，Luna 只负责本地参数实验。

实验纪律：

```text
DEV only
Recall-only
0 LLM calls
不跑 TEST
不跑 Agent
不跑 Oracle
不跑 Judge
```

不是让 Luna “逐 case 思考”，而是写 sweep script 直接调用：

```text
provider.recall()
```

---

# 18. Temperature Sweep 执行量

共：

```text
300 次本地 recall()
```

组成：

```text
improved-recall baseline                     50
whole-query T=1                              50
explicit-clauses T=1                         50
explicit-clauses T=1.3                       50
explicit-clauses T=1.6                       50
explicit-clauses T=2.0                       50
```

DEV：

```text
50 cases
```

没有任何 LLM / Agent / Oracle / Judge 调用。

---

# 19. Temperature Sweep 数据

| Config | MULTI expected recall | MULTI exact | Overall recall | Useful context | FP / memory case | Negative rejection | Returned mean / p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| improved baseline | 0.291667 | 0 | 0.685185 | 0.844444 | 0.148936 | 1.000000 | 0.92 / 2 |
| whole-query T=1 | 0.291667 | 0 | 0.685185 | 0.844444 | 0.148936 | 1.000000 | 0.92 / 2 |
| explicit T=1 | 0.291667 | 0 | 0.685185 | 0.844444 | 0.148936 | 1.000000 | 0.92 / 2 |
| T=1.3 | 0.291667 | 0 | 0.685185 | 0.808511 | 0.191489 | 1.000000 | 0.96 / 2 |
| T=1.6 | 0.291667 | 0 | 0.685185 | 0.760000 | 0.255319 | 1.000000 | 1.02 / 3 |
| T=2.0 | 0.291667 | 0 | 0.685185 | 0.730769 | 0.297872 | 1.000000 | 1.06 / 3 |

所有配置在：

```text
DIRECT
ALIAS
TEMPORAL
NEGATION
DISTRACTOR_HEAVY
```

保持：

```text
expected recall = 1.0
exact core recall = 1.0
```

No-memory rejection：

```text
0.666667
```

在所有配置中不变。

---

# 20. Temperature Sweep 直接结论

随着 T 增大：

```text
MULTI expected recall:
不变

MULTI exact:
不变

Useful context:
0.8444 → 0.7308

FP / memory case:
0.1489 → 0.2979

Mean returned:
0.92 → 1.06
```

也就是说：

> Temperature 确实放宽了后段 competition，但放出来的是额外 context / noise，而不是缺失 gold。

初步结论：

```text
BEST_PARETO_CANDIDATE:
NONE

RECOMMENDATION:
NEEDS_MORE_RESEARCH
```

当时没有冻结新的 T。

---

# 21. 一个非常重要的实验教训：先确认 Intervention 是否生效

Temperature sweep 后，继续做只读 failure trace。

第一步就发现：

```text
DEV MULTI_UNIT:
9 cases

9 / 9:
decompositionReason = no-explicit-separator

9 / 9:
aspectCount = 1
```

即：

> `explicit-clauses` 在真实 DEV 上根本没有触发。

因此此前：

```text
whole-query T=1
vs
explicit-clauses T=1
```

实际上不是有效的 decomposition A/B。

两边都退化成：

```text
whole-query
```

这一点是本阶段最重要的实验方法论教训之一：

> **在做参数 sweep 前，必须先验证被测试的新机制是否实际被触发。**

未来任何机制实验都应先输出：

```text
trigger rate
branch count
activation distribution
fallback reason distribution
```

否则可能出现：

```text
实验跑完了
↓
指标没变化
↓
后来才发现新路径根本没执行
```

---

# 22. DEV MULTI_UNIT Aspect Extraction Failure Diagnosis

DEV 中：

```text
MULTI_UNIT cases = 9
intended aspects = 24
detected aspects = 9
```

实际结构：

```text
three_aspects:
6 cases

two_aspects:
3 cases
```

但全部被检测为：

```text
1 whole-query aspect
```

共同 fallback：

```text
no-explicit-separator
```

---

# 23. 真实 Query Pattern

9/9 MULTI_UNIT 都不是：

```text
A ; B ; C
```

而是：

```text
关于<subject>，记忆中提到
“aspect A”、
“aspect B”、
“aspect C”
的相关内容有哪些？
```

实际分隔边界：

```text
”、“
```

而旧 splitter 只认识：

```text
;
；
以及
另外
```

因此 local aspect scoring 从未运行。

---

# 24. 9 个真实 DEV MULTI_UNIT Queries

## bench_036_multi_unit

Subject：

```text
KC
```

Query：

> 关于KC，记忆中提到“许多针对丰川祥子的指责源于网络用户过度代入角色、迁怒于不顺从自己的其他角色”、“认为奶龙很可爱”、“认为部分富人通过走关系、缺乏能力却赚取大量财富”的相关内容有哪些？

应拆：

```text
1. 许多针对丰川祥子的指责源于网络用户过度代入角色、迁怒于不顺从自己的其他角色
2. 认为奶龙很可爱
3. 认为部分富人通过走关系、缺乏能力却赚取大量财富
```

---

## bench_037_multi_unit

Subject：

```text
柒糖
```

Query：

> 关于柒糖，记忆中提到“不喜欢奶龙表情包”、“认为盗版龙泡泡在淘宝和拼多多上便宜”的相关内容有哪些？

应拆：

```text
1. 不喜欢奶龙表情包
2. 认为盗版龙泡泡在淘宝和拼多多上便宜
```

---

## bench_038_multi_unit

Subject：

```text
NICEICK
```

Query：

> 关于NICEICK，记忆中提到“喜欢或愿意推荐《世界计划》歌曲《Flyway》”、“喜欢打舞萌（maimai）”、“喜欢或关注阳炎相关音乐”的相关内容有哪些？

应拆：

```text
1. 喜欢或愿意推荐《世界计划》歌曲《Flyway》
2. 喜欢打舞萌（maimai）
3. 喜欢或关注阳炎相关音乐
```

---

## bench_039_multi_unit

Subject：

```text
小田
```

Query：

> 关于小田，记忆中提到“喜欢《魔女之旅》角色伊蕾娜”、“喜欢《原神》中的雷电将军”的相关内容有哪些？

应拆：

```text
1. 喜欢《魔女之旅》角色伊蕾娜
2. 喜欢《原神》中的雷电将军
```

---

## bench_040_multi_unit

Subject：

```text
long_Z
```

Query：

> 关于long_Z，记忆中提到“不喜欢一大段连续文字”、“在与笔记相关的话题后曾持续情绪低落”、“认为助手在私聊场景完成度较高”的相关内容有哪些？

应拆：

```text
1. 不喜欢一大段连续文字
2. 在与笔记相关的话题后曾持续情绪低落
3. 认为助手在私聊场景完成度较高
```

---

## bench_041_multi_unit

Subject：

```text
小瑾
```

Query：

> 关于小瑾，记忆中提到“在玩《星露谷物语》”、“有对象”、“在玩《原神》”的相关内容有哪些？

应拆：

```text
1. 在玩《星露谷物语》
2. 有对象
3. 在玩《原神》
```

---

## bench_042_multi_unit

Subject：

```text
助手
```

Query：

> 关于助手，记忆中提到“喜欢《Project Sekai》中的角色星乃一歌”、“认为《若陀龙王战曲》是原神最好的曲子”、“认为BanG Dream”的相关内容有哪些？

应拆：

```text
1. 喜欢《Project Sekai》中的角色星乃一歌
2. 认为《若陀龙王战曲》是原神最好的曲子
3. 认为BanG Dream
```

---

## bench_043_multi_unit

Subject：

```text
3496983886
```

Query：

> 关于3496983886，记忆中提到“是大一新生”、“在玩《我的世界》时会出现3D眩晕”的相关内容有哪些？

应拆：

```text
1. 是大一新生
2. 在玩《我的世界》时会出现3D眩晕
```

---

## bench_044_multi_unit

Subject：

```text
Kc
```

Query：

> 关于Kc，记忆中提到“认为崔健的音乐在其听歌范围内挺原创的”、“认为针对丰川祥子的许多指责源于网络用户过度代入和迁怒”、“在准备法考”的相关内容有哪些？

应拆：

```text
1. 认为崔健的音乐在其听歌范围内挺原创的
2. 认为针对丰川祥子的许多指责源于网络用户过度代入和迁怒
3. 在准备法考
```

---

# 25. Aspect Extraction Failure Taxonomy

| Failure class | Cases | 说明 |
|---|---:|---|
| NO_DECOMPOSITION / NO_RECOGNIZED_SEPARATOR | 9/9 | splitter 没有识别到可用边界 |
| QUOTED_CLAUSE_DELIMITER_UNRECOGNIZED | 9/9 | 未识别 `”、“` |
| WHOLE_QUERY_FALLBACK | 9/9 | 全部回退为整句 |
| ASPECT_COUNT_UNDERSEGMENTED | 9/9 | 真实 2–3 aspects，检测为 1 |
| SUBJECT_SCOPE_IN_WRAPPER | 9/9 | subject 只出现在 `关于<subject>` wrapper |
| QUERY_WRAPPER_PRESENT | 9/9 | 共同 wrapper pattern |
| BAD_ASPECT_SPLIT | 0/9 | 不是拆错，而是完全没拆 |

对 24 个 expected Unit 做 whole-query trace：

```text
COVERAGE_GATE:
17 / 24

RELATIVE_COMPETITION:
0 / 24 final failures

TYPE_HINT:
0 / 24

BUDGET:
0 / 24
```

这给出非常强的根因链：

```text
No decomposition
↓
whole-query coverage dilution
↓
expected Unit 在 coverage gate 被过滤
↓
根本进不到 relative competition
↓
Temperature 无法救回
```

---

# 26. 机制层重新分工

到这里，对 Recall pipeline 的认知变得清晰：

```text
Aspect Extraction
= 当前到底在回忆哪几件事 / “想什么”

Coverage / Eligibility Gates
= 每条记忆是否真的与某个 Recall Target 相关

Temperature
= 已经相关的候选之间允许“想多宽”

Emergence
= 最终哪些 Unit 进入 Working Context
```

因此：

> Temperature 不是错误的概念；只是它位于更后面的层，而当时系统失败在更上游。

---

# 27. Quoted-list Parser Fix

下一轮只允许修两个点：

```text
1. quoted-list extraction
2. wrapper subject inheritance
```

不允许改：

```text
scoring
coverage
minimum score
relative threshold
Temperature
budget
ranking
clean eligibility
benchmark gold
store
```

Temperature 固定：

```text
T = 1.0
```

---

# 28. Quoted-list Pattern

支持已观察到的真实结构：

```text
关于<subject>，记忆中提到
“aspect 1”、
“aspect 2”、
“aspect 3”
的相关内容有哪些？
```

要求：

```text
至少 2 个完整中文引号 clause
使用 `、` 连接
wrapper subject 可明确解析
aspectCount <= maxAspects
```

否则继续 fallback。

---

# 29. Parser Negative / Safety Conditions

不泛化成任意中文拆句器。

下列情况继续 fallback：

```text
只有一个 quoted clause
普通引号引用而非 list
引号未闭合
没有明确 wrapper subject
wrapper subject 与 subjectHints 冲突
超过 maxAspects
condition-dependent clause
```

目标：

> 只修 observed failure，不做 speculative parser expansion。

---

# 30. Quoted-list Fix DEV Re-test

本轮：

```text
DEV only
Recall-only
LLM calls = 0

TEST = NONE
Agent = NONE
Oracle = NONE
Judge = NONE
```

结果：

```text
DEV cases:
50

MULTI_UNIT:
9

quoted-list detected:
9 / 9

fallback:
0

intended aspects:
24

detected aspects:
24

subject inheritance failures:
0
```

Aspect Extraction 层从：

```text
9 detected / 24 intended
```

变成：

```text
24 / 24
```

---

# 31. Quoted-list Fix Recall Results

| Metric | Frozen improved baseline / pre-fix | Fixed quoted-list T=1 | Delta |
|---|---:|---:|---:|
| MULTI_UNIT expected-unit recall | 0.291667 | 1.000000 | +0.708333 |
| MULTI_UNIT exact core recall | 0 | 1.000000 | +1.000000 |
| Overall expected-unit recall | 0.685185 | 1.000000 | +0.314815 |
| Overall exact core recall | 0.769231 | 1.000000 | +0.230769 |
| Useful context rate | 0.844444 | 0.863636 | +0.019192 |
| Distractor rate | 0.022222 | 0 | -0.022222 |
| FP / memory case | 0.148936 | 0.191489 | +0.042553 |
| Negative rejection | 1.000000 | 1.000000 | 0 |
| No-memory rejection | 0.666667 | 0.666667 | 0 |
| Mean returned units | 0.92 | 1.34 | +0.42 |
| P95 returned units | 2 | 4 | +2 |
| Mean latency | 2.021 ms | 2.239 ms | +0.218 ms |
| P95 latency | 6.243 ms | 7.540 ms | +1.297 ms |

---

# 32. Category Guardrails After Fix

| Category | Expected Recall | Exact Core | Useful Context |
|---|---:|---:|---:|
| DIRECT | 1.0 | 1.0 | 0.900 |
| MULTI_UNIT | 1.0 | 1.0 | 0.838710 |
| ALIAS | 1.0 | 1.0 | 1.000 |
| TEMPORAL | 1.0 | 1.0 | 0.714286 |
| NEGATION | 1.0 | 1.0 | 1.000 |
| DISTRACTOR_HEAVY | 1.0 | 1.0 | 0.857143 |

Negative：

```text
DIRTY_OR_AMBIGUOUS rejection:
1.0

INSUFFICIENT_MEMORY rejection:
1.0
```

---

# 33. MULTI_UNIT Raw Count Interpretation

修复前：

```text
expected hits:
7 / 24
```

修复后：

```text
expected hits:
24 / 24
```

新增：

```text
+17 expected hits
```

MULTI_UNIT true FP：

```text
baseline:
3

fixed:
5
```

新增：

```text
+2 true FP
```

因此不是：

```text
为了多找 17 条 expected
顺便塞几十条 context
```

而是：

```text
+17 expected
+2 true FP
```

这说明增益主要来自：

> **恢复了缺失的 Recall Structure。**

而不是粗暴放宽阈值。

---

# 34. MULTI_UNIT Per-case Returned-unit Audit

9 个 MULTI case：

```text
expected units = 24
returned units = 31
useful units   = 26
true FP        = 5
```

逐 case：

```text
bench_036   expected 3 → returned 3   FP 0

bench_037   expected 2 → returned 4
            1 acceptable + 1 true FP

bench_038   expected 3 → returned 4
            1 true FP

bench_039   expected 2 → returned 3
            1 true FP

bench_040   expected 3 → returned 3
            FP 0

bench_041   expected 3 → returned 4
            1 acceptable + 0 true FP

bench_042   expected 3 → returned 3
            FP 0

bench_043   expected 2 → returned 2
            FP 0

bench_044   expected 3 → returned 5
            2 true FP
```

这也暴露出一个未来问题：

> 每个 aspect 独立 emergence 后，supporting context 可能逐 aspect 累积。

但当前阶段没有继续用 DEV 修这个问题。

---

# 35. Fixed Candidate Identity

修复后：

```text
provider:
multi-emergence-recall

config:
0.1.0-candidate + quoted-list extraction

temperature:
1.0

intentMode:
explicit-clauses

fingerprint:
c12b77f43b5a4285ce78b25aa1e86c5a666f00c5dcf6e6e8b6fbe0b5f2d7d82c

source SHA256:
4ae9cae5897054da271a6111ea15e3cb0197e221bbd8ed59a20b1ff5aef657fc
```

Baseline 仍然：

```text
035bb4f78f6031a7fb99d2625d42bc0874f8f6c02101128e451d5a2238da4659
```

---

# 36. Parser Fix Tests

修复后 focused test file：

```text
20 tests
PASS
```

全套：

```text
7 test files
48 tests
PASS
```

Build：

```text
npm run build
PASS
```

---

# 37. 测试所覆盖的关键 Contract

测试并非直接硬编码 DEV gold。

Synthetic / contract tests 覆盖：

```text
1. whole-query coverage failure 在 T=20 下仍救不回来

2. multi-aspect local scoring 能找回三个独立 target

3. whole-query T=1 与 improved-recall IDs / scores 完全兼容

4. 默认 single-intent 行为保持兼容

5. Temperature 只作用于 eligibility 之后

6. 一个 aspect 不能先吃光 budget

7. Unit ID dedup

8. caller limit > 8 时仍 cap 到 8

9. 多主体 aspect 不泄漏 subject state

10. 普通 “和” 复合话题不随意拆

11. ambiguous / excessive / empty aspect fail closed

12. subject 名字内含 separator 时不误拆

13. 高温不 pad unknown memory

14. invalid Temperature / invalid limit fail closed

15. quoted-list 2/3 aspects

16. wrapper subject inheritance

17. nested 《title》 brackets

18. Latin / numeric subject

19. KC / Kc normalization

20. malformed quote / missing wrapper / condition / maxAspects / subject mismatch fallback
```

---

# 38. 对 runner / report 的代码审计

在阶段末对实际：

```text
run-quoted-list-fix-dev.ts
multi-emergence-recall.test.ts
```

进行了只读检查。

整体实验结构可信：

```text
benchmark SHA hard assert
store SHA hard assert

dataset.version == 0.2.0
dataset.frozen == true

DEV == 50
MULTI == 9

baseline 本轮重跑
fixed candidate 本轮重跑

Temperature == 1
intentMode == explicit-clauses

无 Agent / Judge / LLM 调用
```

---

# 39. runner 审计发现的小问题

这些不是当前结果的 blocker，但应记录。

## 39.1 Subject inheritance validation 不够严格

当前 runner 的 `subjectInheritanceFailures` 更接近检查：

```text
所有 aspect subjects
是否彼此一致
```

而不是严格检查：

```text
aspect subject
==
wrapper regex 捕获出的 subject
```

因此理论上：

```text
关于KC
```

如果全部错误继承为同一个其他 subject，也可能被 runner 的这一项漏掉。

好消息：

> focused tests 对 NICEICK / numeric / Kc 等 literal subject 做了预期验证，所以不是完全无覆盖。

未来 runner 应直接比较 normalized wrapper subject。

---

## 39.2 Remaining failure taxonomy 没真正细分

runner 输出 taxonomy：

```text
ASPECT_EXTRACTION
SUBJECT_GATE
COVERAGE_GATE
ABSOLUTE_SCORE
RELATIVE_COMPETITION
TYPE_HINT
BUDGET
OTHER
```

但当前代码对 remaining miss 实际只做：

```text
if decomposition != quoted-list:
    ASPECT_EXTRACTION
else:
    OTHER
```

并没有真正追踪全部内部 rejection stage。

这次：

```text
remaining failures = []
```

所以所有 count=0 并不影响结论。

但以后若有 miss：

> 不能直接把这些 0 当成完整 stage trace，除非接入真实 diagnostics。

---

## 39.3 Markdown 表头小问题

报告表头：

```text
Fallback
```

实际填的是：

```text
decompositionReason
```

所以成功 case 可能显示：

```text
Fallback = quoted-list
```

正确命名应为：

```text
Decomposition reason
```

这是展示问题，不影响实验结果。

---

## 39.4 Historical pre-fix artifact provenance

runner 读取历史：

```text
multi-emergence-dev-sweep/sweep-summary.json
```

作为 pre-fix control。

代码验证对应 config 存在，但当前 runner 没重新 assert 历史 sweep artifact 本身的：

```text
benchmark fingerprint
store fingerprint
candidate fingerprint
```

当前实验整体 provenance 已知一致，但未来正式化可以补 hard assert。

---

# 40. Recall Temperature 最终阶段结论

当前不能说：

```text
Temperature 无意义
```

正确说法是：

> **Temperature 没有解决当前被观察到的 MULTI_UNIT failure。**

本轮实验说明：

```text
Aspect Extraction
= 首要问题

Temperature
= 后段 breadth control
```

当前冻结：

```text
T = 1.0
```

没有证据支持：

```text
T > 1
```

作为新的 operating point。

未来如果有：

```text
自然 multi-aspect 已正确 decomposition
+
候选已经通过 gates
+
仍存在次强 genuine memory 被 relative competition 压掉
```

才值得重新研究 Temperature。

---

# 41. 当前 Recall P0 核心结论

## 41.1 强 baseline 已建立

`improved-recall` 已经是：

```text
强 lexical / structured baseline
```

不是简单 Top-K。

它具有：

```text
dynamic return count
subject gate
topic gate
absolute floor
relative filtering
negative rejection
low FP
```

---

## 41.2 Multi-Unit 不应只做 whole-query scoring

如果：

```text
Query = A + B + C
```

每个 Cognitive Unit 只对应其中一个目标，则：

```text
whole-query coverage
```

会天然稀释局部 evidence。

因此：

> **Multi-Unit Recall 需要显式表示多个 Recall Targets。**

---

## 41.3 Aspect Extraction 与 Temperature 是不同层

```text
Aspect Extraction
= 想什么

Temperature
= 想多宽
```

当前失败曾发生在：

```text
“想什么”
```

还没正确表达的阶段。

---

## 41.4 Multi-emergence 的核心不是“多返回”

核心是：

> **多个独立 target 各自获得一次 relevance competition 的资格。**

这不同于：

```text
Top-8
```

也不同于：

```text
降低全局 threshold
```

---

## 41.5 当前 quoted-list parser 只是窄验证

它证明：

> 当 Recall Target 正确拆分时，现有 gates 足以在当前 DEV 的 9 个 MULTI_UNIT / 24 个 expected Unit 上实现完整 Recall。

它没有证明：

```text
任意自然语言 multi-intent
都能被正确拆分
```

---

# 42. 当前已知限制

必须保留：

```text
1. quoted-list parser 是窄规则。

2. 没有显式 quoted-list 的自然 multi-goal query 仍可能 under-segment。

3. T > 1 当前只增加 context/noise，没有 Recall 增益证据。

4. multi-aspect 会增加 supporting context / FP。

5. budget 不足时，aspect ordering 仍可能影响结果。

6. 当前 Store 约千级 Cognitive Units，未做百万级规模验证。

7. 当前 provider 仍是 lexical / structured provider，不是最终 Associative Attention。

8. v0.2 TEST 已经被使用过，不能用于未来新 candidate 的 unseen holdout 声明。

9. NO_MEMORY_NEEDED rejection 仍有历史 baseline 问题。

10. Recall miss 不能被 Agent 解释为 Memory Store 中事实不存在。

11. Parser fix DEV = 1.0 不能解释成“Memory SOTA 已完成”。

12. 新的 natural multi-aspect generalization 需要新的 unseen evaluation。
```

---

# 43. 实验方法论：这一阶段真正学到的东西

## 43.1 不要先调参数，先验证路径

本轮最典型的坑：

```text
设计 multi-emergence
↓
跑 Temperature sweep
↓
结果完全不提升
↓
后来才发现 9/9 DEV case 根本没触发 decomposition
```

以后任何新机制实验，先做：

```text
Trigger-rate Audit
```

例如：

```text
多少 case 进入新 branch？
多少 fallback？
状态分布是什么？
```

---

## 43.2 先做局部函数实验，再烧模型

Temperature：

```text
300 local recall calls
0 LLM calls
```

这比：

```text
Agent × 300
```

便宜几个数量级。

原则：

> **能在 MemoryProvider 层回答的问题，不要先跑 Agent。**

---

## 43.3 一个实验只改一层

Parser Fix 时严格不改：

```text
coverage
scoring
Temperature
threshold
budget
```

因此：

```text
MULTI 0.2917 → 1.0
```

可以明确归因于：

```text
Aspect Extraction
```

这是非常重要的实验可解释性。

---

## 43.4 负结果很值钱

Temperature sweep 看起来“失败”：

```text
Recall 不涨
Noise 上升
```

但正是它帮助否定了：

```text
“只是 relative competition 太尖”
```

这个错误假设。

因此：

> **没有提升的实验，只要设计得可证伪，就是有效实验。**

---

## 43.5 Gold Recall 与 Context Utility 必须分开

`lexical-top8`：

```text
Recall 100%
```

但：

```text
FP rate 73.9%
```

说明：

> 单看 Recall 可以鼓励错误架构。

因此 Recall 系统至少要同时看：

```text
Core recall
Useful context
Distractor rate
FP / case
Negative rejection
Returned count
Latency
```

---

## 43.6 Agent / Recall / Oracle 必须分层

如果只有 E2E：

```text
Answer 错了
```

无法知道到底是：

```text
Tool Decision
Recall
Answer use
Hallucination
```

三层 benchmark 证明非常有价值：

```text
Recall-only
Agent
Oracle
```

---

## 43.7 TEST 看过以后就不再是 unseen

虽然 benchmark v0.2.0 本身仍然 frozen，但现在：

```text
我们已经知道它的 failure shape
```

甚至针对 MULTI_UNIT failure 做了新算法。

因此：

> 新 `multi-emergence` 以后如果跑 v0.2 TEST，只能称 historical regression / diagnostic evaluation。

不能再称：

```text
unseen holdout final
```

---

# 44. Astra / Luna / Codex 的实际分工经验

这一阶段形成了很实用的分工。

## Astra

用于：

```text
hard architecture diagnosis
mechanism redesign
root-cause reasoning
```

典型贡献：

```text
发现 Temperature 不是全部问题
发现 whole-query coverage gate 更早过滤
设计 multi-emergence candidate
```

---

## Luna

适合：

```text
本地 sweep
failure tracing
统计
窄 parser fix
DEV recall-only 验证
```

但本轮也暴露出：

> Routine agent 在执行 sweep 前也必须先做机制 activation audit。

---

## Codex / scripts

适合：

```text
deterministic runner
parallel benchmark
artifact persistence
hash verification
freeze / archive
```

原则：

> **强模型用于改变思路；脚本用于重复实验；低成本模型用于机械分析。**

---

# 45. Recall P0 当前冻结状态

当前决定：

```text
Recall P0
→ 告一段落
```

冻结对象：

### Baseline

```text
improved-recall
1.0.0-final-candidate
fingerprint:
035bb4f78f6031a7fb99d2625d42bc0874f8f6c02101128e451d5a2238da4659
```

### Candidate

```text
multi-emergence-recall
0.1.0-candidate + quoted-list extraction
T = 1.0

fingerprint:
c12b77f43b5a4285ce78b25aa1e86c5a666f00c5dcf6e6e8b6fbe0b5f2d7d82c

source SHA:
4ae9cae5897054da271a6111ea15e3cb0197e221bbd8ed59a20b1ff5aef657fc
```

### Benchmark

```text
v0.2.0 frozen

SHA:
14be135076979992d9043553585f9f2290c6155937b3cba56dff5b24ce228ca9
```

### Store

```text
SHA:
92f5b405b10f00ba82c05f5f8197fc277966853d70499cbcd949d3ece7e34ef8
```

---

# 46. Freeze & Archive 状态

已经编写并交给 Codex：

```text
Recall P0 Freeze & Archive Spec
```

目标归档：

```text
archive/
└── recall-p0-2026-09-22/
```

包括：

```text
code
configs
tests
scripts
frozen evidence
temperature findings
multi-unit root cause
quoted-list evidence
manifest
checksums
stage summary
next-stage boundary
```

同时生成：

```text
recall-p0-2026-09-22.zip
```

截至本备忘录截点：

> Freeze / Archive Spec 已发出；本备忘录不假定 Codex 已完成最终归档执行，最终 archive manifest / zip 应以 Codex 后续交付为准。

---

# 47. 下一阶段边界

当前不继续：

```text
Temperature 调参
coverage 调参
threshold 调参
parser 无限加规则
继续用当前 DEV 打磨
重新跑旧 TEST 做“新 final”
```

下一阶段可以任选：

```text
A. 新 unseen natural multi-aspect evaluation

B. generalized aspect extraction

C. Associative Attention MemoryProvider

D. Ambient Recall integration

E. Dream / write-side consolidation
```

但这些都属于：

```text
Recall P1 / Memory system next stage
```

而不是 Recall P0。

---

# 48. 与更大 Memory 架构的连接

当前 Recall P0 本质上仍是工程 baseline。

最终架构方向仍然是：

```text
Long-term Memory
      │
Current Conversation
      ↓
Ambient Recall
      ↓
Memory Emergence
      ↓
bounded Cognitive Units
      ↓
LLM Working Context
      ↓
LLM
      │
      └── insufficient → Deep Recall Tool
```

未来 Associative Attention 需要挑战的 baseline，不应再是：

```text
lexical-top8
```

而应该是：

```text
improved-recall
+
multi-emergence behavior
```

因为只有挑战强 baseline，才能证明：

> Attention Diffusion / Associative Recall 本身真的带来结构性收益。

---

# 49. 本阶段最终研究结论

本阶段最初的问题看起来是：

```text
Recall 太保守
```

随后怀疑：

```text
relative threshold 太高
```

再提出：

```text
Recall Temperature
```

但实验逐层证明：

```text
不是单纯 Temperature
不是单纯 relative competition
不是预算不足
不是 LLM 不会使用 memory
```

最终定位：

```text
Multi-Unit Query
↓
Recall Targets 未被正确表达
↓
whole-query coverage 被稀释
↓
expected Unit 在 eligibility gate 前后过早消失
```

修复：

```text
Query
↓
Aspect Extraction
↓
A / B / C independent recall targets
↓
各自 relevance gates
↓
Multi-Emergence
↓
bounded merge
```

DEV：

```text
MULTI expected recall:
0.291667 → 1.000000

MULTI exact:
0 → 1.000000

expected hits:
7 / 24 → 24 / 24

additional expected hits:
+17

additional true FP:
+2
```

因此这一阶段最值得保留的一句话是：

> **Multi-Unit Recall 的核心不是把 Recall 放得更宽，而是先正确表达“当前到底有哪几件事值得被独立想起来”。**

以及：

> **Aspect Extraction 决定“想什么”；Temperature 决定“想多宽”；Emergence 决定“什么最终进入工作上下文”。**

---

# 50. 一页数据总览

## Frozen Benchmark

```text
v0.2.0
200 cases
DEV 50
TEST 150

benchmark SHA:
14be135076979992d9043553585f9f2290c6155937b3cba56dff5b24ce228ca9

store SHA:
92f5b405b10f00ba82c05f5f8197fc277966853d70499cbcd949d3ece7e34ef8
```

## Final improved-recall TEST

```text
Expected Recall         72.73%
Exact Core              77.59%
Useful Context          85.19%
FP Rate                 14.81%
FP / case               0.145
Negative Rejection      100%
Mean Returned           0.913
Mean Latency            1.40 ms
```

## Agent

```text
Tool F1                 98.53%
Fact Accuracy           60.00%
Unsupported Claims      31.68%
E2E Success             61.33%
```

## Oracle

```text
Fact Accuracy           97.39%
Unsupported Claims      10.26%
E2E Success             87.33%
```

## Temperature DEV Sweep

```text
T:
1.0 / 1.3 / 1.6 / 2.0

MULTI recall:
全部 29.17%

Useful context:
84.44% → 73.08%

FP / memory case:
0.149 → 0.298
```

## Aspect Diagnosis

```text
MULTI cases:
9

intended aspects:
24

before detected:
9

quoted-list triggered:
0 / 9
```

## Parser Fix DEV

```text
quoted-list:
9 / 9

aspects:
24 / 24

MULTI expected recall:
100%

MULTI exact:
100%

overall expected recall:
100%

overall exact:
100%

negative rejection:
100%

mean returned:
1.34

p95 returned:
4

mean latency:
2.239 ms
```

## Frozen Candidate

```text
multi-emergence-recall
T = 1.0

fingerprint:
c12b77f43b5a4285ce78b25aa1e86c5a666f00c5dcf6e6e8b6fbe0b5f2d7d82c

source SHA:
4ae9cae5897054da271a6111ea15e3cb0197e221bbd8ed59a20b1ff5aef657fc
```

---

# 51. 最终状态

```text
RECALL P0:
FROZEN IN DESIGN / FREEZE DECISION

BASELINE:
FROZEN

MULTI-EMERGENCE:
DEV VALIDATED

QUOTED-LIST PARSER:
FREEZE_PARSER

TEMPERATURE:
T = 1.0
NO WINNING >1 PARETO POINT

OLD TEST:
HISTORICAL / SEEN
NOT FUTURE UNSEEN HOLDOUT

NEXT:
DEFERRED
```

本阶段到此结束。

后续 Recall 工作不应继续无边界地打磨本 P0，而应从新的实验问题重新立项。
