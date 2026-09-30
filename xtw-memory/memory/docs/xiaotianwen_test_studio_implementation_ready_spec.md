# 小天文 Test Studio MVP
## Implementation-Ready Spec（低自由度，一次性交付版）

> 这份文档可以直接交给 coding agent 实现。
>
> 实现者不要重新设计架构，不要自行增加框架，不要改变主要技术栈。
>
> **优先级：能跑 > 易懂 > 功能完整 > 漂亮。**

---

# 0. 最终要做出的东西

实现一个本地 Web 应用：**小天文 Test Studio**。

它只解决四件事：

1. 手动输入一条群聊消息，看看小天文会怎么处理。
2. 导入历史群聊记录，按原顺序重新回放。
3. 查看每条消息为什么回复 / 为什么没回复。
4. 对同一批聊天，用两套不同配置跑一遍并比较差异。

它不是 AstrBot 管理后台、Prompt IDE、Workflow Builder、通用 Agent 平台、生产控制台或 Observability SaaS。

---

# 1. 硬性要求

## 1.1 默认完全离线

启动后不需要 AstrBot、OpenAI、Jev、Iris、API Key 或网络，也必须能完整使用：

- Playground
- Datasets
- Replay
- Review
- Golden Case
- Compare
- Runs

## 1.2 不允许真正发群消息

测试台永远使用 `RecordingExecutor`，只记录 Action，不向 QQ / AstrBot 发送消息。

即使未来接入真实 Judge / Agent，也不能绕过这一限制。

## 1.3 中文优先

页面主标题使用：

- 参与判断
- 读取到的记忆
- 模型看到的内容
- 最终动作
- 完整处理过程

不要用 Judgment、Retrieval、Span、Trace Node、Execution Graph 作为主标题。

---

# 2. 固定技术栈

不要自行替换。

## Backend

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x
- SQLite
- Uvicorn

## Frontend

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui
- TanStack Query
- React Router

## Testing

- pytest
- pytest-asyncio
- Playwright

## Deployment

- Docker
- docker compose

---

# 3. 固定项目目录

严格按下面目录创建：

```text
xiaotianwen-test-studio/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── runs.py
│   │   │   ├── datasets.py
│   │   │   ├── replay.py
│   │   │   ├── compare.py
│   │   │   ├── reviews.py
│   │   │   ├── golden.py
│   │   │   └── components.py
│   │   ├── db/
│   │   │   ├── database.py
│   │   │   └── models.py
│   │   ├── schemas/
│   │   │   ├── events.py
│   │   │   ├── runs.py
│   │   │   ├── datasets.py
│   │   │   ├── trace.py
│   │   │   └── components.py
│   │   ├── harness/
│   │   │   ├── harness.py
│   │   │   ├── world.py
│   │   │   ├── trace.py
│   │   │   ├── result.py
│   │   │   └── compare.py
│   │   ├── components/
│   │   │   ├── interfaces.py
│   │   │   ├── fake_judge.py
│   │   │   ├── fake_agent.py
│   │   │   ├── fake_memory.py
│   │   │   ├── fake_tools.py
│   │   │   ├── fake_clock.py
│   │   │   └── recording_executor.py
│   │   └── services/
│   │       ├── dataset_service.py
│   │       ├── replay_service.py
│   │       └── run_service.py
│   ├── tests/
│   │   ├── test_harness.py
│   │   ├── test_replay.py
│   │   ├── test_compare.py
│   │   └── test_api.py
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/client.ts
│   │   ├── pages/
│   │   │   ├── PlaygroundPage.tsx
│   │   │   ├── DatasetsPage.tsx
│   │   │   ├── DatasetDetailPage.tsx
│   │   │   ├── ReplayPage.tsx
│   │   │   ├── ComparePage.tsx
│   │   │   ├── RunsPage.tsx
│   │   │   ├── RunDetailPage.tsx
│   │   │   └── ComponentsPage.tsx
│   │   ├── components/
│   │   │   ├── Layout.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   ├── MessageBubble.tsx
│   │   │   ├── RunSummary.tsx
│   │   │   ├── RunProcess.tsx
│   │   │   ├── ProcessStep.tsx
│   │   │   ├── JudgmentCard.tsx
│   │   │   ├── ContextCard.tsx
│   │   │   ├── MemoryCard.tsx
│   │   │   ├── ToolCard.tsx
│   │   │   ├── ActionCard.tsx
│   │   │   └── ReviewBar.tsx
│   │   └── types/index.ts
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── examples/
│   ├── cases.json
│   ├── demo_chat.jsonl
│   └── demo_chat_2.jsonl
├── docker-compose.yml
├── README.md
└── .env.example
```

