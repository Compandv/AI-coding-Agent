# MewCode 第九章验收清单：跨会话记忆系统

## 指令文件验收
- [ ] 存在 `.mewcode/MEWCODE.md` 时会被加载。
- [ ] 存在项目根 `MEWCODE.md` 时会被加载。
- [ ] 存在 `~/.mewcode/MEWCODE.md` 时会被加载。
- [ ] 三层同时存在时，注入顺序为 `.mewcode/MEWCODE.md`、项目根 `MEWCODE.md`、`~/.mewcode/MEWCODE.md`。
- [ ] 指令内容作为 `<system-reminder>` 消息进入 messages 通道。
- [ ] 指令内容不会拼进 system prompt。
- [ ] 不存在任何 `MEWCODE.md` 时启动不报错。
- [ ] 指令文件读取失败时产生可观测提示，不导致 MewCode 启动失败。

## `@include` 验收
- [ ] `@include ./rules/python.md` 可以展开同目录或允许根目录内文件。
- [ ] include 展开后的内容保留来源文件路径提示。
- [ ] include 最大嵌套深度为 5。
- [ ] 超过 include 最大深度时停止展开并产生可观测提示。
- [ ] A include B、B include A 时不会死循环。
- [ ] 循环 include 会被 visited 集合识别并跳过重复文件。
- [ ] 项目指令 include `../outside.md` 会被拒绝。
- [ ] 用户级指令不能 include 项目目录外的任意敏感路径。
- [ ] include 缺失文件时跳过该 include 并提示缺失路径。

## 会话存档验收
- [ ] 新会话 ID 格式为 `YYYYMMDD-HHMMSS-xxxx`。
- [ ] 每个会话对应一个 JSONL 文件。
- [ ] JSONL 文件位于 `.mewcode/sessions/` 下。
- [ ] 用户消息会追加写入 JSONL。
- [ ] assistant 文本消息会追加写入 JSONL。
- [ ] assistant 多工具调用消息会追加写入 JSONL。
- [ ] tool result 消息会追加写入 JSONL。
- [ ] JSONL 每行都是一个可独立解析的 JSON 对象。
- [ ] 崩溃导致最后一行不完整时，恢复时只跳过坏行。
- [ ] 不维护独立 meta 文件；会话列表标题、消息数和时间通过扫描 JSONL 得到。
- [ ] `.mewcode/sessions/` 不应被提交到 Git。

## 会话恢复验收
- [ ] `/session list` 可以列出当前项目历史会话。
- [ ] `/session resume <id>` 可以恢复指定会话。
- [ ] 恢复后的 ChatSession 包含原用户消息。
- [ ] 恢复后的 ChatSession 包含原 assistant 消息。
- [ ] 恢复后的 ChatSession 包含已配对的 tool calls 和 tool results。
- [ ] 坏 JSONL 行会被跳过并计入恢复提示。
- [ ] tool result 没有对应 tool call 时，会截断到安全位置。
- [ ] assistant tool call 缺少后续 tool result 时，会截断到安全位置。
- [ ] 恢复后不存在 orphan tool result。
- [ ] 恢复会话超过 token 阈值时，会先触发一次现有 context compact。
- [ ] 恢复时间跨度超过 24 小时时，会注入时间跨度提醒。
- [ ] 恢复时间跨度提醒不会进入 system prompt。

## 会话清理验收
- [ ] 默认清理 30 天以上的过期会话。
- [ ] 清理会删除过期 JSONL 会话文件。
- [ ] 清理会删除对应 `.mewcode/sessions/<session_id>/tool-results/` 缓存目录。
- [ ] 清理失败时产生可观测提示，但不阻塞启动。
- [ ] 用户可以通过配置关闭自动清理。

## 自动记忆验收
- [ ] 自动记忆默认开启。
- [ ] Agent 自然结束且没有工具调用需要继续时，会触发记忆提取。
- [ ] 权限等待、用户取消、工具确认中断时不会触发自动记忆。
- [ ] 自动记忆提取不会阻塞最终回复进入会话历史。
- [ ] 记忆提取失败不会让本轮对话失败。
- [ ] 记忆类别包含 `user_preference`。
- [ ] 记忆类别包含 `correction_feedback`。
- [ ] 记忆类别包含 `project_knowledge`。
- [ ] 记忆类别包含 `reference`。
- [ ] 用户级偏好写入 `~/.mewcode/` 下的记忆目录。
- [ ] 项目知识写入项目 `.mewcode/` 下的记忆目录。
- [ ] 自动记忆不会保存 `.env`、token、api key 或明显密钥内容。
- [ ] LLM 返回“无需记忆”时不会写入空记忆。
- [ ] 本章本地提取器可以写入四类记忆；后续 LLM 去重升级不影响当前文件格式。

