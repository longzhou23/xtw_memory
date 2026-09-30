# Codex Spec — LLM Memory Benchmark P0

**Project:** 小天文 Memory  
**Version:** `0.1.0-memory-benchmark`  
**Status:** IMPLEMENTATION SPEC  
**Target:** current working LLM Memory Tool Demo  
**Scope:** benchmark only; do not redesign the demo or memory architecture

---

# 0. Benchmark 目标

当前 Demo 已经能够：

```text
User
→ LLM
→ memory_recall Tool
→ MemoryProvider
→ Cognitive Units
→ LLM
→ Final Answer
```

本 Benchmark 的目标不是测 UI，而是回答三个独立问题：

```text
1. Tool Decision
   LLM 知不知道什么时候应该调用 Memory？

2. Recall Quality
   MemoryProvider 能不能召回正确 Cognitive Units，
   同时少带无关内容？

3. Memory Use
   LLM 拿到正确 Memory 后，能不能正确使用，
   不 hallucinate、不丢否定、不乱补事实？
```

必须能区分：

```text
Recall 错
vs
LLM 使用 Memory 错
vs
LLM 根本没调用 Memory
```

---

# 1. Benchmark 不允许修改生产逻辑

本任务只增加：

```text
benchmark dataset
benchmark runner
metrics
reports
optional benchmark UI page
```

禁止：

```text
修改 MemoryProvider 算法
调 Recall threshold
修改 System Prompt
修改 Cognitive Units
重新清洗数据
修改 Tool Schema
修改 demo case 以让结果变好
```

如果 Benchmark 暴露问题：

```text
先记录
不要边跑边改
```

---

# 2. Benchmark 三种运行模式

必须实现：

```text
A. Recall-only Benchmark
B. Agent End-to-End Benchmark
C. Oracle Memory Benchmark
```

---

# 3. A — Recall-only Benchmark

输入：

```text
benchmark query
```

直接调用：

```ts
MemoryProvider.recall(...)
```

不调用 LLM。

流程：

```text
Query
↓
MemoryProvider
↓
Returned Cognitive Units
↓
Compare with gold annotations
```

目的：

> 单独测 Recall Backend。

---

# 4. B — Agent End-to-End Benchmark

流程：

```text
User Message
↓
LLM
↓
tool decision
↓
memory_recall
↓
MemoryProvider
↓
LLM
↓
Final Answer
```

测：

```text
是否调用 Memory
Tool 参数
Recall 结果
最终回答
unsupported claims
abstention
```

---

# 5. C — Oracle Memory Benchmark

完全绕过 MemoryProvider。

将人工 gold Cognitive Units 直接作为：

```text
memory_recall Tool Result
```

提供给 LLM。

流程：

```text
User Query
↓
LLM / forced tool path
↓
Gold expected Units
↓
LLM
↓
Final Answer
```

Oracle 模式的作用：

```text
Normal FAIL
Oracle PASS
→ Recall Provider 问题

Normal FAIL
Oracle FAIL
→ LLM 使用 Memory / Prompt 问题

Normal PASS
Oracle PASS
→ 正常

Normal PASS
Oracle FAIL
→ benchmark/oracle pipeline 有问题，报警
```

---

# 6. Benchmark Case Schema

创建：

```text
data/benchmark/memory_benchmark_v0.1.json
```

Schema：

