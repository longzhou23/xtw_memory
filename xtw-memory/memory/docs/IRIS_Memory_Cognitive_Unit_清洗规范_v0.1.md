# IRIS Memory → Cognitive Unit 清洗规范 v0.1

**日期：2026-09-22**  
**状态：批量清洗前冻结规则**  
**目标：把旧 RAG Memory 转换为适合 Associative Memory 的干净 Cognitive Units**  
**注意：本阶段只做认知单元清洗，不生成 CAUSAL / SIMILARITY / OPPOSITION 联想边。**

---

# 0. 一句话目标

旧 RAG Memory 的基本单位是：

> “适合被检索的一段文本”。

新 Associative Memory 需要的基本单位是：

> **“可以被独立想起、独立判断真值、独立获得 Attention 的认知单元”。**

因此本阶段做：

```text
Raw / Legacy RAG Memory
        ↓
Cognitive Unit Cleaning
        ↓
干净、可独立激活的 Cognitive Units
```

而不是：

```text
Raw Memory
→ Knowledge Graph
```

也不是：

```text
Raw Memory
→ 三关系 Association
```

---

# 1. 最重要的边界

本阶段只回答：

> **一条旧 Memory 里到底包含几个值得独立存在的认知单元？**

本阶段不回答：

```text
这些 Unit 之间是 CAUSAL / SIMILARITY / OPPOSITION 哪一种？
```

Association Building 是后续独立阶段。

因此：

```text
cleaning != association learning
```

---

# 2. Raw Memory 必须永久保留

任何清洗都不得覆盖、改写或删除原始 Memory。

数据结构应是：

```text
Raw Memory
    │
    ├── Derived Cognitive Unit 1
    ├── Derived Cognitive Unit 2
    └── Derived Cognitive Unit 3
```

而不是：

```text
Raw Memory
→ 被新文本替换
```

每个 Cognitive Unit 必须保留：

```text
sourceMemoryId
sourceText
```

以及可选：

```text
sourceSpan
```

用于完整 provenance。

---

# 3. Cognitive Unit 的定义

如果一段信息满足下面的问题：

> “它能否在不依赖同一 chunk 中其他独立事实的情况下，被单独想起来并仍然有完整意义？”

如果可以，它就是一个 Cognitive Unit 候选。

更严格地说，一个 Cognitive Unit 应尽量满足：

```text
1. 一个主要认知断言 / 状态 / 事件 / 偏好 / 目标 / 程序
2. 可以独立进入 Working Memory
3. 可以独立为真或为假
4. 不夹带无关主体或无关主题
5. 保留使其成立所必要的限定条件
```

---

# 4. 什么时候必须拆

## Rule 4.1 — 多主体独立事实必须拆

原文：

```text
A 喜欢 X，B 住在 Y。
```

输出：

```text
[A 喜欢 X]
[B 住在 Y]
```

禁止保留为一个 Unit。

---

## Rule 4.2 — 同一主体的多个独立谓词必须拆

原文：

```text
longz 是小天文的制作者、开发者和维护者。
```

输出：

```text
[longz 是小天文的制作者]
[longz 是小天文的开发者]
[longz 是小天文的维护者]
```

因为三个角色可以独立成立或失效。

---

## Rule 4.3 — 同一谓词的多个独立对象原则上拆

原文：

```text
NICEICK 玩 maimai 和 Project Sekai。
```

输出：

```text
[NICEICK 玩 maimai]
[NICEICK 玩 Project Sekai]
```

原因：

```text
玩 maimai
```

和：

```text
玩 Project Sekai
```

是两个可独立回忆的事实。

---

## Rule 4.4 — 多个独立偏好 / 目标 / 愿望必须拆

原文：

```text
不爱记笔记希望以后和 longz 一起学习和生活，
并希望 longz 早日康复、走出阴影。
```

输出至少：

```text
[不爱记笔记希望以后和 longz 一起学习]
[不爱记笔记希望以后和 longz 一起生活]
[不爱记笔记希望 longz 早日康复]
[不爱记笔记希望 longz 走出阴影]
```

不要把四个目标绑成一个 Attention Node。

---

## Rule 4.5 — Legacy mixed memory 必须拆

如果一条旧 Memory 混入：

```text
不同人物
不同项目
不同地点
不同话题
```

必须拆到互相可以独立存在为止。

原始 mixed memory 仍保留用于 provenance。

---

# 5. 什么时候不应该拆

