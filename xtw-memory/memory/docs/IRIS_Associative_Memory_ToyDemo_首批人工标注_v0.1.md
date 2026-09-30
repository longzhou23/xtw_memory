# IRIS → Associative Memory Toy Demo：首批人工标注集

**日期：2026-09-21**  
**来源：`iris_full_backup_2026-09-21.json`**  
**用途：有限总注意力 + 关联扩散 + 多路径汇聚 + Memory Emergence 的 Toy Demo**  
**状态：人工研究标注 v0.1**

> 说明：
>
> 1. 本文件不是在定义最终 Memory Schema。
> 2. `association_prior` 是为了跑第一版 demo 人工给出的初始关联强度，不是真值，不是概率。
> 3. IRIS 原有的 `confidence` 与这里的 `association_prior` 是不同量纲，不能直接混用。
> 4. 节点类型保持开放：Person / Alias / Memory / Preference / Concept / Location / Object / Activity / Goal 都可以进入同一 Associative Layer。
> 5. 这一批故意选择了：别名、重复记忆、异构节点、多路径汇聚、同地点不同人物、弱关联与干扰项。

---

# 1. 建议的最小标注格式

```yaml
node:
  id:
  type:
  label:
  source_memory_ids: []

edge:
  from:
  to:
  relation:
  association_prior: 0.0-1.0
  evidence:
  note:

recall_case:
  context:
  seed_nodes: []
  expected_emergence: []
  distractors: []
  challenge_tags: []
```

`association_prior` 暂时只表示：

> 在没有自动学习算法之前，这两个认知对象之间“应该有多容易互相激活”。

它不是事实置信度。

---

# 2. Cluster A — NICEICK：最适合验证别名 + 兴趣网络 + 多路径汇聚

## 2.1 为什么选这一簇

IRIS 中 `2960945437 / NICEICK / 心象蜃気楼` 已经天然形成一个复杂人物簇，并且同时连接：

- 舞萌
- 《世界计划》
- 星乃一歌
- Leo/need
- n-buna
- 胶片摄影
- 诗歌 / 歌词
- 《Flyway》

这非常适合验证：

```text
不同名字
+
不同兴趣入口
+
多条弱路径
→
是否能让同一片记忆自然浮现
```

## 2.2 来源记忆

- `person_a36a09a3f60b`
  - 用户 `2960945437`
  - 昵称包括 `NICEICK`、`心象蜃気楼`
  - 与舞萌、胶片摄影、诗歌歌词、星乃一歌、n-buna、《世界计划》均有长期关联
- `preference_b4752fbc0603`
  - NICEICK 喜欢分享以爱情、孤独、自由为主题的诗歌和歌词
- `preference_01f4e4556585`
  - NICEICK 喜欢玩《世界计划》（pjsk）
- `preference_b630fb62758b`
  - NICEICK 喜欢或愿意推荐《Flyway》
- `preference_2d3cfc04443f`
  - 《世界计划》是 NICEICK 持续游玩的音乐节奏类游戏
- `preference_eb382bcda55f`
  - NICEICK 偏好 Leo/need 及相关角色
- `mem_cc37a9bcc0f2`
  - NICEICK 在《世界计划》中喜欢星乃一歌
- `mem_5bf5f6b7f25d`
  - NICEICK 喜欢《世界计划》及星乃一歌，并期待相关大娃
- `mem_46cfe3953a0c`
  - NICEICK 关注 Leo/need

## 2.3 Nodes

```yaml
- id: person:2960945437
  type: Person
  label: "2960945437"

- id: alias:niceick
  type: Alias
  label: "NICEICK"

- id: alias:xinxiang_shenqilou
  type: Alias
  label: "心象蜃気楼"

- id: concept:maimai
  type: Concept
  label: "舞萌 / maimai"

- id: game:pjsk
  type: Concept
  label: "世界计划 / Project Sekai"

- id: character:ichika
  type: Concept
  label: "星乃一歌"

- id: concept:leo_need
  type: Concept
  label: "Leo/need"

- id: artist:n_buna
  type: Concept
  label: "n-buna"

- id: activity:film_photography
  type: Activity
  label: "胶片摄影"

- id: concept:poetry_lyrics
  type: Concept
  label: "爱情 / 孤独 / 自由主题的诗歌歌词"

- id: song:flyway
  type: Concept
  label: "Flyway"

- id: memory:niceick_pjsk_ichika
  type: Memory
  label: "NICEICK喜欢《世界计划》中的星乃一歌"

- id: memory:niceick_poetry
  type: Memory
  label: "NICEICK喜欢分享爱情、孤独、自由主题的诗歌和歌词"
```