```ts
export type BenchmarkCategory =
  | 'DIRECT'
  | 'MULTI_UNIT'
  | 'ALIAS'
  | 'TEMPORAL'
  | 'NEGATION'
  | 'DISTRACTOR_HEAVY'
  | 'DIRTY_OR_AMBIGUOUS'
  | 'INSUFFICIENT_MEMORY'
  | 'NO_MEMORY_NEEDED';

export type BenchmarkDifficulty =
  | 'EASY'
  | 'MEDIUM'
  | 'HARD';

export interface MemoryBenchmarkCase {
  id: string;

  split:
    | 'DEV'
    | 'TEST';

  category: BenchmarkCategory;
  difficulty: BenchmarkDifficulty;

  userMessage: string;

  requiresMemory: boolean;

  recall?: {
    query?: string;

    subjectHints?: string[];
    typeHints?: string[];

    expectedUnitIds: string[];
    acceptableUnitIds?: string[];
    distractorUnitIds?: string[];
  };

  answer: {
    expectedFacts: string[];
    acceptableFacts?: string[];
    forbiddenFacts?: string[];

    shouldAbstain?: boolean;
  };

  notes?: string;
}
```

---

# 7. Case 示例：Direct Recall

```json
{
  "id": "bench_direct_niceick_games",
  "split": "TEST",
  "category": "DIRECT",
  "difficulty": "EASY",

  "userMessage": "NICEICK 平时玩什么？",

  "requiresMemory": true,

  "recall": {
    "expectedUnitIds": [
      "cu_niceick_maimai",
      "cu_niceick_pjsk"
    ],
    "acceptableUnitIds": [],
    "distractorUnitIds": [
      "cu_niceick_bw_photo",
      "cu_niceick_headphone_fit"
    ]
  },

  "answer": {
    "expectedFacts": [
      "NICEICK 玩 maimai",
      "NICEICK 玩 Project Sekai"
    ],
    "forbiddenFacts": [],
    "shouldAbstain": false
  }
}
```

---

# 8. Case 示例：Negation

```json
{
  "id": "bench_negation_niceick_bw",
  "split": "TEST",
  "category": "NEGATION",
  "difficulty": "EASY",

  "userMessage": "NICEICK 喜欢拍黑白照片吗？",

  "requiresMemory": true,

  "recall": {
    "expectedUnitIds": [
      "cu_niceick_dislikes_bw"
    ]
  },

  "answer": {
    "expectedFacts": [
      "NICEICK 不喜欢拍黑白照片"
    ],
    "forbiddenFacts": [
      "NICEICK 喜欢拍黑白照片"
    ],
    "shouldAbstain": false
  }
}
```

---

# 9. Case 示例：Multi-unit

```json
{
  "id": "bench_multi_amaryllis",
  "split": "TEST",
  "category": "MULTI_UNIT",
  "difficulty": "MEDIUM",

  "userMessage": "Amaryllis 现在记忆里在哪？开学后怎么上学？",

  "requiresMemory": true,

  "recall": {
    "expectedUnitIds": [
      "cu_amaryllis_xuhui",
      "cu_amaryllis_not_school",
      "cu_amaryllis_commuting"
    ]
  },

  "answer": {
    "expectedFacts": [
      "Amaryllis 在上海徐汇",
      "Amaryllis 不在学校",
      "Amaryllis 开学后走读"
    ],
    "shouldAbstain": false
  }
}
```

---

# 10. Case 示例：Insufficient Memory

```json
{
  "id": "bench_unknown_restaurant",
  "split": "TEST",
  "category": "INSUFFICIENT_MEMORY",
  "difficulty": "EASY",

  "userMessage": "NICEICK 最喜欢哪家餐厅？",

  "requiresMemory": true,

  "recall": {
    "expectedUnitIds": [],
    "acceptableUnitIds": []
  },

  "answer": {
    "expectedFacts": [],
    "forbiddenFacts": [
      "任何具体餐厅名称"
    ],
    "shouldAbstain": true
  }
}
```

---

# 11. Case 示例：No Memory Needed

```json
{
  "id": "bench_general_meteor",
  "split": "TEST",
  "category": "NO_MEMORY_NEEDED",
  "difficulty": "EASY",

  "userMessage": "什么是流星雨？",

  "requiresMemory": false,

  "answer": {
    "expectedFacts": [],
    "forbiddenFacts": [],
    "shouldAbstain": false
  }
}
```

---

# 12. Benchmark 规模

