# 小天文 Memory 研究备忘录：从“检索记忆”到“有限注意力扩散与记忆涌现”

**日期：2026-09-21**  
**范围：小天文 Memory 模块**  
**状态：研究假设形成 / 尚未工程冻结**  
**前置模块状态：Episode Router P0、Episode Lifecycle P0 已完成并冻结**

---

# 0. 一句话结论

当前 Memory 设计开始从传统：

```text
Query
↓
Vector / RAG Retrieval
↓
Top-K Memories
↓
LLM
```

转向一种新的假设：

> **长期记忆不一定需要被“检索”；它可以被建模为有限总注意力在关联记忆网络中的动态扩散。当前上下文改变网络中的注意力分布，记忆通过竞争、多路径汇聚和阈值跨越自然“涌现”到 Working Memory。**

核心变化是：

```text
不是：
“系统应该取回哪几条记忆？”

而是：
“当前这个念头，会让有限注意力在记忆网络里如何重新分布？”
```

---

# 1. 当前 Memory 主线状态

目前 Memory Write Path（写入路径）前半段已经完成：

```text
Raw Event
↓
Episode Router P0
✅ DONE / FROZEN
↓
OPEN Episode
↓
Episode Lifecycle P0
✅ DONE / FROZEN
↓
CLOSED Episode
```

Router 负责：

> 当前 Event 属于哪个 Episode？

Lifecycle 负责：

> Episode 什么时候继续增长，什么时候 CLOSED？

当前已经决定：

```text
不继续优化 Router P0
不加入复杂 Reconciliation
不在 P0 做 Episode Merge / Split / Reassign
```

原计划下一阶段是：

```text
Final Consolidation P0
```

但本轮讨论后，Memory 后半段的设计思路发生了明显变化。

---

# 2. 最初问题：CLOSED Episode 之后怎么办？

最初有两种方向。

## 2.1 方向 A：每个 Episode CLOSED 后立即整理

例如：

```text
Episode:
小明最近一直在学 Blender
```

立即抽取：

```text
Semantic Memory:
小明正在学习 Blender
```

问题是：

- 单个 Episode 的信息可能只是偶发事件；
- 容易把一次经历过早固化为长期事实；
- 大量 Episode 会产生大量零散 Semantic Fact；
- 很容易退化成“聊天记录 → 事实句子 → 向量检索”的传统 RAG。

## 2.2 方向 B：Dream Consolidation（梦境式整理）

更合理的方向是：

```text
Episode CLOSED
↓
先作为 Episodic Memory 保存
↓
等待 Dream Cycle
↓
一段时间内多个 Episode 一起参与整理
↓
逐渐形成 / 修改 Semantic Memory
```

因此：

```text
Episode
= 发生过什么

Dream
= 对经历做长期整理

Semantic Memory
= 从经历中逐渐形成的稳定认识
```

这个结构比“每个 Episode CLOSED 立即抽事实”更自然。

---

# 3. Dream 不应该全量重放历史

如果每次 Dream 都：

```text
读取全部历史 Episode
↓
重新整理全部 Semantic Memory
```

那么成本会随系统年龄不断增长。

因此 Dream 必须倾向：

```text
Incremental Consolidation
增量巩固
```

即：

```text
New CLOSED Episodes
+
受这些新 Episode 影响的旧 Semantic Memory
↓
局部更新
```

而不是：

```text
全部 Episode
+
全部 Semantic Memory
↓
重建
```

这样 Dream 的成本更接近：

```text
本周期新增经历数量
+
受影响的局部记忆数量
```

而不是：

```text
系统历史总长度
```

---

# 4. 传统 Semantic Memory 的第一个问题：会退化成 RAG

假设将 Episode 交给 LLM：

```text
小明最近一直在学 Blender
```

整理成：

```text
小明 → 学习 → Blender
```

如果后续仍然：

```text
Embedding
↓
Vector DB
↓
Query
↓
Top-K
```

那么本质上只是：

```text
传统 RAG 的 Chunk
```

变成：

```text
结构化 Fact
```

仍然没有真正改变 Recall（回忆）的机制。

因此本轮形成一个重要判断：

> **Semantic Memory 的表示方式不是核心问题；真正决定系统是否还是传统 RAG 的，是 Read Path（记忆如何被想起来）。**