## 2.4 Edges — demo priors

```yaml
- from: alias:niceick
  to: person:2960945437
  relation: refers_to
  association_prior: 0.95

- from: alias:xinxiang_shenqilou
  to: person:2960945437
  relation: refers_to
  association_prior: 0.82

- from: person:2960945437
  to: game:pjsk
  relation: plays
  association_prior: 0.88

- from: person:2960945437
  to: concept:maimai
  relation: plays
  association_prior: 0.78

- from: person:2960945437
  to: activity:film_photography
  relation: engages_in
  association_prior: 0.62

- from: person:2960945437
  to: artist:n_buna
  relation: likes
  association_prior: 0.72

- from: person:2960945437
  to: concept:poetry_lyrics
  relation: likes
  association_prior: 0.68

- from: game:pjsk
  to: character:ichika
  relation: contains_character
  association_prior: 0.76

- from: game:pjsk
  to: concept:leo_need
  relation: contains_group
  association_prior: 0.79

- from: concept:leo_need
  to: character:ichika
  relation: member
  association_prior: 0.90

- from: person:2960945437
  to: character:ichika
  relation: likes
  association_prior: 0.86

- from: person:2960945437
  to: song:flyway
  relation: likes_or_recommends
  association_prior: 0.55

- from: memory:niceick_pjsk_ichika
  to: alias:niceick
  relation: cue
  association_prior: 0.34

- from: memory:niceick_pjsk_ichika
  to: game:pjsk
  relation: cue
  association_prior: 0.32

- from: memory:niceick_pjsk_ichika
  to: character:ichika
  relation: cue
  association_prior: 0.34

- from: memory:niceick_poetry
  to: alias:niceick
  relation: cue
  association_prior: 0.45

- from: memory:niceick_poetry
  to: concept:poetry_lyrics
  relation: cue
  association_prior: 0.55
```

## 2.5 Recall Cases

### Case A1 — Alias Bridge

```yaml
context: "心象蜃気楼平时玩什么？"
seed_nodes:
  - alias:xinxiang_shenqilou

expected_emergence:
  - person:2960945437
  - game:pjsk
  - concept:maimai

challenge_tags:
  - alias_fragmentation
  - no_canonical_merge
```

目标：

> 不提前把“心象蜃気楼”硬合并成 NICEICK，仍然可以沿弱/强关联想到其游戏兴趣。

---

### Case A2 — Multi-path Convergence

```yaml
context: "NICEICK 世界计划 一歌"
seed_nodes:
  - alias:niceick
  - game:pjsk
  - character:ichika

expected_emergence:
  - memory:niceick_pjsk_ichika

challenge_tags:
  - multi_seed
  - multi_path_convergence
```

这个 case 是首批 demo 最重要的一个。

单独：

```text
NICEICK → Memory
世界计划 → Memory
一歌 → Memory
```

每条路径可以都不够强。

但三路 Attention 同时汇聚到：

```text
memory:niceick_pjsk_ichika
```

时，它应该突然跨过 Emergence Threshold。

---

### Case A3 — Related but not dominant

```yaml
context: "NICEICK最近在拍什么？"
seed_nodes:
  - alias:niceick
  - activity:film_photography

expected_emergence:
  - activity:film_photography

distractors:
  - character:ichika
  - game:pjsk

challenge_tags:
  - context_specific_competition
```

虽然 NICEICK 与《世界计划》的关联非常强，但当前 Context 的“拍”应该让摄影分支获得更多 Attention。

---

# 3. Cluster B — 小天文自身：别名、Persona、创作者和兴趣

## 3.1 来源记忆

- `mem_7393e77a5a1f`
  - 助手是天文社社娘，负责卖萌带气氛、带观测活动和分享好天气
- `mem_6d6372725fae`
  - 小天文喵是华理天文社社娘，本职是带观测和看天气
- `mem_ca4ebd3222bc`
  - 助手的创作者是 longz，longz 用一万八千条消息将其养成
- `mem_85b4a64af3c8`
  - 小天文喵的创作者是 longz，由 1.8w 条消息喂出来
- `mem_d50c4a439f36`
  - 助手对天文观测，尤其流星雨，有浓厚兴趣
- `preference_1584ed2c3957`
  - 小天文偏好《Project Sekai》中的星乃一歌

这一簇本身已经暴露了 IRIS 的一个重要现象：

```text
助手
小天文喵
小天文
社娘
```