不要额外创建 `workflow/`、`graph/`、`orchestration/`、`event_bus/`、`middleware/`、`plugins/`。

---

# 4. 后端核心数据结构

## 4.1 TestEvent

文件：`backend/app/schemas/events.py`

```python
from datetime import datetime
from pydantic import BaseModel, Field

class TestMessage(BaseModel):
    sender_id: str
    sender_name: str
    text: str
    timestamp: datetime | None = None

class TestEvent(BaseModel):
    event_id: str | None = None
    conversation_id: str = "test-group"
    conversation_name: str = "测试群"
    sender_id: str = "test-user"
    sender_name: str = "测试用户"
    text: str = ""
    timestamp: datetime | None = None
    mentioned_bot: bool = False
    reply_to_text: str | None = None
    image_descriptions: list[str] = Field(default_factory=list)
    history: list[TestMessage] = Field(default_factory=list)
```

## 4.2 Judgment

```python
class Judgment(BaseModel):
    participate: bool
    participate_probability: float = 0.0
    route: str = "casual"
    need_memory: bool = False
    need_tool: bool = False
    memory_worthy: bool = False
    reason: str = ""
```

## 4.3 AgentResult

```python
class AgentResult(BaseModel):
    text: str
    model_name: str = "fake-agent"
    input_tokens: int = 0
    output_tokens: int = 0
    tool_requests: list[str] = Field(default_factory=list)
```

## 4.4 MemoryItem

```python
class MemoryItem(BaseModel):
    id: str
    text: str
    score: float = 1.0
```

## 4.5 Action

MVP 只做两个 Action：

```python
class SendTextAction(BaseModel):
    type: Literal["send_text"] = "send_text"
    text: str

class NoAction(BaseModel):
    type: Literal["none"] = "none"
```

不要实现 SendImage、SendEmoji、Reaction 等额外 Action。

---

# 5. Component 接口

文件：`backend/app/components/interfaces.py`

```python
from typing import Protocol

class Judge(Protocol):
    async def judge(self, event: TestEvent) -> Judgment: ...

class Agent(Protocol):
    async def run(
        self,
        event: TestEvent,
        judgment: Judgment,
        memories: list[MemoryItem],
    ) -> AgentResult: ...

class Memory(Protocol):
    async def search(self, event: TestEvent) -> list[MemoryItem]: ...
    async def write(self, text: str) -> None: ...

class Executor(Protocol):
    async def execute(self, action) -> dict: ...
```

不要增加更多抽象。

---

# 6. Fake Components

必须实现：

- FakeAgent
- FakeMemory
- FakeTools
- FakeClock
- RecordingExecutor
- AlwaysReplyJudge
- NeverReplyJudge
- KeywordJudge

## 6.1 RecordingExecutor

```python
class RecordingExecutor:
    def __init__(self):
        self.actions = []

    async def execute(self, action):
        self.actions.append(action)
        return {
            "success": True,
            "message_id": f"test-message-{len(self.actions)}",
        }
```

不能访问网络。

## 6.2 AlwaysReplyJudge

所有非空消息：

```text
participate = true
probability = 1.0
route = casual
reason = AlwaysReplyJudge 固定参与
```

## 6.3 NeverReplyJudge

所有消息：

```text
participate = false
probability = 0.0
route = casual
reason = NeverReplyJudge 固定不参与
```

## 6.4 KeywordJudge

如果满足任意条件则参与：

- mentioned_bot == true
- 文本包含“小天文”
- 文本包含“天文”
- 文本包含“星”
- 文本包含“望远镜”
- 文本包含“相机”
- 文本包含“镜头”
- 文本包含“观测”
- 文本包含“今晚”
- 文本包含“月亮”
- 文本包含“土星”
- 文本包含“木星”

参与时：

```text
participate = true
probability = 0.90
```

否则：

```text
participate = false
probability = 0.20
```

route：

- 包含“星 / 天文 / 观测 / 月亮 / 土星 / 木星” -> `astronomy`
- 包含“相机 / 镜头 / 望远镜” -> `technical`
- 否则 -> `casual`