P0 目标：

```text
200 cases
```

推荐分布：

```text
DIRECT                    35
MULTI_UNIT                35
ALIAS                     25
TEMPORAL                  20
NEGATION                  20
DISTRACTOR_HEAVY          20
DIRTY_OR_AMBIGUOUS        15
INSUFFICIENT_MEMORY       15
NO_MEMORY_NEEDED          15
----------------------------
TOTAL                    200
```

---

# 13. DEV / TEST 切分

固定：

```text
DEV   = 50 cases
TEST  = 150 cases
```

DEV 可以用于：

```text
debug runner
debug scoring
验证 case 标注
将来调 provider 参数
```

TEST 不允许用于调参。

---

# 14. TEST Freeze

一旦：

```text
memory_benchmark_v0.1.json
```

被标记：

```text
frozen = true
```

禁止：

```text
因为某 Provider 表现差而修改 expectedUnitIds
删除失败 case
降低难度
修改 query
修改 forbidden facts
```

如果发现标注确实错误：

```text
记录 benchmark annotation bug
升级 dataset version
例如 v0.1 → v0.2
```

不得静默修改。

---

# 15. Case 生成原则

Benchmark query 必须来自：

```text
已经存在的 Cognitive Units
```

但不能简单把 Unit 文本原封不动改成问句。

要覆盖：

```text
自然表达
别名
省略
多目标查询
否定问法
模糊但可回答的问题
近似同义表达
```

---

# 16. Recall-only Metrics

必须输出以下指标。

---

# 17. Expected Unit Recall

对每个 case：

\[
Recall_c
=
\frac{
|Returned \cap Expected|
}{
|Expected|
}
\]

Dataset-level：

```text
micro recall
macro recall
```

都报告。

---

# 18. Exact Expected Recall Success

如果：

```text
所有 expected units 都成功返回
```

则：

```text
caseRecallSuccess = true
```

即：

\[
Expected \subseteq Returned
\]

报告：

```text
Exact Recall Success Rate
```

---

# 19. Precision

定义 useful units：

```text
Expected
∪
Acceptable
```

则：

\[
Precision_c
=
\frac{
|Returned \cap Useful|
}{
|Returned|
}
\]

如果 returned 为空：

```text
若 expected 也为空 → precision = 1
若 expected 非空 → precision = 0
```

---

# 20. Distractor Hit Rate

如果 case 有：

```text
distractorUnitIds
```

记录：

\[
DistractorHitRate
=
\frac{
召回到的 distractor 数
}{
标注 distractor 总数
}
\]

同时报告：

```text
cases with >=1 distractor
```

---

# 21. False Positive Per Case

定义：

```text
FP units =
Returned
-
Expected
-
Acceptable
```

报告：

```text
mean FP / case
median FP / case
p90 FP / case
```

---

# 22. Returned Unit Count

记录：

```text
mean
median
p90
max
```

原因：

> Recall 变高但一次返回 30 条 Memory，不一定更好。

---

# 23. Recall Latency

记录：

```text
p50
p90
p95
p99
max
```

单位：

```text
milliseconds
```

只计 MemoryProvider，不含 LLM。

---

# 24. Empty Recall

分别统计：

```text
expected non-empty but returned empty
expected empty and returned empty
```

前者是 miss。

后者可能是正确 abstention 支持。

---

# 25. Category Breakdown

所有 Recall Metrics 必须按：

```text
category
difficulty
split
```

分组输出。

例如：

```text
ALIAS Recall
NEGATION Recall
DISTRACTOR_HEAVY Precision
```

不能只给 overall。

---

# 26. Agent Tool Decision Metrics

对 End-to-End：

```text
requiresMemory = true
```

视为 positive。

模型实际：

```text
memoryCalls > 0
```

视为 predicted positive。

得到：

```text
TP
FP
TN
FN
```

计算：

```text
Tool Decision Precision
Tool Decision Recall
Tool Decision F1
Tool Decision Accuracy
```