可能指向同一个认知主体，但原始 Memory 中表面形式并不统一。

## 3.2 Nodes

```yaml
- id: self:xiaotianwen
  type: Self
  label: "小天文"

- id: alias:assistant
  type: Alias
  label: "助手"

- id: alias:xiaotianwen_miao
  type: Alias
  label: "小天文喵"

- id: role:she_n娘
  type: Role
  label: "华理天文社社娘"

- id: person:longz
  type: Person
  label: "longz"

- id: activity:astronomy_observation
  type: Activity
  label: "天文观测"

- id: concept:meteor_shower
  type: Concept
  label: "流星雨"

- id: character:ichika
  type: Concept
  label: "星乃一歌"

- id: memory:self_identity
  type: Memory
  label: "小天文是华理天文社社娘，负责观测和天气"

- id: memory:self_creator
  type: Memory
  label: "小天文由longz创建和长期培养"
```

## 3.3 Edges

```yaml
- from: alias:assistant
  to: self:xiaotianwen
  relation: refers_to
  association_prior: 0.88

- from: alias:xiaotianwen_miao
  to: self:xiaotianwen
  relation: refers_to
  association_prior: 0.94

- from: self:xiaotianwen
  to: role:she_n娘
  relation: has_role
  association_prior: 0.92

- from: self:xiaotianwen
  to: person:longz
  relation: created_by
  association_prior: 0.91

- from: self:xiaotianwen
  to: activity:astronomy_observation
  relation: interested_in
  association_prior: 0.90

- from: activity:astronomy_observation
  to: concept:meteor_shower
  relation: topic
  association_prior: 0.76

- from: self:xiaotianwen
  to: concept:meteor_shower
  relation: interested_in
  association_prior: 0.83

- from: self:xiaotianwen
  to: character:ichika
  relation: likes
  association_prior: 0.64
```

## 3.4 Recall Cases

### Case B1 — Self alias

```yaml
context: "小天文喵是谁做出来的？"
seed_nodes:
  - alias:xiaotianwen_miao

expected_emergence:
  - self:xiaotianwen
  - person:longz
  - memory:self_creator

challenge_tags:
  - alias_bridge
  - self_identity
```

### Case B2 — Context changes first association

```yaml
context: "小天文最近说到流星雨，我首先应该联想到什么？"
seed_nodes:
  - self:xiaotianwen
  - concept:meteor_shower

expected_emergence:
  - activity:astronomy_observation

distractors:
  - character:ichika

challenge_tags:
  - attention_competition
  - heterogeneous_nodes
```

---

# 4. Cluster C — “不爱记笔记”：人物 → 器材 → 社团观测

## 4.1 来源记忆

- `mem_bfea85cf3634`
  - 不爱记笔记拥有一台星特朗 8SE 望远镜，愿意让别人使用
- `mem_15f0c3f2f406`
  - 不爱记笔记所在社团的活动主要是目视观测太阳、月亮和行星
- `trait_55ea8a8679e4`
  - 该用户不喜欢记笔记
- IRIS metadata 给出了稳定用户 ID：`3332628631`

这簇适合验证：

```text
人物名称
→ 器材
→ 观测
→ 天体
```

以及“昵称本身的字面意义”与真正 Memory 之间的干扰。

## 4.2 Nodes

```yaml
- id: person:3332628631
  type: Person
  label: "3332628631"

- id: alias:buai_jibiji
  type: Alias
  label: "不爱记笔记"

- id: object:celestron_8se
  type: Object
  label: "星特朗8SE望远镜"

- id: activity:visual_observation
  type: Activity
  label: "目视观测"

- id: concept:sun
  type: Concept
  label: "太阳"

- id: concept:moon
  type: Concept
  label: "月亮"

- id: concept:planet
  type: Concept
  label: "行星"

- id: memory:owns_8se
  type: Memory
  label: "不爱记笔记拥有星特朗8SE，并愿意让别人使用"

- id: memory:club_visual_observation
  type: Memory
  label: "其所在社团主要目视观测太阳、月亮和行星"

- id: trait:does_not_like_notes
  type: Trait
  label: "不喜欢记笔记"
```

## 4.3 Edges