KeywordJudge 仅用于离线 Demo。

## 6.5 FakeAgent

按 route 返回固定文本：

- astronomy -> `这是一个天文相关问题，我会参与这段对话（测试回复）`
- technical -> `这是一个器材或技术相关问题，我会参与这段对话（测试回复）`
- 其他 -> `我会参与这段对话（测试回复）`

## 6.6 FakeMemory

支持：

- 初始化若干 MemoryItem
- `search()` 返回所有预置 MemoryItem
- 记录 search 次数
- `write()` 记录写入内容

默认可预置：

```text
用户使用 Sony A6400
用户喜欢天文摄影
```

---

# 7. Trace

文件：`backend/app/harness/trace.py`

```python
class TraceEvent(BaseModel):
    step: str
    title: str
    summary: str
    data: dict = Field(default_factory=dict)

class TraceRecorder:
    def __init__(self):
        self.events: list[TraceEvent] = []

    def add(self, step: str, title: str, summary: str, data: dict | None = None):
        self.events.append(
            TraceEvent(
                step=step,
                title=title,
                summary=summary,
                data=data or {},
            )
        )
```

正常参与时固定 Trace 顺序：

```text
event.received
judgment.completed
memory.completed
context.completed
agent.completed
action.created
action.executed
run.completed
```

不参与时：

```text
event.received
judgment.completed
action.created
run.completed
```

失败时最后必须有：

```text
run.failed
```

---

# 8. TestHarness

文件：`backend/app/harness/harness.py`

这是整个项目最重要的代码。保持简单。

逻辑必须严格是：

```text
收到 TestEvent
↓
记录 event.received
↓
Judge
↓
记录 judgment.completed
↓
如果不参与：生成 NoAction → 返回
↓
如果 need_memory：Memory.search
↓
记录 memory.completed
↓
准备 Context 摘要
↓
记录 context.completed
↓
Agent.run
↓
记录 agent.completed
↓
生成 SendTextAction
↓
RecordingExecutor.execute
↓
记录 action.executed
↓
返回 TestResult
```

不要实现 workflow graph、dynamic node、middleware pipeline、event dispatch、retry graph。

## 8.1 ComponentSet

```python
@dataclass
class ComponentSet:
    judge: Judge
    agent: Agent
    memory: Memory
    tools: object
    executor: RecordingExecutor
```

## 8.2 TestResult

```python
class TestResult(BaseModel):
    run_id: str
    status: Literal["success", "failed"]
    participated: bool
    judgment: Judgment | None = None
    memories: list[MemoryItem] = Field(default_factory=list)
    agent_result: AgentResult | None = None
    actions: list[dict] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    error: str | None = None
```

---

# 9. Component Preset

只实现三个：

## offline-keyword

```text
Judge = KeywordJudge
Agent = FakeAgent
Memory = FakeMemory
Tools = FakeTools
Executor = RecordingExecutor
```

## offline-always-reply

```text
Judge = AlwaysReplyJudge
Agent = FakeAgent
Memory = FakeMemory
Tools = FakeTools
Executor = RecordingExecutor
```

## offline-never-reply

```text
Judge = NeverReplyJudge
Agent = FakeAgent
Memory = FakeMemory
Tools = FakeTools
Executor = RecordingExecutor
```

MVP 不实现真实 Jev / GPT / Iris。

---

# 10. SQLite 数据库

数据库默认：

```text
./data/test_studio.db
```

只建立以下表。

## datasets

```text
id
name
description
created_at
```

## dataset_events

```text
id
dataset_id
event_index
timestamp
conversation_id
conversation_name
sender_id
sender_name
text
mentioned_bot
reply_to_text
image_descriptions_json
raw_json
```

## runs

```text
id
source
dataset_id nullable
dataset_event_id nullable
preset
status
participated
input_json
result_json
created_at
```

source 只能是：

```text
playground
replay
compare
```

## reviews

```text
id
run_id
participation_review
response_review
note
created_at
```

`participation_review` 允许：

```text
good
should_not_participate
should_have_participated
skip
```

`response_review` 允许：

```text
natural
okay
unnatural
skip
```

## golden_cases

```text
id
source_run_id
name
event_json
expected_participate
note
created_at
```

---

# 11. 固定 API

不要重新设计。

## POST /api/runs