---

# 5. 第二个问题：实体归一并不能自然解决身份问题

例如：

```text
小明 → 学习 → Blender

张明 → 喜欢 → 天文摄影
```

但现实中：

```text
小明 = 张明
```

如果 Memory Graph 直接把字符串当节点：

```text
小明        张明
 │           │
Blender     天文摄影
```

两部分网络会断开。

传统做法是：

```text
Entity Resolution
↓
Canonical ID
↓
person_123
```

但在现有 IRIS 类记忆机制中，这类 Entity / Alias → ID 机制效果往往不稳定。

原因之一是：

> **语义相似度并不等于身份同一性。**

例如：

```text
“小明”
“张明”
“部长”
“@123456”
“昨天拿赤道仪的人”
```

文本语义可能完全不同，却可能指向同一人。

而：

```text
“小明”
“小明”
```

完全一样的字符串，也可能指向不同的人。

因此 embedding 本身不是 Identity 判断器。

---

# 6. 是否把 Identity 独立成模块？

讨论过两条路线。

## 6.1 独立 Identity Module

会引入：

```text
alias
same_as
refers_to
confidence
merge
unmerge
context-specific identity
identity conflict
```

优点：

- 身份归一明确；
- 图结构更干净。

缺点：

- 系统复杂度显著上升；
- 错误 merge 会污染整张图；
- 需要维护大量身份推理逻辑；
- 很可能重复 IRIS 已经存在但效果不佳的问题。

## 6.2 Identity 作为普通 Semantic Relation

例如：

```text
小明 ──refers_to── 张明
张明 ──has_account── qq:123456
张明 ──learns── Blender
```

身份关系：

```text
refers_to
same_as
alias_of
```

暂时与：

```text
likes
learns
owns
member_of
```

处于同一 Semantic Memory / Graph 层。

这样：

- 不强制 merge；
- 关系可修订；
- 错误不会直接污染全部事实；
- 后续 Recall 可以沿这些关系传播。

当前倾向：

> **P0 不把 Identity 做成独立 Memory Module。**

只有当后续 benchmark 明确证明：

```text
大量 Recall 错误
=
身份断裂导致
```

再考虑 Identity P1。

---

# 7. 一个更重要的转折：Memory Graph 不一定是传统知识图谱

之前默认的图结构是：

```text
Entity
──relation──
Entity
```

例如：

```text
小明
 └─learns→ Blender
```

但本轮讨论后，开始倾向另一种理解：

> **Memory Graph 更像 Associative Memory Network（联想记忆网络），而不是静态 Knowledge Graph（知识图谱）。**

它的核心不一定是：

```text
主语 → 谓语 → 宾语
```

而可能是：

```text
Cue
↓
Memory
↓
Cue
↓
Memory
```

例如：

```text
张明
↓
Memory B:
“张明平时被叫作小明”
↓
小明
↓
Memory A:
“小明最近在学 Blender”
↓
Blender
```

这样：

```text
张明
```

可以通过联想传播逐渐“想到”：

```text
小明
→ Blender
```

不需要提前执行：

```text
张明 = 小明
```

的硬合并。

---

# 8. Weak Relation（弱联系）并不一定是问题

最初担忧：

> 如果身份、概念、事件之间只用弱关系连接，会不会导致 Recall 不稳定？

后来形成的判断：

> **弱联系本身不是问题；关键在于弱联系如何参与 Recall。**

人类记忆本身也不是：

```text
所有概念都有确定、唯一、永久 ID
```

更多时候是：

```text
“这个名字好像是那个人”
“提到这个人我会想到 Blender”
“这件事让我隐约想到另一次经历”
```

因此，Memory Graph 可以允许：

```text
strong relation
weak relation
uncertain relation
contextual relation
```

长期共存。

一个重要原则：

> **弱关系可以影响“想到什么”，但不能单独决定“什么是真的”。**

即：

```text
Weak Relation
→ Recall Path

Weak Relation
≠ Truth Rewrite
```

例如：

```text
小明 ──same_as(0.55)── 张明
张明 ──likes── 咖啡
```

可以允许查询“小明”时：

```text
张明喜欢咖啡
```

