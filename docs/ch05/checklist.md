# MewCode 第五章验收清单：Prompt 工程与缓存管线

## System Prompt 模块验收
- [ ] `src/mewcode/prompts.py` 中可以找到统一的 Prompt 模块定义。
- [ ] System Prompt 包含 `IdentitySection`。
- [ ] System Prompt 包含 `BehaviorSection`。
- [ ] System Prompt 包含 `ToolUsageSection`。
- [ ] System Prompt 包含 `CodeQualitySection`。
- [ ] System Prompt 包含 `SecuritySection`。
- [ ] System Prompt 包含 `TaskPatternSection`。
- [ ] System Prompt 包含 `OutputStyleSection`。
- [ ] 七个模块都包含名称、优先级和正文内容。
- [ ] 拼装结果按优先级稳定排序。
- [ ] 重复调用拼装函数两次，输出文本完全一致。
- [ ] 普通模式下，用户消息不会被拼接全局身份或模式说明前缀。

## Prompt 组装管线验收
- [ ] 组装后的 API payload 明确区分 `system`、`messages`、`tools` 三类信息。
- [ ] 组装管线明确处理七类输入源：稳定 System Prompt、工具定义、环境上下文、会话历史、当前用户输入、工具调用结果、system-reminder。
- [ ] 七模块全局指令进入 `system` 通道。
- [ ] 会话历史进入 `messages` 通道。
- [ ] 工具定义进入 `tools` 通道。
- [ ] 用户当前输入只作为普通用户消息进入 `messages` 通道。
- [ ] 工具调用历史和工具结果仍能按第四章格式进入 `messages` 通道。
- [ ] Provider 不再各自临时拼接全局提示词。
- [ ] OpenAI Provider 可以从统一 payload 生成合法请求体。
- [ ] Anthropic Provider 可以从统一 payload 生成合法请求体。

## 环境上下文验收
- [ ] 环境上下文不会出现在七模块 System Prompt 文本中。
- [ ] 环境上下文以首条系统级补充 user 消息进入 `messages`。
- [ ] 环境上下文只作为请求时 overlay 参与组装，不写入持久 `ChatSession.messages`。
- [ ] 环境上下文至少包含当前工作目录。
- [ ] 环境上下文至少包含操作系统或平台信息。
- [ ] 环境上下文至少包含当前日期或时间。
- [ ] 环境上下文至少包含 Git 分支或 Git 状态不可用说明。
- [ ] 工作目录或 Git 状态变化时，System Prompt 文本保持不变。

## system-reminder 验收
- [ ] system-reminder 使用 `<system-reminder>` 和 `</system-reminder>` 包裹内容。
- [ ] system-reminder 消息使用 `role=user`。
- [ ] system-reminder 只作为请求时 overlay 参与组装，不写入持久 `ChatSession.messages`。
- [ ] 会话级 reminder 注入在普通用户任务之前。
- [ ] 轮次级 reminder 注入在当前用户请求附近。
- [ ] system-reminder 不会被保存为 assistant 最终回答。
- [ ] 模型最终回答中不应复述 `<system-reminder>` 标签。

## Plan Mode 验收
- [ ] `agent.py` 中不再存在把 Plan Mode 文本直接拼接到用户消息的逻辑。
- [ ] `/plan` 后第 1 次模型请求会注入完整 Plan Mode system-reminder。
- [ ] Plan Mode 第 2、3、4 次模型请求注入精简提醒或不注入完整提醒。
- [ ] Plan Mode 第 5 次模型请求再次注入完整 Plan Mode system-reminder。
- [ ] `/do` 后不再注入 Plan Mode reminder。
- [ ] Plan Mode 默认只在聊天中输出计划，不自动写入 `plans/` 或 `docs/plans/` 文件。
- [ ] 用户明确要求保存计划文件时，Plan Mode 才允许调用 `WritePlanFile`。
- [ ] Plan Mode 下 `ReadFile`、`Glob`、`Grep` 仍可执行。
- [ ] Plan Mode 下 `WriteFile`、`EditFile`、`Bash` 仍被执行层拦截。
- [ ] Plan Mode 下复杂需求会优先倾向使用 `AskUserQuestion` 澄清。
- [ ] Plan Mode 最终可以输出计划摘要，并提示用户接受或调整。