Playground 使用。

请求：

```json
{
  "preset": "offline-keyword",
  "event": {
    "conversation_id": "test-group",
    "conversation_name": "测试群",
    "sender_id": "user-1",
    "sender_name": "龙洲",
    "text": "今晚还能看土星吗",
    "mentioned_bot": false,
    "history": []
  }
}
```

返回完整 TestResult。

## GET /api/runs

支持 `?limit=50`，按时间倒序。

## GET /api/runs/{run_id}

返回完整 Run。

## POST /api/datasets/import

使用 multipart/form-data：

```text
file=.jsonl
name=数据集名称
```

## GET /api/datasets

返回数据集列表。

## GET /api/datasets/{dataset_id}

返回基本信息和消息数。

## GET /api/datasets/{dataset_id}/events

支持：

```text
?offset=0&limit=100
```

## POST /api/replay

请求：

```json
{
  "dataset_id": "xxx",
  "preset": "offline-keyword",
  "mode": "session"
}
```

MVP 只实现 session，但保留 mode 字段。

返回：

```json
{
  "replay_id": "...",
  "total": 100,
  "participated": 20,
  "ignored": 80,
  "failed": 0,
  "run_ids": []
}
```

## POST /api/reviews

```json
{
  "run_id": "...",
  "participation_review": "good",
  "response_review": "natural",
  "note": ""
}
```

## POST /api/golden

```json
{
  "run_id": "...",
  "name": "天文问题：今晚看土星",
  "expected_participate": true,
  "note": ""
}
```

## GET /api/golden

返回 Golden Case 列表。

## POST /api/compare

```json
{
  "dataset_id": "...",
  "baseline_preset": "offline-keyword",
  "candidate_preset": "offline-always-reply"
}
```

返回：

```json
{
  "total": 100,
  "same": 60,
  "changed": 40,
  "false_to_true": 40,
  "true_to_false": 0,
  "differences": []
}
```

每个 difference：

```json
{
  "event_id": "...",
  "text": "哈哈哈哈",
  "baseline": {
    "participated": false,
    "probability": 0.2
  },
  "candidate": {
    "participated": true,
    "probability": 1.0
  }
}
```

## GET /api/components

返回三个 preset 的说明。

## GET /api/health

返回：

```json
{"ok": true}
```

---

# 12. JSONL 导入格式

最低支持：

```json
{"timestamp":"2026-08-20T20:00:00+08:00","sender":"user-1","sender_name":"小明","text":"今天云好多"}
```

也支持：

```json
{"timestamp":"2026-08-20T20:00:05+08:00","group":"group-1","group_name":"26级天文迎新群","sender":"user-2","sender_name":"龙洲","text":"今晚还观测吗","mentioned_bot":false}
```

缺省：

```text
group = imported-group
group_name = 导入群聊
mentioned_bot = false
```

---

# 13. Replay 的关键规则

Historical Replay 第一版不模拟平行世界。

第 N 条消息运行时：

```text
history = 前面最近 10 条真实历史消息
```

**不要把测试台生成的小天文回复写回 history。**

原因：第一版只回答：

> 如果小天文当时看到真实聊天历史，它会不会参与？

不要让模拟回复改变后续真实历史。

---

# 14. Frontend 全局布局

固定左侧栏：

```text
小天文 Test Studio

Playground
Datasets
Replay
Compare
Runs
Components
```

左侧栏约 220px。

桌面优先。

---

# 15. Playground 页面

路由：`/playground`，并让 `/` 重定向到 `/playground`。

标题：

```text
测试一条消息
```

副标题：

```text
模拟一条群聊消息，看看小天文会怎么处理。
```

## 输入字段顺序

### 测试模式

Select：

```text
Keyword Judge
Always Reply
Never Reply
```

默认 Keyword Judge。

### 发送者昵称

默认：`测试用户`

### 群聊名称

默认：`测试群`

### 当前消息

Textarea placeholder：

```text
例如：今晚还能看土星吗
```

### 是否 @ 小天文

Checkbox。

### 最近聊天

初始为空。

按钮：

```text
+ 添加前序消息
```

每条只有：

- 发送者昵称
- 消息内容
- 删除

不要做拖拽。

### 图片描述

可选 textarea。

placeholder：

```text
如果这是一张图片，可以手动描述图片内容。
例如：一张夜空照片，云很多。
```