作为候选记忆被激活。

但不能直接在 Storage 中写成：

```text
小明喜欢咖啡
```

---

# 9. 每条记忆内部可以有不同 Cue Weight

对于一条 Memory：

```text
M17:
“小明近期持续学习 Blender”
```

可以给其中不同 Cue（线索）不同权重：

```text
小明        0.38
Blender     0.34
3D建模      0.16
学习        0.12
----------------
sum         1.00
```

这些权重不表示：

```text
“小明比 Blender 更重要”
```

而表示：

> **这条 Memory 更容易被哪些线索唤起。**

因此更合适的名字可能是：

```text
Cue Weight
Salience
Associative Weight
```

而不是简单叫：

```text
Importance
```

---

# 10. Cue Weight 与 Memory Strength 应分开

如果：

```text
Memory A:
“小明正在学 Blender”

Cue:
小明 = 0.4
```

另一条：

```text
Memory B:
“小明昨天买了一瓶可乐”

Cue:
小明 = 0.6
```

不能因为：

```text
0.6 > 0.4
```

就意味着提到“小明”首先想起买可乐。

还需要另一个量：

```text
Memory Strength
```

表示：

> 这条 Memory 本身目前有多容易被想起来。

例如：

```text
M17 strength = 0.85
M18 strength = 0.20
```

概念上：

```text
Activation
≈ Cue Match
× Cue Weight
× Memory Strength
× Context Match
```

P0 暂时不必冻结公式。

---

# 11. 真正的重要转折：Memory Retrieval 可能不是“检索”

本轮最重要的概念变化是：

```text
Retrieval
```

可能不是最准确的词。

传统 Retrieval：

```text
Query
↓
Search
↓
Top-K
```

当前方向：

```text
Current Context
↓
形成当前注意力中心
↓
激活一部分节点
↓
注意力沿关联网络扩散
↓
节点之间竞争
↓
部分节点获得足够注意力
↓
Memory Emergence
```

更接近：

```text
Associative Activation
Spreading Activation
Attention Diffusion
Memory Emergence
```

即：

> **不是去记忆库里查“我记得什么”，而是当前念头使整个记忆网络的局部注意力重新分布，从而让相关记忆浮现。**

---

# 12. 每次 Recall 有一个 Context Center

每次 Recall 都应该有：

```text
Context Center
```

它表示：

> Agent 当前正在“想什么”。

但这个中心不一定是长期图中的某个已有节点。

例如：

```text
“小明最近还在学 Blender 吗？”
```

可以形成一个临时 Context Center：

```text
             Current Context
               /        \
             小明      Blender
```

Context Center：

```text
只存在于当前时刻
不一定写入长期 Memory
```

它可以触发多个：

```text
Seed Nodes
```

例如：

```text
小明
Blender
最近
学习
```

---

# 13. 核心假设：Agent 的总注意力应该是有限常数

用户提出的关键假设：

> **每个激活节点获得的注意力不同，因此能继续扩散出去的节点数量也不同；但在任意时刻，Agent 的总注意力应该是一个固定总量。**

形式化：

\[
\sum_i A_i(t)=A_{\text{total}}
\]

其中：

```text
A_total
= Agent 当前总注意力状态
```

```text
A_i(t)
= 时刻 t，节点 i 占有的注意力份额
```

例如：

```text
Total Attention = 1.0

小明        0.40
Blender     0.27
天文社      0.18
摄影        0.10
咖啡        0.05
----------------
            1.00
```

---

# 14. 这个假设带来的直接结果

注意力较高的节点：

```text
有能力维持更多有效关联
可以使更多邻居跨过激活阈值
```

注意力较低的节点：

```text
只够维持自己
或者只够激活一个很强关联
```

因此：

```text
Attention 高
→ 有效扩散分支较多

Attention 低
→ 有效扩散分支较少

Attention 极低
→ 不再继续扩散
```

于是 Recall 边界不再依赖：

```text
固定 Top-K
固定 hop 数
```

而由有限注意力自然形成。

---

# 15. Memory Graph 可以无限增长，但 Working Attention 不增长

即使未来：

```text
Memory Nodes = 1,000,000
```

只要：

```text
Σ Attention = constant
```