## 工具描述验收
- [ ] `ReadFile` 描述说明它用于读取文件内容，并建议编辑前先读目标文件。
- [ ] `EditFile` 描述说明它用于精确替换，并要求基于已读取内容构造匹配文本。
- [ ] `WriteFile` 描述说明它会创建或覆盖文件，并提醒避免误覆盖未知内容。
- [ ] `Bash` 描述说明它用于运行必要命令，并提醒优先使用专用读写搜索工具。
- [ ] `Glob` 描述说明它适合按文件名或路径模式定位候选文件。
- [ ] `Grep` 描述说明它适合按符号、短语或错误信息搜索文件内容。
- [ ] 工具描述能体现 `Glob`/`Grep` 定位后再 `ReadFile` 的配合关系。
- [ ] 工具描述能体现修改后可用 `ReadFile` 或 `Bash` 验证结果。
- [ ] `tests/test_tool_registry.py` 覆盖强化后的关键描述片段。

## Prompt Cache 验收
- [ ] Prompt 组装管线输出 Provider-neutral cache policy。
- [ ] Anthropic Provider 会把 cache policy 翻译为显式缓存控制字段。
- [ ] OpenAI Provider 不会错误发送 Anthropic 风格的 `cache_control` 字段。
- [ ] OpenAI Provider 可以读取自动 Prompt Caching 的 cached token usage。
- [ ] 不支持缓存控制的 Provider 不会因为缺少缓存字段而报错。
- [ ] Provider 响应结构可以携带总 input token 信息。
- [ ] Provider 响应结构可以携带 cache read token 信息或等价字段。
- [ ] Provider 响应结构可以携带 cache creation token 信息或等价字段。
- [ ] 达到供应商缓存门槛后，第二次发送相同稳定 system 和 tools 的请求时，可以从 usage 中观察到缓存读取字段或 cached token 字段。
- [ ] 未达到供应商缓存门槛时，usage 可以显示未命中或零缓存 token，而不是被测试误判为失败。
- [ ] 环境上下文变化不会导致 system 文本重新生成不同内容。

## 典型场景评估验收
- [ ] 项目中存在 5 个提示词行为评估场景。
- [ ] 场景 1 覆盖“帮我找项目入口并说明原因”。
- [ ] 场景 2 覆盖“修改文件前先读取目标文件”。
- [ ] 场景 3 覆盖“Plan Mode 下规划大型项目并先澄清问题，默认不写计划文件”。
- [ ] 场景 4 覆盖“优先使用 Glob/Grep/ReadFile 而不是 Bash 搜索文件”。
- [ ] 场景 5 覆盖“重复请求时观察 Prompt Cache usage”。
- [ ] 每个场景包含输入、期望工具行为和人工观察点。
- [ ] 评估脚本或文档不要求真实 MCP Server。

## 回归验收
- [ ] 第四章 Agent Loop 的多步工具调用仍然可用。
- [ ] 同一轮多个读工具仍可分批执行。
- [ ] normal mode 下写文件和 Bash 仍可自动执行。
- [ ] TUI 中工具状态、Markdown 渲染和 clarification UI 仍可用。
- [ ] fallback 行模式仍支持 `/plan` 和 `/do`。
- [ ] `.\.venv\Scripts\python.exe -m pytest -q` 可以通过。

## 范围边界验收
- [ ] 本章没有实现 `MEWCODE.md` 或项目指令文件加载。
- [ ] 本章没有实现自动记忆系统。
- [ ] 本章没有接入真实 MCP Server。
- [ ] 本章没有实现自动评估打分。
- [ ] 本章没有实现上下文压缩。
- [ ] 本章没有重新引入完整权限系统。

## 端到端验收
- [ ] normal mode 输入“帮我找项目入口并说明原因”，观察到模型优先使用搜索和读取工具，并给出 Markdown 总结。
- [ ] normal mode 输入“修改某个已存在文件的一行内容”，观察到模型先读取目标文件，再执行编辑，再验证结果。
- [ ] 输入 `/plan 我想做一个电商系统`，观察到模型通过 clarification UI 询问关键问题，而不是直接改文件或自动保存计划文件。
- [ ] Plan Mode 生成计划后，输入 `/do` 并请求实现其中一小步，观察到模型切回正常执行模式。
- [ ] 连续两次发起相似请求时，可以在调试 usage 中看到缓存命中信息或明确的不支持说明。