### 主按钮

```text
运行测试
```

---

# 16. Playground 结果

运行后不跳页，在输入下方显示。

最顶部显示三种之一：

```text
小天文决定参与
小天文没有参与
运行失败
```

然后固定显示五项：

1. 是否回复：是 / 否
2. 为什么：`judgment.reason`
3. 参与概率：例如 `90%`，加简单进度条
4. 类型：日常 / 天文 / 技术器材
5. 最终动作：发送文本或没有发送

route 翻译：

```text
casual -> 日常
astronomy -> 天文
technical -> 技术 / 器材
```

---

# 17. 完整处理过程

组件：`RunProcess.tsx`

纵向显示，禁止默认画节点图。

固定步骤：

```text
收到消息
参与判断
读取记忆
准备模型上下文
模型生成
最终动作
```

只显示实际发生的步骤。

## 收到消息

显示：

```text
发送者
群聊
消息
是否 @ 小天文
```

## 参与判断

显示：

```text
决定
参与概率
类型
需要记忆
需要工具
原因
```

## 读取记忆

有记忆：

```text
读取到 2 条记忆
• 用户使用 Sony A6400
• 用户喜欢天文摄影
```

没有：

```text
本次没有读取记忆
```

## 准备模型上下文

只显示四块：

- 当前消息
- 最近聊天
- 相关记忆
- 图片描述

底部可有“查看原始数据”，默认折叠 JSON。

## 模型生成

显示：

```text
模型：fake-agent
输出：...
```

Token 可以小字显示。

## 最终动作

参与：

```text
发送文本
...
测试环境只记录，没有真正发送群消息。
```

不参与：

```text
没有执行发送动作。
```

---

# 18. Datasets 页面

路由：`/datasets`

标题：

```text
历史聊天数据
```

说明：

```text
导入以前的真实群聊记录，用来模拟“如果当时小天文在线会发生什么”。
```

顶部按钮：

```text
导入 JSONL
```

列表列：

- 名称
- 消息数量
- 创建时间
- 操作

操作：

```text
查看
开始 Replay
```

---

# 19. Dataset Detail 页面

显示：

- 数据集名称
- 消息数
- 时间范围

然后按聊天记录形式显示前 100 条：

```text
20:31 小明
今天云好多

20:31 龙洲
今晚还观测吗
```

不要用表格作为聊天主体。

---

# 20. Replay 页面

路由：`/replay?dataset=xxx`

顶部：

```text
数据集：[名称]
测试模式：[Keyword Judge ▼]
[开始历史回放]
```

结果摘要：

```text
总消息：100
参与：22
忽略：78
失败：0
```

下面按聊天顺序显示。

未参与：

```text
小明
今天云好多

小天文
○ 未参与
[查看原因]
```

参与：

```text
龙洲
今晚还观测吗

小天文
● 决定参与

这是一个天文相关问题，我会参与这段对话（测试回复）

[查看完整过程]
```

点击查看完整过程使用 Dialog 或 Drawer，复用 RunProcess。

---

# 21. ReviewBar

每条 Replay 结果下方可以评价。

参与判断：

```text
这次参与是否合适？

[合适]
[不该参与]
[应该参与但没参与]
[跳过]
```

如果 participated == true，再显示：

```text
回复自然吗？

[自然]
[一般]
[不自然]
[跳过]
```

再提供备注 textarea 和：

```text
保存评价
```

---

# 22. Golden Case

Replay 每条 Run 有按钮：

```text
保存为 Golden Case
```

弹窗字段：

- 名称
- 期望：应该参与 / 不应该参与
- 备注

按钮：`保存`

MVP 不做单独 Golden 页面。

---

# 23. Compare 页面

路由：`/compare`

三个 Select：

- 数据集
- Baseline
- Candidate

默认：

```text
Baseline = Keyword Judge
Candidate = Always Reply
```

按钮：

```text
开始比较
```

结果顶部：

```text
共 100 条
行为相同：60
行为不同：40
不参与 → 参与：40
参与 → 不参与：0
```

下面只列差异。

每条：

```text
消息：哈哈哈哈

Baseline：
不参与
20%

Candidate：
参与
100%

[查看差异]
```

查看差异左右两栏，仅显示：

- 是否参与
- 概率
- route
- reason

不要展示复杂指标。

---

# 24. Runs 页面

路由：`/runs`