Atomic 不等于“越短越好”。

有些信息一拆就丢失真正意义。

---

## Rule 5.1 — 关系本身是事实时，不拆关系两端

原文：

```text
路德维希的录取通知与分班结果间隔半个多月。
```

应保持：

```text
[路德维希的录取通知与分班结果间隔半个多月]
```

不要拆成：

```text
[路德维希收到录取通知]
[路德维希收到分班结果]
[半个多月]
```

因为真正值得记住的是“两个事件之间的时间关系”。

---

## Rule 5.2 — 程序 / 顺序不能机械拆

原文：

```text
苦雪读论文时通常先翻译，再总结。
```

保持一个 Procedure Unit：

```text
[苦雪读论文时通常先翻译，再总结]
```

因为：

```text
先翻译 → 再总结
```

的顺序本身就是知识。

可以在 payload 中额外记录 steps，但不要把原 Procedure Unit 删除。

---

## Rule 5.3 — 否定必须和断言绑定

原文：

```text
NICEICK 不喜欢拍黑白照片。
```

必须保留完整：

```text
[NICEICK 不喜欢拍黑白照片]
```

禁止清洗成：

```text
[NICEICK 喜欢拍黑白照片]
```

加一个外部 negative 标记后让自然语言变正面。

文本本身应保留否定语义。

---

## Rule 5.4 — 时间限定不能丢

原文：

```text
Amaryllis 开学后走读。
```

输出必须仍然包含：

```text
开学后
```

不能简化成：

```text
Amaryllis 走读。
```

时间限定改变真值条件。

---

## Rule 5.5 — 模态不能丢

例如：

```text
可能
计划
希望
打算
认为
听说
猜测
```

都属于真值条件的一部分。

原文：

```text
苦雪认为原神剧情与魔裁相似。
```

输出：

```text
[苦雪认为原神剧情与魔裁相似]
```

不能写成：

```text
[原神剧情与魔裁相似]
```

因为后者把“苦雪的观点”错误提升成客观事实。

---

## Rule 5.6 — 原因/结果关系如果本身是记忆重点，可保留复合 Unit

原文：

```text
仅核对专业名称不足以确认身份，因为知道外国语学院名称的人也可能并非本校学生。
```

允许输出：

```text
[仅核对专业名称不足以确认入群者身份]
[知道外国语学院名称不足以证明一个人是本校学生]
```

但不要为了原子化把：

```text
不足以确认
```

这种逻辑结构拆碎。

---

# 6. 判断是否继续拆：Independent Truth Test

每遇到：

```text
A 且 B
A、B、C
A 然后 B
A 因为 B
```

都问：

> **A 和 B 是否可以一个为真、另一个为假，而原 Memory 仍有意义？**

如果：

```text
YES
```

通常应该拆。

如果：

```text
NO
```

或者拆后会破坏：

```text
时间关系
因果关系
比较关系
条件关系
程序顺序
否定范围
引用/观点归属
```

则保持一个 Unit。

---

# 7. 派生 Unit 不是 SVO 爆炸

禁止机械执行：

```text
每出现一个动词
→ 创建一个节点
```

也禁止：

```text
每个名词
→ 创建一个 Proposition
```

标准不是语法，而是：

> **是否值得独立获得 Attention。**

---

# 8. Cognitive Unit 类型

推荐使用统一 `CognitiveUnit`，再使用 subtype。

```ts
type CognitiveUnitType =
  | 'FACT'
  | 'STATE'
  | 'EVENT'
  | 'PREFERENCE'
  | 'GOAL'
  | 'OPINION'
  | 'PROCEDURE'
  | 'IDENTITY_CLAIM'
  | 'RELATION'
  | 'OTHER';
```

这只是内容类型。

它不等于 Associative Edge type。

---

# 9. 类型说明

## FACT

相对稳定的一般事实。

```text
NICEICK 玩 Project Sekai。
```

---

## STATE

具有状态性、可能随时间变化。

```text
Amaryllis 开学后走读。
```

---

## EVENT

一次发生的动作 / 事件。

```text
苦雪购买了佩丽卡的毛巾。
```

---

## PREFERENCE

喜欢 / 不喜欢 / 重视 / 偏好。

```text
NICEICK 不喜欢拍黑白照片。
```

---

## GOAL

希望 / 计划 / 想做。

```text
不爱记笔记希望 longz 早日康复。
```

---

## OPINION

明确归属于某人的判断、看法。