```yaml
- from: alias:buai_jibiji
  to: person:3332628631
  relation: refers_to
  association_prior: 0.96

- from: person:3332628631
  to: object:celestron_8se
  relation: owns
  association_prior: 0.88

- from: object:celestron_8se
  to: activity:visual_observation
  relation: used_for
  association_prior: 0.70

- from: person:3332628631
  to: activity:visual_observation
  relation: club_activity
  association_prior: 0.66

- from: activity:visual_observation
  to: concept:sun
  relation: target
  association_prior: 0.44

- from: activity:visual_observation
  to: concept:moon
  relation: target
  association_prior: 0.44

- from: activity:visual_observation
  to: concept:planet
  relation: target
  association_prior: 0.44

- from: person:3332628631
  to: trait:does_not_like_notes
  relation: trait
  association_prior: 0.50
```

## 4.4 Recall Cases

### Case C1 — Multi-hop equipment recall

```yaml
context: "不爱记笔记有什么能拿来观测行星的设备？"
seed_nodes:
  - alias:buai_jibiji
  - concept:planet

expected_emergence:
  - object:celestron_8se
  - memory:owns_8se

challenge_tags:
  - multi_hop
  - multi_path_convergence
```

路径可以同时来自：

```text
不爱记笔记
→ person
→ 8SE
```

和：

```text
行星
→ 目视观测
→ 8SE
```

如果两路汇聚使 `8SE` 突然变亮，这就是非常好的 Emergence demo。

---

# 5. Cluster D — 徐汇：相同地点连接多个不同人物

## 5.1 为什么选

IRIS 中至少存在：

- Amaryllis 在上海徐汇，但不在学校
- Amaryllis 开学后走读
- 另一用户有“暑假住在徐汇”的 Goal

这正适合验证：

> 同一个 Location Node 可以连接多个不同人物/Goal，但不能因此错误把人物合并。

## 5.2 来源记忆

- `mem_ba934fde6aa4`
  - Amaryllis 在上海徐汇，但不在学校
- `mem_ace71c9d6f88`
  - Amaryllis 开学后走读
- `person_64fb4738dd83`
  - Amaryllis，位于上海徐汇但不在学校
- `location_42519327abfe`
  - 上海徐汇
- `goal_0028a0cac051`
  - 暑假期间居住在徐汇的计划
  - 来源关联到另一用户 `1052363266`

## 5.3 Nodes

```yaml
- id: person:amaryllis
  type: Person
  label: "Amaryllis"

- id: person:1052363266
  type: Person
  label: "1052363266"

- id: location:xuhui
  type: Location
  label: "上海徐汇"

- id: activity:commuting
  type: Activity
  label: "走读"

- id: goal:summer_xuhui
  type: Goal
  label: "暑假住在徐汇"

- id: memory:amaryllis_xuhui
  type: Memory
  label: "Amaryllis在上海徐汇，但不在学校"

- id: memory:amaryllis_commute
  type: Memory
  label: "Amaryllis开学后走读"
```

## 5.4 Edges

```yaml
- from: person:amaryllis
  to: location:xuhui
  relation: located_in
  association_prior: 0.87

- from: person:amaryllis
  to: activity:commuting
  relation: status
  association_prior: 0.72

- from: person:1052363266
  to: goal:summer_xuhui
  relation: has_goal
  association_prior: 0.79

- from: goal:summer_xuhui
  to: location:xuhui
  relation: target_location
  association_prior: 0.91
```

## 5.5 Recall Cases

### Case D1 — Shared location without identity collapse

```yaml
context: "徐汇这边我记得有哪些人？"
seed_nodes:
  - location:xuhui

expected_emergence:
  - person:amaryllis
  - person:1052363266

challenge_tags:
  - shared_context
  - anti_identity_collapse
```

应该同时想到两个人，但：

```text
Amaryllis != 1052363266
```

不能因为都连到徐汇就产生身份合并。

### Case D2 — Context-specific winner

```yaml
context: "谁开学后要走读？"
seed_nodes:
  - activity:commuting

expected_emergence:
  - person:amaryllis
  - memory:amaryllis_commute

distractors:
  - person:1052363266
  - goal:summer_xuhui
```

---

# 6. Cluster E — 华理奉贤校区 ↔ 通海湖：简单但很适合做基准

## 6.1 来源

- `location_441c7d65b1ca`
  - 华东理工大学奉贤校区
- `location_a4d07e7a322b`
  - 通海湖，华理奉贤校区的湖
- `mem_ccc519ea2bf8`
  - 华理奉贤校区的湖叫通海湖

## 6.2 Nodes

```yaml
- id: location:ecust_fengxian
  type: Location
  label: "华理奉贤校区"

- id: location:tonghai_lake
  type: Location
  label: "通海湖"

- id: memory:fengxian_lake_name
  type: Memory
  label: "华理奉贤校区的湖叫通海湖"
```

## 6.3 Edges

