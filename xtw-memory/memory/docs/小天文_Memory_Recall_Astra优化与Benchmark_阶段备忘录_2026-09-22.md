# 小天文 Memory Recall：Astra 优化与 Benchmark 备忘录

**日期：2026-09-22**  
**状态：Recall Provider 已冻结；Benchmark annotation 尚未正式 freeze**  
**主题：从 `lexical-top8` 到 `improved-recall` 的算法变化与 DEV / TEST Benchmark 结果**

---

## 1. 背景

当前 Memory 系统已经完成：

```text
Raw / Legacy RAG Memory
→ Cognitive Unit Cleaning
→ Cognitive Unit Store
```

并建立了独立 Recall Benchmark harness，用于比较不同 MemoryProvider 的检索能力。

本轮优化的目标不是修改 Memory 架构，也不是修改 Cognitive Unit 数据，而是：

> **在现有 Cognitive Unit Store 上，把一个简单的 lexical Top-K baseline 改造成更可靠的、具有拒绝能力和动态返回数量的 Recall Provider。**

整个优化过程保持以下边界：

```text
不修改 Cognitive Unit Store
不修改 benchmark gold
不修改 Agent / Oracle runner
不修改 Attention / Dream engine
不修改长期 Memory 理论
```

因此这轮工作只针对：

```text
Recall Provider
```

---

# 2. 优化前：lexical-top8 baseline

原始 baseline 的行为可以概括为：

```text
Query
↓
简单 normalization / token overlap
↓
subject token overlap
↓
type bonus
↓
简单 score
↓
Top-K
↓
最多 8 条
```

实际行为接近：

```text
“排序后尽量填满 8 条”
```

因此在 benchmark 中表现出几个明显特征：

```text
- Recall 不算完全失败
- 但低相关条目大量进入返回结果
- Negative case 缺乏拒绝能力
- 返回数量接近固定 8 条
```

这也是为什么早期 TEST Recall-only 结果中：

```text
Returned units / case p50 = 8
```

Precision / false-positive 指标很差。

需要特别说明：

> `limit=8` 在实际应用中可以作为上下文预算上限；  
> 但在 benchmark 中不能把“填满 8 条”本身视为成功。

---

# 3. Astra 的核心改动

Astra 没有仅仅调一个 threshold，而是把 Recall 流程重构成：

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

最终 provider：

```text
improved-recall
```

---

# 4. 具体算法变化

## 4.1 文本归一化增强

加入：

```text
NFKC Unicode normalization
大小写归一
dash 形式归一
invisible separator 清理
空白归一
```

目的：

> 降低文本表面格式差异对 lexical matching 的影响。

---

## 4.2 Tokenization 改进

中文 / 日文：

```text
在连续 script span 内构造 bigram
```

避免：

```text
跨标点
跨空白
跨不相关片段
```

产生虚假 token。

Latin identifier：

```text
保留 token boundary
```

用于人名、ID、英文术语、型号等。

---

## 4.3 构建一次性 lexical index

Provider 初始化时构建：

```text
normalized text
tokens
subjects
mentions
aliases
negative cues
temporal cues
document frequency
```

Recall 时不再重复做全部预处理。

这也是最终 latency 显著下降的重要原因之一。

---

# 5. IDF weighting

Astra 引入 document frequency / IDF：

```text
高频词
→ 较低区分度

稀有词
→ 更高区分度
```

这使 Recall 不再只是简单 token overlap。

例如：

```text
“记忆”
“情况”
“关于”
```

这类高频 query scaffold 不应主导结果；

而：

```text
NICEICK
Project Sekai
NIKKOR
Amaryllis
```

这类更具辨识度的词应该获得更高价值。

---

# 6. 最关键的改动：Subject 与 Topic 分离

这是本轮最重要的算法变化。

旧逻辑容易出现：

```text
Query:
NICEICK 玩什么？
```

只要一条 Memory：

```text
“关于 NICEICK”
```

就可能因为 subject overlap 获得很高分。

Astra 改为：

```text
Query
├── Subject: NICEICK
└── Topic: 玩什么 / 游戏
```

然后分别处理：

```text
Subject Match
≠
Topical Relevance
```

核心原则：

> **Subject 命中不能补偿 Topic evidence 缺失。**

也就是：

```text
“这是 NICEICK 的 Memory”
```

不等于：

```text
“这是回答 NICEICK 玩什么的 Memory”
```

这也是 improved-recall 能减少大量无关 same-subject memory 的核心原因。