```text
NICEICK 认为 Z 58/0.95 主要是向 F 卡口 58/1.2 致敬。
```

---

## PROCEDURE

流程、步骤、顺序。

```text
苦雪读论文时通常先翻译，再总结。
```

---

## IDENTITY_CLAIM

名字、昵称、账号、身份指代。

```text
long_Z 的真名是龙洲。
```

注意：

> IDENTITY_CLAIM 只是记忆内容，不执行 canonical merge。

---

## RELATION

核心内容本身就是多个对象之间的关系。

```text
录取通知和分班结果间隔半个多月。
```

---

# 10. 推荐输出结构

```json
{
  "id": "cu:<deterministic-id>",

  "type": "PREFERENCE",

  "text": "NICEICK 不喜欢拍黑白照片。",

  "subjects": [
    {
      "text": "NICEICK",
      "entityId": "2960945437"
    }
  ],

  "mentions": [
    "NICEICK",
    "黑白照片"
  ],

  "semantic": {
    "predicate": "dislikes",
    "polarity": "negative",
    "modality": "asserted"
  },

  "provenance": {
    "sourceMemoryIds": [
      "mem_c8086103904d"
    ],
    "sourceTexts": [
      "NICEICK不喜欢拍黑白照片"
    ]
  },

  "cleaning": {
    "status": "CLEAN",
    "confidence": 0.98
  }
}
```

---

# 11. semantic 字段是 optional metadata

例如：

```text
predicate = owns
predicate = likes
predicate = located_in
```

可以存在于：

```text
unit.semantic
```

但它们：

```text
不是 Associative Edge
```

Attention Diffusion 引擎不得依赖这些 predicate。

它们主要用于：

```text
审计
未来 query parsing
debug
可能的后续 reasoning
```

---

# 12. subjectless 处理

旧数据中存在：

```text
“所在地或发货地是山东省烟台市牟平区”
```

但没有主体。

规则：

### 如果主体在同一 Raw Memory 内可以明确恢复

可以恢复。

### 如果需要查询其他 Memory / embedding 才能猜主体

禁止恢复。

输出：

```json
{
  "text": "所在地或发货地是山东省烟台市牟平区。",
  "subjects": [],
  "cleaning": {
    "status": "SUBJECTLESS"
  }
}
```

宁可保留 subjectless，也不要猜错人。

---

# 13. 指代消解

## 同一 Raw Memory 内

允许：

```text
苦雪买了一条佩丽卡毛巾，它来自终末地嘉年华。
```

将：

```text
它
```

解析为：

```text
佩丽卡毛巾
```

因为 antecedent 在同一 source 内明确。

---

## 跨 Memory

禁止自动补。

如果：

```text
“她后来去了徐汇。”
```

单条 Memory 内没有明确“她”是谁：

```text
status = UNRESOLVED_REFERENCE
```

不要通过 embedding 猜。

---

# 14. Alias / Identity

允许从明确来源提取：

```text
long_Z 的真名是龙洲
NICEICK 也叫心象蜃気楼
```

成为：

```text
IDENTITY_CLAIM
```

但清洗器不得执行：

```text
merge entities
canonicalize person IDs
copy facts between aliases
```

原则仍然是：

> weak/explicit identity memory may later affect recall, but cleaning does not rewrite identity truth.

---

# 15. Duplicate 处理

Raw Memory 永不删除。

Derived Cognitive Units 可以处理重复，但必须保守。

---

## 15.1 完全等价重复

例如两个 source 都明确说：

```text
小天文的创作者是 longz。
```

可以生成一个 Cognitive Unit：

```text
[小天文的创作者是 longz]
```

其 provenance：

```json
{
  "sourceMemoryIds": [
    "mem_x",
    "mem_y"
  ]
}
```

---

## 15.2 Near Duplicate

例如：

```text
longz 是小天文的创作者
```

与：

```text
小天文由 longz 用长期对话培养出来
```

不要自动 merge。

它们语义相关，但未必完全等价。

标记：

```text
DUPLICATE_CANDIDATE
```

留给后续 consolidation。

---

# 16. Duplicate merge 的硬条件

只有同时满足：

```text
主体相同
核心断言相同
对象相同
polarity 相同
modality 相同
关键时间限定相同
观点归属相同
```

才允许自动 merge。

如果有任何关键维度不同：

```text
不 merge
```

---

# 17. Conflict / Contradiction

例如：