Agent 当前真正能够高强度激活的节点数量仍然有限。

因此：

> **长期记忆容量可以不断增长，但当前认知带宽始终有限。**

这比：

```text
Memory 越多
→ 每次检索扫描越多
```

更接近我们想要的长期 Agent 行为。

---

# 16. Significance / Association Strength 与 Attention 不是同一个东西

需要明确区分。

## 16.1 Association Strength / Significance

长期量。

表示：

> 两个节点平时有多强的关联。

例如：

```text
小明 ↔ Blender = strong
小明 ↔ 咖啡 = weak
```

它类似：

```text
道路本身有多宽
```

## 16.2 Attention

瞬时量。

表示：

> Agent 当前有多少注意力放在这个节点上。

例如：

```text
t = now

小明 = 0.42
Blender = 0.31
```

它类似：

```text
当前道路上有多少流量
```

因此：

```text
Association
决定注意力倾向往哪里流

Attention
决定当前到底有多少东西有能力继续被激活
```

---

# 17. 多路径汇聚是“涌现”的核心

假设：

```text
A → X
B → X
C → X
```

每一条边单独都很弱：

```text
A → X = 0.04
B → X = 0.06
C → X = 0.08
```

如果：

```text
A
B
C
```

在当前 Context 中同时被激活，那么：

```text
X
```

可能接收到：

```text
0.04 + 0.06 + 0.08 = 0.18
```

于是跨过 Emergence Threshold：

```text
X suddenly emerges
```

这对应非常直观的人类体验：

> “等等，我突然想起来了。”

因此真正有趣的不是：

```text
某一条边很强
```

而是：

> **多个局部弱关联可以通过注意力汇聚共同使一个记忆浮现。**

---

# 18. Recall 与 Activation 不应完全等价

可以区分：

```text
Activation
=
某节点在网络里获得了一定注意力
```

和：

```text
Emergence / Recall
=
该节点真正进入 Working Memory
```

例如：

```text
M1 = 0.41
M2 = 0.25
M3 = 0.14
M4 = 0.08
M5 = 0.04
```

假设：

```text
Emergence Threshold = 0.10
```

真正浮现：

```text
M1
M2
M3
```

而：

```text
M4
M5
```

可能只是参与了潜在传播，但没有真正进入意识层。

---

# 19. 如何统一不同关系的“量纲”

不同原始证据天然不同：

```text
出现次数          7 次
语义相似度        0.82
最近出现时间      3 天前
reply relation     true
模型判断置信度    0.7
```

这些不能直接相加。

因此提出三层结构。

## Layer 1：Evidence

原始异构信号：

```text
frequency
recency
reply
semantic similarity
explicit relation
episode evidence
LLM / JEV judgment
```

各自有自己的单位和含义。

## Layer 2：Association Score

每一种原始 Evidence 经过自己的 Calibration Function（校准函数）：

```text
frequency
→ f_frequency

recency
→ f_recency

semantic
→ f_semantic

explicit relation
→ f_explicit
```

映射成统一的：

```text
S(i,j)
= Association Score / Association Logit
```

它是无量纲内部值。

不要把它理解成严格概率。

## Layer 3：Attention Share

真正进入注意力传播时，将一组 Association Score 归一化。

例如可使用：

\[
P_{ij}
=
\frac{e^{S_{ij}/T}}
{\sum_k e^{S_{ik}/T}}
\]

即：

```text
Softmax
```

这样：

\[
\sum_j P_{ij}=1
\]

其中：

```text
P(i→j)
```

表示：

> 节点 i 当前有多少比例的可传播注意力倾向流向 j。

此时所有关系最终统一到一个无量纲比例。

---

# 20. Attention Transition Matrix

如果整个 Graph 的转移比例写成：

```text
P
```

当前注意力分布写成：

```text
A_t
```

那么最简单形式：

\[
A_{t+1}=P^T A_t
\]

如果：

```text
P 每一行和为 1
```

那么：

\[
\sum_i A_i(t+1)=\sum_i A_i(t)
\]

即：

> **总注意力守恒。**

---

# 21. Context Center 需要持续提供锚定

如果只做纯扩散：

\[
A_{t+1}=P^T A_t
\]

注意力可能逐渐漂离当前话题。