---

# 27. Memory Call Count

报告：

```text
mean memory calls / case
p90
max
```

并记录：

```text
cases hitting MAX_TOOL_ROUNDS
```

避免模型变成：

```text
每个问题都调用 Memory 三次
```

---

# 28. Tool Query Quality

记录 LLM 实际生成的：

```text
query
subjectHints
typeHints
limit
```

至少保存 trace。

P0 不必对 query 做自动评分。

但报告：

```text
empty query count
invalid args count
```

---

# 29. Answer Fact Accuracy

对每个：

```text
expectedFacts
```

判断最终 answer 是否表达该事实。

P0 建议采用：

```text
LLM Judge
+
人工可复核 evidence
```

不要只做字符串完全匹配。

Judge 输入：

```text
User query
Expected Fact
Final Answer
```

Judge 输出：

```json
{
  "entailed": true,
  "contradicted": false,
  "missing": false
}
```

---

# 30. Judge 必须结构化

Judge schema：

```ts
interface FactJudgeResult {
  fact: string;

  status:
    | 'ENTAILED'
    | 'CONTRADICTED'
    | 'MISSING';

  evidenceQuote?: string;
}
```

Judge 不应知道 Provider 名称。

---

# 31. Forbidden Fact Violations

对于：

```text
forbiddenFacts
```

判断 Final Answer 是否表达了这些错误内容。

例如：

```text
Expected:
NICEICK 不喜欢黑白摄影

Forbidden:
NICEICK 喜欢黑白摄影
```

若命中：

```text
Forbidden Fact Violation
```

---

# 32. Unsupported Personal Fact Rate

这是最重要指标之一。

Final Answer 中所有：

```text
关于用户 / 记忆人物 / 项目历史的具体事实性断言
```

必须能够被：

```text
current conversation
OR
recalled Cognitive Units
```

支持。

如果没有支持：

```text
Unsupported Personal Claim
```

---

# 33. Unsupported Claim Judge

给 Judge：

```text
User query
Current chat context
Recalled units
Final answer
```

要求提取所有 personal/project claims，并判断：

```text
SUPPORTED
UNSUPPORTED
```

输出：

```json
{
  "claims": [
    {
      "text": "...",
      "status": "SUPPORTED",
      "supportingUnitIds": ["cu_x"]
    }
  ]
}
```

---

# 34. Unsupported Fact Rate

计算：

\[
UnsupportedClaimRate
=
\frac{
UNSUPPORTED claims
}{
all personal/project factual claims
}
\]

目标：

```text
尽可能接近 0
```

---

# 35. Abstention Accuracy

对：

```text
shouldAbstain = true
```

的 case：

正确行为应类似：

```text
Memory 中没有足够信息确认
无法从当前记忆判断
```

不是必须匹配固定句子。

Judge 判断：

```text
ABSTAINED
ANSWERED_WITH_CLAIM
```

计算：

```text
Abstention Accuracy
```

---

# 36. No-Memory-Needed Accuracy

对于：

```text
requiresMemory = false
```

报告：

```text
No-memory compliance rate
```

即：

```text
memoryCalls = 0
```

---

# 37. Oracle Benchmark Metrics

Oracle 模式至少报告：

```text
Oracle Answer Fact Accuracy
Oracle Forbidden Violation
Oracle Unsupported Claim Rate
Oracle Abstention Accuracy
```

不报告 Recall metrics，因为 gold memory 已直接提供。

---

# 38. Failure Attribution

每个 End-to-End case 自动归类：

```text
PASS

TOOL_DECISION_FAIL
RECALL_FAIL
ANSWER_USE_FAIL
HALLUCINATION_FAIL
ABSTENTION_FAIL
MULTIPLE_FAILURES
```

规则：

## TOOL_DECISION_FAIL

```text
requiresMemory=true
AND
memoryCalls=0
```

---