```text
A 住在上海
A 不住在上海
```

禁止：

```text
选一个
覆盖旧值
平均
```

两条都保留。

可以额外标记：

```text
CONFLICT_CANDIDATE
```

但 Truth Resolution 不属于 Cleaning。

---

# 18. 时间

区分：

```text
source timestamp
```

与：

```text
memory semantic time
```

source 的写入时间只能放 metadata。

不能因为：

```text
Memory created at 2026-09-20
```

就把事实改写为：

```text
2026-09-20 时 A 在上海
```

除非原文确实表达这个时间。

---

# 19. Cleaning Confidence

允许：

```text
cleaning.confidence
```

但它只表示：

> “这次拆分 / 解析有多确定。”

不表示：

```text
事实真值
Memory importance
Association strength
Attention
```

这几个量必须严格分开。

---

# 20. Cleaning Status

允许：

```ts
type CleaningStatus =
  | 'CLEAN'
  | 'SUBJECTLESS'
  | 'UNRESOLVED_REFERENCE'
  | 'AMBIGUOUS'
  | 'MIXED_SPLIT'
  | 'DUPLICATE_CANDIDATE'
  | 'CONFLICT_CANDIDATE'
  | 'REJECTED';
```

---

# 21. REJECTED 什么时候允许

只有当内容根本不能形成可解释认知单元，例如：

```text
纯噪声
严重截断
无法恢复任何语义
系统残片
```

才可：

```text
REJECTED
```

并必须保留：

```text
rejectReason
```

禁止因为：

```text
太难
subjectless
不确定
```

就直接删除。

---

# 22. 具体 IRIS 示例

## Example A — 游戏列表

原始：

```text
NICEICK玩舞萌（maimai）和世界计划（Project Sekai）
```

清洗：

```text
CU1 FACT
NICEICK 玩 maimai。

CU2 FACT
NICEICK 玩 Project Sekai。
```

---

## Example B — 地点 + 否定状态

原始：

```text
Amaryllis在上海徐汇，但不在学校
```

清洗：

```text
CU1 STATE
Amaryllis 在上海徐汇。

CU2 STATE
Amaryllis 不在学校。
```

不要输出：

```text
Amaryllis ↔ 徐汇
```

这种关联边。

---

## Example C — Procedure

原始：

```text
苦雪阅读论文时通常采用先翻译、再总结的方式。
```

清洗：

```text
CU1 PROCEDURE
苦雪阅读论文时通常先翻译，再总结。
```

不拆为两个互相失去顺序的事实。

---

## Example D — Opinion

原始：

```text
NICEICK认为尼康NIKKOR Z 58mm f/0.95 S主要是向F卡口58mm f/1.2镜头致敬，而不是以大量销售为目标
```

建议：

```text
CU1 OPINION
NICEICK 认为 NIKKOR Z 58mm f/0.95 S 主要是向 F 卡口 58mm f/1.2 镜头致敬。

CU2 OPINION
NICEICK 认为 NIKKOR Z 58mm f/0.95 S 的主要目的不是大量销售。
```

保留：

```text
NICEICK认为
```

不能提升为客观 Nikon 产品事实。

---

## Example E — 多目标

原始：

```text
不爱记笔记希望以后一起学习和生活，希望longz早日康复并积极寻找更阳光向上的生活。
```

建议：

```text
CU1 GOAL
不爱记笔记希望以后和 longz 一起学习。

CU2 GOAL
不爱记笔记希望以后和 longz 一起生活。

CU3 GOAL
不爱记笔记希望 longz 早日康复。

CU4 GOAL
不爱记笔记希望 longz 过更阳光向上的生活。
```

---

## Example F — mixed legacy

原始：

```text
long_Z 是小天文的制作者、开发者和维护者；
同一 legacy memory 又混入苦雪的其他偏好。
```

必须拆。

至少：

```text
CU1 FACT
long_Z 是小天文的制作者。

CU2 FACT
long_Z 是小天文的开发者。

CU3 FACT
long_Z 是小天文的维护者。

CU4...
苦雪的偏好单独形成 Unit。
```

状态：

```text
MIXED_SPLIT
```

---

## Example G — 时间关系

原始：

```text
路德维希回忆自己当年录取通知和分班结果间隔了半个多月
```

输出：

```text
CU1 RELATION
路德维希回忆自己的录取通知与分班结果间隔了半个多月。
```

不要过拆。

---