因此更合理的形式可能是：

\[
A_{t+1}
=
\alpha P^T A_t
+
(1-\alpha)C
\]

其中：

```text
C
= 当前 Context Center 对节点的注意力分布
```

例如：

```text
用户：
“小明最近还学 Blender 吗？”

C:
小明      0.55
Blender   0.45
```

如果：

```text
α = 0.8
```

则：

```text
80%
由长期联想网络决定

20%
持续被当前上下文重新锚定
```

只要：

```text
ΣA = 1
ΣC = 1
```

总注意力仍然保持固定。

---

# 22. Attention Temperature

Softmax 中的：

```text
T
```

可以解释为：

```text
Attention Temperature
注意力温度
```

低温：

```text
最强关系获得绝大部分注意力
```

对应：

```text
专注
收敛
```

高温：

```text
多个关系同时获得较多注意力
```

对应：

```text
发散
联想
探索
```

未来可能：

```text
专注工作
→ lower temperature

闲聊
→ medium temperature

Dream
→ higher temperature
```

但目前不冻结参数。

---

# 23. 一个非常重要的理论区别

传统 RAG 固定的是：

```text
返回几条
top_k = 8
```

当前模型固定的是：

```text
总认知资源
Σ Attention = constant
```

因此可能出现：

### 情况 A

```text
Memory A = 0.78
Memory B = 0.12
其他很弱
```

表现：

> “一提到这个，我第一个想到的就是 A。”

### 情况 B

```text
A = 0.21
B = 0.18
C = 0.16
D = 0.12
```

表现：

> “这个东西会同时让我想到好几件事。”

### 情况 C

多个弱关联：

```text
A ─┐
B ─┼──→ X
C ─┘
```

同时汇聚后：

```text
X suddenly rises
```

表现：

> “等等，我突然想起来了。”

这些行为不是通过：

```text
if / else
```

硬编码出来的，而是由网络动力学产生。

---

# 24. 因此 Recall 更像 Dynamic System，而不是 Search

传统形式：

\[
Recall(q)=TopK(M,q)
\]

当前假设：

\[
A_{t+1}=F(A_t,C_t,G)
\]

其中：

```text
A_t
= 当前注意力状态

C_t
= 当前 Context

G
= 长期 Associative Memory Graph

F
= 注意力重新分布过程
```

然后：

\[
Memory_i\ emerges
\quad if \quad
A_i > \theta
\]

因此 Memory Recall 被重新描述为：

```text
一个状态随时间变化的动态系统
```

而不是：

```text
一次数据库查询
```

---

# 25. 当前形成的核心术语

建议暂时使用：

```text
Associative Memory Network
联想记忆网络
```

```text
Global Attention State
全局注意力状态
```

```text
Attention Diffusion
注意力扩散
```

```text
Association Strength
关联强度
```

```text
Context Center
当前上下文中心
```

```text
Seed Nodes
种子节点
```

```text
Emergence Threshold
涌现阈值
```

```text
Memory Emergence
记忆涌现
```

```text
Working Memory
工作记忆 / 当前意识记忆
```

---

# 26. 当前核心研究假设

英文版：

> **Long-term agent recall can be modeled as constrained attention diffusion over an associative memory network: a fixed global attention state is redistributed by context and learned associations, and memories are recalled when they emerge through competition and multi-path convergence rather than being selected by fixed Top-K retrieval.**

中文版：

> **长期 Agent 记忆可以被建模为有限全局注意力在关联记忆网络中的动态扩散：当前上下文与长期关联共同重新分配有限注意力，记忆通过竞争与多路径汇聚自然涌现，而不是由固定 Top-K 检索选出。**

---

# 27. 与传统 RAG 的本质区别

## Traditional RAG

```text
Query
↓
Embedding
↓
Similarity Search
↓
Top-K
↓
Context
```

核心问题：

> 哪些存储项和 Query 最相似？

## 当前假设

```text
Current Context
↓
Context Center
↓
Initial Attention
↓
Associative Network
↓
Attention Diffusion
↓
Competition / Convergence
↓
Emergence
↓
Working Memory
```

核心问题：

> 当前这个念头会如何改变有限注意力在整个局部记忆网络中的分布？

---

