# MewCode 第八章任务拆解：上下文管理

## 任务 1：梳理现有会话历史、工具结果和 Provider 请求结构
- 目标：确认消息结构、工具结果写入路径、Prompt Payload 组装和 Agent 请求入口。
- 影响文件：`src/mewcode/session.py`、`src/mewcode/agent.py`、`src/mewcode/prompts.py`、`src/mewcode/providers/`
- 依赖任务：无
- 参考资料定位：`docs/ch08/spec.md` 的「背景」「设计骨架」

## 任务 2：新增 Token 估算与上下文配置
- 目标：实现稳定的近似 Token 估算，并从配置文件读取上下文窗口、压缩余量、结果阈值和预览大小。
- 影响文件：`src/mewcode/context.py`、`src/mewcode/config.py`、`tests/test_context.py`、`tests/test_config.py`
- 依赖任务：任务 1
- 参考资料定位：`docs/ch08/spec.md` 的「Token 估算层」「配置边界」

## 任务 3：实现会话隔离的上下文缓存目录
- 目标：为每个 ChatSession 分配稳定 session id，并把上下文缓存限定在会话目录中。
- 影响文件：`src/mewcode/session.py`、`src/mewcode/compact/state.py`、`tests/test_context.py`、`tests/compact/`
- 依赖任务：任务 2
- 参考资料定位：`docs/ch08/spec.md` 的「大结果存储层」

## 任务 4：实现大工具结果落盘
- 目标：当工具结果超过阈值时，完整内容写入本地文件，对话里只保留 head preview、tail preview、stored path 和边界提醒。
- 影响文件：`src/mewcode/compact/layer1.py`、`src/mewcode/context.py`、`tests/compact/test_layer1.py`、`tests/test_context.py`
- 依赖任务：任务 3
- 参考资料定位：`docs/ch08/spec.md` 的「大结果存储层」「轻量预防层」

## 任务 5：接入工具结果写入前处理
- 目标：Agent 在工具结果进入历史前调用上下文管理器，确保大结果不会先污染会话。
- 影响文件：`src/mewcode/agent.py`、`tests/test_agent.py`
- 依赖任务：任务 4
- 参考资料定位：`docs/ch08/spec.md` 的「Agent Loop 集成层」

## 任务 6：实现摘要 Prompt 与恢复消息
- 目标：构建无工具摘要请求，提取正式摘要，并生成包含摘要、文件快照、工具概览和边界提醒的恢复消息。
- 影响文件：`src/mewcode/compact/summary_prompt.py`、`src/mewcode/compact/recovery.py`、`src/mewcode/context.py`、`tests/compact/test_summary_prompt.py`
- 依赖任务：任务 2
- 参考资料定位：`docs/ch08/spec.md` 的「摘要 Prompt 层」「摘要内容边界」

## 任务 7：实现分块摘要与 final merge
- 目标：将旧消息按用户轮次或消息组切块，分别摘要后合并为最终 compact summary。
- 影响文件：`src/mewcode/context.py`、`tests/test_context.py`
- 依赖任务：任务 6
- 参考资料定位：`docs/ch08/spec.md` 的「分块摘要层」

## 任务 8：实现 fallback 与自动压缩熔断
- 目标：LLM 摘要失败时使用本地 deterministic summary 兜底，自动压缩连续失败后熔断。
- 影响文件：`src/mewcode/context.py`、`tests/test_context.py`
- 依赖任务：任务 7
- 参考资料定位：`docs/ch08/spec.md` 的「fallback 与熔断层」

## 任务 9：新增上下文事件流
- 目标：暴露压缩开始、分块开始、分块完成、fallback、完成、失败、跳过、紧急重试和统计事件。
- 影响文件：`src/mewcode/context.py`、`src/mewcode/agent.py`、`src/mewcode/repl.py`、`tests/test_agent.py`、`tests/test_repl.py`
- 依赖任务：任务 8
- 参考资料定位：`docs/ch08/spec.md` 的「事件流层」

## 任务 10：实现 `/compact`、`/compact focus` 和 `/context`
- 目标：支持手动压缩、带重点提示的手动压缩和只读上下文状态查看。
- 影响文件：`src/mewcode/agent.py`、`src/mewcode/repl.py`、`tests/test_agent.py`、`tests/test_repl.py`
- 依赖任务：任务 9
- 参考资料定位：`docs/ch08/spec.md` 的「命令接入层」

## 任务 11：接入主流程
- 目标：CLI 启动时创建 ContextManager，并让 Agent、TUI、line mode 都使用统一上下文管理能力。
- 影响文件：`src/mewcode/cli.py`、`src/mewcode/agent.py`、`src/mewcode/repl.py`、`tests/test_cli.py`
- 依赖任务：任务 1 至任务 10
- 参考资料定位：`docs/ch08/spec.md` 的「完成定义」

## 任务 12：端到端验证
- 目标：验证大文件读取落盘、自动压缩、手动压缩、focus 压缩、fallback、上下文统计和后续继续对话。
- 影响文件：`tests/`、`docs/ch08/checklist.md`
- 依赖任务：任务 11
- 参考资料定位：`docs/ch08/checklist.md` 的「端到端验收」
