# 小天文 Test Studio MVP Spec

## 1. 目标

实现一个简单、可理解、可离线运行的 **小天文测试平台**。

它不是生产控制台，也不是复杂的 Agent Observability 平台。

核心目标只有三个：

1. **测试一条消息时，小天文会怎么处理**
2. **回放真实历史群聊，观察小天文如果当时在线会不会参与**
3. **清楚看到“小天文为什么这样做”**

整个系统应尽量简单，优先保证：

- 能运行
- 能理解
- 能回放
- 能比较
- 能保存结果

---

# 2. 核心思路

测试流程：

```text
历史消息 / 手动输入
        ↓
   Test Harness
        ↓
     Runtime
        ↓
 ┌──────┼──────┐
 Judge Memory Agent
        ↓
      Tools
        ↓
     Actions
        ↓
 Recording Executor
        ↓
     WebUI
```

测试环境默认：

```text
不启动 AstrBot
不真正往群里发消息
不需要真实 API
不需要真实 Iris
```

所有组件均可以用 Fake 实现。

---

# 3. 最重要的概念

只保留以下几个核心对象：

```text
TestCase
Dataset
TestHarness
TestWorld
TestResult
Trace
```

不要引入：

- DAG
- Workflow Engine
- Event Bus
- Actor Model
- 复杂中间件系统
- 复杂测试 DSL

---

# 4. Test Harness

Test Harness 负责：

```text
准备测试环境
↓
注入 Fake / Real Component
↓
运行 Runtime
↓
记录整个过程
↓
返回 TestResult
```

建议接口：

```python
class TestHarness:
    async def run(
        self,
        case: TestCase,
        components: ComponentSet,
    ) -> TestResult:
        ...
```

---

# 5. TestWorld

表示一次测试运行中的环境。

```python
@dataclass
class TestWorld:
    runtime: Runtime

    judge: Judge
    agent: Agent
    memory: Memory
    tools: ToolRegistry
    executor: Executor

    clock: Clock
    trace: TraceRecorder
```

Runtime 不应该知道自己正在测试环境。

禁止：

```python
if test_mode:
    ...
```

测试能力全部通过依赖注入实现。

---

# 6. Fake Components

MVP 必须提供：

```text
FakeJudge
FakeAgent
FakeMemory
FakeTools
FakeClock
RecordingExecutor
```

## FakeJudge

可以固定返回：

```text
是否参与
route
confidence
是否需要工具
是否值得记忆
```

## FakeAgent

可以：

```text
返回固定文本
模拟 Tool Call
模拟异常
```

## FakeMemory

可以：

```text
预置记忆
记录读取
记录写入
```

## FakeTools

可以：

```text
返回固定结果
模拟失败
```

## RecordingExecutor

只记录 Action。

不真正发送消息。

---

# 7. Trace

Trace 用于回答：

> 这条消息到底经历了什么？

至少记录：

```text
收到消息
整理消息
参与判断
读取记忆
构建上下文
调用模型
调用工具
写入记忆
生成 Action
执行 Action
```

数据结构可以很简单：

```python
@dataclass
class TraceEvent:
    event: str
    title: str
    summary: str | None
    data: dict
```

例如：

```json
{
  "event": "judge.completed",
  "title": "完成参与判断",
  "summary": "决定回复，置信度 87%"
}
```

WebUI 优先显示：

```text
完成参与判断
决定回复，置信度 87%
```

而不是直接显示技术事件名。

---

# 8. WebUI

WebUI 是主要入口。

左侧只保留：

```text
Playground
Datasets
Replay
Compare
Runs
Components
```

不需要更多一级页面。

---

# 9. Playground

用于手动测试一条消息。

输入：

```text
消息内容
发送者
群聊
是否 @ 小天文
最近聊天
图片描述（可选）
```

示例：

```text
发送者：龙洲

消息：
今晚还能看土星吗

最近聊天：
小明：今天云好多
小王：感觉晚上要寄
```

点击：

```text
运行测试
```

---

# 10. Playground 结果

结果必须首先回答：

```text
小天文回复了吗？

为什么？

模型看到了什么？

有没有调用工具？

最后做了什么？
```

例如：

```text
小天文决定回复

原因：
Judge 判断当前适合参与

置信度：
87%

读取记忆：
2 条

工具：
weather

最终回复：
今晚云量可能有点多（
```

---

# 11. 完整过程

点击：

```text
查看完整过程
```

显示纵向流程：

```text
1. 收到消息
2. 整理消息
3. 是否参与
4. 读取记忆
5. 准备上下文
6. 模型调用
7. 工具调用
8. 最终动作
```

每一步可以展开。

不要默认使用复杂流程图。

---

# 12. “模型看到了什么”

这是 WebUI 最重要的区域之一。

必须能直接看到：

```text
Persona
最近聊天
用户资料
相关记忆
图片描述
工具说明
当前消息
```

例如：

```text
相关记忆

1. 龙洲使用 Sony A6400
   相关度：0.82

2. 龙洲喜欢天文摄影
   相关度：0.76
```

并提供：

```text
查看最终 Model Input
```