## RECALL_FAIL

```text
Memory called
AND
expectedUnitIds not sufficiently recalled
AND
Oracle mode passes
```

---

## ANSWER_USE_FAIL

```text
Expected units recalled
AND
final answer misses / contradicts expected facts
AND
Oracle also fails or normal tool results were sufficient
```

---

## HALLUCINATION_FAIL

```text
unsupported personal claim exists
OR
forbidden fact violation exists
```

---

## ABSTENTION_FAIL

```text
shouldAbstain=true
AND
model asserts unsupported answer
```

---

# 39. End-to-End Success

Case PASS only if：

```text
Tool decision correct
AND
required facts present
AND
no forbidden fact
AND
no unsupported personal claim
AND
abstention behavior correct
```

报告：

```text
E2E Success Rate
```

---

# 40. 不使用单一总分

禁止只输出：

```text
Memory Score = 87
```

Benchmark 必须保留多维结果。

核心至少：

```text
Recall Success
Recall Precision
False Positives
Tool Decision F1
Answer Fact Accuracy
Unsupported Claim Rate
Abstention Accuracy
E2E Success
Latency
```

---

# 41. Provider Comparison

Benchmark Runner 必须允许：

```bash
npm run bench -- --provider lexical
npm run bench -- --provider embedding
npm run bench -- --provider attention
```

当前若只有一个 provider：

```text
照样实现 provider 参数接口
```

未实现 provider 可返回明确：

```text
Provider not available
```

---

# 42. Provider 必须使用同一接口

```ts
interface MemoryProvider {
  readonly name: string;

  recall(
    request: MemoryRecallRequest
  ): Promise<MemoryRecallResult>;

  stats(): MemoryProviderStats;
}
```

Benchmark 不得针对某个 Provider 写特殊评分逻辑。

---

# 43. Provider Comparison 固定条件

未来比较：

```text
Lexical
Embedding
Attention Diffusion
```

必须固定：

```text
Cognitive Unit Store
Benchmark Cases
LLM Model
System Prompt
Tool Schema
Tool limit cap
Judge Model
TEST split
```

否则结果不可比较。

---

# 44. Attention Provider 的额外 diagnostics

未来 Attention Provider 可额外报告：

```text
activeFrontierPerStep
flowingEdgesPerStep
stepsToFirstExpectedEmergence
peakExpectedAttention
attentionEntropy
maxNodeAttention
attentionConservationError
```

这些是 diagnostics。

不能替代：

```text
Recall / Answer benchmark metrics
```

---

# 45. Benchmark Runner CLI

新增：

```text
scripts/run-memory-benchmark.ts
```

支持：

```bash
npm run bench
```

参数：

```text
--mode recall
--mode agent
--mode oracle
--mode all

--split dev
--split test
--split all

--provider <name>

--case <case-id>

--category <category>

--concurrency <n>

--output <dir>
```

---

# 46. 默认运行

推荐：

```bash
npm run bench -- \
  --mode all \
  --split test \
  --provider current \
  --concurrency 4
```

---

# 47. 单 case debug

必须支持：

```bash
npm run bench -- \
  --case bench_negation_niceick_bw \
  --mode all
```

打印：

```text
QUERY
TOOL CALL
RETURNED UNITS
EXPECTED UNITS
FINAL ANSWER
FACT JUDGMENT
ORACLE ANSWER
FAILURE ATTRIBUTION
```

这是调试最有用的模式。

---

# 48. Benchmark 输出目录

每次运行：

```text
benchmark-results/
└── 2026-09-22Txxxxxx/
    ├── summary.json
    ├── summary.md
    ├── cases.jsonl
    ├── failures.md
    ├── recall.csv
    └── config.json
```

---

# 49. config.json

必须记录：

