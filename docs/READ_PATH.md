# 原生当前对话读取路径

在当前消息入库前，以 currentState 读取同 scope 既有长期记忆。沿用 BGE embedding + FP32 reranker、三关系方向和来源合同，支持 formed_multiquery、graph_expansion、attention_diffusion，不用词面替身冒充语义读取。

POST /api/context 输入 scope、currentState，选填 mode、autoSignificance、limit、checkBudget、contextBudget。默认 attention_diffusion，无额外模型调用；未判断时只返回候选，工作上下文为空。autoSignificance=true 最多一次独立模型判断，仅来源支持且适合当前对话的记忆进入内部上下文，不授权真实群披露或回复。

currentState 为 messages（1–8 条，id/speaker/time/text/replyTo）和 focusSpeakerId。拒绝未知字段、query/gold、目标 ID 和未来污染。调用须在当前消息入库前，同 scope 的未完成任务需先处理。读取使用一致快照，索引在快照建立；源 scope 期间变化则拒绝陈旧结果，不隐式重试。

contextText JSON 包含当前状态和通过判断的记忆，字符数不超过 contextBudget。单条记录完整保留或舍弃，当前状态超预算拒绝，不静默截断；审计 trace 不受上下文预算限制。成功读取写 recalls，不改变既有原文、节点或关联。

公开模型准备工具下载固定 revision 和哈希的 ONNX 文件，不读或上传聊天。运行语义读取离线；显式适用性判断才发送当前状态、候选及来源给现有同款模型。此路径限内部小规模使用，不宣称质量或收益验收。

## 当前验证（2026-10-05）

192 项合成测试通过。另在新建临时数据库上使用人工合成历史，通过 HTTP 实际加载本地 BGE：formed_multiquery、graph_expansion、attention_diffusion 均返回四条候选；关闭适用性判断时 selectedMemories 全为空。一次显式 gpt-6.1-sol medium 判断完成，模型调用 1 次，四条合成候选进入内部上下文，contextText 为 964 字符（预算 8000），四次成功读取均写入审计。

这证明此次环境中的模型加载、HTTP 传输、判断调用和上下文封装可执行，不是独立质量、扩散收益、真实群部署或生产验收。