# 28. 与传统 Knowledge Graph 的区别

传统 Knowledge Graph 更强调：

```text
A --relation--> B
```

表示一个相对确定的结构化事实。

当前 Associative Memory Network 更强调：

```text
A --association strength--> B
```

表示：

> A 和 B 在长期记忆中有多强的联想关系。

它允许：

```text
不确定
弱关系
变化
强化
衰减
上下文相关
```

因此 Graph 更像：

```text
belief / association network
```

而不是静态事实数据库。

---

# 29. Dream 的角色也因此改变

Dream 不应该只是：

```text
Episode
↓
LLM Summary
↓
Semantic Fact
```

而更可能是：

```text
Recent Closed Episodes
↓
发现新的 Cue / Memory / Relation
↓
强化已有 Association
↓
削弱过时 Association
↓
发现冲突
↓
形成新的多节点联结
↓
更新 Associative Memory Network
```

也就是说：

> **Dream 更像 Memory Network Learning，而不是文本总结。**

---

# 30. Dream 与 Recall 的分工

## Dream

慢路径。

负责：

```text
学习网络结构
更新长期关系
强化
衰减
冲突
重组
```

## Recall / Emergence

快路径。

负责：

```text
当前 Context
↓
在已经学习好的关联网络上扩散 Attention
↓
形成 Working Memory
```

这使：

```text
Learning
```

和：

```text
Thinking / Remembering
```

分离。

---

# 31. 身份问题在新框架中的位置

当前不需要：

```text
Identity Module
```

也不需要立即：

```text
Canonical Merge
```

可以先让：

```text
小明
张明
qq:123456
```

作为不同节点存在。

它们之间通过：

```text
refers_to
same_as
alias_of
co-occurs_with
```

等关联连接。

身份关系与其他关系一样：

```text
可以强
可以弱
可以变化
可以被反证
```

在 Recall 时：

```text
张明
↓
小明
↓
Blender
```

可以通过扩散自然连通。

如果未来 benchmark 证明身份碎片是主要瓶颈，再单独升级 Identity P1。

---

# 32. “弱关系”的安全原则

必须坚持：

> **Association can affect recall, but cannot automatically rewrite truth.**

中文：

> **联想关系可以影响“想到什么”，但不能自动改写“什么是真的”。**

例如：

```text
小明 --same_as(0.55)--> 张明
```

可以允许：

```text
张明的相关 Memory
```

在查询“小明”时获得一定 Attention。

但不能直接复制：

```text
张明的所有事实
```

到：

```text
小明
```

名下。

---

# 33. 当前最有价值的 Demo 不应该先做完整 Memory

下一步最适合的工程目标：

```text
Attention Diffusion Toy Demo
```

只需要：

```text
20～50 个节点
少量手工 Relation
手工 Association Strength
```

不需要：

```text
LLM
Dream
真实群聊
完整 Semantic Extraction
```

只验证一件事：

> **有限总注意力 + 关联扩散 + 多路径汇聚，能不能产生我们期待的 Recall 行为？**

---

# 34. Toy Demo 建议场景

手工建立：

```text
小明
张明
Blender
天文社
咖啡
摄影
赤道仪
木星

Memory A
Memory B
Memory C
...
```

例如：

```text
小明 ↔ 张明
小明 ↔ Blender
张明 ↔ 天文社
Blender ↔ 3D建模
天文社 ↔ 摄影
```

输入：

```text
“小明最近在干什么？”
```

可视化：

```text
t0
小明 = 0.60
最近 = 0.20
其他 = 0.20

t1
张明 = 0.22
Blender = 0.18
天文社 = 0.10

t2
Memory X = 0.27
```

如果：

```text
Memory X
```

因为多条路径汇聚跨过阈值：

```text
EMERGED
```

则 Demo 已经验证最核心动力学。

---

# 35. Demo 最应该可视化什么

建议 UI 至少显示：

```text
Node
Current Attention
Association Strength
Incoming Attention
Outgoing Attention
Emergence State
```

并支持按时间步：

```text
t0
t1
t2
t3
```

查看 Attention 如何流动。

最理想效果：

> 用户可以亲眼看到某个原本不显眼的 Memory，因为多个弱路径同时汇聚而突然被点亮。

