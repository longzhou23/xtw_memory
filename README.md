# 小天文 Memory：完整链路的最小实现

从当前开发工作区提取的内部轻度群聊服务：CPU Router → SQLite 持久接收队列 → Episode FIFO/Temporary → 真实模型 Writer → Final 记忆及来源审计。提供本地 HTTP API、文件导入、状态查询和显式失败恢复。

本分支是独立源码快照，不包含研究历史、私有聊天、数据库、令牌、训练数据或模型权重。Router 仍有误并/误拆，历史语义验收为 NOT_ADOPTED；此服务仅供内部小规模试用。没有自动群聊回复、图片识别或线上质量保证。读取接口提供形成记忆及来源；研究版的关联召回、扩散实验和回应生成未纳入此最小网关。

## 环境与安装

Linux、Python 3.11+（使用 fcntl 和 hashlib.file_digest）。首次安装 CPU 模型依赖需要网络，运行 Router 时仅读取本地封存权重。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install 'torch==2.13.0+cpu' --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r router_deploy/requirements-cpu.txt
```

Writer 使用已安装、已登录的 **Codex CLI 0.159.3**，并要求当前账户可运行 `gpt-6.1-sol`。实现保留已有版本与官方服务预检；版本不同或端点被覆盖时拒绝调用模型。启动显式启用 `gpt-6.1-sol` / `medium` 写入；原文会发给配置的模型，单次最多 180 秒，失败不自动重试。

## Router 模型

源码本身不能替代已有的两份 CPU 分类权重。准备模型持有者提供的 `model_seal.json` 与 boundary/ranking 完整 checkpoint，按 [模型说明](docs/MODELS.md) 设置路径。加载时逐文件校验 SHA-256，禁止用未封存的替代模型冒充当前版本。

```sh
export XTW_MEMORY_SEAL=/absolute/path/to/model_seal.json
scripts/chat-gateway serve --writer codex
```

也可使用 `scripts/chat-gateway serve --writer codex --seal /absolute/path/to/model_seal.json`。默认监听 `127.0.0.1:8767`，数据与私有令牌保存在 `research-mvp/var/`。可通过 `XTW_MEMORY_PYTHON` 指定另一个已安装 CPU 依赖的 Python。

## 试用

另一个终端运行：

```sh
scripts/chat-gateway status
scripts/chat-gateway import examples/messages.json --close
scripts/chat-gateway jobs synthetic-demo
scripts/chat-gateway summary synthetic-demo
scripts/chat-gateway memories synthetic-demo
scripts/chat-gateway stop
```

导入返回持久接收回执，后台整理随后执行；用 jobs 确认消息和 close 任务均为 DONE。示例完全合成，不读取既有聊天。客户端自动读取本地私有令牌。

详见 [HTTP API 与恢复操作](docs/GATEWAY.md)。单群按接收顺序处理，同群同 ID 同内容幂等；重复 ID 正文冲突拒绝。FIFO 12 / 批量 6，Episode 最多 24 条，空闲 15 分钟或跨度 1 小时后关闭。晚到、超长或不可读媒体保留原文并标为 ARCHIVED。

## 离线测试

这些测试使用合成输入与模型替身，验证持久接收、去重、失败阻塞、恢复、FIFO、Final、来源合同和 HTTP 行为，不调用真实 Writer 或评估 Router 语义质量。无需安装模型依赖：

```sh
cd research-mvp
PYTHONPATH=.:../router_deploy python3 -m unittest discover -s tests -t . -v
```

[提取与验证记录](docs/DELIVERY.md)说明此次交付范围。仓库保持私有；不授予未声明的第三方模型许可。
