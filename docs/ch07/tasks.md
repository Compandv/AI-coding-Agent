# MewCode 第七章任务拆解：MCP 外部工具生态

## 任务 1：梳理现有工具注册、配置加载和权限分类入口
- 目标：确认内置工具注册、ToolDefinition schema、CLI 启动配置、权限工具分类和 Agent 工具执行路径。
- 影响文件：`src/mewcode/tools/`、`src/mewcode/config.py`、`src/mewcode/cli.py`、`src/mewcode/permissions.py`、`tests/`
- 依赖任务：无
- 参考资料定位：`docs/ch07/spec.md` 的「背景」「设计骨架」

## 任务 2：新增 JSON-RPC 2.0 协议层
- 目标：实现 MCP 所需的请求、响应、错误和通知消息编解码，并支持请求 id 与响应 id 的匹配。
- 影响文件：`src/mewcode/mcp/`、`tests/test_mcp_jsonrpc.py`
- 依赖任务：任务 1
- 参考资料定位：`docs/ch07/spec.md` 的「JSON-RPC 协议层」

## 任务 3：实现 Transport 抽象与 stdio transport
- 目标：定义统一 Transport 接口，实现本地子进程 stdio 通信，按行收发 JSON-RPC 消息，并支持关闭子进程。
- 影响文件：`src/mewcode/mcp/`、`tests/test_mcp_transport.py`
- 依赖任务：任务 2
- 参考资料定位：`docs/ch07/spec.md` 的「Transport 层」

## 任务 4：实现 Streamable HTTP JSON transport
- 目标：实现 HTTP POST JSON 请求响应模式，明确拒绝或跳过 SSE 响应。
- 影响文件：`src/mewcode/mcp/`、`tests/test_mcp_transport.py`
- 依赖任务：任务 2
- 参考资料定位：`docs/ch07/spec.md` 的「Transport 层」「Out of Scope」

## 任务 5：实现 MCP Client 握手、工具发现和工具调用
- 目标：通过 Transport 完成 initialize、initialized、tools/list、tools/call 流程，并把协议错误转换为可理解异常。
- 影响文件：`src/mewcode/mcp/`、`tests/test_mcp_client.py`
- 依赖任务：任务 3、任务 4
- 参考资料定位：`docs/ch07/spec.md` 的「MCP Client 层」

## 任务 6：扩展工具 schema 以支持 MCP 原始 JSON Schema
- 目标：让 ToolDefinition 能承载 MCP 工具返回的 inputSchema，同时保持内置工具现有 schema 行为不变。
- 影响文件：`src/mewcode/tools/base.py`、`tests/test_tool_registry.py`
- 依赖任务：任务 1
- 参考资料定位：`docs/ch07/spec.md` 的「MCP Tool Wrapper 层」

## 任务 7：实现 MCPToolWrapper
- 目标：把远端 MCP 工具包装成 MewCode Tool，注册名使用 `server__tool`，执行时转发到对应 MCP Client。
- 影响文件：`src/mewcode/mcp/`、`src/mewcode/tools/registry.py`、`tests/test_mcp_tools.py`
- 依赖任务：任务 5、任务 6
- 参考资料定位：`docs/ch07/spec.md` 的「MCP Tool Wrapper 层」

## 任务 8：实现 MCP 配置加载、合并和环境变量展开
- 目标：从用户级 `~/.mewcode/config.yaml` 和项目级 `.mewcode.yaml` 加载 `mcp_servers`，兼容旧的 `mcp.servers`，按 Server 名覆盖合并，处理 stdio、HTTP、env、headers 和只读工具声明。
- 影响文件：`src/mewcode/config.py`、`tests/test_config.py`
- 依赖任务：任务 1
- 参考资料定位：`docs/ch07/spec.md` 的「配置边界」

## 任务 9：实现 MCP Manager 生命周期管理
- 目标：根据配置创建 MCP Client，连接成功后发现工具并注册；单个 Server 失败时跳过该 Server，关闭时释放所有连接。
- 影响文件：`src/mewcode/mcp/`、`src/mewcode/tools/registry.py`、`tests/test_mcp_manager.py`
- 依赖任务：任务 5、任务 7、任务 8
- 参考资料定位：`docs/ch07/spec.md` 的「MCP Manager 层」

## 任务 10：接入权限系统
- 目标：让 MCP 工具默认需要确认，配置声明的只读 MCP 工具进入读工具集合，Plan Mode 下只允许只读 MCP 工具。
- 影响文件：`src/mewcode/permissions.py`、`src/mewcode/agent.py`、`tests/test_permissions.py`、`tests/test_agent.py`
- 依赖任务：任务 7、任务 8、任务 9
- 参考资料定位：`docs/ch07/spec.md` 的「权限系统接入层」

## 任务 11：接入主流程
- 目标：CLI 启动时加载 MCP 配置，连接 MCP Server，注册外部工具，创建 Agent，并在退出时关闭 MCP 连接。
- 影响文件：`src/mewcode/cli.py`、`src/mewcode/tools/registry.py`、`tests/test_cli.py`
- 依赖任务：任务 1 至任务 10
- 参考资料定位：`docs/ch07/spec.md` 的「完成定义」

## 任务 12：端到端验证
- 目标：验证 stdio MCP、HTTP MCP、工具注册、Agent 调用、权限确认、Plan Mode 只读和 Server 失败隔离。
- 影响文件：`tests/`、`docs/ch07/checklist.md`
- 依赖任务：任务 11
- 参考资料定位：`docs/ch07/checklist.md` 的「端到端验收」
