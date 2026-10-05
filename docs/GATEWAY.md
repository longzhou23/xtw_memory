# HTTP API 与显式恢复

启动与安装见 [README](../README.md)。以下命令从仓库根目录运行。

## 看懂状态与恢复

| 状态 | 意义 | 操作 |
|---|---|---|
| QUEUED | 原文已保存，尚未开始整理 | 等待 |
| RUNNING | 正在分类或整理 | 查询，不重发新 ID |
| DONE | 这个任务已提交 | 消息完成不等于已经 Final，关闭任务也应检查 DONE |
| ARCHIVED | 原文保留，但未进入语义整理 | 查看 reason；晚到、超长或纯不可读媒体 |
| FAILED | 已知失败，当前群后续任务暂停 | 修正失败原因后显式 retry |
| REVIEW | 进程中断，外部调用结果不确定 | 先核查旧进程/外部调用，不自动重试 |

```sh
scripts/chat-gateway job 13
scripts/chat-gateway retry 13
scripts/chat-gateway close 试用群 --id manual-close-001
```

对 REVIEW，只有操作者确认旧进程和调用均已结束、且无可采用的已提交结果后，才执行：

```sh
scripts/chat-gateway review 13 --confirm-ended
scripts/chat-gateway retry 13
```

确认会保留核查记录，并将未确认的写入标为失败；不会伪造成功或删除原文。可能再次产生模型成本。若旧 scope 进程仍存活，程序拒绝确认。不要用这个操作处理仍在运行的调用。

## 后续 Bot 接口

只接受回环 HTTP 和 `Authorization: Bearer <本地令牌>`，请求为 `application/json`，不超过 65536 字节。消息接口无需 sequence，也无需 Episode ID。

| 接口 | 输入 / 用途 |
|---|---|
| POST /api/messages | `{scope,event}`；202 返回持久接收 jobId |
| GET /api/job?id=13 | 单个任务、原始消息、结果或失败原因 |
| GET /api/jobs?scope=群号&after=0&limit=50 | 按接收 ID 分页，包含未整理原文 |
| GET /health | 后台状态、队列和失败数量、CPU 计数 |
| POST /api/stop | `{confirm:true}`；停止接收，等待当前调用结束，保留队列 |
| POST /api/close | `{scope,id}`；同群先处理完前面的消息，再关闭和 Final |
| POST /api/retry | `{jobId}`；只重试已知 FAILED |
| POST /api/review | `{jobId,confirmEnded:true}`；显式核查确认，不自动重试 |
| GET /api/summary?scope=群号 | 原文、节点、Episode、写入计数 |
| GET /api/memories?scope=群号&after=0&limit=50 | 记忆/实体节点，包括 stage、status、evidence |

未确认接收时：格式错误为 400，重复 ID 正文冲突为 409，容量不足为 429，存储暂不可用为 503。发送方在失败后保留自己的消息，可重发相同 ID；收到 202 后用 jobId 查询。群聊平台适配器只承担事件格式转换和可靠投递，暂不需要承担记忆整理或模型选择。

## 试用边界

默认 FIFO 12 / 批量 6，Episode 最多 24 条，空闲 15 分钟 / 最长 1 小时后关闭。单群按接收顺序处理；较旧时间的晚到消息留档，不修改原时间。已知误并/误拆仍存在。慢 writer 会延迟后台整理，接收继续；单个 writer 最多等待 180 秒，失败不无限重试。

本轮目标是完整且可观察的内部小规模使用。Bot harness、对真实群的自动发言、图片识别和大流量部署尚未包含。记忆的来源可追溯不等于陈述必然正确；已完成的历史研究否定结论继续保留。