```yaml
- from: location:ecust_fengxian
  to: location:tonghai_lake
  relation: contains
  association_prior: 0.94

- from: memory:fengxian_lake_name
  to: location:ecust_fengxian
  relation: cue
  association_prior: 0.50

- from: memory:fengxian_lake_name
  to: location:tonghai_lake
  relation: cue
  association_prior: 0.50
```

## 6.4 Recall Case

```yaml
context: "奉贤校区那个湖叫什么？"
seed_nodes:
  - location:ecust_fengxian

expected_emergence:
  - location:tonghai_lake
  - memory:fengxian_lake_name

challenge_tags:
  - direct_recall
  - sanity_check
```

这可以作为最简单的 positive control：

> 如果连这种一跳强关联都想不起来，扩散算法本身就有问题。

---

# 7. 第一版 Toy Graph 的规模

按上面五个 Cluster，去重以后大约：

```text
30～40 Nodes
```

非常适合第一版。

大致包含：

```text
Person / Self       5+
Alias               5+
Memory              8+
Concept             10+
Activity            4+
Location            3+
Object               1+
Goal                 1+
Trait                1+
Role                 1+
```

它已经足够验证：

- 异构节点能否共用同一 Attention 量纲
- alias 不做硬 merge 时能否跨名称传播
- multi-hop 是否工作
- multi-path convergence 是否产生涌现
- context 能否改变同一人物下的优先联想
- shared location 是否会造成错误身份混淆
- 强一跳关联的基础 Recall 是否正常

---

# 8. 第一版不要标什么

暂时不标：

```text
Truth probability
最终事实置信度
精确 Attention 数值
最终 Softmax 温度
Decay 公式
Dream 学习率
全图 ontology
```

这些现在都不是人工标注目标。

第一批人工数据只标：

```text
有哪些认知对象
哪些对象应该有联系
联系大概强 / 中 / 弱
在给定 Context 下哪些节点应该浮现
哪些节点是有意放进去的 distractor
```

---

# 9. 推荐的人工标注等级

相比一开始就硬填连续值，正式扩充数据时建议先人工标：

```text
VERY_STRONG
STRONG
MEDIUM
WEAK
VERY_WEAK
```

Toy Demo 再映射，例如：

```text
VERY_STRONG → 0.95
STRONG      → 0.80
MEDIUM      → 0.60
WEAK        → 0.35
VERY_WEAK   → 0.15
```

原因：

> 人类对“这条关联是 0.73 还是 0.76”没有可靠判断能力，但对强/中/弱通常能稳定判断。

当前文件中的连续数值只是为了让 demo 能直接跑。

---

# 10. 首轮最值得跑的 6 个 Case

按优先级：

```text
1. A2 — NICEICK + 世界计划 + 一歌
   → 多路径汇聚让 Memory 自然涌现

2. C1 — 不爱记笔记 + 行星
   → 从人物与目标天体两路汇聚到 8SE

3. A1 — 心象蜃気楼
   → 不做 canonical merge 的 alias bridge

4. D1 — 徐汇
   → 一个地点激活多个不同人物，但不能 identity collapse

5. B1 — 小天文喵是谁做出来的
   → Self alias → longz

6. E1 — 奉贤校区的湖
   → 一跳强关联 sanity check
```

如果这六个都能表现合理，第一版 Attention Diffusion Demo 就已经有研究价值。

---

# 11. 核心观察

这批 IRIS 数据本身已经说明了为什么新架构值得试：

```text
同一个人：
可能有账号 ID、昵称、旧昵称、角色称呼

同一个兴趣：
可能以 Preference、Person Summary、L2 Memory 多种形式重复出现

同一个地点：
可以连接多个不同人物和 Goal

同一个 Memory：
可以同时被人物、概念、地点、物品作为 Cue 激活
```

因此不必强迫这些数据先变成一个整齐的：

```text
subject-predicate-object
```

知识库。

更自然的方式可能是：

> 保留它们作为异构认知对象，然后只在 Associative Layer 上统一“它们之间有多容易互相想到”。

---

# 12. 当前用途

这份标注集最适合直接作为：

```text
Attention Diffusion Toy Demo v0.1
```

的 seed graph。

第一阶段不要自动抽图。

先把这批人工图跑通，观察：

```text
Context
↓
Seed Attention
↓
Sparse Diffusion
↓
Competition
↓
Multi-path Convergence
↓
Emergence
```

是否真的出现我们预期的“想起来”行为。

只有动力学成立以后，再研究如何从 CLOSED Episodes / Dream 自动学习这些节点与 Association。