```json
{
  "benchmarkVersion": "0.1.0",
  "benchmarkFileSha256": "...",

  "providerName": "...",
  "providerConfig": {},

  "llmModel": "...",
  "judgeModel": "...",

  "systemPromptSha256": "...",
  "toolSchemaSha256": "...",

  "split": "TEST",

  "timestamp": "..."
}
```

保证以后可复现。

---

# 50. cases.jsonl

每个 case 一行完整结果：

```json
{
  "caseId": "...",

  "recall": {
    "returnedUnitIds": [],
    "latencyMs": 0,
    "precision": 0,
    "recall": 0
  },

  "agent": {
    "memoryCalls": 0,
    "toolCalls": [],
    "answer": ""
  },

  "judge": {
    "facts": [],
    "unsupportedClaims": [],
    "abstained": false
  },

  "oracle": {
    "answer": "",
    "facts": []
  },

  "failure": "PASS"
}
```

---

# 51. summary.md

必须适合人直接阅读。

顶部：

```text
Memory Benchmark v0.1
Provider: CognitiveUnitMemoryProvider
Cases: 150 TEST
```

核心表：

```text
Recall Exact Success        84.7%
Expected Unit Recall        91.2%
Precision                   79.4%
False Positives / Case       0.63
Returned Units / Case        3.4
Recall p95                  18 ms

Tool Decision Precision     96.0%
Tool Decision Recall        92.3%
Tool Decision F1            94.1%

Answer Fact Accuracy        89.8%
Unsupported Claim Rate       1.2%
Abstention Accuracy         93.3%
E2E Success                 82.0%
```

---

# 52. Category 表

必须有：

```text
Category                  Cases   Recall   Precision   E2E
----------------------------------------------------------
DIRECT                    ...
MULTI_UNIT                ...
ALIAS                     ...
TEMPORAL                  ...
NEGATION                  ...
DISTRACTOR_HEAVY          ...
DIRTY_OR_AMBIGUOUS        ...
INSUFFICIENT_MEMORY       ...
NO_MEMORY_NEEDED          ...
```

---

# 53. failures.md

只列失败 case。

格式：

```text
## bench_xxx

Category:
NEGATION

Query:
...

Expected Units:
...

Returned Units:
...

Final Answer:
...

Oracle Answer:
...

Failure:
RECALL_FAIL

Reason:
Expected negative preference unit was not recalled.
```

---

# 54. Judge Model

允许单独配置：

```bash
BENCH_JUDGE_BASE_URL=
BENCH_JUDGE_API_KEY=
BENCH_JUDGE_MODEL=
```

Judge 和被测 Agent 可以是同一个模型，也可以不同。

但报告中必须记录。

---

# 55. Judge temperature

如果 provider 支持：

```text
temperature = 0
```

或最低可用值。

Judge 要尽量 deterministic。

---

# 56. Judge 不允许知道实验 Provider

Judge Prompt 里禁止出现：

```text
Lexical
Embedding
Attention
Provider name
```

避免评价偏差。

---

# 57. Judge Fail-closed

如果 Judge：

```text
invalid JSON
timeout
provider error
```

case 标记：

```text
JUDGE_ERROR
```

不要自动当 PASS。

---

# 58. Human Audit

P0 benchmark 第一次跑完后：

随机抽：

```text
20 PASS
20 FAIL
```

人工检查 Judge。

输出：

```text
benchmark-results/.../human_audit_sample.md
```

用于确认自动 Judge 没明显跑偏。

---

# 59. Benchmark 数据制作流程

不要让 LLM 自动生成 200 个 case 后直接冻结。

建议：

```text
Step 1
从 Cognitive Units 中抽候选 facts

Step 2
生成 query draft

Step 3
人工核对 expectedUnitIds

Step 4
人工核对 expectedFacts / forbiddenFacts

Step 5
标 category / difficulty

Step 6
冻结 TEST
```

---

# 60. Benchmark Case 必须基于清洗后的 Unit ID

禁止 benchmark 直接引用旧：

```text
mem_xxx
```

作为 gold recall target。

