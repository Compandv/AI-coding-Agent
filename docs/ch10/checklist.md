# MewCode 第十章验收清单：Slash Command 内置命令框架

## 命令注册验收
- [ ] 注册中心可以注册命令名称。
- [ ] 注册中心可以注册命令别名。
- [ ] 命令名查找大小写不敏感。
- [ ] 别名查找大小写不敏感。
- [ ] 命令名与已有命令名冲突时启动失败。
- [ ] 命令名与已有别名冲突时启动失败。
- [ ] 别名与已有命令名冲突时启动失败。
- [ ] 别名与已有别名冲突时启动失败。
- [ ] 隐藏命令可以执行。
- [ ] 隐藏命令不会出现在 `/help`。
- [ ] 隐藏命令不会出现在 Tab 补全候选。

## 命令解析验收
- [ ] 空输入不产生命令执行。
- [ ] 不以 `/` 开头的输入不进入命令分发。
- [ ] `/HELP` 可以解析为 `help`。
- [ ] `/compact focus keep context.py` 的参数保留为 `focus keep context.py`。
- [ ] `/plan inspect project` 可以拆出命令和剩余文本。
- [ ] 未知 `/foo` 不进入 Agent Loop。
- [ ] 未知 `/foo` 显示包含 `/help` 的提示。

## 内置命令验收
- [ ] `/help` 显示 `help`、`compact`、`clear`、`plan`、`do`、`session`、`memory`、`permission`、`status`、`review`。
- [ ] `/help` 显示每个公开命令的用法。
- [ ] `/clear` 清空当前界面显示。
- [ ] `/clear` 不清空当前 ChatSession。
- [ ] `/clear` 不删除 `.mewcode/sessions/`。
- [ ] `/clear` 不删除 `.mewcode/memory/`。
- [ ] `/compact` 触发现有手动压缩事件流。
- [ ] `/compact focus keep context.py details` 把 focus 文本传给压缩逻辑。
- [ ] `/plan` 切换到 Plan Mode。
- [ ] `/plan inspect project` 切换到 Plan Mode 后立即发送 `inspect project`。
- [ ] `/do` 切换到 normal mode。
- [ ] `/do implement changes` 切换到 normal mode 后立即发送 `implement changes`。
- [ ] `/session current` 仍走现有 session 命令逻辑。
- [ ] `/memory list` 仍走现有 memory 命令逻辑。
- [ ] `/permission` 显示当前权限模式和可选权限模式。
- [ ] `/permission default` 切换到 `default`。
- [ ] `/permission acceptEdits` 切换到 `acceptEdits`。
- [ ] `/permission plan` 切换到 `plan`。
- [ ] `/permission bypassPermissions` 切换到 `bypassPermissions`。
- [ ] `/permission nope` 显示明确错误，不改变当前权限模式。
- [ ] `/status` 显示模型、工作目录、Agent mode、Permission mode、MCP 状态、context 状态和 memory/session 状态。
- [ ] `/review` 进入 Agent Loop。
- [ ] `/review` 发送给 Agent 的文本要求审查当前 Git 工作区改动。

## 兼容命令验收
- [ ] `/context` 仍触发现有 context stats。
- [ ] `/accept` 仍接受最近规划文件并切回 normal mode。
- [ ] `/copy` 在 TUI 中仍复制 transcript。
- [ ] `/copy last` 在 TUI 中仍复制最近 assistant 回复。
- [ ] `/exit` 仍退出程序。
- [ ] `/quit` 仍退出程序。
- [ ] 兼容命令不出现在 `/help` 的十个公开命令中。

## TUI 验收
- [ ] TUI 回车入口对 slash command 先走命令分发。
- [ ] TUI 执行本地命令不调用 Agent。
- [ ] TUI 执行提示词命令会调用 Agent。
- [ ] TUI 输入 `/c` 后按 Tab 可以补全为 `/clear `。
- [ ] TUI 输入 `/co` 后按 Tab 显示多个候选或不误补。
- [ ] TUI 输入 `/perm` 后按 Tab 可以补全为 `/permission `。
- [ ] TUI 执行 `/clear` 后消息列表为空或只保留清屏状态提示。
- [ ] TUI 执行 `/permission bypassPermissions` 后输入框边框变为 bypass 主题色。
- [ ] TUI 状态栏显示 `[DEFAULT]`。
- [ ] TUI 执行 `/plan` 后状态栏显示 `[PLAN]`。
- [ ] TUI 执行 `/do` 后状态栏显示 `[DEFAULT]`。

## line mode 验收
- [ ] line mode 回车入口对 slash command 先走命令分发。
- [ ] line mode 输入 `/help` 直接输出帮助，不调用 Agent。
- [ ] line mode 输入 `/clear` 直接输出清屏控制或清屏提示，不调用 Agent。
- [ ] line mode 输入 `/status` 直接输出状态，不调用 Agent。
- [ ] line mode 输入 `/review` 会调用 Agent。
- [ ] line mode 输入未知 `/foo` 不调用 Agent。
- [ ] line mode 现有 `/compact`、`/context`、`/session`、`/memory` 测试保持通过。

## 状态与历史验收
- [ ] 本地命令不会追加 user message 到 ChatSession。
- [ ] UI 状态命令不会追加 user message 到 ChatSession。
- [ ] 提示词命令会按普通用户任务进入 ChatSession。
- [ ] `/plan <text>` 写入会话的是剩余任务文本，不是完整 slash command。
- [ ] `/review` 写入会话的是生成后的 review 任务文本。

## 端到端验收
- [ ] 启动 MewCode 后输入 `/help` 能看到十个公开命令。
- [ ] 输入 `/clear` 不产生 Provider 调用。
- [ ] 输入 `/status` 不产生 Provider 调用。
- [ ] 输入 `/permission acceptEdits` 后状态栏和权限检查器都切到 edit 模式。
- [ ] 输入 `/review` 后 Agent 会审查当前 Git 工作区改动。
- [ ] 输入 `/foo` 后本地提示使用 `/help`，Agent 没有收到 `/foo`。
- [ ] `.\.venv\Scripts\python.exe -m pytest -q` 可以通过。