高级用户可以展开原始内容。

---

# 13. Datasets

用户手上已有大量真实历史群聊。

这些数据应该直接作为测试场景。

历史数据不是一开始就有“标准答案”。

因此分成三层：

```text
Raw
原始历史聊天

Reviewed
已经人工看过部分结果

Golden
已经明确确认，可以用于回归测试
```

---

# 14. 历史聊天导入

至少支持 JSONL。

示例：

```json
{"timestamp":"2026-08-20T20:00:00+08:00","group":"group_1","sender":"A","sender_name":"小明","text":"今天云好多"}
{"timestamp":"2026-08-20T20:00:05+08:00","group":"group_1","sender":"B","sender_name":"龙洲","text":"今晚还观测吗"}
```

可选字段：

```text
reply_to
mentioned_bot
images
metadata
```

---

# 15. Historical Replay

核心用途：

> 如果当时小天文在线，它会怎么做？

例如真实聊天：

```text
20:31 小明：今天云好多
20:31 龙洲：晚上是不是寄了
20:32 小王：不是说九点会散吗
20:33 龙洲：我镜头都带出来了（
```

Replay 后：

```text
20:31 小明
今天云好多

小天文：
未参与


20:31 龙洲
晚上是不是寄了

小天文：
决定参与

模拟回复：
大概率得看看晚点云能不能散（
```

---

# 16. Replay UI

Replay 应该看起来像聊天记录。

不要默认显示 Trace。

例如：

```text
小明
今天云好多

              小天文
              ○ 未参与


龙洲
晚上是不是寄了

              小天文
              ● 参与
              大概率得看看晚点云能不能散（

              [查看原因]
```

点击任意一条：

```text
查看完整过程
```

进入和 Playground 相同的 Inspector。

---

# 17. Replay 模式

支持两个模式。

## Session

整段聊天连续运行。

保留：

```text
聊天上下文
工作记忆
Runtime 状态
```

用于真实群聊模拟。

## Isolated

每条消息独立运行。

用于：

```text
Judge benchmark
Routing benchmark
```

默认使用：

```text
Session
```

---

# 18. Review

历史记录没有标准答案。

因此 Replay 后允许人工快速标记。

参与判断：

```text
这次参与是否合适？

[合适]
[不该参与]
[应该参与但没参与]
[跳过]
```

如果小天文回复了：

```text
回复自然吗？

[自然]
[一般]
[不自然]
```

允许添加备注：

```text
这里没人问它，不应该突然插嘴。
```

---

# 19. Golden Case

当一个历史场景经过人工确认后，可以：

```text
保存为 Golden Case
```

例如：

```text
用户：
今晚还观测吗

上下文：
前面正在讨论天气

期望：
应该参与
```

之后每次重构都可以重新运行。

---

# 20. Compare

用于比较两套配置。

例如：

```text
OldJudge
vs
JevJudge
```

或者：

```text
旧 Prompt
vs
新 Prompt
```

或者：

```text
旧 Iris
vs
新 Iris
```

---

# 21. Compare UI

选择：

```text
Baseline
Candidate
Dataset
```

运行后显示：

```text
共 200 个场景

行为相同：
182

行为变化：
18

不回复 → 回复：
11

回复 → 不回复：
7
```

下面只列出发生变化的场景。

例如：

```text
消息：
哈哈哈哈哈哈

Baseline：
不回复

Candidate：
回复
confidence: 0.54

[查看差异]
```

---

# 22. Compare Inspector

左右显示：

```text
Baseline              Candidate

Judge: ignore         Judge: reply
confidence: 0.91      confidence: 0.54

Agent: 未调用          Agent: 已调用

Action: none          SendText(...)
```

只高亮真正不同的地方。

---

# 23. Runs

保存所有运行记录。

列表：

```text
时间       来源         输入               结果

14:31      Playground   今晚看土星吗       回复
14:28      Replay       哈哈哈哈哈          忽略
14:20      Golden       普通问候            PASS
```

点击后可以重新查看完整过程。

---

# 24. Components

这个页面只回答：

> 当前测试用了哪些真的组件，哪些假的？

例如：

```text
Judge
FakeJudge

Agent
FakeAgent

Memory
FakeMemory

Tools
FakeTools

Executor
RecordingExecutor
```

提供几个预设即可。

## Offline

全部 Fake。

## Judge Test

```text
Judge：Real / Jev
Agent：Fake
Memory：Fake
Tools：Fake
```

## Agent Test

```text
Judge：AlwaysReply
Agent：Real
Memory：Fake
Tools：Fake
```

## Integration

```text
Judge：Real
Agent：Real
Memory：Iris
Tools：Real
```

Executor 仍然必须：

```text
RecordingExecutor
```

Test Studio 不允许直接往真实群聊发送消息。

---

# 25. 数据存储

使用 SQLite。

最低保存：

```text
cases
datasets
dataset_events
runs
trace_events
reviews
golden_cases
```

JSON 字段可以直接使用。

不要过度设计数据库。

---

# 26. Backend

推荐：

```text
Python
FastAPI
Pydantic
SQLite
```

最低 API：