Gold target 必须是：

```text
Cognitive Unit ID
```

Raw source memory 只用于 provenance。

---

# 61. Multi-unit Case 的要求

至少 35 条。

每条 expected：

```text
2–4 Cognitive Units
```

禁止全部 case 都是：

```text
一个 query → 一个 unit
```

否则无法测组合 Recall。

---

# 62. Distractor-heavy Case 的要求

必须选择：

```text
同一个 subject 有大量 Memory Units
```

例如：

```text
NICEICK
小天文
苦雪
longz
```

Query 只问其中一个具体方面。

观察：

```text
Provider 是否把同一个人的所有记忆全召回来
```

---

# 63. Alias Case

Query 使用：

```text
nickname
alternate name
account id
```

Gold Unit 可能使用另一名称。

测：

```text
alias fragmentation
```

如果当前 Cognitive Unit Store 没有可靠 identity 信息：

```text
只标明确存在的 alias case
不要人工假设同一人
```

---

# 64. Temporal Case

必须包含：

```text
开学后
暑假
当时
后来
目前记忆中
```

等具有时间限定的 Unit。

Judge 必须检查时间限定有没有被答案丢掉。

---

# 65. Dirty / Ambiguous Case

从：

```text
SUBJECTLESS
AMBIGUOUS
UNRESOLVED_REFERENCE
MIXED_SPLIT
```

等清洗状态中选。

目标不是要求系统猜对。

而是测：

```text
能否避免过度推断
```

很多此类 case 应：

```text
shouldAbstain = true
```

---

# 66. Benchmark 数据版本

顶层：

```json
{
  "version": "0.1.0",
  "frozen": false,
  "cases": []
}
```

正式冻结 TEST 后：

```json
{
  "version": "0.1.0",
  "frozen": true,
  "cases": []
}
```

---

# 67. Schema Validation

Benchmark 启动前必须验证：

```text
version is string
case id unique
expected Unit IDs exist in current store
distractor IDs exist
requiresMemory consistent with category
expectedFacts array valid
relation between split and frozen valid
```

若 gold Unit 不存在：

```text
直接停止 benchmark
```

不要忽略。

---

# 68. Store Fingerprint

Benchmark 运行前对：

```text
Cognitive Unit Store
```

生成 SHA256。

写入：

```text
config.json
```

这样数据清洗发生变化后，旧 benchmark 结果不会被误认为可直接比较。

---

# 69. Provider Determinism

Recall-only benchmark 对同一 Provider：

连续运行至少：

```text
3 次
```

如果结果应 deterministic：

```text
returned Unit IDs 必须完全一致
```

否则报告：

```text
NON_DETERMINISTIC_RECALL
```

LLM Agent 不要求完全 deterministic。

---

# 70. LLM Repeats

Agent E2E P0 默认：

```text
1 run / case
```

如果需要正式模型比较：

```text
3 runs / case
```

再报告：

```text
mean
pass@1
consistency
```

P0 先不强制三跑，避免成本太高。

---

# 71. 成本统计

Agent Benchmark 额外记录：

```text
input tokens
output tokens
tool rounds
LLM calls
judge calls
```

如果 provider API 给 token usage。

报告：

```text
average tokens / case
```

方便以后比较不同 Memory Provider 是否增加上下文成本。

---

# 72. Provider 返回数量不固定

Benchmark 不要求：

```text
必须返回 K 条
```

如果只有两条达到 threshold：

```text
返回 2 条
```

如果 0 条：

```text
返回 0 条
```

`limit` 只是 safety cap。

---

# 73. 不允许 benchmark runner 注入 gold 信息

Normal Agent 模式中：

```text
LLM
```

绝不能看到：

```text
expectedUnitIds
expectedFacts
forbiddenFacts
category
difficulty
```

只有 evaluator 能看到。

---

# 74. Oracle 不能污染 Normal

Normal 和 Oracle：

```text
必须是独立 agent run
```