# 23. Unit Text 的改写原则

允许：

```text
去掉无意义口头语
修复明显标点
补足同一 source 内明确的省略主语
统一少量格式
```

禁止：

```text
总结成更强的断言
添加常识
添加跨 Memory 信息
替用户解释动机
修改观点归属
修改时间范围
修改否定
```

---

# 24. Entailment Hard Rule

每个 Derived Unit 必须满足：

> **只看其 source memory，这个 Unit 就能被 source 支持。**

如果需要：

```text
其他 Memory
外部知识
embedding 猜测
常识推断
```

才能成立：

```text
禁止生成
```

这是清洗阶段最重要的安全约束。

---

# 25. 禁止 Cross-Memory Enrichment

清洗每条 Raw Memory 时：

```text
只允许看：
- 当前 Raw Memory
- 当前 Memory 自带 metadata
```

禁止为了让 Unit 更完整：

```text
搜索同一用户其他记忆
搜索 alias
查询向量库
把两个 Memory 拼起来
```

跨 Memory Consolidation 是后续 Dream / maintenance 的职责。

---

# 26. Entity mention 可以记录，但不强制建 Entity Node

清洗输出可以包含：

```json
"mentions": [
  "NICEICK",
  "Project Sekai"
]
```

但本阶段不要因为 mention 就自动构建最终图。

目标是：

```text
先得到干净 Cognitive Units
```

图构建后做。

---

# 27. Deterministic ID

每个 Unit ID 必须可复现。

建议：

```text
cu:<sourceMemoryId>:<unitIndex>
```

但如果后续重新排序会破坏 ID，可以改成：

```text
cu:<sha256(sourceMemoryId + canonicalUnitText)[0:16]>
```

推荐后者。

同样输入应得到同样 ID。

---

# 28. 建议批处理 Pipeline

```text
Phase 1
Load Raw Memories
    ↓
Phase 2
Per-memory Cognitive Unit Extraction
    ↓
Phase 3
Atomicity Validation
    ↓
Phase 4
Entailment Validation
    ↓
Phase 5
Conservative Exact-Semantic Dedup
    ↓
Phase 6
Conflict / Duplicate Candidate Marking
    ↓
Phase 7
Export Clean Cognitive Unit Store
    ↓
Phase 8
Human Audit Sample
```

注意：

```text
Phase 8 之后才讨论 Association Graph。
```

---

# 29. 如果使用 LLM 清洗

建议 LLM 每次只处理单条 Memory。

输入：

```json
{
  "memoryId": "...",
  "text": "...",
  "metadata": {}
}
```

要求 Structured JSON 输出。

禁止一次把整个 Memory DB 喂给 LLM 再让它自由整理。

原因：

```text
减少 cross-memory hallucination
保留 provenance
方便重跑
方便审计
```

---

# 30. LLM 清洗提示词核心约束

可以直接放进 System / Developer Prompt：

```text
Your task is cognitive-unit extraction, not summarization.

Split the source memory into the minimum number of independently recallable cognitive units.

Every output unit must be fully entailed by the source memory alone.

Preserve:
- subject
- negation
- attribution
- modality
- temporal qualifiers
- comparison
- causal/conditional wording
- procedural order

Do not:
- use external knowledge
- use other memories
- infer missing identities
- canonicalize aliases
- resolve contradictions
- generate associative edges
- convert every verb into a separate unit

Split independent facts.
Keep relations/procedures whose meaning would be destroyed by splitting.
```

---

# 31. Structured Output

建议：

```json
{
  "sourceMemoryId": "mem_xxx",

  "sourceStatus": "CLEAN",

  "units": [
    {
      "type": "FACT",
      "text": "...",

      "subjects": [],
      "mentions": [],

      "semantic": {
        "predicate": null,
        "polarity": "positive",
        "modality": "asserted",
        "temporal": null
      },

      "cleaning": {
        "status": "CLEAN",
        "confidence": 0.95,
        "notes": ""
      }
    }
  ]
}
```

---

# 32. Atomicity validator

清洗后做第二遍检查。

Validator 问：

```text
1. 这个 Unit 是否包含两个不同主体？
2. 是否包含可以独立真假的两个断言？
3. 是否存在“并且/以及/同时/还/又”连接独立事实？
4. 是否把观点误写成事实？
5. 是否丢失否定？
6. 是否丢失时间限定？
7. 是否丢失目标/希望/计划模态？
8. 是否依赖 source 之外的信息？
```

