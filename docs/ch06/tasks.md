# MewCode 第六章任务拆解：权限系统

## 任务 1：梳理现有工具执行与确认遗留路径
- 目标：确认工具执行入口、路径解析逻辑、Plan Mode 拦截逻辑、TUI 确认事件和行模式输出的当前状态。
- 影响文件：`src/mewcode/agent.py`、`src/mewcode/tools/context.py`、`src/mewcode/repl.py`、`tests/`
- 依赖任务：无
- 参考资料定位：`docs/ch06/spec.md` 的「背景」「设计骨架」

## 任务 2：新增权限决策数据结构
- 目标：定义四种权限模式、规则结果、检查结果、确认动作和权限错误的统一结构，供规则引擎、Agent 和 UI 共享。
- 影响文件：`src/mewcode/permissions.py`、`tests/test_permissions.py`
- 依赖任务：任务 1
- 参考资料定位：`docs/ch06/spec.md` 的「能力清单」「权限模式边界」

## 任务 3：实现危险命令检测器
- 目标：用正则黑名单识别不可逆系统破坏命令，并保证这层不可被规则、模式或用户确认覆盖。
- 影响文件：`src/mewcode/permissions.py`、`tests/test_permissions.py`
- 依赖任务：任务 2
- 参考资料定位：`docs/ch06/spec.md` 的「危险命令检测层」

## 任务 4：加固路径沙箱
- 目标：复核并扩展现有路径解析，确保文件工具和计划文件工具都基于解析后的真实路径做工作区边界检查。
- 影响文件：`src/mewcode/tools/context.py`、`src/mewcode/tools/file_tools.py`、`src/mewcode/tools/plan_tools.py`、`tests/test_tool_context.py`
- 依赖任务：任务 2
- 参考资料定位：`docs/ch06/spec.md` 的「路径沙箱层」

## 任务 5：实现敏感读取保护
- 目标：拦截 `ReadFile(*.env*)` 这类宽泛环境文件读取，并提示模型改用明确候选文件名逐个尝试。
- 影响文件：`src/mewcode/permissions.py`、`src/mewcode/tools/file_tools.py`、`tests/test_permissions.py`、`tests/test_agent.py`
- 依赖任务：任务 4
- 参考资料定位：`docs/ch06/spec.md` 的「敏感读取保护层」

## 任务 6：实现规则文件加载
- 目标：加载 `~/.mewcode/permissions.yaml`、`.mewcode/permissions.yaml`、`.mewcode/permissions.local.yaml`，处理文件不存在、格式错误和规则无效。
- 影响文件：`src/mewcode/permissions.py`、`src/mewcode/config.py`、`tests/test_permissions.py`、`tests/test_config.py`
- 依赖任务：任务 2
- 参考资料定位：`docs/ch06/spec.md` 的「规则加载层」「规则与配置边界」

## 任务 7：实现规则匹配与优先级
- 目标：支持 `工具名(模式)` 规则语法，按本地级 > 项目级 > 用户级的顺序返回 allow、deny 或未命中，并保证同层 deny 优先于 allow。
- 影响文件：`src/mewcode/permissions.py`、`tests/test_permissions.py`
- 依赖任务：任务 6
- 参考资料定位：`docs/ch06/spec.md` 的「规则匹配层」

## 任务 8：实现四种权限模式
- 目标：实现 `default`、`acceptEdits`、`plan`、`bypassPermissions` 在规则未命中时的默认决策，并提供循环切换所需的模式顺序。
- 影响文件：`src/mewcode/permissions.py`、`src/mewcode/config.py`、`tests/test_permissions.py`、`tests/test_config.py`
- 依赖任务：任务 7
- 参考资料定位：`docs/ch06/spec.md` 的「权限模式层」

## 任务 9：实现权限检查器
- 目标：串联危险命令检测、路径沙箱、规则匹配、权限模式和 HITL 需要确认判断，输出统一权限决策。
- 影响文件：`src/mewcode/permissions.py`、`src/mewcode/agent.py`、`tests/test_permissions.py`、`tests/test_agent.py`
- 依赖任务：任务 3 至任务 8
- 参考资料定位：`docs/ch06/spec.md` 的「权限检查器层」

## 任务 10：接入 Agent 工具执行
- 目标：在工具真实执行前调用权限检查器；允许时执行，拒绝时回填结构化结果，需要确认时发出事件并暂停当前轮。
- 影响文件：`src/mewcode/agent.py`、`tests/test_agent.py`
- 依赖任务：任务 9
- 参考资料定位：`docs/ch06/spec.md` 的「HITL 行为边界」

## 任务 11：实现 HITL UI、模式显示与规则写回
- 目标：升级 TUI 和行模式确认流程，支持允许本次、永久允许和拒绝本次；支持快捷键循环切换权限模式，并在状态栏常驻显示当前模式。
- 影响文件：`src/mewcode/repl.py`、`src/mewcode/permissions.py`、`tests/test_repl.py`、`tests/test_permissions.py`
- 依赖任务：任务 10
- 参考资料定位：`docs/ch06/spec.md` 的「Agent 事件层」「UI 交互层」

## 任务 12：接入主流程
- 目标：启动时加载权限配置和规则文件，创建权限检查器，传入 Agent，并确保 CLI、TUI、行模式和 Plan Mode 都走统一权限路径。
- 影响文件：`src/mewcode/cli.py`、`src/mewcode/config.py`、`src/mewcode/agent.py`、`src/mewcode/repl.py`、`tests/test_cli.py`
- 依赖任务：任务 1 至任务 11
- 参考资料定位：`docs/ch06/spec.md` 的「完成定义」

## 任务 13：端到端验证
- 目标：验证危险 Bash 拦截、路径逃逸拦截、规则优先级、四种模式、HITL 三种选择、Plan Mode 兼容和 Agent Loop 拒绝后继续。
- 影响文件：`tests/`、`docs/ch06/checklist.md`
- 依赖任务：任务 12
- 参考资料定位：`docs/ch06/checklist.md` 的「端到端验收」
