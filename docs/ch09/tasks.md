# MewCode 第九章任务拆解：跨会话记忆系统

## 任务 1：梳理现有会话、上下文和 Prompt 注入入口
- 目标：确认 `ChatSession` 消息结构、上下文落盘目录、Agent Loop 结束事件、REPL 命令分发和 system-reminder 注入方式。
- 影响文件：`src/mewcode/session.py`、`src/mewcode/context.py`、`src/mewcode/agent.py`、`src/mewcode/prompts.py`、`src/mewcode/repl.py`、`tests/`
- 依赖任务：无
- 参考资料定位：`docs/ch09/spec.md` 的「背景」「设计骨架」

## 任务 2：新增记忆与会话配置模型
- 目标：扩展配置读取，支持自动记忆开关、会话保留策略、指令加载和记忆索引相关配置，同时保持现有配置兼容。
- 影响文件：`src/mewcode/config.py`、`tests/test_config.py`
- 依赖任务：任务 1
- 参考资料定位：`docs/ch09/spec.md` 的「配置边界」

## 任务 3：实现指令文件发现与优先级加载
- 目标：发现用户级、项目根和项目私有 `MEWCODE.md`，按 `.mewcode/MEWCODE.md`、根目录 `MEWCODE.md`、用户级 `MEWCODE.md` 的顺序生成可注入内容。
- 影响文件：`src/mewcode/memory/`、`tests/test_memory_instructions.py`
- 依赖任务：任务 2
- 参考资料定位：`docs/ch09/spec.md` 的「指令文件加载层」

## 任务 4：实现 `@include` 安全展开
- 目标：支持 Markdown 指令文件中的模块化引用，限制嵌套深度，使用 visited 集合防循环，并拒绝跳出允许根目录的 include 路径。
- 影响文件：`src/mewcode/memory/`、`tests/test_memory_instructions.py`
- 依赖任务：任务 3
- 参考资料定位：`docs/ch09/spec.md` 的「指令文件加载层」「非功能要求」

## 任务 5：实现 JSONL 会话存档
- 目标：把用户消息、助手消息、工具调用和工具结果追加写入项目 `.mewcode/` 下的会话存档；列表信息通过扫描 JSONL 生成，不维护独立 meta 文件。
- 影响文件：`src/mewcode/session.py`、`src/mewcode/memory/`、`tests/test_session_store.py`
- 依赖任务：任务 1、任务 2
- 参考资料定位：`docs/ch09/spec.md` 的「会话存档层」

## 任务 6：实现会话恢复与完整性修复
- 目标：从 JSONL 重建会话，跳过坏行，校验工具调用和工具结果配对，遇到不完整链路时截断到安全位置。
- 影响文件：`src/mewcode/session.py`、`src/mewcode/memory/`、`tests/test_session_store.py`
- 依赖任务：任务 5
- 参考资料定位：`docs/ch09/spec.md` 的「会话恢复层」

## 任务 7：接入上下文压缩和时间跨度提醒
- 目标：恢复会话后检查 token 占用，必要时调用现有上下文压缩；会话间隔较久时注入时间跨度提醒，避免模型误判旧状态。
- 影响文件：`src/mewcode/context.py`、`src/mewcode/prompts.py`、`src/mewcode/memory/`、`tests/test_session_store.py`、`tests/test_prompts.py`
- 依赖任务：任务 6
- 参考资料定位：`docs/ch09/spec.md` 的「会话恢复层」「Prompt 注入层」

## 任务 8：实现过期会话清理
- 目标：按配置清理过期会话存档和对应本地缓存目录，清理失败可观测但不阻塞启动。
- 影响文件：`src/mewcode/memory/`、`tests/test_session_store.py`
- 依赖任务：任务 5
- 参考资料定位：`docs/ch09/spec.md` 的「会话生命周期层」

## 任务 9：实现自动记忆提取与写入
- 目标：在 Agent 自然结束且没有待执行工具时提取长期记忆，区分用户偏好、纠正反馈、项目知识和参考资料，并写入对应用户级或项目级位置；本章先使用可测试的本地提取器。
- 影响文件：`src/mewcode/agent.py`、`src/mewcode/memory/`、`tests/test_agent.py`、`tests/test_memory_store.py`
- 依赖任务：任务 2、任务 6
- 参考资料定位：`docs/ch09/spec.md` 的「自动记忆提取层」「记忆存储层」

## 任务 10：实现记忆索引与 Prompt 注入
- 目标：维护轻量记忆索引，在每轮请求前把指令文件、记忆索引和恢复提醒作为 system-reminder 注入 messages 通道。
- 影响文件：`src/mewcode/prompts.py`、`src/mewcode/agent.py`、`src/mewcode/memory/`、`tests/test_prompts.py`、`tests/test_agent.py`
- 依赖任务：任务 3、任务 7、任务 9
- 参考资料定位：`docs/ch09/spec.md` 的「记忆存储层」「Prompt 注入层」

## 任务 11：实现 `/session` 和 `/memory` 命令
- 目标：让 TUI 和 line mode 都能查看、恢复、删除会话，以及查看、刷新、开关和删除记忆。
- 影响文件：`src/mewcode/repl.py`、`tests/test_repl.py`
- 依赖任务：任务 5 至任务 10
- 参考资料定位：`docs/ch09/spec.md` 的「REPL 命令层」

## 任务 12：接入主流程
- 目标：CLI 启动时创建跨会话记忆组件，加载指令和记忆，连接 Agent、ContextManager、SessionStore 和 REPL，并确保退出时会话已落盘。
- 影响文件：`src/mewcode/cli.py`、`src/mewcode/agent.py`、`src/mewcode/repl.py`、`tests/test_cli.py`
- 依赖任务：任务 1 至任务 11
- 参考资料定位：`docs/ch09/spec.md` 的「完成定义」

## 任务 13：端到端验证
- 目标：验证新会话加载指令、会话恢复、自动记忆跨会话生效、命令管理、异常存档恢复和上下文压缩协作。
- 影响文件：`tests/`、`docs/ch09/checklist.md`
- 依赖任务：任务 12
- 参考资料定位：`docs/ch09/checklist.md` 的「端到端验收」