---

# 7. Query scaffolding 清理

Astra 会尽量从 query 中去除低价值问句框架，例如：

```text
关于
记忆里
记得
什么
哪些
具体情况
偏好
看法
```

只保留真正用于检索的 topical signal。

目标：

```text
Question Language
↓
Retrieval Intent
```

而不是把整个自然语言问句一视同仁地做 token overlap。

---

# 8. Subject / Mention / Alias

Provider 支持：

```text
subjects
mentions
aliases
```

用于主体识别。

但当前 Cognitive Unit Store 的实际情况是：

```text
mentions / aliases 字段尚未 populated
```

因此：

```text
这些路径有 contract tests
但当前真实 benchmark 主要依赖 subject / text
```

Astra 没有构造新的 identity graph，也没有做推测式 alias merge。

---

# 9. Content Coverage Gate

候选不只需要“有一些 matching token”，还需要满足 topical coverage。

最终配置中主要参数包括：

```text
minContentCoverage = 0.36
noSubjectCoverage  = 0.55
```

含义：

```text
如果明确识别到 subject：
topic coverage 至少达到一个最低门槛

如果没有明确 subject：
要求更高的 topical coverage
```

这样可以减少：

```text
泛 query
→ 随便返回同主题弱相关 Memory
```

---

# 10. Phrase / Type / Temporal / Negation signals

Astra 还加入了轻量 soft signals：

```text
phrase match
type hint
temporal cue
negative cue
```

例如：

```text
“不喜欢”
“后来”
“目前”
“过去”
“目标”
“偏好”
“观点”
```

这些不会改变 Memory 的事实语义，只作为排序 bonus。

因此：

> Provider 仍然是 lexical retrieval，不是逻辑推理器。

---

# 11. 双重 Threshold

最终候选不是只看一个绝对分数，而是：

```text
absolute score floor
+
relative-to-best threshold
```

最终配置包括：

```text
minimumScore      = 1.5
relativeThreshold = 0.78
```

候选必须同时满足：

```text
score >= minimumScore
```

以及：

```text
score >= bestScore * 0.78
```

因此：

```text
limit=8
```

只表示：

> **最大 context budget**

而不是：

> **必须返回 8 条**

最终结果可以：

```text
0 条
1 条
3 条
8 条
```

---

# 12. CLEAN-only indexing

当前 improved provider 只索引：

```text
CLEAN
或没有 cleaning status 的 Unit
```

明确排除：

```text
SUBJECTLESS
REJECTED
```

优点：

```text
减少脏 Unit 对 Recall 的污染
```

代价：

```text
部分 subjectless 但实际上可能有用的 Memory
永远不会进入当前 provider 的 Recall 空间
```

这是一个已知 Recall ceiling。

---

# 13. Astra 的 DEV 优化轨迹

Astra 的优化不是一次完成，而是经历多个阶段。

大致轨迹：

```text
initial
↓
refined
↓
relative threshold exploration
↓
identity / subject boundary refinement
↓
FINAL_CANDIDATE
```

值得注意的是：

> 某些阶段 config 参数没有变化，但 provider fingerprint 发生变化。

这说明 Astra 确实改了代码逻辑，而不只是参数搜索。

---

# 14. Threshold 选择

Astra 曾比较较宽松 threshold 与最终 threshold。

较宽松版本：

```text
relativeThreshold = 0.60
```

没有提高核心 Recall，却增加：

```text
false positives
returned unit count
```

最终选择：

```text
relativeThreshold = 0.78
```

选择依据是：

```text
保持最高 expected-unit recall / exact core recall
同时减少 false positives
提高 useful-context rate
```

---

# 15. 最终冻结信息

最终 provider：

```text
provider:
improved-recall

config:
1.0.0-final-candidate

limit:
8
```

Provider fingerprint：

```text
035bb4f78f6031a7fb99d2625d42bc0874f8f6c02101128e451d5a2238da4659
```

实现提交：

```text
ec485a69872b48360678e33aa8e8058398ac0579
```

最终报告提交：

```text
48c750e7f388e5bc88755bec1b4ea589c6b48ecf
```

Benchmark SHA256：

```text
0f87ba864fa5fe5a0ffdfd59e3b22f882d10079dc98e36ec44e6c36df06f268c
```

Cognitive Unit Store SHA256：

```text
92f5b405b10f00ba82c05f5f8197fc277966853d70499cbcd949d3ece7e34ef8
```

---

# 16. Benchmark Protocol

比较：