任何一项失败：

```text
needs_review = true
```

---

# 33. Over-splitting validator

同时防止过度拆分。

检查：

```text
1. 是否把“先A再B”的 Procedure 拆坏？
2. 是否把“X与Y间隔T”的 Relation 拆坏？
3. 是否把比较关系拆成互不相关碎片？
4. 是否把条件句拆掉条件？
5. 是否把因果解释拆到失去因果意义？
6. 是否产生只有“半个多月”“徐汇”“黑白照片”之类无断言碎片？
```

如果是：

```text
needs_review = true
```

---

# 34. 批量清洗验收指标

批量跑完全部 IRIS 后必须报告：

```text
Raw Memory Count

Derived Cognitive Unit Count

Units per Memory:
- mean
- median
- p90
- max

Status Counts:
- CLEAN
- SUBJECTLESS
- UNRESOLVED_REFERENCE
- AMBIGUOUS
- MIXED_SPLIT
- DUPLICATE_CANDIDATE
- CONFLICT_CANDIDATE
- REJECTED

Exact-semantic dedup count

Duplicate candidate count

Conflict candidate count

Rejected count

Needs-review count
```

---

# 35. 异常报警

以下情况应该自动报警：

```text
平均每条 Memory > 5 个 Unit
```

可能过拆。

```text
> 20% Memory 只产生 0 个 Unit
```

可能 extraction 失败。

```text
> 30% Unit 没有任何 subject/mention
```

可能清洗质量差。

```text
绝大部分 Unit 只有 2～4 个字
```

明显过拆。

```text
Derived Unit Count 接近 Raw Memory Count 且已知原库大量 mixed
```

可能根本没洗。

---

# 36. 人工抽检

批量完成后：

随机抽：

```text
100 条 Raw Memory
```

同时展示：

```text
Raw
→ Derived Units
```

人工只打四个标签：

```text
PASS
UNDER_SPLIT
OVER_SPLIT
HALLUCINATION
```

目标：

```text
HALLUCINATION ≈ 0
```

这是最高优先级。

宁可：

```text
UNDER_SPLIT
```

也不能：

```text
HALLUCINATION
```

---

# 37. 与 Association Graph 的接口

清洗阶段输出：

```text
Cognitive Units
+
mentions
+
optional semantic metadata
+
provenance
```

后续 Graph Builder 才决定：

```text
哪些 Cognitive Units / Entities 成为 Node
哪些 Node 之间建立 Association
Association 是：
- CAUSAL
- SIMILARITY
- OPPOSITION
Association Strength 是多少
```

两步必须分开。

---

# 38. 为什么要分开

如果 Cleaning 阶段一边拆事实，一边决定三关系：

```text
容易为了图结构修改事实
容易把 owns / located_in 硬塞成 similarity
容易污染 provenance
```

所以固定顺序：

```text
先把“记忆是什么”洗干净

再研究“记忆之间怎么联想”
```

---

# 39. 对旧 RAG 的定位

旧数据不是“错误数据”。

它只是面向不同目标：

```text
旧 RAG：
检索友好的文本块

新 Associative Memory：
认知友好的可激活单元
```

因此本阶段属于：

```text
representation migration
```

而不是：

```text
repair bad facts
```

---

# 40. Frozen Rules Summary

必须遵守：

1. **Raw Memory 永不改写。**
2. **Derived Unit 必须可独立获得 Attention。**
3. **独立真值的事实必须拆。**
4. **时间、否定、模态、观点归属不能丢。**
5. **关系/程序拆后失真时不要拆。**
6. **只根据当前 source memory 清洗。**
7. **不跨 Memory 猜主体。**
8. **不 canonical merge identity。**
9. **不解决冲突。**
10. **重复合并必须极度保守。**
11. **predicate 可以放 payload，但不是 Association Edge。**
12. **Cleaning 阶段不生成 CAUSAL / SIMILARITY / OPPOSITION。**
13. **宁可少拆，不可 hallucinate。**
14. **每个 Unit 都必须保留 provenance。**
15. **清洗完成后再构建 Associative Graph。**

---

# 41. 这轮的最终目标

批量清洗后的数据应满足：

> 当一个 Cognitive Unit 获得 Attention 时，它只应该把“一个完整认知内容”带进 Working Memory，而不是把旧 RAG chunk 中混在一起的五六个话题一次性全部带进来。

这就是本次清洗是否成功的最终标准。
