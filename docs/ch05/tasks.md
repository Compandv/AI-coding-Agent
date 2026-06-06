# MewCode 第五章任务拆解：Prompt 工程与缓存管线

## 任务 1：梳理现有提示词入口与 Provider payload
- 目标：确认第四章中用户消息、Plan Mode 前缀、工具定义和 Provider 消息转换的现状，为重构划清边界。
- 影响文件：`src/mewcode/agent.py`、`src/mewcode/session.py`、`src/mewcode/providers/openai.py`、`src/mewcode/providers/anthropic.py`、`tests/`
- 依赖任务：无
- 参考资料定位：`docs/ch05/spec.md` 的「背景」「七源到三通道分发原则」

## 任务 2：新增七模块 System Prompt 结构
- 目标：定义提示词模块结构，建立身份、行为、工具使用、代码质量、安全边界、任务模式、输出风格七个稳定模块，并支持按优先级稳定拼装。
- 影响文件：`src/mewcode/prompts.py`、`tests/test_prompts.py`
- 依赖任务：任务 1
- 参考资料定位：`docs/ch05/spec.md` 的「System Prompt 模块层」「能力清单」

## 任务 3：实现环境上下文 request overlay
- 目标：收集运行环境信息，并把它格式化成请求首条系统级补充消息，而不是放进全局 System Prompt 或持久会话历史。
- 影响文件：`src/mewcode/prompts.py`、`src/mewcode/agent.py`、`tests/test_prompts.py`、`tests/test_agent.py`
- 依赖任务：任务 2
- 参考资料定位：`docs/ch05/spec.md` 的「环境上下文层」「七源到三通道分发原则」

## 任务 4：实现 system-reminder request overlay
- 目标：支持用特殊标签消息注入会话级和轮次级补充指令，确保它进入 messages 通道，并且不污染持久会话历史。
- 影响文件：`src/mewcode/prompts.py`、`src/mewcode/agent.py`、`src/mewcode/session.py`、`tests/test_prompts.py`、`tests/test_agent.py`
- 依赖任务：任务 2、任务 3
- 参考资料定位：`docs/ch05/spec.md` 的「system-reminder 层」

## 任务 5：实现七源到三通道 Prompt 组装管线
- 目标：建立统一 payload 组装入口，把七类输入源分发到 system、messages、tools 三通道，并用统一中间结构表达 cache policy 和调试元信息。
- 影响文件：`src/mewcode/prompts.py`、`src/mewcode/providers/base.py`、`tests/test_prompts.py`
- 依赖任务：任务 2 至任务 4
- 参考资料定位：`docs/ch05/spec.md` 的「Prompt 组装管线层」「七源到三通道分发原则」

## 任务 6：改造 Provider 以支持 system 与缓存策略翻译
- 目标：让 OpenAI 和 Anthropic Provider 使用组装后的 system、messages 和 tools；Anthropic 翻译显式缓存控制，OpenAI 保持稳定前缀并读取自动缓存 usage。
- 影响文件：`src/mewcode/providers/openai.py`、`src/mewcode/providers/anthropic.py`、`src/mewcode/providers/base.py`、`tests/test_providers_streaming.py`
- 依赖任务：任务 5
- 参考资料定位：`docs/ch05/spec.md` 的「缓存观测层」「缓存策略边界」

## 任务 7：强化内置工具描述
- 目标：补齐 ReadFile、EditFile、WriteFile、Bash、Glob、Grep 的用途、优先级、配合关系和注意事项，让模型更稳定地选择工具。
- 影响文件：`src/mewcode/tools/file_tools.py`、`src/mewcode/tools/search_tools.py`、`src/mewcode/tools/bash_tool.py`、`tests/test_tool_registry.py`
- 依赖任务：任务 2
- 参考资料定位：`docs/ch05/spec.md` 的「工具描述层」

## 任务 8：改造 Plan Mode 提示注入
- 目标：移除把 Plan Mode 文本拼接到用户消息的做法，改为按模型请求轮通过 system-reminder 注入完整或精简提醒；默认只在聊天中输出计划，用户明确要求时才保存计划文件。
- 影响文件：`src/mewcode/agent.py`、`src/mewcode/prompts.py`、`src/mewcode/repl.py`、`tests/test_agent.py`、`tests/test_repl.py`
- 依赖任务：任务 4、任务 5
- 参考资料定位：`docs/ch05/spec.md` 的「Plan Mode 提示层」「Plan Mode 行为边界」

## 任务 9：暴露 Provider-aware usage 与调试信息
- 目标：把 Provider 返回的 token usage、缓存读取、缓存写入或不支持状态传回 Agent 或调试事件，方便验证缓存策略是否实际生效。
- 影响文件：`src/mewcode/providers/base.py`、`src/mewcode/providers/openai.py`、`src/mewcode/providers/anthropic.py`、`src/mewcode/agent.py`、`tests/test_agent.py`
- 依赖任务：任务 6
- 参考资料定位：`docs/ch05/spec.md` 的「缓存观测层」

## 任务 10：新增典型场景评估脚本
- 目标：提供五个定性评估场景，覆盖入口定位、编辑前读取、Plan Mode 澄清且默认不落盘、工具选择和缓存观测，便于人工对比提示词效果。
- 影响文件：`scripts/`、`docs/ch05/checklist.md`
- 依赖任务：任务 7、任务 8、任务 9
- 参考资料定位：`docs/ch05/spec.md` 的「评估场景层」

## 任务 11：接入主流程
- 目标：让 CLI、TUI、行模式和 Agent Loop 都通过新的 Prompt 组装管线发起模型请求，并保持第四章已有功能可用。
- 影响文件：`src/mewcode/cli.py`、`src/mewcode/repl.py`、`src/mewcode/agent.py`、`tests/test_cli.py`、`tests/test_repl.py`
- 依赖任务：任务 1 至任务 10
- 参考资料定位：`docs/ch05/spec.md` 的「完成定义」

## 任务 12：端到端验证
- 目标：验证普通模式、Plan Mode、工具描述、缓存观测、TUI 和行模式在新 Prompt 管线下都能正常工作。
- 影响文件：`tests/`、`docs/ch05/checklist.md`
- 依赖任务：任务 11
- 参考资料定位：`docs/ch05/checklist.md` 的「端到端验收」
