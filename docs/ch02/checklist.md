# MewCode 第二章验收清单：常驻式 Textual Agent 界面

## 配置文件验收
- [ ] 在 Windows 用户目录创建 `C:\Users\lhj\.mewcode\config.yaml` 后，运行 `mewcode` 会读取该配置文件。
- [ ] 在类 Unix 环境创建 `~/.mewcode/config.yaml` 后，运行 `mewcode` 会读取该配置文件。
- [ ] 配置文件包含以下四个核心字段时可通过基础校验：`protocol`、`model`、`base_url`、`api_key`。
- [ ] 使用以下 Claude 示例配置时，程序选择 Claude Provider：
  ```yaml
  protocol: anthropic
  model: claude-sonnet-4-6
  base_url: https://api.anthropic.com
  api_key: sk-ant-placeholder
  ```
- [ ] 使用以下 OpenAI 示例配置时，程序选择 OpenAI Provider：
  ```yaml
  protocol: openai
  model: gpt-4.1
  base_url: https://api.openai.com/v1
  api_key: sk-placeholder
  ```
- [ ] 配置文件额外包含 `thinking`、`timeout_seconds` 这类可选字段时，程序不会因为存在额外字段而拒绝启动。
- [ ] 缺少 `protocol`、`model`、`base_url`、`api_key` 任意一个核心字段时，终端输出能指出缺失字段名称。

## 启动命令验收
- [ ] 安装项目后，在项目外任意目录运行 `mewcode` 可以启动程序。
- [ ] 运行 `python -m mewcode` 也可以启动同一个主流程。
- [ ] 在交互式 PowerShell 终端运行 `uv run python -m mewcode` 后，会进入 Textual 全屏终端界面。
- [ ] 在非交互式管道中运行 `printf '/exit\n' | uv run python -m mewcode` 不会进入 Textual 全屏界面，但会走 fallback 并正常退出。

## Textual 界面验收
- [ ] 程序交互式启动后，整体背景为黑色。
- [ ] 顶部左侧显示红色 block 风格 ASCII logo，并且 logo 中可见 `███` 这类块字符。
- [ ] 顶部右侧显示 `MewCode Agent v0.1.0`。
- [ ] 顶部右侧显示当前模型信息，例如 `gpt-4.1 with high effort · API Usage Billing`。
- [ ] 顶部右侧不再显示 `Learn MyCode Agent`。
- [ ] 顶部品牌区下面有一条横向分隔线。
- [ ] 中间对话区域可显示多轮历史。
- [ ] 底部有固定输入框，输入框不会随着对话历史滚动到屏幕外。
- [ ] 最底部显示 `esc to interrupt · mode: chat · plan/auto coming soon`。

## 对话区域验收
- [ ] 用户提交 `hello` 后，对话区新增一条用户消息。
- [ ] 用户消息前面显示蓝色 `>` 标识。
- [ ] 当前正在处理的用户消息使用灰色背景高亮。
- [ ] AI 回复消息前面显示紫色圆点 `●` 标识。
- [ ] AI 回复内容追加到同一条 assistant 消息中，而不是每个增量生成一条新消息。
- [ ] 一轮回复完成后，当前用户消息不再保持高亮。
- [ ] 连续两轮提问后，中间对话区仍能看到上一轮历史。

## 状态验收
- [ ] 用户提交问题后，状态行先显示 `Thinking`。
- [ ] 状态行显示动态图标，例如 `⠋`、`⠙`、`⠹` 之一。
- [ ] 收到第一段模型增量后，状态切换到 `Coding`。
- [ ] 模型流结束后，状态切换到 `Done`。
- [ ] 状态行包含耗时秒数，例如 `(0s)`、`(1s)`。
- [ ] 模型回复过程中再次提交新输入时，界面提示等待当前回答完成或按 esc 中断。

## 真实 LLM 验收
- [ ] 用户在 Textual 界面输入普通文本并回车后，程序调用当前配置对应的 `ChatProvider.stream_chat()`。
- [ ] 使用 FakeProvider 运行测试时，输入 `hello` 后 provider 收到的消息列表包含 `{"role": "user", "content": "hello"}`。
- [ ] 使用真实 Claude 或 OpenAI 配置时，模型回复以流式增量显示在 Textual 对话区。
- [ ] 模型流式结束后，完整 assistant 回复被写入进程内会话历史。
- [ ] fallback 行模式也调用真实 provider，而不是返回 mock 文本。
- [ ] `grep -R "mock AI 回复\|MOCK_RESPONSE" src tests` 不再显示界面默认回复路径。

## 多轮对话验收
- [ ] 第一轮输入 `请记住一个词：蓝莓`，第二轮输入 `我刚才让你记住的词是什么？`，第二轮请求会包含第一轮用户消息和模型回复。
- [ ] 同一进程内连续三轮对话时，第 3 轮请求仍能带上前两轮上下文。
- [ ] 退出 MewCode 后重新启动，再询问上一轮会话内容时，请求中不包含上一次进程的历史消息。
- [ ] 项目目录和用户配置目录中不会因为普通聊天自动生成会话历史文件。