```text
POST /api/runs
GET  /api/runs
GET  /api/runs/{id}

POST /api/datasets
GET  /api/datasets
GET  /api/datasets/{id}

POST /api/replay

POST /api/reviews

POST /api/golden

POST /api/compare

GET  /api/components
PUT  /api/components

GET  /api/health
```

---

# 27. Frontend

推荐：

```text
React
TypeScript
Vite
Tailwind
shadcn/ui
TanStack Query
```

UI 风格：

```text
简单
开发工具风格
信息清楚
中文优先
支持 Dark Mode
```

不要：

```text
AI 渐变
巨大 KPI 卡片
复杂动画
大量图表
满屏 JSON
```

---

# 28. WebUI 文案原则

默认使用容易理解的中文。

例如：

不要只写：

```text
Judgment
```

显示：

```text
参与判断
```

下面可以小字：

```text
Judgment
```

不要只写：

```text
Retrieval
```

显示：

```text
读取到的记忆
```

不要只写：

```text
Trace
```

显示：

```text
完整处理过程
```

---

# 29. 错误显示

如果失败：

```text
运行失败

失败位置：
Agent

错误：
FakeAgentError

执行进度：

✓ 收到消息
✓ 判断是否参与
✓ 读取记忆
✕ 模型调用
○ 最终动作未执行
```

用户应该立即知道：

```text
哪里坏了
前面哪些步骤成功了
后面哪些没有执行
```

---

# 30. 离线模式

这是硬性要求。

没有：

```text
AstrBot
Iris
Jev
OpenAI
网络
API Key
```

仍然可以使用：

```text
Playground
Datasets
Replay
Review
Golden Case
Compare
Runs
完整过程
```

---

# 31. WebUI 最重要的验收标准

打开任意一次 Run 后，不看 JSON、不翻日志，也能回答：

```text
用户说了什么？
小天文有没有参与？
为什么？
读取了什么记忆？
模型看到了什么？
调用了什么工具？
模型生成了什么？
最后做了什么？
哪里失败了？
```

如果必须查看原始 JSON 才能回答，则 UI 不合格。

---

# 32. MVP 页面

最终只需要：

```text
Playground
Datasets
Replay
Compare
Runs
Components
```

不要继续增加一级功能。

---

# 33. 示例数据

交付时附带：

```text
10 个简单 Case
2 段 Replay Dataset
1 个 Compare Demo
```

至少覆盖：

```text
普通聊天
不参与
@小天文
天文问题
技术问题
图片描述
Memory retrieval
Tool call
Agent error
Tool error
```

---

# 34. 自动测试

至少覆盖：

```text
Offline Harness 可以运行
FakeJudge
FakeAgent
FakeMemory
RecordingExecutor
Trace 正确记录
Replay session 正常
Compare 正常
SQLite 能保存 Run
WebUI Playground 能运行测试
Replay 可以查看某条消息
```

---

# 35. 启动方式

最终应支持：

```bash
docker compose up
```

然后：

```text
http://localhost:3000
```

即可进入 WebUI。

也可以提供开发模式：

```bash
uv run backend
npm run dev
```

---

# 36. 最终交付物

一次性交付：

```text
Backend
Frontend
SQLite
Test Harness
Fake Components
Trace
Playground
Datasets
Historical Replay
Review
Golden Cases
Compare
Runs
Components
示例数据
自动测试
Docker
README
```

---

# 37. 非目标

本次不做：

```text
生产 AstrBot 管理
真实 QQ 发消息
Prompt IDE
Workflow 编辑器
Memory 管理后台
低代码 Agent Builder
复杂 Benchmark 平台
账号系统
权限系统
多人协作
云同步
```

---

# 38. 最终产品定位

这个项目不是：

```text
Agent Observability Dashboard
```

也不是：

```text
Agent Workflow Builder
```

而是：

# 小天文实验台

它应该让开发者可以把一段真实群聊放进去，然后清楚看到：

```text
如果小天文当时在线
↓
它会不会参与
↓
为什么参与
↓
它想起了什么
↓
它看到了什么上下文
↓
它调用了什么
↓
它会说什么
↓
最后做了什么
```

然后通过大量真实历史聊天：

```text
Raw Dataset
↓
Historical Replay
↓
人工 Review
↓
Golden Cases
↓
Regression / Compare
```

逐渐建立一套真正属于“小天文”的测试集。

---

# 39. Definition of Done

以下全部完成才算交付：

```text
[ ] Offline 模式可完整运行
[ ] WebUI 中文且能理解
[ ] Playground 可用
[ ] Dataset 可导入
[ ] Historical Replay 可用
[ ] Replay 像聊天记录
[ ] 可人工 Review
[ ] 可保存 Golden Case
[ ] Compare 可用
[ ] Runs 可查看
[ ] Trace 可查看
[ ] Fake Components 完整
[ ] 不启动 AstrBot
[ ] 不需要 API Key
[ ] 不会真正发送群消息
[ ] SQLite 持久化
[ ] 自动测试通过
[ ] 示例数据存在
[ ] Docker 可启动
[ ] README 完整
```