```text
lexical-top8
vs
improved-recall
```

固定：

```text
相同 Cognitive Unit Store
相同 benchmark cases
相同 gold
相同 limit=8
```

优化阶段：

```text
只使用 DEV
```

最终 TEST：

```text
Provider lock 后一次性执行
无 retry
fingerprint 必须匹配
```

TEST 启动后：

```text
重复 TEST 会被阻止
```

这保证了：

> TEST 没被用于继续调 provider。

---

# 17. DEV Benchmark — 50 cases

| Metric | lexical-top8 | improved-recall | Delta |
|---|---:|---:|---:|
| Expected-unit recall | 69.09% | **81.82%** | **+12.73 pp** |
| Exact core recall | 69.23% | **84.62%** | **+15.38 pp** |
| Useful-context rate | 12.18% | **22.17%** | **+9.99 pp** |
| Distractor rate | **1.71%** | 5.91% | **+4.20 pp regression** |
| False positives / memory case | 6.64 | **3.36** | **-3.28** |
| Negative rejection | 0% | **100%** | **+100 pp** |
| Mean returned units | 7.16 | **4.08** | **-3.08** |
| Mean recall latency | 13.43 ms | **1.80 ms** | **-11.63 ms** |

Expected-unit hits：

```text
baseline:
38 / 55

improved:
45 / 55
```

Memory-case total returned units：

```text
baseline:
350

improved:
203
```

---

# 18. TEST Benchmark — 150 cases

最终 TEST 在 provider lock 后一次性执行。

| Metric | lexical-top8 | improved-recall | Delta |
|---|---:|---:|---:|
| Expected-unit recall | 73.08% | **82.05%** | **+8.97 pp** |
| Exact core recall | 72.41% | **82.76%** | **+10.34 pp** |
| Useful-context rate | 12.28% | **21.77%** | **+9.48 pp** |
| Distractor rate | **1.64%** | 3.57% | **+1.93 pp regression** |
| False positives / memory case | 6.70 | **3.33** | **-3.36** |
| Negative rejection | 0% | **100%** | **+100 pp** |
| No-memory rejection | 58.33% | **83.33%** | **+25 pp** |
| Mean returned units | 7.19 | **3.93** | **-3.25** |
| Mean recall latency | 12.52 ms | **1.56 ms** | **-10.95 ms** |

Expected-unit hits：

```text
baseline:
114 / 156

improved:
128 / 156
```

Memory-case total returned units：

```text
baseline:
1038

improved:
588
```

---

# 19. TEST 的总体解释

最重要的变化不是单独某一个指标，而是以下变化同时发生：

```text
正确 Memory Recall ↑

完整核心 Recall ↑

Useful Context ↑

False Positive ↓

平均返回数量 ↓

Negative Rejection ↑

Latency ↓
```

也就是说 improved-recall 并不是：

```text
“少返回，所以 Precision 好看”
```

而是：

> **返回数量明显减少，同时正确 Recall 反而提高。**

这说明算法的 relevance discrimination 确实改善。

---

# 20. Generalization

DEV：

```text
Expected-unit recall
+12.73 pp
```

TEST：

```text
+8.97 pp
```

存在正常 generalization gap，但 TEST 仍保持明显优势。

因此当前结果比：

```text
只在 DEV 上优化成功
```

更可信。

---

# 21. 主要回归：Distractor

改进版本唯一明确保留下来的主要回归是：

```text
explicit distractor hits ↑
```

TEST：

```text
17 → 21
```

DEV：

```text
6 → 12
```

最明显的类别：

```text
DISTRACTOR_HEAVY
```

TEST expected-unit recall：

```text
baseline:
86.67%

improved:
73.33%
```

TEST distractor rate：

```text
baseline:
12.50%

improved:
17.05%
```

---

# 22. Distractor-heavy 的含义

这一类问题表明：

```text
Entity / Subject relevance
```

已经做得较强，

但：

```text
Aspect relevance
```

仍然不够稳定。

例如：

```text
Query:
NICEICK 玩什么？
```

系统已经知道：

```text
NICEICK
```

是目标主体。

但同主体下仍可能有：

```text
Nikon
黑白摄影
耳机
游戏
音乐
```

等多个 Memory aspect。

因此当前主要残留问题可以表述为：

> **Same-subject, different-aspect discrimination 仍然不足。**

---

# 23. 为什么不继续优化

最终选择冻结，而不是继续追求所有指标都改善。

原因：