简单表格：

- 时间
- 来源
- 发送者
- 消息
- 结果

结果只允许：

```text
参与
忽略
失败
```

点击进入 `/runs/:id`。

Run Detail 必须复用 Playground 的 `RunSummary` 和 `RunProcess`，不要做第二套 Inspector。

---

# 25. Components 页面

路由：`/components`

只显示三个 preset 的组件组成。

例如：

```text
Keyword Judge
Judge: KeywordJudge
Agent: FakeAgent
Memory: FakeMemory
Executor: RecordingExecutor
```

页面底部写：

```text
当前版本只提供离线测试组件。
未来真实 Jev / LLM / Iris 应通过同样接口接入。
```

MVP 不做真实组件配置 UI。

---

# 26. 错误 UX

不要自动 retry。

任何组件异常：

```text
TestResult.status = failed
```

UI 显示：

```text
运行失败

失败位置：
模型调用

错误：
FakeAgentError: simulated failure
```

Trace 最后必须有 `run.failed`。

---

# 27. Loading UX

单条运行时：

```text
正在运行...
```

禁用重复点击。

Replay 可以先整批等待返回，不需要 SSE 或 WebSocket。

不要为了实时进度增加复杂度。

---

# 28. 样式要求

目标：简单、清楚、像开发工具。

建议：

- 轻边框
- 8~12px 圆角
- 合理留白
- 支持 Dark Mode

不要：

- AI 渐变
- 粒子动画
- 玻璃拟态
- 巨型 KPI Dashboard
- 大量图表

Dark Mode 支持 light / dark / system，前端本地保存即可。

---

# 29. 示例数据

必须提供 `examples/demo_chat.jsonl`，至少 20 条消息，包含：

- 普通闲聊
- 哈哈哈哈
- 天气讨论
- 今晚观测
- 土星
- 相机
- 镜头
- 望远镜
- 无关校园聊天

再提供 `examples/demo_chat_2.jsonl`，至少 10 条，用于 Compare。

---

# 30. Backend 自动测试

必须写以下测试。

## test_harness_participate

AlwaysReplyJudge：

```text
status == success
participated == true
actions 长度 == 1
actions[0].type == send_text
```

## test_harness_ignore

NeverReplyJudge：

```text
participated == false
actions 为空
Agent 没有被调用
```

## test_keyword_judge

输入：

```text
今晚还能看土星吗
```

断言：

```text
participate == true
route == astronomy
```

输入：

```text
哈哈哈哈
```

断言：

```text
participate == false
```

## test_trace_order

参与场景必须严格是：

```text
event.received
judgment.completed
memory.completed
context.completed
agent.completed
action.created
action.executed
run.completed
```

## test_replay

3 条：

```text
哈哈
今晚看土星吗
我买了镜头
```

KeywordJudge 应：

```text
false
true
true
```

## test_compare

Baseline NeverReply，Candidate AlwaysReply，3 条消息：

```text
changed == 3
false_to_true == 3
```

---

# 31. Frontend Playwright E2E

只做四个。

## E2E 1

Playground 输入：

```text
今晚还能看土星吗
```

运行后出现：

```text
小天文决定参与
```

## E2E 2

输入：

```text
哈哈哈哈
```

出现：

```text
小天文没有参与
```

## E2E 3

Datasets 导入 `demo_chat.jsonl`，列表出现该数据集。

## E2E 4

运行 Replay，页面出现：

```text
总消息
参与
忽略
```

---

# 32. Docker

根目录 `docker-compose.yml` 只需要：

- backend
- frontend

端口：

```text
backend 8000
frontend 3000
```

启动：

```bash
docker compose up --build
```

访问：

```text
http://localhost:3000
```

---

# 33. README

README 不写成长论文，只包含：

1. 项目是什么
2. `docker compose up --build`
3. 打开 `http://localhost:3000`
4. Playground 怎么用
5. JSONL 怎么导入
6. Replay 是什么
7. Review 是什么
8. Compare 怎么用
9. 简单项目结构
10. 测试命令

---

# 34. 强制实现顺序

Coding Agent 必须按顺序实现。

## Phase 1：Backend Harness

先完成：

- schemas
- component interfaces
- fake components
- trace
- TestHarness

然后运行 pytest。

确认 harness / keyword judge / trace tests 通过。

## Phase 2：Database + API

实现：

