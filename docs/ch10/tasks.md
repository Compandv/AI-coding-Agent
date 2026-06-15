# MewCode 第十章任务拆解：Slash Command 内置命令框架

## 任务 1：梳理现有 slash command 分支
- 目标：确认 TUI 和 line mode 中现有 `/plan`、`/do`、`/compact`、`/context`、`/session`、`/memory`、`/accept`、`/copy` 的入口、事件流和测试覆盖。
- 影响文件：`src/mewcode/repl.py`、`src/mewcode/agent.py`、`tests/test_repl.py`
- 依赖任务：无
- 参考资料定位：`docs/ch10/spec.md` 的「背景」「设计骨架」

## 任务 2：新增命令定义与解析模型
- 目标：实现命令元数据、命令分类、解析结果和执行结果的数据结构，支持命令名大小写不敏感、参数保留和空输入早返回。
- 影响文件：`src/mewcode/commands/`、`tests/test_commands.py`
- 依赖任务：任务 1
- 参考资料定位：`docs/ch10/spec.md` 的「命令定义层」「命令解析层」

## 任务 3：实现命令注册中心
- 目标：支持注册、查找、列举、补全和冲突检测；隐藏命令不参与帮助和补全。
- 影响文件：`src/mewcode/commands/`、`tests/test_commands.py`
- 依赖任务：任务 2
- 参考资料定位：`docs/ch10/spec.md` 的「命令注册层」

## 任务 4：定义 UI 控制抽象和执行结果
- 目标：把命令执行结果表达为 UI 可消费动作，避免命令实现直接依赖 Textual 或 line mode。
- 影响文件：`src/mewcode/commands/`、`src/mewcode/repl.py`、`tests/test_commands.py`
- 依赖任务：任务 2、任务 3
- 参考资料定位：`docs/ch10/spec.md` 的「命令执行层」「UI 控制层」

## 任务 5：注册内置命令
- 目标：实现 `help`、`compact`、`clear`、`plan`、`do`、`session`、`memory`、`permission`、`status`、`review` 的命令定义，并补充隐藏兼容命令。
- 影响文件：`src/mewcode/commands/`、`tests/test_commands.py`
- 依赖任务：任务 3、任务 4
- 参考资料定位：`docs/ch10/spec.md` 的「内置命令层」

## 任务 6：迁移 TUI 命令入口
- 目标：把 TUI 回车处理中的 slash command 分支改为统一 dispatcher，保持权限确认、用户问询和普通 Agent 输入行为不变。
- 影响文件：`src/mewcode/repl.py`、`tests/test_repl.py`
- 依赖任务：任务 5
- 参考资料定位：`docs/ch10/spec.md` 的「UI 控制层」

## 任务 7：迁移 line mode 命令入口
- 目标：让 line mode 使用同一套命令分发逻辑，并保持现有输出文本兼容。
- 影响文件：`src/mewcode/repl.py`、`tests/test_repl.py`
- 依赖任务：任务 5、任务 6
- 参考资料定位：`docs/ch10/spec.md` 的「命令执行层」

## 任务 8：实现状态栏与权限命令联动
- 目标：在状态栏展示 Agent mode 标记，支持 `/permission` 查看和切换权限模式，并保持 Shift+Tab 循环切换可用。
- 影响文件：`src/mewcode/repl.py`、`tests/test_repl.py`
- 依赖任务：任务 6
- 参考资料定位：`docs/ch10/spec.md` 的「能力清单」

## 任务 9：实现 TUI Tab 补全
- 目标：TUI 输入框按 Tab 时根据命令注册中心补全 slash command，单候选直接补全，多候选显示候选提示。
- 影响文件：`src/mewcode/repl.py`、`tests/test_repl.py`
- 依赖任务：任务 3、任务 6
- 参考资料定位：`docs/ch10/spec.md` 的「补全层」

## 任务 10：补充文档与兼容验收
- 目标：确认第十章规格、任务和验收清单完整覆盖命令框架、十个命令、未知命令、补全和状态栏。
- 影响文件：`docs/ch10/spec.md`、`docs/ch10/tasks.md`、`docs/ch10/checklist.md`
- 依赖任务：任务 1 至任务 9
- 参考资料定位：`docs/ch10/checklist.md`

## 任务 11：接入主流程
- 目标：CLI 创建 REPL 时自动拥有内置命令注册中心；TUI 和 line mode 启动后都通过统一命令框架处理 slash command。
- 影响文件：`src/mewcode/cli.py`、`src/mewcode/repl.py`、`tests/test_cli.py`
- 依赖任务：任务 1 至任务 10
- 参考资料定位：`docs/ch10/spec.md` 的「完成定义」

## 任务 12：端到端验证
- 目标：验证 `/help`、`/clear`、`/status`、`/permission`、`/review` 和既有命令兼容；确认本地命令不触发 LLM，提示词命令进入 Agent，未知 slash command 被本地拦截。
- 影响文件：`tests/`、`docs/ch10/checklist.md`
- 依赖任务：任务 11
- 参考资料定位：`docs/ch10/checklist.md` 的「端到端验收」