```text
DEV 已被用于优化

TEST 已一次性运行

继续修改 provider
→ 会破坏 holdout 的实验意义
```

因此保留：

```text
distractor regression
```

而不在 TEST 后继续调参。

这也是最终报告可信度的重要组成部分。

---

# 24. 性能意义

TEST 平均 Recall latency：

```text
lexical-top8:
12.52 ms

improved-recall:
1.56 ms
```

当前 Store 规模约两千级 Cognitive Units 时：

> **Recall 本身已经非常便宜。**

这支持后续架构：

```text
每轮 LLM inference 前
自动执行 Ambient Recall
```

而不是必须：

```text
等待 LLM 主动发出 memory_recall Tool Call
```

真正昂贵的部分更可能是：

```text
LLM inference
+
进入 LLM context 的 Memory token 数
```

而不是 Memory 搜索本身。

---

# 25. 当前 Recall Provider 定位

现在可以将三个阶段明确区分：

```text
Baseline 0:
lexical-top8

传统固定预算 lexical retrieval
```

```text
Baseline 1:
improved-recall

强 lexical relevance
+ rejection
+ dynamic result count
```

未来：

```text
Associative Attention Recall

Context-conditioned
attention diffusion
memory emergence
```

---

# 26. Attention Memory 的未来比较门槛

后续 Attention / Associative Memory 不应该只与原始弱 baseline 比较。

真正应该挑战的是 frozen：

```text
improved-recall
```

当前 TEST 门槛：

```text
Expected-unit recall:
82.05%

Exact core recall:
82.76%

Negative rejection:
100%

Mean returned:
3.93

Mean latency:
1.56 ms
```

因此未来 Attention 模型如果要证明价值，至少需要在某些维度提供真实增益：

```text
更好的 multi-path recall
更好的 same-subject aspect discrimination
更好的 semantic paraphrase
更好的 temporal/context conditioning
更自然的 Memory emergence
更高 downstream LLM utility
```

而不是只做到：

```text
“能找出相关 Memory”
```

---

# 27. 与 Ambient Recall 的关系

本轮结果进一步支持：

```text
Current Context
↓
cheap automatic recall
↓
少量高相关 Cognitive Units
↓
LLM Working Context
```

当前 improved-recall 已经具备：

```text
低 latency
可空返回
动态数量
negative rejection
```

所以它实际上已经可以作为：

```text
Ambient Recall baseline
```

用于后续系统实验。

---

# 28. 仍未完成的部分

当前 benchmark 文件自身仍：

```json
"frozen": false
```

原因：

```text
annotation audit 尚未完成
```

因此：

```text
Provider freeze
✅

Provider TEST
✅

Formal benchmark annotation freeze
❌

Agent E2E
❌

Oracle
❌
```

当前 Recall TEST 应被准确称为：

> **provider-locked, pre-annotation-freeze Recall evaluation**

而不是最终论文级 benchmark。

---

# 29. 当前结论

本轮 Astra 优化成功将原始：

```text
simple lexical Top-K
```

升级为：

```text
query-decomposed
subject-aware
topic-gated
IDF-weighted
thresholded
reject-capable
dynamic-count
lexical retrieval policy
```

最核心的算法思想是：

> **Subject relevance 与 topical relevance 必须分离；“关于这个人”不能代替“关于当前问题”。**

Benchmark 显示：

```text
Recall ↑
Exact core ↑
Useful context ↑
False positive ↓
Returned count ↓
Negative rejection ↑
Latency ↓
```

同时保留一个清晰的弱点：

```text
DISTRACTOR_HEAVY
=
same-subject different-aspect discrimination
```

因此 `improved-recall` 适合作为后续：

```text
Associative Attention Memory
```

的冻结强 baseline。

---

# 30. 阶段冻结结论

```text
improved-recall
= FROZEN STRONG LEXICAL BASELINE
```

禁止：

```text
继续根据现有 TEST 调参数
修改 score
修改 threshold
针对 TEST case 加 special-case
```

未来如果需要新版本：

```text
另起 provider version
另开 DEV / benchmark protocol
```

不要覆盖当前 frozen candidate。

---

# 31. 一句话总结

> **Astra 没有把 Top-8 调得更漂亮，而是把“词面相似排序器”升级成了真正具有主体识别、主题判别、拒绝能力和动态返回数量的 Recall Policy；在冻结 TEST 上，它用更少的返回结果召回了更多正确 Memory，并由此成为后续 Associative Attention Memory 必须击败的强 baseline。**