## Provider 切换验收
- [ ] 当 `protocol: anthropic` 时，Provider 工厂创建 Claude 后端。
- [ ] 当 `protocol: openai` 时，Provider 工厂创建 OpenAI 后端。
- [ ] 当 `protocol: unknown` 时，运行 `mewcode` 会输出包含 `unknown` 的协议不支持提示。
- [ ] Textual 交互层不需要判断当前使用的是 Claude 还是 OpenAI，也能完成流式输出。

## Claude 验收
- [ ] 使用 Claude 配置时，请求地址基于 `base_url: https://api.anthropic.com`。
- [ ] 使用 Claude 配置时，请求认证使用 `api_key` 中的值。
- [ ] 使用 Claude 配置时，模型名称使用 `model: claude-sonnet-4-6`。
- [ ] Claude SSE 事件中的文本增量会被转换为 Textual 对话区中的 assistant 输出。
- [ ] Claude 流式结束事件到达后，本轮回复被写入进程内会话历史。

## Claude thinking 验收
- [ ] 配置包含以下片段时，Claude 请求启用 extended thinking：
  ```yaml
  thinking:
    enabled: true
    budget_tokens: 1024
  ```
- [ ] 配置包含 `thinking.enabled: false` 时，Claude 请求不启用 extended thinking。
- [ ] 使用 OpenAI 配置时，即使配置文件包含 `thinking` 字段，也不会把 Claude thinking 选项发送给 OpenAI 后端。
- [ ] 默认终端聊天输出只显示最终回答文本，不把 thinking 内容混在普通回复中。

## OpenAI 验收
- [ ] 使用 OpenAI 配置时，请求地址基于 `base_url: https://api.openai.com/v1`。
- [ ] 使用 OpenAI 配置时，请求认证使用 `api_key` 中的值。
- [ ] 使用 OpenAI 配置时，模型名称使用 `model: gpt-4.1`。
- [ ] OpenAI SSE 事件中的文本增量会被转换为 Textual 对话区中的 assistant 输出。
- [ ] OpenAI 流式结束事件到达后，本轮回复被写入进程内会话历史。

## 中断验收
- [ ] 模型回复过程中按 `Esc`，底部提示中的 `esc to interrupt` 与实际行为一致。
- [ ] 按 `Esc` 后，当前状态显示 Interrupted 或 Done interrupted。
- [ ] 按 `Esc` 后，当前用户消息不再保持高亮。
- [ ] 中断后界面回到可继续输入的状态。
- [ ] 按 `Ctrl+C` 可以退出程序，不打印 Python traceback。

## 错误处理验收
- [ ] 用户目录不存在配置文件时，运行 `mewcode` 会提示应创建 `~/.mewcode/config.yaml`。
- [ ] YAML 格式错误时，运行 `mewcode` 会提示配置文件解析失败，并显示配置文件路径。
- [ ] API 返回认证失败时，终端提示认证失败或 API key 无效，不打印完整密钥。
- [ ] 网络连接失败时，Textual 状态区或 fallback 输出提示网络或连接失败，不打印 Python traceback。
- [ ] SSE 流中断时，界面提示本轮响应未正常完成，并回到可继续输入或可退出的状态。

## 范围边界验收
- [ ] `grep -R "tool_use\|tool use" src tests` 不会显示已经实现工具调用执行逻辑的代码。
- [ ] `grep -R "subprocess\|os.system" src tests` 不会显示根据模型回复执行 shell 命令的代码。
- [ ] 普通对话过程中，MewCode 不会读取用户当前目录下的源代码文件作为上下文。
- [ ] 普通对话过程中，MewCode 不会修改用户当前目录下的任何文件。
- [ ] 底部出现 `plan/auto coming soon` 只表示预留模式提示，不代表本阶段已经实现 plan 或 auto 行为。

## 端到端验收
- [ ] 准备 `C:\Users\lhj\.mewcode\config.yaml`，内容为可用 Claude 或 OpenAI 配置，运行 `uv run python -m mewcode`，进入 Textual 全屏界面。
- [ ] 在底部输入框输入 `请用一句话介绍你自己` 并回车，观察到对话区新增蓝色 `>` 用户消息。
- [ ] 同一轮中观察到状态从动态 `Thinking` 变成动态 `Coding`，最后变成 `Done`。
- [ ] 同一轮中观察到紫色 `●` 后面的 assistant 回复逐步增长，而不是一次性出现。
- [ ] 在同一次运行中继续输入 `把上一句改写得更简短`，观察到模型请求包含上一轮上下文，且终端流式输出第二轮回复。
- [ ] 回复过程中按 `Esc`，观察到当前回复被中断，界面回到可继续输入状态。
- [ ] 输入 `/exit` 或按 `Ctrl+C` 后程序退出，随后重新运行 `mewcode`，新会话不包含上一次运行的对话历史。
- [ ] 将配置从 `protocol: anthropic` 改为 `protocol: openai` 并更换对应模型与密钥后，不修改 Textual 交互层代码即可完成一次新的流式对话。
