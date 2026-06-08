# MewCode 第七章验收清单：MCP 外部工具生态

## JSON-RPC 验收
- [ ] 可以编码 JSON-RPC 请求，包含 `jsonrpc: "2.0"`、`id`、`method` 和 `params`。
- [ ] 可以编码 JSON-RPC 通知，包含 `jsonrpc: "2.0"` 和 `method`，不包含 `id`。
- [ ] 可以解码成功响应并按 `id` 匹配原请求。
- [ ] 可以解码错误响应并保留错误 code、message 和 data。
- [ ] 非法 JSON-RPC 消息会产生可测试的协议错误。

## stdio transport 验收
- [ ] stdio transport 可以启动配置中的 MCP Server 子进程。
- [ ] stdio transport 通过换行分隔 JSON-RPC 消息。
- [ ] stdio transport 可以向子进程 stdin 写入请求。
- [ ] stdio transport 可以从子进程 stdout 读取响应。
- [ ] stdio 子进程环境默认只包含 `PATH`、Windows 启动必要系统变量和配置中显式声明的变量。
- [ ] stdio transport 关闭时会释放子进程资源。

## HTTP transport 验收
- [ ] HTTP transport 使用 POST 发送 JSON-RPC 请求。
- [ ] HTTP transport 可以携带配置中的 headers。
- [ ] HTTP transport 可以解析 JSON 响应。
- [ ] HTTP 响应为 SSE 或非 JSON 时，本章明确报错或跳过。
- [ ] HTTP 请求失败时返回可观测错误，不导致整个程序崩溃。

## MCP Client 验收
- [ ] Client 连接后会发送 initialize 请求。
- [ ] initialize 成功后会发送 initialized 通知。
- [ ] Client 可以调用 tools/list 获取远端工具列表。
- [ ] Client 可以调用 tools/call 执行远端工具。
- [ ] tools/call 失败时会转换为 ToolResult 失败结果或可观测异常。
- [ ] 单个 Server 初始化失败不会影响其他 Server。

## 工具注册验收
- [ ] MCP 工具注册名格式为 `server__tool`。
- [ ] MCP 工具不会覆盖内置工具。
- [ ] 两个 Server 暴露同名工具时，注册名仍然唯一。
- [ ] MCP 工具 description 会进入模型工具描述。
- [ ] MCP 工具 inputSchema 会作为工具 schema 传给 Provider。
- [ ] ToolRegistry 可以同时列出内置工具和 MCP 工具。

## 配置验收
- [ ] 用户级 MCP 配置路径为 `~/.mewcode/config.yaml`。
- [ ] 项目级 MCP 配置路径为项目根目录 `.mewcode.yaml`。
- [ ] MCP 配置优先使用顶层 `mcp_servers`，并兼容旧的 `mcp.servers`。
- [ ] stdio Server 支持 `type: stdio`、`command`、`args`、`env`，并兼容 `transport: stdio`。
- [ ] HTTP Server 支持 `type: http`、`url`、`headers`，并兼容 `transport: http`。
- [ ] env 和 headers 中的 `${VAR}` 可以从当前环境展开。
- [ ] `${VAR}` 缺失时跳过对应 Server。
- [ ] 项目级同名 Server 会覆盖用户级同名 Server。
- [ ] 配置中的 `read_only_tools` 可以声明只读 MCP 工具。
- [ ] 项目根目录 `.mewcode.yaml` 中默认声明 `context7` stdio Server。

## 权限验收
- [ ] 未声明只读的 MCP 工具在 `default` 模式下需要 HITL 确认。
- [ ] 声明为只读的 MCP 工具在 `default` 模式下可以直接执行。
- [ ] Plan Mode 下只读 MCP 工具可以执行。
- [ ] Plan Mode 下非只读 MCP 工具被拒绝。
- [ ] `acceptEdits` 模式不会自动放行未知 MCP 工具。
- [ ] `bypassPermissions` 模式可以放行非危险、未违反沙箱的 MCP 工具。
- [ ] 权限拒绝会作为结构化工具结果回填给模型。

## Agent Loop 验收
- [ ] Agent 可以在一轮任务中调用 MCP 工具并继续下一轮。
- [ ] MCP 工具结果会按普通工具结果写回会话。
- [ ] MCP 工具失败不会导致 Agent Loop 崩溃。
- [ ] 多工具响应中 MCP 只读工具可以和内置读工具一起批量执行。
- [ ] 多工具响应中未知 MCP 工具按不安全工具串行或确认处理。
- [ ] MCP 工具事件中可以看到 `server__tool` 名称。

## 范围边界验收
- [ ] 本章没有实现 SSE 流式推送。
- [ ] 本章没有实现 MCP Resources 消费。
- [ ] 本章没有实现 MCP Prompts 消费。
- [ ] 本章没有实现 Sampling。
- [ ] 本章没有实现 Elicitation。
- [ ] 本章没有实现自动重连。
- [ ] 本章没有实现 Server 健康检查。

## 端到端验收
- [ ] 配置一个 fake stdio MCP Server 后，启动 MewCode 可以看到其工具被注册为 `fake__echo`。
- [ ] 请求模型调用 `fake__echo` 后，可以看到工具执行、结果回填和最终回答。
- [ ] 配置一个 fake HTTP MCP Server 后，MewCode 可以通过 HTTP 调用远端工具。
- [ ] 一个 MCP Server 配置错误时，其他可用 Server 的工具仍能注册。
- [ ] 在 `default` 模式调用未知 MCP 工具时，TUI 出现权限确认。
- [ ] 在 `/plan` 模式调用非只读 MCP 工具时，工具不执行且模型收到拒绝原因。
- [ ] `.\.venv\Scripts\python.exe -m pytest -q` 可以通过。
