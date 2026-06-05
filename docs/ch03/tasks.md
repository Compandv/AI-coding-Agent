# MewCode 第三章任务拆解：工具系统

## 任务 1：定义 Tool 抽象和结构化结果
- 目标：建立统一工具接口，约定工具名称、描述、参数 Schema、执行方法和结构化返回格式。
- 影响文件：`src/mewcode/tools/base.py`、`src/mewcode/tools/__init__.py`、`tests/test_tools_base.py`
- 依赖任务：无
- 参考资料定位：`spec.md` 的「工具抽象层」「能力清单」

## 任务 2：实现工具执行上下文与路径边界
- 目标：定义工具运行时上下文，记录当前工作目录、超时设置和路径安全检查，确保文件工具只能操作当前目录内路径。
- 影响文件：`src/mewcode/tools/context.py`、`tests/test_tool_context.py`
- 依赖任务：任务 1
- 参考资料定位：`spec.md` 的「权限与边界」、`checklist.md` 的「路径边界验收」

## 任务 3：实现 ReadFile 工具
- 目标：读取当前工作目录内文件内容，并在文件不存在、路径越界或读取失败时返回结构化错误。
- 影响文件：`src/mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
- 依赖任务：任务 1、任务 2
- 参考资料定位：`checklist.md` 的「ReadFile 验收」

## 任务 4：实现 WriteFile 工具
- 目标：在当前工作目录内创建或覆盖文件，并标记为默认需要用户确认的敏感工具。
- 影响文件：`src/mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
- 依赖任务：任务 1、任务 2
- 参考资料定位：`checklist.md` 的「WriteFile 验收」「权限确认验收」

## 任务 5：实现 EditFile 工具
- 目标：按原文唯一匹配替换修改文件；匹配不到或匹配多次时返回清晰错误。
- 影响文件：`src/mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
- 依赖任务：任务 1、任务 2、任务 3
- 参考资料定位：`spec.md` 的「能力清单」、`checklist.md` 的「EditFile 验收」

## 任务 6：实现 Glob 工具
- 目标：按路径模式查找当前工作目录内文件，返回匹配路径列表，并限制结果数量。
- 影响文件：`src/mewcode/tools/search_tools.py`、`tests/test_search_tools.py`
- 依赖任务：任务 1、任务 2
- 参考资料定位：`checklist.md` 的「Glob 验收」

## 任务 7：实现 Grep 工具
- 目标：搜索当前工作目录内文件内容，支持关键词或正则表达式，返回文件路径、行号和匹配行摘要。
- 影响文件：`src/mewcode/tools/search_tools.py`、`tests/test_search_tools.py`
- 依赖任务：任务 1、任务 2
- 参考资料定位：`checklist.md` 的「Grep 验收」

## 任务 8：实现 Bash 工具
- 目标：执行受控命令，支持工作目录、超时、退出码、stdout、stderr 和结构化错误，并标记为默认需要用户确认的敏感工具。
- 影响文件：`src/mewcode/tools/bash_tool.py`、`tests/test_bash_tool.py`
- 依赖任务：任务 1、任务 2
- 参考资料定位：`spec.md` 的「权限与边界」、`checklist.md` 的「Bash 验收」

## 任务 9：实现工具注册中心
- 目标：集中登记六个核心工具，支持按名称查找、列出工具、转换为模型 API 工具描述。
- 影响文件：`src/mewcode/tools/registry.py`、`src/mewcode/tools/__init__.py`、`tests/test_tool_registry.py`
- 依赖任务：任务 3 至任务 8
- 参考资料定位：`spec.md` 的「工具注册层」、`checklist.md` 的「注册中心验收」

## 任务 10：扩展会话消息以承载工具调用与工具结果
- 目标：让当前进程内会话可以表达用户消息、助手消息、工具调用请求和工具结果，供 Provider 回灌使用。
- 影响文件：`src/mewcode/session.py`、`tests/test_session.py`
- 依赖任务：任务 1
- 参考资料定位：`spec.md` 的「会话与编排层」、`checklist.md` 的「工具结果回灌验收」

## 任务 11：扩展 Provider 工具调用协议
- 目标：让 Provider 可以接收工具描述，解析模型流式返回中的工具调用事件，拼接 JSON 参数碎片，并把工具结果回传给模型生成最终回答。
- 影响文件：`src/mewcode/providers/base.py`、`src/mewcode/providers/anthropic.py`、`src/mewcode/providers/openai.py`、`tests/test_providers_streaming.py`
- 依赖任务：任务 9、任务 10
- 参考资料定位：Anthropic tool use 文档、OpenAI tool calling 文档、`checklist.md` 的「Provider 工具调用验收」

## 任务 12：实现单次工具调用编排器
- 目标：在一轮用户请求中完成“模型请求工具 → MewCode 执行一次工具 → 工具结果回灌 → 模型最终回答”的流程，不做自动循环。
- 影响文件：`src/mewcode/agent.py`、`tests/test_agent.py`
- 依赖任务：任务 9、任务 10、任务 11
- 参考资料定位：`spec.md` 的「阶段目标」「会话与编排层」、`checklist.md` 的「一次工具后停验收」

## 任务 13：接入 Textual 工具状态与确认流程
- 目标：在界面中展示工具调用状态，对 WriteFile、EditFile、Bash 请求用户确认，允许拒绝并把拒绝结果结构化回灌给模型。
- 影响文件：`src/mewcode/repl.py`、`tests/test_repl.py`
- 依赖任务：任务 12
- 参考资料定位：`spec.md` 的「Textual 交互层」「权限与边界」、`checklist.md` 的「权限确认验收」「界面验收」

## 任务 14：接入主流程
- 目标：启动时创建工具上下文、注册中心和单次工具编排器，把现有聊天路径切换为支持工具调用的主流程。
- 影响文件：`src/mewcode/cli.py`、`src/mewcode/repl.py`、`src/mewcode/agent.py`、`tests/test_cli.py`
- 依赖任务：任务 1 至任务 13
- 参考资料定位：`spec.md` 的「设计骨架」、`checklist.md` 的「启动与主流程验收」

## 任务 15：端到端验证
- 目标：用示例项目验证六个工具、权限确认、工具失败回灌、Provider 工具调用和一次工具后停的完整行为。
- 影响文件：`tests/`、`docs/ch03/checklist.md`、必要时补充 `README.md`
- 依赖任务：任务 14
- 参考资料定位：`checklist.md` 的「端到端验收」
