# MewCode 第七章规格说明：MCP 外部工具生态

## 背景
前几章让 MewCode 具备了 Agent Loop、Prompt 管线和权限系统，但工具仍然是封闭的内置集合。新增工具需要修改源码、注册类、补测试并重新发布。

第七章要让 MewCode 支持 MCP Server。用户只要在配置文件声明外部 Server，MewCode 就能在启动时连接、发现工具、注册到工具中心，并让 Agent 像调用内置工具一样调用外部工具。

## 目标用户
- 想把 GitHub、数据库、Slack、浏览器等外部能力接入 MewCode 的用户。
- 想学习 MCP 协议、JSON-RPC、Transport 抽象和工具适配器实现的开发者。
- 想通过配置扩展工具生态，而不是修改 MewCode 源码的人。

## 能力清单
- MewCode 可以从配置文件读取 MCP Server 列表。
- MewCode 可以通过 stdio 启动本地 MCP Server。
- MewCode 可以通过 Streamable HTTP 连接远程 MCP Server。
- MCP Client 可以完成初始化握手、工具发现和工具调用。
- MCP 工具可以被包装成 MewCode 内部 Tool 接口。
- 外部工具注册后可以参与 Agent Loop、多工具调用和事件流展示。
- 外部工具默认视为不安全工具，除非配置声明为只读工具。
- MCP stdio 子进程只接收最小环境变量，避免泄露敏感信息。
- 单个 MCP Server 连接失败不会阻塞 MewCode 启动或影响其他 Server。

## 非功能要求
- JSON-RPC 编解码必须可测试，不能依赖真实外部服务。
- Transport 层与 MCP Client 层分离，方便后续增加 SSE、重连和高级能力。
- MCP Server 生命周期要可关闭，避免子进程残留。
- 外部工具名称必须稳定、可追踪、避免与内置工具冲突。
- 配置加载失败要给出明确错误，不能静默启用危险默认值。
- MCP 工具调用结果要以结构化 ToolResult 回填给模型。

## 设计骨架
1. JSON-RPC 协议层
   - 负责请求、响应、错误和通知消息的编码解码。
   - 负责请求 id 和响应 id 的关联基础结构。

2. Transport 层
   - stdio transport 负责启动子进程并通过标准输入输出通信。
   - HTTP transport 负责向远程 MCP endpoint 发送 JSON 请求并接收 JSON 响应。
   - 本章不处理 SSE 流式响应。

3. MCP Client 层
   - 负责初始化握手。
   - 负责列出 Server 暴露的工具。
   - 负责调用指定工具并返回结果。
   - 负责连接关闭和异常传播。

4. MCP Tool Wrapper 层
   - 把 MCP 工具描述转换成 MewCode 工具定义。
   - 把 MewCode 工具调用参数转发为 MCP tools/call。
   - 把 MCP 调用结果转换为 MewCode ToolResult。

5. MCP Manager 层
   - 负责加载和合并配置。
   - 负责创建、缓存和关闭 MCP Client。
   - 负责把发现到的 MCP 工具注册到 ToolRegistry。

6. 权限系统接入层
   - 未声明只读的 MCP 工具默认需要确认。
   - 配置声明的只读 MCP 工具可以按读工具处理。
   - Plan Mode 下只允许只读 MCP 工具运行。

## 配置边界
- MCP 配置放在 `mcp_servers` 下，兼容旧的 `mcp.servers` 写法。
- 用户级配置来自 `~/.mewcode/config.yaml`。
- 项目级配置来自项目根目录 `.mewcode.yaml`，兼容旧的 `.mewcode/config.yaml`。
- 项目级 Server 配置按 Server 名覆盖用户级同名 Server。
- stdio Server 声明命令、参数和显式环境变量。
- HTTP Server 声明 URL 和显式请求头。
- 环境变量引用缺失时跳过对应 Server，并产生可观测错误。
- MCP 工具注册名使用 `server__tool` 形式。

## Out of Scope
- 不做 SSE 流式推送。
- 不消费 MCP Resources。
- 不消费 MCP Prompts。
- 不实现 Sampling。
- 不实现 Elicitation。
- 不做 Server 健康检查。
- 不做自动重连。
- 不做网络请求权限限制。
- 不做远程 Server 凭据管理 UI。

## 完成定义
当 MewCode 启动时可以读取 MCP 配置，连接至少一个 stdio MCP Server 或 HTTP MCP Server，发现工具并注册为 `server__tool`，Agent 能调用这些工具并收到结果，同时权限系统能对外部工具做默认确认和只读放行判断时，本章达到核心完成标准。