- SQLite
- runs
- datasets
- replay
- reviews
- golden
- compare

再运行 pytest。

## Phase 3：Frontend Skeleton

实现：

- Layout
- Sidebar
- routing
- API client

## Phase 4：Playground

完整打通：

```text
输入
→ POST /api/runs
→ RunSummary
→ RunProcess
```

## Phase 5：Datasets + Replay

实现：

```text
JSONL upload
Dataset list
Dataset detail
Replay
Review
Golden
```

## Phase 6：Compare + Runs + Components

完成剩余页面。

## Phase 7：Docker + README + E2E

最后确保：

```bash
docker compose up --build
```

成功，并运行所有测试。

---

# 35. 禁止 Coding Agent 自行增加的东西

不要：

- 改技术栈
- 引入 LangGraph
- 引入 Celery
- 引入 Redis
- 引入 PostgreSQL
- 引入 WebSocket
- 引入 Kafka
- 引入 OpenTelemetry
- 引入复杂 DI 框架
- 引入 Redux
- 做账号系统
- 做权限系统
- 做云同步
- 实现真实 Jev
- 实现真实 OpenAI
- 实现真实 Iris
- 实现 AstrBot

除非后续单独要求。

---

# 36. 代码风格要求

优先：

- 短函数
- 普通类
- 明确类型
- 少抽象
- 容易读

推荐：

```python
result = await harness.run(event, components)
```

不要做：

```python
RuntimeExecutionCoordinator(
    GraphExecutionStrategy(
        DynamicWorkflowNodeResolver(...)
    )
)
```

---

# 37. 最终 Demo 验收

交付前必须自己完成下面步骤。

## Demo 1：Playground

输入：

```text
今晚还能看土星吗
```

Keyword Judge。

必须看到：

```text
小天文决定参与
90%
天文
```

并看到 FakeAgent 回复。

## Demo 2：不参与

输入：

```text
哈哈哈哈
```

必须看到：

```text
小天文没有参与
```

## Demo 3：Dataset

导入 `examples/demo_chat.jsonl`，页面显示消息数量。

## Demo 4：Replay

Keyword Judge 回放数据集，看到总消息 / 参与 / 忽略 / 失败，并逐条看到聊天形式结果。

## Demo 5：Review

任意一条选择“合适”，保存成功。

## Demo 6：Golden

任意一条保存为 Golden Case，`GET /api/golden` 能查到。

## Demo 7：Compare

Keyword Judge vs Always Reply，必须出现差异。

## Demo 8：Runs

Runs 页面看到之前所有 Playground / Replay Run，点击能查看完整过程。

---

# 38. 最终验收 Checklist

必须全部通过：

```text
[ ] docker compose up --build 成功
[ ] localhost:3000 可访问
[ ] 不需要任何 API Key
[ ] 不需要 AstrBot
[ ] Playground 可运行
[ ] 天文关键词会参与
[ ] 哈哈哈会忽略
[ ] 结果能看懂
[ ] 能展开完整处理过程
[ ] JSONL 能导入
[ ] Dataset 能显示聊天
[ ] Replay 能运行
[ ] Replay 是聊天形式
[ ] 可以人工 Review
[ ] 可以保存 Golden Case
[ ] Compare 能运行
[ ] Runs 能查看
[ ] Run Detail 可用
[ ] Components 页面可用
[ ] SQLite 数据持久化
[ ] pytest 全通过
[ ] Playwright E2E 全通过
[ ] README 完整
```

---

# 39. WebUI 理解性验收

打开任意 Run，不看代码、不看 JSON、不看后台日志，必须能回答：

1. 用户说了什么？
2. 小天文参与了吗？
3. 为什么参与 / 不参与？
4. 参与概率多少？
5. 这是什么类型的问题？
6. 有没有读取记忆？
7. 模型看到了哪些内容？
8. 模型输出了什么？
9. 最后执行了什么？
10. 如果失败，失败在哪一步？

如果其中任何一个问题只能通过读 JSON 才知道，则 WebUI 不合格。

---

# 40. 整个 MVP 的一句话

最终成品应该让开发者能够：

> 导入一段过去小天文没有参与过的真实群聊，然后像看聊天记录一样重新播放，并看到“如果当时小天文在线，它会不会参与、为什么、会说什么”。

这就是第一版 Test Studio 的全部目标。

**不要继续扩展。**
