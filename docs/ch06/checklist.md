# MewCode 第六章验收清单：权限系统

## 危险命令检测验收
- [ ] `Bash` 命令 `rm -rf /` 在执行前被拒绝。
- [ ] `Bash` 命令 `rm -rf C:\` 或等价 Windows 根目录删除命令在执行前被拒绝。
- [ ] `Bash` 命令 `del /s /q C:\*` 在执行前被拒绝。
- [ ] `Bash` 命令 `format C:` 在执行前被拒绝。
- [ ] `Bash` 命令 `shutdown /s` 或 `shutdown -h now` 在执行前被拒绝。
- [ ] 危险命令命中后不会进入 HITL 确认。
- [ ] 危险命令命中后不会被 allow 规则放行。
- [ ] 危险命令拒绝结果包含 `blocked_by_dangerous_command` 元数据。

## 路径沙箱验收
- [ ] `ReadFile` 读取工作区内普通文件可以通过路径检查。
- [ ] `ReadFile` 读取 `../outside.txt` 被拒绝。
- [ ] `WriteFile` 写入 `../outside.txt` 被拒绝。
- [ ] `EditFile` 修改 `../outside.txt` 被拒绝。
- [ ] 指向工作区外文件的符号链接在解析真实路径后被拒绝。
- [ ] `.mewcode/permissions.local.yaml` 可以在工作区内创建。
- [ ] 路径逃逸不会进入 HITL 确认。
- [ ] 路径逃逸拒绝结果包含 `blocked_by_sandbox` 元数据。

## 敏感读取保护验收
- [ ] `ReadFile(*.env*)` 会被拒绝，不会当成批量文件读取执行。
- [ ] `ReadFile(**/.env.*)` 会被拒绝，不会把环境文件族一次性读入模型上下文。
- [ ] `ReadFile(.env)` 作为明确单文件读取可以继续进入普通权限判断。
- [ ] `ReadFile(.env.local)` 作为明确单文件读取可以继续进入普通权限判断。
- [ ] 宽泛环境文件读取拒绝结果包含 `blocked_by_sensitive_read_pattern` 元数据。
- [ ] 宽泛环境文件读取拒绝结果包含候选路径 `.env`、`.env.local`、`.env.example`、`.env.development`、`.env.production`。
- [ ] 模型收到拒绝结果后，可以改为逐个尝试明确候选 `.env` 文件名。

## 规则文件验收
- [ ] 用户级规则文件路径为 `~/.mewcode/permissions.yaml`。
- [ ] 项目级规则文件路径为 `.mewcode/permissions.yaml`。
- [ ] 本地级规则文件路径为 `.mewcode/permissions.local.yaml`。
- [ ] `.mewcode/permissions.local.yaml` 被加入 `.gitignore`。
- [ ] 三个规则文件都不存在时，程序仍能启动。
- [ ] YAML 格式错误会给出可理解配置错误。
- [ ] 非 allow/deny 结果会被视为无效规则。
- [ ] 规则 `Bash(git *)` 可以匹配 `git status`。
- [ ] 规则 `ReadFile(src/**/*.py)` 可以匹配 `src/mewcode/agent.py`。
- [ ] 规则 `WriteFile(docs/*.md)` 可以匹配 `docs/test.md`。

## 规则优先级验收
- [ ] 用户级 allow 被项目级 deny 覆盖。
- [ ] 项目级 allow 被本地级 deny 覆盖。
- [ ] 本地级 allow 优先于项目级 deny。
- [ ] 同一层同时命中 allow 和 deny 时，deny 优先。
- [ ] 未命中任何规则时，进入权限模式默认决策。

## 权限模式验收
- [ ] 默认权限模式为 `default`。
- [ ] `default` 模式允许 `ReadFile`、`Glob`、`Grep`。
- [ ] `default` 模式对 `WriteFile`、`EditFile`、`Bash` 请求 HITL 确认。
- [ ] `acceptEdits` 模式允许 `WriteFile` 和 `EditFile`。
- [ ] `acceptEdits` 模式对 `Bash` 仍请求 HITL 确认。
- [ ] `plan` 模式只允许只读和规划工具。
- [ ] `plan` 模式拒绝 `WriteFile`、`EditFile` 和 `Bash`。
- [ ] `bypassPermissions` 模式允许非危险、未逃逸沙箱的工具调用。
- [ ] `bypassPermissions` 不能绕过危险命令检测。
- [ ] `bypassPermissions` 不能绕过路径沙箱。
- [ ] Shift+Tab 可以按固定顺序循环切换四种模式。
- [ ] 状态栏常驻显示当前权限模式。
- [ ] 状态栏中 `bypassPermissions` 显示警示符号。
- [ ] 输入框边框随权限模式切换主题色：`default` 灰色、`acceptEdits` 蓝色、`plan` 紫色、`bypassPermissions` 橙色。

## 权限检查器验收
- [ ] 工具真实执行前一定先调用权限检查器。
- [ ] 允许决策会继续执行原工具。
- [ ] 拒绝决策不会执行原工具。
- [ ] 拒绝决策会回填结构化工具结果给模型。
- [ ] 需要确认决策会发出 Agent 事件并暂停当前工具执行。
- [ ] Plan Mode 的不安全工具拦截仍然生效。
- [ ] Plan Mode 不会因为权限模式为 `acceptEdits` 或 `bypassPermissions` 而执行源码写入或 Bash。

## HITL 验收
- [ ] TUI 中待确认工具调用会显示工具名和关键参数。
- [ ] 行模式中待确认工具调用会显示工具名和关键参数。
- [ ] TUI 中待确认工具调用会显示三项选择：允许本次、永久允许、拒绝本次。
- [ ] TUI 中可以用上下键切换三项选择，并用 Enter 确认。
- [ ] 用户选择“允许本次”后，只执行当前工具调用。
- [ ] 用户选择“永久允许”后，精确 allow 规则写入 `.mewcode/permissions.local.yaml`。
- [ ] 用户选择“拒绝本次”后，工具不执行，拒绝结果回填给模型。
- [ ] HITL 等待期间 Esc 或取消操作可以干净退出当前轮。
- [ ] 永久允许不会写入 `~/.mewcode/permissions.yaml`。

## 配置验收
- [ ] `~/.mewcode/config.yaml` 可以配置权限模式。
- [ ] 未配置权限模式时使用 `default`。
- [ ] 配置未知权限模式会报错。
- [ ] CLI 启动时会加载用户级、项目级、本地级规则。
- [ ] 规则加载错误不会静默切换到更宽松模式。

## Agent Loop 验收
- [ ] 权限拒绝后 Agent Loop 不崩溃。
- [ ] 权限拒绝后模型可以收到拒绝原因并选择替代方案。
- [ ] 工具失败、权限拒绝和用户拒绝在事件流中可区分。
- [ ] 多工具响应中，前一个工具需要 HITL 时不会继续执行后续不安全工具。
- [ ] 多个安全读工具仍可按第四章逻辑批量执行。

## 范围边界验收
- [ ] 本章没有实现网络请求限制。
- [ ] 本章没有实现资源用量配额。
- [ ] 本章没有实现审计日志。
- [ ] 本章没有实现操作系统级容器沙箱。
- [ ] 本章没有实现远程策略同步。

## 端到端验收
- [ ] 在 `default` 模式输入“创建 demo 文件并写入 hello”，观察到 UI 请求确认，选择允许本次后文件被创建。
- [ ] 在 `default` 模式输入“运行 rm -rf /”，观察到命令被硬拒绝，不出现确认框。
- [ ] 创建项目级规则 `Bash(git *)`: allow 后，请求运行 `git status` 不再触发确认。
- [ ] 创建本地级规则覆盖项目级规则后，观察本地级决策优先。
- [ ] 同一层同时配置 allow 和 deny 时，观察 deny 优先。
- [ ] 输入读取工作区外符号链接的请求，观察路径沙箱拒绝且模型收到拒绝原因。
- [ ] 输入“读取 `*.env*`”，观察宽泛读取被拒绝，模型随后逐个尝试 `.env`、`.env.local` 等明确候选文件名。
- [ ] 输入 `/plan 修改某文件`，观察 Plan Mode 仍只读，不会被权限规则放开。
- [ ] `.\.venv\Scripts\python.exe -m pytest -q` 可以通过。