---

# 36. 最小 Benchmark 方向

未来可以比较：

```text
Vector Top-K
vs
Graph Top-K
vs
普通 Spreading Activation
vs
Global-Attention Emergence
```

---

# 37. 建议测试任务

## 37.1 Direct Recall

```text
一个 Query
直接对应一个事实
```

看是否至少不弱于传统 retrieval。

## 37.2 Alias / Name Fragmentation

例如：

```text
小明
张明
```

没有 canonical merge。

测试：

> 是否仍能通过关联扩散想起另一侧 Memory？

## 37.3 Multi-Hop

```text
A → B → C
```

测试：

> 多跳是否能自然发生，同时避免无限漂移？

## 37.4 Multi-Path Convergence

```text
A → X
B → X
C → X
```

每条边单独不足。

测试：

> A+B+C 同时出现时，X 是否自然涌现？

这是非常关键的 benchmark。

## 37.5 Distractor Noise

加入大量：

```text
语义上相关
但实际上无关
```

的节点。

测试：

> 有限 Attention 是否比 Top-K 更抗噪？

## 37.6 Scale

逐渐扩大：

```text
1k
10k
100k
Memory Nodes
```

测试：

```text
Recall latency
active subgraph size
attention concentration
accuracy
```

是否保持可控。

---

# 38. 当前需要警惕的风险

## 38.1 Attention Hub Problem

高连接节点：

```text
人
软件
天文
学校
```

可能因为 Degree 太高吸走大量 Attention。

需要未来考虑：

```text
degree normalization
hub penalty
```

但 P0 暂时不冻结。

## 38.2 Attention Dilution

某节点有：

```text
1000 个邻居
```

如果平均分配，真正重要关联可能变得过弱。

因此：

```text
relative share
```

和：

```text
absolute relation strength
```

可能需要分开。

## 38.3 Cycles

例如：

```text
小明 ↔ Blender
```

Attention 可能循环。

需要：

```text
decay
context anchoring
visited suppression
inhibition
```

中的一种或多种。

P0 暂时只做最简单控制。

## 38.4 Over-Diffusion

网络可能：

```text
小明
→ Blender
→ 3D建模
→ Maya
→ 软件
→ 程序员
→ ...
```

逐渐偏离 Context。

需要：

```text
Context Center reinjection
```

保持当前主题锚定。

## 38.5 Relation Calibration

不同来源的 Association：

```text
LLM
co-occurrence
reply
frequency
explicit statement
```

如何校准成统一 S(i,j)，仍是开放问题。

## 38.6 Emergence Threshold

阈值太低：

```text
想到太多
```

阈值太高：

```text
什么都想不起来
```

需要通过 benchmark 校准。

---

# 39. 当前不应该立刻做的事情

暂时不要：

```text
设计完整 Identity System
做复杂 Dream Scheduler
做全量 Memory Graph
做 Semantic Ontology
做几十种 Relation Type
做长期自动衰减规则
做完整 Cognitive Architecture
```

因为这些都会把最重要的假设淹没。

现在最优先验证：

```text
Global Attention Conservation
+
Association Diffusion
+
Multi-Path Convergence
+
Emergence
```

是否真的产生有价值的 Recall 行为。

---

# 40. 当前最小研究路线

## Phase 0

```text
Router P0
✅ DONE

Lifecycle P0
✅ DONE
```

## Phase 1

```text
Attention Diffusion Toy Demo
```

目标：

> 验证核心动力学。

## Phase 2

接入真实：

```text
Episode
Semantic Memory
```

目标：

> 验证图结构能否由真实 Memory 支撑。

## Phase 3

```text
Dream Consolidation
```

目标：

> 让 Relation Strength / Cue Weight 不再手工设置，而是由经历逐渐学习。

## Phase 4

```text
Benchmark
```

比较：

```text
Vector Retrieval
Graph Retrieval
Spreading Activation
Attention Emergence
```

---

# 41. 一个可能的论文问题

不是：

> Graph Memory 是否优于 RAG？

而是：

> **当长期 Agent Memory 被建模为有限认知资源下的动态关联网络时，是否能产生比固定 Top-K Retrieval 更稳定、更自然、更具多路径联想能力的 Recall？**