不要：

```text
先运行 Normal
再把 Normal history 带给 Oracle
```

---

# 75. Test Requirements

新增测试：

```text
benchmark schema validation
metric calculations
failure attribution
oracle injection
provider selection
result serialization
store fingerprint
```

---

# 76. Metric Unit Tests

必须测试：

```text
Expected = [A,B]
Returned = [A,B,C]
```

得到：

```text
Recall = 1.0
Precision = 2/3
FP = 1
Exact Recall Success = true
```

以及：

```text
Expected = [A,B]
Returned = [A]
```

得到：

```text
Recall = 0.5
Exact Recall Success = false
```

---

# 77. 不修改现有 Demo 路径

正常：

```text
npm run dev
```

仍然启动 Demo。

Benchmark：

```text
npm run bench
```

独立执行。

---

# 78. package.json Scripts

增加：

```json
{
  "scripts": {
    "bench": "tsx scripts/run-memory-benchmark.ts",
    "bench:dev": "tsx scripts/run-memory-benchmark.ts --split dev --mode all",
    "bench:test": "tsx scripts/run-memory-benchmark.ts --split test --mode all"
  }
}
```

根据当前项目实际 TS runtime 调整。

---

# 79. README

增加：

```text
## Memory Benchmark
```

说明：

```text
Recall-only
Agent E2E
Oracle
```

以及：

```bash
npm run bench:dev
npm run bench:test
```

---

# 80. P0 Acceptance Criteria

Benchmark P0 DONE 必须满足：

```text
[ ] benchmark JSON schema implemented
[ ] DEV/TEST split supported
[ ] Recall-only runner works
[ ] Agent E2E runner works
[ ] Oracle runner works
[ ] Recall metrics implemented
[ ] Tool decision metrics implemented
[ ] Answer judge implemented
[ ] Unsupported claim judge implemented
[ ] Abstention evaluation implemented
[ ] Failure attribution implemented
[ ] summary.md generated
[ ] cases.jsonl generated
[ ] failures.md generated
[ ] per-category breakdown generated
[ ] store + prompt + tool schema fingerprints recorded
[ ] single-case debug mode works
[ ] npm test passes
[ ] npm run build passes
[ ] existing Demo still works
```

---

# 81. Required Final Report

Codex 完成后返回：

```text
STATE: EXECUTED

TASK:
LLM Memory Benchmark P0

BENCHMARK_DATASET:
version:
cases:
dev:
test:
frozen:

MODES:
recall_only: PASS/FAIL
agent_e2e: PASS/FAIL
oracle: PASS/FAIL

METRICS_IMPLEMENTED:
expected_unit_recall:
precision:
false_positive:
tool_decision_f1:
answer_fact_accuracy:
unsupported_claim_rate:
abstention_accuracy:
e2e_success:
latency:

OUTPUTS:
summary.json:
summary.md:
cases.jsonl:
failures.md:
recall.csv:

SINGLE_CASE_DEBUG:
PASS/FAIL

STORE_FINGERPRINT:
PASS/FAIL

TESTS:
...

BUILD:
...

DEMO_REGRESSION:
PASS/FAIL

KNOWN_LIMITATIONS:
...

BLOCKERS:
NONE
or exact blocker
```

---

# 82. Benchmark 最终回答的问题

这套 Benchmark 最终必须能回答：

```text
MemoryProvider 有没有想起正确的东西？

想起正确东西的同时，有没有想起太多垃圾？

LLM 知不知道什么时候应该用 Memory？

LLM 拿到正确 Memory 后，会不会正确使用？

Memory 不足时，会不会承认不知道？

换成另一套 Recall Provider 后，到底是真的更好，
还是只是“看起来更智能”？
```

---

# 83. One-line principle

> **先把“想没想起来”和“想起来之后会不会用”分开测，再用同一套冻结 TEST 对不同 MemoryProvider 做公平比较。**
