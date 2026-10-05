# CPU Router 模型边界

当前入口是 `xtw_router.frozen.FrozenTwoJudgeCPU`，输入版本 `two-judge-observable-v3`，阈值 0.50。加载 boundary/ranking 两份历史稳定双判别器权重，各约 1.29 GB；网关约需 4–5 GiB 内存。模型未通过独立语义验收，保持实验身份。

本分支只投放运行源码和合成测试，不含 checkpoint、训练资料、原始实验封存文件中的本机路径。不存在公共权重下载地址；新机器必须另外取得现有受控模型包，源码克隆并不等于即开即用。

每个 checkpoint 需要 `model.safetensors`、`rl_agent_config.json`、`encoder/config.json`、`tokenizer/tokenizer_config.json` 和 `tokenizer/tokenizer.json`。封存 JSON 的 `checkpoints` 数组需要 boundary/ranking 两项，分别包含 `branch`、checkpoint 的绝对 `path`、`files`（相对文件名映射到 `sha256`）。保留原模型的哈希；复制后只更新路径，不改写权重或冒充新验收。

`XTW_MEMORY_SEAL` 或 `serve --seal` 指向封存 JSON。数据库绑定封存文件 SHA-256；重新定位模型导致封存文件变化时，使用新的试用数据库，不迁移或绕过原身份校验。默认服务不启用 typed overlays、encoder suffix 或其他训练实验。

不要把已有私有聊天、标注数据或密钥加入模型包。训练代码和训练数据不在最小运行范围内。

[封存文件模板](../examples/model_seal.example.json)保留当前两份模型的文件哈希与实验身份；复制并修改两项 `path` 后通过 `--seal` 指定，不需要修改源码。