或者更具体：

> **Can constrained global attention diffusion over an associative memory network produce more robust long-term agent recall than fixed Top-K retrieval, particularly under alias fragmentation, multi-hop dependencies, and multi-path convergence?**

---

# 42. 当前最重要的创新候选点

注意：以下是“研究贡献候选”，尚未经过完整文献查重，不应现在宣称原创。

可能的贡献组合包括：

```text
1. Persistent Global Attention State
   全局注意力不是一次 Query 的临时分数，
   而是 Agent 当前持续存在的认知状态。

2. Attention Conservation / Competition
   总注意力固定，
   所有 Memory 节点竞争有限认知资源。

3. Emergence instead of Fixed Top-K
   Recall 数量不是人工指定，
   而由注意力竞争自然决定。

4. Multi-Path Convergence
   多条弱关系可以共同使一个 Memory 突然涌现。

5. Episodic-to-Associative Learning
   CLOSED Episodes 通过 Dream 更新长期关联网络。

6. Weak Identity as Association
   不要求所有别名预先 canonical merge，
   而允许身份关系通过普通关联参与 Recall。
```

真正是否具有论文 novelty（新颖性），必须后续系统性文献检索确认。

---

# 43. 当前最重要的哲学变化

过去：

```text
Memory
=
存储 + 搜索
```

现在：

```text
Memory
=
长期关联结构
+
有限注意力状态
+
动态扩散
+
自然涌现
```

过去：

```text
Recall
=
找到最相似的几条
```

现在：

```text
Recall
=
当前 Context 改变注意力分布，
相关 Memory 在竞争中浮现
```

---

# 44. 最简洁的一句话

> **不是从记忆库里“搜出”几条记忆，而是让有限的注意力在关联网络中流动，让最相关的记忆自己浮现出来。**

---

# 45. 更正式的一句话

> **Memory Retrieval is reframed as constrained attention diffusion over an associative memory network, where a fixed global attention state is redistributed by context and learned associations, and recall occurs through competitive emergence rather than fixed Top-K selection.**

---

# 46. 当前状态判断

现在还不能说：

```text
Attention Emergence Memory
= DONE
```

更准确是：

```text
Research Hypothesis
= FORMULATED

Mathematical Skeleton
= FIRST DRAFT

Toy Demo
= NEXT

Benchmark
= NOT STARTED

Novelty Verification
= NOT COMPLETE
```

---

# 47. 下一步

当前最值得做的事情不是继续扩展架构，而是：

```text
构造一个 20～50 节点的小型 Attention Diffusion Demo
```

只验证：

```text
固定总 Attention
+
Association Strength
+
Context Center
+
多路径汇聚
+
Emergence Threshold
```

能否产生直观、有解释力的 Recall 行为。

如果这个 Demo 跑出来以后确实出现：

> “它不是被搜出来的，而是真的在网络里被逐步想起来了。”

那么再继续：

```text
真实 Episode
↓
Dream
↓
Associative Memory Network
```

才有工程意义。

---

# 48. 当前总览

```text
                 MEMORY WRITE PATH
────────────────────────────────────────

Raw Event
   ↓
Episode Router P0
   ✅ FROZEN
   ↓
OPEN Episode
   ↓
Episode Lifecycle P0
   ✅ FROZEN
   ↓
CLOSED Episode
   ↓
Episodic Store


             MEMORY LEARNING PATH
────────────────────────────────────────

Recent CLOSED Episodes
   ↓
Dream Consolidation
   ↓
Cue / Memory / Relation Learning
   ↓
Associative Memory Network


              MEMORY READ PATH
────────────────────────────────────────

Current Context
   ↓
Context Center
   ↓
Seed Attention
   ↓
Global Attention Diffusion
   ↓
Competition + Multi-Path Convergence
   ↓
Memory Emergence
   ↓
Working Memory
   ↓
Agent Response
```

---

# 49. 当前最核心原则

> **不要预先规定 Agent 应该“检索”哪几条记忆。**

而是：

> **给 Agent 一份有限的全局注意力，让当前上下文改变这份注意力在关联网络中的分布，让真正相关的记忆自己竞争着浮现。**

这可能是当前小天文 Memory 项目最值得继续验证的核心假设。
