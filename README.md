# 小天文 Memory：完整链路的最小实现

小天文 Memory 是一个面向**内部、小规模群聊试用**的记忆整理服务。它先把消息可靠地保存到本地，再用 CPU 分类模型分配话题，把话题中的消息逐步整理成临时记忆，最后形成带来源证据的长期记忆。

```text
群聊平台 / JSON 消息文件
          │
          ▼
本地 HTTP 网关 → SQLite 持久接收队列 → 接收回执 jobId
                                      │
                                      ▼
                         CPU Router 自动选择 Episode
                                      │
                                      ▼
                         Episode 独立 FIFO 工作上下文
                                      │ 挤出触发
                                      ▼
                         真实 Writer → Temporary 记录
                                      │ 关闭后整理
                                      ▼
                         Final 记忆 / 实体 / 关联 / 来源
```

本分支提取当前开发版本的运行源码、合成示例和测试，便于单独阅读、验证和接入。**当前 Router 权重通过同仓库的 [GitHub Release](https://github.com/longzhou23/xtw_memory/releases/tag/memory-minimal-20261005-router-v02) 提供；真实运行还需要已登录的 Writer 环境。** 仓库和 Release 保持私有，下载需要仓库访问权限。大文件作为 Release 附件分发，不进入源码 Git 历史。

Router 仍有误并、误拆，历史语义验收为 `NOT_ADOPTED`。完整链路可以用于观察内部轻度使用行为，但不能据此宣称话题分类准确、记忆陈述必然正确或已经通过生产验收。

## 目录

- [功能与范围](#功能与范围)
- [核心概念与处理流程](#核心概念与处理流程)
- [环境要求](#环境要求)
- [安装与模型准备](#安装与模型准备)
- [启动与首次试用](#启动与首次试用)
- [消息格式](#消息格式)
- [命令行参考](#命令行参考)
- [HTTP API 与 Bot 接入](#http-api-与-bot-接入)
- [任务状态与失败恢复](#任务状态与失败恢复)
- [数据存储与备份](#数据存储与备份)
- [固定配置与容量边界](#固定配置与容量边界)
- [测试与验证范围](#测试与验证范围)
- [常见问题](#常见问题)
- [源码结构与相关资料](#源码结构与相关资料)

## 功能与范围

| 功能 | 当前行为 |
|---|---|
| 持久接收 | 返回回执前保存原始消息；整理在后台执行 |
| 自动话题分配 | 本地 CPU 双判别器选择新建或延续已有 Episode |
| 临时记忆 | 每个 Episode 独立 FIFO；批量挤出时调用 Writer |
| 最终整理 | Episode 关闭后形成 Final 节点、关联及来源记录 |
| 来源约束 | 校验实际可读事件、记忆引用和结构，不把未决内容自动变为确定事实 |
| 可观察状态 | 查询接收、处理中、成功、归档、失败与待核查任务 |
| 恢复 | 保留队列与原文；已知失败显式重试，不确定外部调用显式核查 |
| 接入方式 | 回环 HTTP API，以及 JSON / JSONL 文件导入客户端 |
| 读取 | 分页查看形成的记忆与实体节点、阶段、状态及证据 |

本最小网关没有提供自动群聊回复、图片识别、网页管理界面、按查询召回接口、关联扩散实验、回应生成或完整 Bot 平台适配器。Final 可以形成关联，但 HTTP 网关不提供图遍历和关联检索接口。

## 核心概念与处理流程

| 概念 | 含义 |
|---|---|
| `scope` | 数据空间，通常对应一个稳定的群聊 ID |
| Event | 带稳定 ID、作者、时间和正文的原始消息 |
| Episode | Router 自动分配的话题容器；分到同一容器不证明语义完全一致 |
| FIFO | 每个 Episode 最近消息构成的工作上下文 |
| Temporary | FIFO 挤出时形成的增量记录，可表达陈述、更新、未决指代和冲突 |
| Final | 关闭经历后的整理结果；确定内容与未决内容保留不同阶段 |
| `jobId` | 网关生成的持久任务编号，用于查询状态和恢复 |
| 模型封存文件 | 描述 checkpoint 路径、文件哈希和模型身份的 JSON |

一次消息处理包括以下步骤：

1. 校验消息并写入接收队列，返回 `202` 与 `jobId`。这表示已经保存，后台可能尚未开始整理。
2. 后台按同一 `scope` 的接收顺序取出任务，使用此前实际提交的历史建立 Router 候选。调用方不提供 Episode ID 或序号。
3. 无候选时直接建立新 Episode，不执行分类模型；有候选时由两个 CPU 判别分支判断新话题及候选归属。
4. 消息进入该 Episode 的 FIFO。容量未满时不会仅因这条消息调用 Temporary Writer；挤出时批量整理，并保留来源和写入记录。
5. 达到关闭条件或收到显式关闭任务后，归档该 Episode 的临时集合，执行 Final 整理。关闭后的 Episode 不重新打开；同一群仍可接收新消息，形成后续 Episode。

消息 `DONE` 不等于已经形成 Final。需要最终结果时，检查关闭任务也为 `DONE`。Writer 可能返回空记录，不能以记忆条数判断是否处理成功。

## 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Linux；工作进程锁使用 `fcntl` |
| Python | 3.11+；使用 `tomllib` 和 `hashlib.file_digest` |
| 存储 | 本地可写目录，使用 Python 自带 SQLite |
| Router | 两份完整、哈希匹配的 boundary / ranking checkpoint |
| CPU 依赖 | 版本见 [requirements-cpu.txt](router_deploy/requirements-cpu.txt) |
| Writer | 已安装且已登录的 **Codex CLI 0.159.3**；账户可运行 `gpt-6.1-sol` |
| 内存 | 原本机完整网关约需 4–5 GiB；加载峰值及其他进程还需额外空间 |
| 网络 | 安装依赖和真实 Writer 需要网络；Router 从本地离线加载模型 |

当前网关固定使用 `gpt-6.1-sol`、`medium`、官方 OpenAI 认证路径和单次 180 秒预算。调用前核对 CLI 版本与配置身份；版本不同或存在受禁止的端点覆盖时拒绝调用。网关没有选择其他 Writer 的命令行参数。

Writer 会把相关消息、上下文及来源材料发送给配置的模型。运行合成示例也会产生真实模型调用和相应成本。HTTP 消息接收本身无需等待这一调用完成。

## 安装与模型准备

### 1. 获取本分支

仓库为私有，需要具有读取权限的 GitHub 账户。当前默认分支 `main` 已包含最小实现。以下命令获取主分支：

```sh
git clone --single-branch --branch main \
  https://github.com/longzhou23/xtw_memory.git xtw-memory-minimal
cd xtw-memory-minimal
```

后面的命令均从这个仓库根目录运行，除非明确写了 `cd research-mvp`。它是独立源码快照，目录结构与原研究工作区不同。

### 2. 安装 CPU 依赖

```sh
python3 -m venv .venv
.venv/bin/python -m pip install 'torch==2.13.0+cpu' \
  --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r router_deploy/requirements-cpu.txt
```

不需要激活虚拟环境；启动脚本会自动选择根目录 `.venv/bin/python`。首次安装需联网。依赖或 Python 版本不支持当前平台时，先解决安装问题，再启动网关。

### 3. 下载并准备当前权重

权重入口：[当前网关 Router 权重 Release](https://github.com/longzhou23/xtw_memory/releases/tag/memory-minimal-20261005-router-v02)。需要已登录、具有本仓库读取权限的 GitHub 账户。该发布保留实验身份，版本是当前服务使用的历史稳定双判别器 v0.2，输入版本为 `two-judge-observable-v3`，没有切换到其他训练实验。

Release 包含两个完整模型包、包校验文件和发布清单：

| 附件 | 内容 |
|---|---|
| `xtw-router-boundary-v0.2-observable-v3.tar.gz` | 新话题 / 延续判断分支，包含权重、编码器配置和 tokenizer |
| `xtw-router-ranking-v0.2-observable-v3.tar.gz` | 已有 Episode 排序分支，同样包含完整运行文件 |
| `SHA256SUMS` | 两个压缩包的 SHA-256 |
| `release_manifest.json` | 模型身份、输入版本、阈值、附件大小和哈希 |

安装并登录 GitHub CLI 后，从仓库根目录下载：

```sh
mkdir -p models/downloads
gh release download memory-minimal-20261005-router-v02 \
  --repo longzhou23/xtw_memory \
  --pattern 'xtw-router-*.tar.gz' \
  --pattern SHA256SUMS \
  --pattern release_manifest.json \
  --dir models/downloads

# 两项都应显示 OK；校验失败时不要解压使用
(cd models/downloads && sha256sum -c SHA256SUMS)

tar -xzf models/downloads/xtw-router-boundary-v0.2-observable-v3.tar.gz -C models
tar -xzf models/downloads/xtw-router-ranking-v0.2-observable-v3.tar.gz -C models
```

也可在 Release 网页下载同名附件，放到 `models/downloads/` 后运行校验和解压命令。GitHub 自动生成的 Source code 压缩包只包含源码，**不包含这两份模型**。

解压后结构如下，两个 checkpoint 的文件集合相同：

```text
models/
├── boundary/checkpoint/
│   ├── model.safetensors
│   ├── rl_agent_config.json
│   ├── encoder/config.json
│   └── tokenizer/
│       ├── tokenizer_config.json
│       └── tokenizer.json
├── ranking/checkpoint/
│   └── 同样的五个文件
└── downloads/
```

两份解压后的 `model.safetensors` 各为 1,287,653,720 字节，完整模型目录合计约 2.64 GB；下载和解压同时保留时还需压缩包空间。`models/` 已被 Git 忽略。

根据仓库提供的封存模板，为本机生成绝对路径配置：

```sh
python3 - <<'PYTHON'
import json
from pathlib import Path

root = Path.cwd()
seal = json.loads((root / 'examples/model_seal.example.json').read_text())
for checkpoint in seal['checkpoints']:
    path = root / 'models' / checkpoint['branch'] / 'checkpoint'
    if not path.is_dir():
        raise SystemExit(f'缺少模型目录：{path}')
    checkpoint['path'] = str(path.resolve())
(root / 'models/model_seal.json').write_text(
    json.dumps(seal, ensure_ascii=False, indent=2) + '\n'
)
PYTHON
export XTW_MEMORY_SEAL="$(pwd)/models/model_seal.json"
```

模型包内只包含封存清单列出的五个运行文件，不包含训练数据、聊天原文、用户凭据或本机软链接。模板保留当前模型的逐文件 SHA-256，加载器会再次核对；不要改写哈希绕过校验。

数据库绑定封存 JSON 自身的 SHA-256：修改路径、格式或内容后，旧数据库可能因身份不同而被拒绝。已有网关继续使用原封存文件即可；在新机器或重新定位模型时，保留旧库并使用新的试用数据库，项目不提供迁移。

更多说明见 [CPU Router 模型边界](docs/MODELS.md)。

### 4. 确认 Writer 环境

```sh
codex --version
```

当前实现要求输出 `codex-cli 0.159.3`。登录由现有 Codex 环境管理，仓库不包含凭据。依赖安装、Router 权重就绪和 CLI 已登录分别是不同条件；只有实际执行 Writer 才能确认本次认证、网络和模型调用可用。

## 启动与首次试用

### 启动

```sh
scripts/chat-gateway serve --writer codex
```

也可直接指定封存文件：

```sh
scripts/chat-gateway serve --writer codex \
  --seal /absolute/path/to/model_seal.json
```

服务固定监听回环地址，默认 `http://127.0.0.1:8767`。第一次启动生成本地私有令牌，终端输出数据库位置、令牌文件位置和 `LOADING` 状态，不输出令牌正文。

另开一个终端检查：

```sh
scripts/chat-gateway status
```

确认 `worker` 为 `READY`、`status` 为 `ok` 后再试用。监听成功不等于模型加载成功；若状态为 `ERROR`，查看返回的 `error`。`READY` 也不等于 Writer 已经完成真实调用。

### 导入合成示例

```sh
scripts/chat-gateway import examples/messages.json --close
scripts/chat-gateway jobs synthetic-demo
scripts/chat-gateway summary synthetic-demo
scripts/chat-gateway memories synthetic-demo
```

示例只含虚构的笔记本送修计划，不读取既有聊天。`--close` 在文件消息之后为各 `scope` 排入关闭任务。导入输出中的 `accepted` 表示请求已被确认，后台整理状态应以任务查询为准。

示例包含固定历史时间。实际试用时可以准备带当前时间的新合成文件；历史消息的时间会影响 TTL 关闭，因此不保证每次试用出现相同的 Episode 数、调用次数或记忆条数。

### 停止与续跑

```sh
scripts/chat-gateway stop
```

也可在服务终端按 Ctrl+C。程序停止接收，等待当前有界模型调用结束，未处理队列保留。重新执行同样的启动命令、使用相同数据库及封存配置即可继续。一个数据库只允许一个工作进程。

## 消息格式

文件导入支持 UTF-8 JSON 数组，以及每行一个对象的 JSONL。JSON 数组文件最多 4 MiB；更大的文件使用 JSONL，每条请求仍受 HTTP 大小限制。

```json
[
  {
    "scope": "group-demo",
    "event": {
      "id": "message-001",
      "speaker": "member-a",
      "time": "2026-10-05T10:00:00+08:00",
      "text": "准备周五送笔记本维修，还没送到店里。",
      "displayName": "小林",
      "role": "user",
      "media": "text_only"
    }
  },
  {
    "scope": "group-demo",
    "event": {
      "id": "message-002",
      "speaker": "member-a",
      "time": "2026-10-05T10:00:01+08:00",
      "text": "更正：改周六送修。",
      "replyTo": "message-001"
    }
  }
]
```

| 字段 | 必需 | 规则 |
|---|---|---|
| `scope` | 是 | 非空字符串，最多 200 字符；通常使用稳定群号 |
| `event.id` | 是 | 非空字符串，最多 200 字符；同 scope 消息 ID 唯一 |
| `event.speaker` | 是 | 非空字符串，最多 200 字符；稳定作者 ID，不依赖昵称识别人 |
| `event.time` | 是 | 带时区的 ISO 8601 时间，例如 `+08:00` 或 `Z` |
| `event.text` | 是 | 正文最多 12000 字符；超过路由长度上限时只留档 |
| `event.replyTo` | 否 | 原始回复目标 ID 或 `null`；不要求目标已经在接收窗口中 |
| `event.displayName` | 否 | 非空显示名，最多 200 字符，或 `null` |
| `event.role` | 否 | `user` / `assistant` / `system` / `unknown`；默认 `unknown` |
| `event.media` | 否 | `none` / `unreadable` / `text_only`；默认 `none` |

外层只接受 `scope`、`event`；事件不接受表中之外的字段。**不要自行传 `sequence` 或 Episode ID。** 未呈现原文的回复目标只作为结构指针保存，不被自动解释成已知人物或事实。

纯不可读媒体使用 `text: ""`、`media: "unreadable"`，接收后标为归档。如果有图片说明文字，提交实际可读说明；服务不会读取图片像素。其他普通消息正文应为非空文本。

重复提交同一 `scope`、同一消息 ID、相同标准化内容时返回原回执，不重复处理。正文、时间或其他保留元数据不同则视为冲突。不同 `scope` 可以使用相同消息 ID。

## 命令行参考

```text
scripts/chat-gateway [全局选项] 子命令 [子命令选项]
```

| 全局选项 | 默认值 / 用途 |
|---|---|
| `--db PATH` | 仓库内 `research-mvp/var/chat-light.sqlite3` |
| `--token-file PATH` | 数据库路径后追加 `.token` |
| `--url URL` | `http://127.0.0.1:8767`；用于客户端连接 |

| 子命令 | 用途 |
|---|---|
| `serve --writer codex [--seal PATH] [--port N]` | 启动服务；明确启用真实 Writer |
| `status` | 查看后台状态、队列数量与 CPU 计数 |
| `import FILE [--close]` | 顺序导入文件；可在导入后排入关闭任务 |
| `jobs SCOPE [--after N] [--limit N]` | 按任务编号分页查询 |
| `job ID` | 查询单个任务、原始输入、结果和错误 |
| `summary SCOPE` | 查看事件、Episode、节点及写入等数量 |
| `memories SCOPE [--after N] [--limit N]` | 分页查看记忆 / 实体节点 |
| `close SCOPE --id REQUEST_ID` | 排入该 scope 所有开放 Episode 的关闭及最终整理 |
| `retry ID` | 显式重试已知 `FAILED` 任务 |
| `review ID --confirm-ended` | 对 `REVIEW` 任务记录操作者核查确认 |
| `stop` | 停止接收，等待当前调用结束 |

全局选项放在子命令之前。自定义数据库和端口示例：

```sh
scripts/chat-gateway --db /absolute/path/to/trial.sqlite3 \
  serve --writer codex --seal /absolute/path/to/model_seal.json --port 8768

# 客户端必须选择相同数据库对应的令牌和端口
scripts/chat-gateway --db /absolute/path/to/trial.sqlite3 \
  --url http://127.0.0.1:8768 status
```

`--url` 不改变服务监听端口，服务端使用 `serve --port`。检查完整帮助：

```sh
scripts/chat-gateway --help
scripts/chat-gateway serve --help
```

启动包装脚本依次选择 `XTW_MEMORY_PYTHON`、根目录 `.venv/bin/python`、系统 `python3`。需要使用已有 CPU 环境时：

```sh
export XTW_MEMORY_PYTHON=/absolute/path/to/venv/bin/python
```

`XTW_MEMORY_SEAL` 提供默认封存文件；显式 `--seal` 优先。`XTW_RESEARCH_TMP` 可指定 Writer 临时文件目录，默认 `/tmp/opencode`，每次调用的临时子目录在退出后清理。

## HTTP API 与 Bot 接入

所有接口，**包括 `/health`**，均需要：

```http
Authorization: Bearer <本地令牌>
```

POST 还需要 `Content-Type: application/json`、有效的 `Content-Length`，正文为 JSON 对象，大小 1–65536 字节。不接受分块传输。服务校验 `Host` 为对应端口的 `127.0.0.1` 或 `localhost`，客户端只支持回环 HTTP。

令牌是本地管理员凭据，可以访问所有 scope。scope 数据隔离不构成多租户权限控制；当前没有公网部署或远程用户认证入口。

| 方法 | 路径 | 参数 / 返回 |
|---|---|---|
| POST | `/api/messages` | `{scope,event}`；返回接收回执 |
| GET | `/api/job?id=13` | 单个任务回执、输入、结果及错误 |
| GET | `/api/jobs?scope=群号&after=0&limit=50` | 任务数组；按 `jobId` 递增 |
| GET | `/health` | `worker`、`queued`、`running`、`failed`、`review`、`archived`、`done`、错误和计数 |
| POST | `/api/close` | `{scope,id}`；排入关闭任务 |
| POST | `/api/retry` | `{jobId}`；重排已知失败任务 |
| POST | `/api/review` | `{jobId,confirmEnded:true}`；记录不确定调用的核查确认 |
| POST | `/api/stop` | `{confirm:true}`；请求停止 |
| GET | `/api/summary?scope=群号` | 事件、节点、关联、Episode、写入等计数 |
| GET | `/api/memories?scope=群号&after=0&limit=50` | `{items,next}`；形成的记忆 / 实体节点 |

`jobs` 与 `memories` 的 `limit` 为 1–200，默认 50。任务分页将最后一条 `jobId` 作为下一页 `after`；记忆分页将返回的 `next` 作为下一页 `after`。`next` 为 `null` 表示本次没有条目。

用 curl 发送消息文件中的一个对象时，可以先准备 `one-message.json`，再运行：

```sh
XTW_MEMORY_TOKEN=$(cat research-mvp/var/chat-light.sqlite3.token)
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $XTW_MEMORY_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @one-message.json \
  http://127.0.0.1:8767/api/messages
```

`one-message.json` 应是单个 `{scope,event}` 对象，而非文件导入使用的数组。接收回执主要字段包括 `jobId`、`scope`、`kind`、原始 `id`、`status`、`received`、`updated`、`duplicate`、`event`、`result` 和 `error`。对于关闭任务，输入字段为 `operation`。

Bot 适配器应把平台稳定群号、作者 ID、消息 ID、时间与正文转换成上述格式，可靠投递并保存回执。它不需要选择 Episode 或组织临时记忆。收到 `202` 后使用 `jobId` 查询；未获得明确回执时，保留本地消息并用相同 ID、相同内容重送。

| HTTP 状态 | 含义 |
|---|---|
| `200` | 查询成功 |
| `202` | 写操作已接受；不表示记忆形成完毕 |
| `400` | 格式、字段、参数或操作状态不合法 |
| `401` | 缺少令牌或令牌不匹配 |
| `403` | Host 不符合回环接口要求 |
| `404` | 未知 GET 路径；未知 POST 路径返回 `400` |
| `409` | 同 scope 同 ID 的保留内容发生冲突 |
| `429` | 接收容量不足，未确认此次接收 |
| `503` | 存储暂不可用；保留消息，可重送相同 ID |

## 任务状态与失败恢复

| 状态 | 意义 | 处理方式 |
|---|---|---|
| `QUEUED` | 原文已保存，等待后台处理 | 查询进度 |
| `RUNNING` | 正在分类或整理 | 等待，不用新 ID 重发 |
| `DONE` | 本任务已提交 | 需要 Final 时另查关闭任务 |
| `ARCHIVED` | 原文保存，但未进入语义整理 | 查看 `result.reason` |
| `FAILED` | 已知处理失败 | 修正原因后显式 `retry` |
| `REVIEW` | 中断后存在不确定的外部调用或在途状态 | 核查旧进程和调用后显式确认 |

常见归档原因：`TEXT_LIMIT`（超过路由正文长度）、`UNREADABLE_ONLY`（纯不可读媒体）、`LATE_MESSAGE`（处理时发现早于该 scope 已提交时钟）。这些原文仍可从任务回执查询。超过 12000 字符的正文会在校验阶段拒绝，不属于已接收归档。

失败或待核查任务会阻塞同一 scope 的后续任务；其他 scope 仍可处理，但所有模型工作共享一个后台工作进程，正在等待的慢 Writer 会延迟其他 scope 的整理。HTTP 接收可继续。

已知失败：

```sh
scripts/chat-gateway job 13
# 修正 job 返回的具体错误后
scripts/chat-gateway retry 13
scripts/chat-gateway job 13
```

不确定调用：先确认旧进程和相关外部调用已经结束，并核查是否已有可采用的提交结果。满足条件后执行：

```sh
scripts/chat-gateway review 13 --confirm-ended
scripts/chat-gateway retry 13
```

确认会保存核查记录，并将未确认写入标为失败；不删除原文，也不伪造成功。旧 scope 操作仍存活时会拒绝确认。重试可能再次产生模型费用。不要通过修改数据库状态绕过这个流程。

文件导入不是整个文件的一次原子事务。遇到格式错误或容量上限时，之前已经确认的条目保留，输出 `acceptedBeforeError`。修正后可重导同一文件，已接收消息依据 ID 与内容去重。

## 数据存储与备份

默认运行目录：

```text
research-mvp/var/
├── chat-light.sqlite3           # 接收队列、原文、Episode、记忆、证据和调用记录
├── chat-light.sqlite3-wal       # SQLite 运行时可能存在
├── chat-light.sqlite3-shm       # SQLite 运行时可能存在
├── chat-light.sqlite3.token     # 本地管理员令牌，权限 0600
└── chat-light.sqlite3.worker.lock
```

数据库与令牌在启动时设置为私有权限。令牌文件必须由当前用户拥有，且不得开放组或其他用户权限；软链接令牌文件被拒绝。数据库不是加密存储，操作系统账户和文件访问权限仍是数据边界。

`var/`、模型文件、虚拟环境及日志等已被 Git 忽略。不要把真实聊天、数据库、认证文件、数据导出或个人身份映射加入提交。

最简单的完整备份方式是先执行 `stop`，确认服务进程已退出，再将整个运行目录复制到受控备份位置。不要只在服务运行中复制 `.sqlite3` 主文件而遗漏可能存在的 WAL。备份应同时保留模型封存文件与对应权重的身份信息。

恢复时使用相同配置和模型封存文件。旧研究数据库、不同网关配置或不同封存身份都会被拒绝；本项目不提供向后兼容和数据迁移。需要新配置时保留旧数据目录并用 `--db` 指定新的试用库。

## 固定配置与容量边界

以下是当前启动入口采用的固定值，除列出的启动参数外没有对应 CLI 调节项：

| 项目 | 当前值 |
|---|---|
| Episode FIFO 容量 | 12 条 |
| 挤出批量 | 6 条 |
| 单 Episode 事件上限 | 24 条 |
| 空闲关闭间隔 | 900 秒，即 15 分钟 |
| 最大经历跨度 | 3600 秒，即 1 小时 |
| Router 输入版本 | `two-judge-observable-v3` |
| 新话题判断阈值 | 0.50 |
| CPU 模型线程数 | 4 |
| 进入语义处理的正文上限 | 1024 字符 |
| 可接收正文上限 | 12000 字符；1025–12000 字符留档 |
| 未完成任务上限 | 1000；包含失败与待核查任务 |
| 消息接收记录上限 | 50000 条；关闭等操作另按同样条数上限计数 |
| 接收消息载荷累计上限 | 268435456 字节，即 256 MiB |
| HTTP POST 正文上限 | 65536 字节 |
| Writer 单次时间预算 | 180 秒，包含受控预检 |
| Writer 请求 / 流重试 | 0；应用层失败也不自动重试 |

256 MiB 限制统计接收消息序列化载荷，不是整个 SQLite 文件大小。后台完成任务不会删除接收历史，持续积累仍会触达总量上限。

自动关闭依据事件时间、已提交历史及后台调度检查执行。队列积压、失败阻塞、历史或未来时间均可能影响关闭时机，不保证墙钟到点立即完成 Final。

## 测试与验证范围

离线测试只需 Linux 与 Python 3.11+，不需要安装 PyTorch、下载权重、登录 Codex 或调用模型：

```sh
cd research-mvp
PYTHONPATH=.:../router_deploy python3 -m unittest discover -s tests -t . -v
```

当前快照包含 **100 项测试**，覆盖持久接收、认证、去重、scope 隔离、慢 Writer 并行接收、TTL、FIFO、Temporary / Final 合同、来源检查、失败恢复、Router 可见输入和发行入口。

此源码交付已经通过本机测试、包含空格路径的全新克隆测试，以及 GitHub Actions 的 Python 3.11 / 3.14 验证。最新运行记录见 [GitHub Actions](https://github.com/longzhou23/xtw_memory/actions)。

这些测试使用合成输入及模型替身，证明软件合同和已覆盖的恢复行为。它们不证明真实 Router 语义质量、真实 Writer 本次可用、长期群聊效果或记忆系统的研究净优势。此次整理没有重新执行真实模型端到端验收。权重发布另完成逐文件及压缩包哈希复核，并从两包重新解压、实际 CPU 加载和执行一次合成路由（两个编码分支，零 Writer 调用），验证发布包可加载。

## 常见问题

| 现象 | 检查与处理 |
|---|---|
| 启动提示需要 `--seal` | 设置 `XTW_MEMORY_SEAL`，或在 `serve` 后传 `--seal` |
| `ModuleNotFoundError` | 确认根目录 `.venv` 已安装 CPU 依赖，或指定正确的 `XTW_MEMORY_PYTHON` |
| checkpoint 缺文件、哈希不符 | 核对模型包和模板中的绝对路径；补齐原文件，不修改哈希绕过校验 |
| 已监听但 `worker=ERROR` | 用 `status` 查看加载错误；HTTP 监听并不代表后台已就绪 |
| 首次模型写入失败 | 查询任务错误，检查 CLI 0.159.3、现有登录、账户模型权限、配置与网络 |
| 提示网关冻结配置不同 | 保留旧库，用新的 `--db` 路径；不要迁移旧研究库或手改配置表 |
| 提示已有工作进程 | 找到原服务并正常停止；不要同时启动两个进程处理同一数据库 |
| `401` / 令牌权限错误 | 客户端使用服务实际令牌；自定义数据库时同步指定 `--db` 或 `--token-file`，核对所有者和 0600 权限 |
| 任务长期 `QUEUED` | 检查后台是否 READY、是否正在等待 Writer，以及同 scope 更早的 FAILED / REVIEW |
| 所有消息 DONE 但看不到 Final | 排入 `close`，并确认关闭任务 DONE；模型也可能没有形成可用节点 |
| 消息 ARCHIVED | 查看归档 reason；原文仍保存，未进入语义整理 |
| 导入返回部分成功后失败 | 看 `acceptedBeforeError`，修正原因后用同 ID 重导 |
| `429` 容量不足 | 区分队列积压与累计上限；处理失败 / 待核查任务，或保留旧库后另建试用库 |
| 内存不足或模型工作异常 | 停止继续投递，检查本机可用内存与 job 状态；存在不确定调用时走 REVIEW 核查流程 |

## 源码结构与相关资料

```text
.
├── README.md
├── scripts/chat-gateway              # 可移植启动包装脚本
├── examples/
│   ├── messages.json                 # 合成消息
│   └── model_seal.example.json        # 当前模型封存模板
├── research-mvp/
│   ├── scripts/chat_gateway.py        # 网关 CLI / 本地客户端
│   ├── research_memory/
│   │   ├── chat_gateway.py            # 接收队列、后台工作进程、HTTP API
│   │   ├── routing.py                 # 持久 Router 与生命周期接入
│   │   ├── episode_runtime.py         # FIFO / Temporary
│   │   ├── episode_final.py           # Final 整理与来源校验
│   │   ├── store.py                   # SQLite 存储
│   │   ├── contracts.py               # 输入及写入合同
│   │   ├── providers.py               # Writer 适配器
│   │   └── consolidation.py           # 存储模块所需整理依赖
│   └── tests/
├── router_deploy/
│   ├── requirements-cpu.txt
│   └── xtw_router/                    # 封存 CPU 判别器、协议及候选检索
├── docs/
└── .github/workflows/tests.yml
```

- [HTTP API 与恢复说明](docs/GATEWAY.md)
- [CPU Router 模型边界](docs/MODELS.md)
- [源码提取与验证记录](docs/DELIVERY.md)
- [原始输入文件哈希清单](docs/SOURCE_MANIFEST.json)

当前仓库保持私有，未声明开放源码许可。第三方依赖和模型权重适用各自许可；源码快照不授予额外的第三方权重分发权。
