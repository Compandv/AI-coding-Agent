# MewCode 第八章验收清单：上下文管理

## Token 估算验收
- [ ] `TokenEstimator.estimate_text("abcd")` 返回稳定的正整数。
- [ ] 包含工具结果的 message 估算值大于同等纯文本估算值。
- [ ] Provider usage 记录后，后续 session token 估算不低于 usage input token 锚点。
- [ ] `/context` 输出当前 estimated tokens 和 context window。

## 工具结果落盘验收
- [ ] 单个工具结果超过 `single_result_byte_threshold` 时会写入 `.mewcode/sessions/<session_id>/tool-results/`。
- [ ] 落盘后的工具结果 metadata 包含 `stored_on_disk: true`。
- [ ] 落盘后的工具结果 metadata 包含 `stored_path`。
- [ ] 落盘后的工具结果 metadata 包含当前 `session_id`。
- [ ] 对话中的预览包含 `[head preview]`。
- [ ] 对话中的预览包含 `[tail preview]`。
- [ ] 对话中的预览包含 stored path。
- [ ] stored path 指向的文件可以读取到完整原始工具结果。
- [ ] stderr、错误日志或失败输出尾部包含的最终错误不会被只保留头部而丢失。

## 会话隔离验收
- [ ] 两个 ChatSession 生成不同的 `session_id`。
- [ ] 两个会话读取同名大文件时，stored path 不相同。
- [ ] 第一个会话的 stored path 包含第一个 session id。
- [ ] 第二个会话的 stored path 包含第二个 session id。
- [ ] `.mewcode/sessions/` 不会被提交到 Git。

## 自动压缩验收
- [ ] 请求模型前会先执行大工具结果瘦身。
- [ ] 请求 token 小于自动阈值时不会触发 compact。
- [ ] 请求 token 超过自动阈值时会触发 auto compact。
- [ ] auto compact 完成后会更新外层 ChatSession messages。
- [ ] auto compact 完成后不会留下 orphan tool result。
- [ ] auto compact 后 `ContextCompressionFinished.after_tokens` 不高于目标预算。
- [ ] Provider usage 锚点会在 compact 替换历史后清空。

## 分块摘要验收
- [ ] 长旧历史会被拆成多个 summary chunk。
- [ ] 每个 chunk 开始时产生 `ContextChunkSummaryStarted`。
- [ ] 每个 chunk 完成时产生 `ContextChunkSummaryFinished`。
- [ ] 多个 chunk summary 会再合并成 final compact summary。
- [ ] final merge prompt 中包含 chunk summary。
- [ ] focus 文本会进入 chunk summary prompt。
- [ ] focus 文本会进入 final merge prompt。

## fallback 与熔断验收
- [ ] LLM 摘要失败时，compact 不破坏原始会话。
- [ ] LLM 摘要失败时，会使用本地 deterministic summary 兜底。
- [ ] LLM 失败后的 fallback 事件 quality 为 `llm_failed`。
- [ ] LLM 失败后的完成事件 summary quality 为 `llm_failed`。
- [ ] 手动 compact fallback 不显示自动失败计数。
- [ ] fallback 成功时不会重复显示两条相同的 timeout 提示。
- [ ] auto compact 连续失败达到阈值后会熔断。
- [ ] auto compact 熔断后会走 `Local fallback only`。
- [ ] 手动 compact 可以绕过 auto compact 熔断。

## 恢复上下文验收
- [ ] 压缩后的第一条消息包含 `Compacted Summary`。
- [ ] 压缩后的第一条消息包含最近读文件快照区域。
- [ ] 压缩后的第一条消息包含当前可用工具概览。
- [ ] 压缩后的第一条消息包含边界提醒。
- [ ] 边界提醒要求需要精确内容时重新读取文件或 stored path。
- [ ] 摘要中的 `<analysis>` 草稿不会进入会话历史。
- [ ] 本地 fallback 摘要明确说明质量较低或需要重新读取精确内容。

## `/compact` 命令验收
- [ ] 输入 `/compact` 会触发 manual compact。
- [ ] manual compact 成功时显示压缩前后 estimated tokens。
- [ ] manual compact LLM 成功时显示 `LLM compact succeeded`。
- [ ] manual compact LLM 超时时显示 `LLM compact fallback`。
- [ ] manual compact 没有可压缩内容时显示 skipped。
- [ ] manual compact 完成后输入框恢复可用。

## `/compact focus` 命令验收
- [ ] 输入 `/compact focus 重点保留 context.py 实现细节` 会触发 manual compact。
- [ ] focus 文本会传给摘要 prompt。
- [ ] focus 文本超过 `compact_focus_max_chars` 时会被截断。
- [ ] `/compact focus ...` 完成后仍显示压缩前后 token。
- [ ] `/compact nope` 不会被误识别为 compact 命令。

## `/context` 命令验收
- [ ] 输入 `/context` 会输出 `Context stats`。
- [ ] `/context` 输出 system/prompt token 估算。
- [ ] `/context` 输出 tools token 估算。
- [ ] `/context` 输出 user history token 估算。
- [ ] `/context` 输出 assistant history token 估算。
- [ ] `/context` 输出 tool results token 估算。
- [ ] `/context` 输出 compact summary token 估算。
- [ ] `/context` 输出 recent raw messages token 估算。
- [ ] `/context` 输出 auto compact threshold。
- [ ] `/context` 输出 auto compact disabled 状态。
- [ ] `/context` 输出最近一次 compact 前后 token。
- [ ] `/context` 不触发 LLM 请求。
- [ ] `/context` 不调用工具。
- [ ] `/context` 不修改会话历史。

## UI / CLI 验收
- [ ] TUI 显示 context compact 的动态 spinner。
- [ ] TUI 显示工具结果落盘提示。
- [ ] TUI 显示 LLM compact fallback 提示。
- [ ] TUI 显示 `Compacted: before -> after estimated tokens (...)`。
- [ ] line mode 可以显示同样的 compact 事件。
- [ ] line mode 可以执行 `/compact focus ...`。
- [ ] line mode 可以执行 `/context`。
- [ ] Esc 中断时正在显示的 compact 状态会结束为 interrupted。

## 端到端验收
- [ ] 创建一个 60k 以上文本文件后，让 MewCode 读取该文件，会看到工具结果落盘提示。
- [ ] 读取大文件后输入 `/context`，可以看到 tool results token 占用。
- [ ] 读取多个大文件后输入 `/compact`，最终仍能继续回答普通问题。
- [ ] 输入 `/compact focus 重点保留第八章上下文管理实现` 后，后续回答能围绕该重点恢复上下文。
- [ ] LLM 摘要超时时，UI 显示一条 fallback 原因和一条 compact 完成质量标签，不重复打印 timeout 原因。
- [ ] 压缩后询问精确代码内容时，模型倾向重新 `ReadFile`，而不是凭摘要编造。
- [ ] `.\.venv\Scripts\python.exe -m pytest -q` 可以通过。
