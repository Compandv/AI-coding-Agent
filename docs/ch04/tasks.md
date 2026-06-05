# MewCode 第四章任务拆解：Agent Loop

## 任务 1：扩展 Provider 工具调用返回结构
- 目标：把单个工具调用升级为工具调用列表，同时保留无工具纯文本响应能力。
- 影响文件：`src/mewcode/providers/base.py`、`src/mewcode/providers/openai.py`、`src/mewcode/providers/anthropic.py`、`tests/test_providers_streaming.py`
- 依赖任务：无
- 参考资料定位：`docs/ch04/spec.md` 的「Provider 工具响应层」「能力清单」

## 任务 2：扩展会话消息以支持多工具对应关系
- 目标：让会话历史能表达一次 assistant 工具响应对应多个工具调用，并让多个工具结果按稳定 id 回填。
- 影响文件：`src/mewcode/session.py`、`tests/test_session.py`
- 依赖任务：任务 1
- 参考资料定位：`docs/ch04/spec.md` 的「会话层」

## 任务 3：定义 Agent 事件流和循环配置
- 目标：建立 AgentEvent 作为 Agent 与 UI 的解耦边界，并定义循环模式、停止原因和默认步数上限。
- 影响文件：`src/mewcode/agent.py`、`tests/test_agent.py`
- 依赖任务：任务 1、任务 2
- 参考资料定位：`docs/ch04/spec.md` 的「Agent 事件层」「停止条件」

## 任务 4：实现流式收集器
- 目标：在每轮模型响应中实时透传文本增量，同时积攒完整文本和工具调用列表供循环判断。
- 影响文件：`src/mewcode/agent.py`、`tests/test_agent.py`
- 依赖任务：任务 3
- 参考资料定位：`docs/ch04/spec.md` 的「Agent Loop 编排层」

## 任务 5：实现 ReAct Agent Loop
- 目标：用循环式 Agent 替代单工具后停的流程，支持连续模型请求、工具执行、结果回填和五种停止条件。
- 影响文件：`src/mewcode/agent.py`、`tests/test_agent.py`
- 依赖任务：任务 3、任务 4
- 参考资料定位：`docs/ch04/spec.md` 的「阶段目标」「停止条件」

## 任务 6：实现工具分批执行
- 目标：实现工具调用分组，安全读工具批量执行，不安全工具按模型顺序串行执行，并按原始顺序回填结果。
- 影响文件：`src/mewcode/agent.py`、`tests/test_agent.py`
- 依赖任务：任务 5
- 参考资料定位：`docs/ch04/spec.md` 的「工具批处理层」

## 任务 7：实现 Plan Mode 与模式切换
- 目标：支持正常执行模式和 Plan Mode；Plan Mode 只允许读工具，不安全工具被拦截为结构化结果。
- 影响文件：`src/mewcode/agent.py`、`src/mewcode/repl.py`、`tests/test_agent.py`、`tests/test_repl.py`
- 依赖任务：任务 5、任务 6
- 参考资料定位：`docs/ch04/spec.md` 的「模式控制层」「权限与边界」

## 任务 8：接入 Textual 事件消费
- 目标：让 Textual 界面消费统一 AgentEvent，显示多次工具调用、工具结果、最终回答、取消和错误。
- 影响文件：`src/mewcode/repl.py`、`tests/test_repl.py`
- 依赖任务：任务 3 至任务 7
- 参考资料定位：`docs/ch04/spec.md` 的「Textual 与行模式交互层」

## 任务 9：接入 fallback 行模式事件消费
- 目标：让非交互式或强制行模式使用同一 Agent Loop，支持 `/plan`、`/do` 和多工具过程输出。
- 影响文件：`src/mewcode/repl.py`、`tests/test_repl.py`
- 依赖任务：任务 8
- 参考资料定位：`docs/ch04/checklist.md` 的「行模式验收」

## 任务 10：接入主流程
- 目标：启动时创建循环式 Agent，并确保现有命令入口、配置、Provider、工具注册中心和 UI 都走新主流程。
- 影响文件：`src/mewcode/cli.py`、`src/mewcode/agent.py`、`src/mewcode/repl.py`、`tests/test_cli.py`
- 依赖任务：任务 1 至任务 9
- 参考资料定位：`docs/ch04/spec.md` 的「设计骨架」

## 任务 11：端到端验证
- 目标：验证多步搜索读取、写入后读取确认、Plan Mode 只读、步数上限、取消和行模式完整行为。
- 影响文件：`tests/`、`docs/ch04/checklist.md`
- 依赖任务：任务 10
- 参考资料定位：`docs/ch04/checklist.md` 的「端到端验收」