## 记忆文件验收
- [ ] 每条自动记忆以 Markdown 文件保存。
- [ ] 每条记忆文件包含 frontmatter。
- [ ] frontmatter 包含记忆类别。
- [ ] frontmatter 包含创建时间。
- [ ] frontmatter 包含作用域：用户级或项目级。
- [ ] 记忆索引文件存在。
- [ ] 记忆索引最多保留 200 行。
- [ ] 记忆索引最大体积为 25KB。
- [ ] 超过索引限制时会压缩或裁剪索引。
- [ ] 记忆索引刷新不会删除原始记忆文件。

## Prompt 注入验收
- [ ] 每轮请求前会加载当前指令文件内容。
- [ ] 每轮请求前会加载当前记忆索引。
- [ ] 指令文件、记忆索引和恢复提醒都通过 `<system-reminder>` 注入。
- [ ] 指令文件、记忆索引和恢复提醒不进入 system prompt cache。
- [ ] Plan Mode 下仍会注入指令和记忆。
- [ ] 上下文压缩后的恢复消息和记忆注入可以同时存在。
- [ ] `/context` 输出能反映记忆和指令注入带来的 token 占用。

## `/session` 命令验收
- [ ] 输入 `/session` 显示可用子命令。
- [ ] 输入 `/session list` 显示会话 ID、标题、消息数和最近更新时间。
- [ ] 输入 `/session current` 显示当前会话 ID。
- [ ] 输入 `/session resume <id>` 恢复指定会话。
- [ ] 输入 `/session delete <id>` 删除指定会话。
- [ ] 输入 `/session rename <id> <title>` 更新会话显示标题或标题提示。
- [ ] line mode 支持 `/session` 命令。
- [ ] TUI 支持 `/session` 命令并恢复输入框可用状态。
- [ ] 恢复不存在的会话 ID 会显示明确错误。

## `/memory` 命令验收
- [ ] 输入 `/memory` 显示可用子命令。
- [ ] 输入 `/memory list` 显示当前可用记忆条目。
- [ ] 输入 `/memory refresh` 重建记忆索引。
- [ ] 输入 `/memory on` 开启自动记忆。
- [ ] 输入 `/memory off` 关闭自动记忆。
- [ ] 输入 `/memory delete <id>` 删除指定记忆条目。
- [ ] line mode 支持 `/memory` 命令。
- [ ] TUI 支持 `/memory` 命令并恢复输入框可用状态。
- [ ] 删除不存在的记忆 ID 会显示明确错误。

## UI / CLI 验收
- [ ] TUI 启动时可以显示当前会话 ID 或会话状态。
- [ ] TUI 可以显示已加载指令文件数量。
- [ ] TUI 可以显示已加载记忆条目数量。
- [ ] line mode 启动时可以输出会话和记忆状态。
- [ ] 记忆提取进行中或失败时有可观测状态。
- [ ] 会话恢复、截断、压缩和清理事件有可观测状态。

## 端到端验收
- [ ] 在 `.mewcode/MEWCODE.md` 写入“回答时优先使用中文”，启动新会话后模型按该指令回答。
- [ ] 在项目根 `MEWCODE.md` 和 `.mewcode/MEWCODE.md` 写入冲突偏好时，`.mewcode/MEWCODE.md` 生效优先。
- [ ] 一轮对话中用户强调“以后测试优先跑窄测试”，自然结束后生成用户偏好记忆。
- [ ] 新会话中询问“我之前说测试怎么跑”，模型能根据记忆索引回答。
- [ ] 执行一个包含工具调用的任务后退出，再用 `/session resume <id>` 可以继续原任务。
- [ ] 手动破坏 JSONL 最后一行后，恢复会话仍能跳过坏行并继续。
- [ ] 构造孤儿 tool result 后，恢复会话会截断且不会触发 Provider 的 tool_call 配对错误。
- [ ] 恢复一个很长的会话时，会先触发 context compact，再继续回答。
- [ ] 输入 `/memory off` 后，后续自然结束不会写入新自动记忆。
- [ ] `.\.venv\Scripts\python.exe -m pytest -q` 可以通过。
