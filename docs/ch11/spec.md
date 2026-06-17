# MewCode 第十一章规格说明：Skill 技能包系统

## 背景
前几章让 MewCode 具备了 Agent Loop、权限系统、MCP 外部工具、上下文管理、跨会话记忆和 Slash Command。现在用户已经可以用 `/review` 这类内置命令触发预设工作流，但这些工作流仍然写在代码里，想新增或调整就要改源码。

第十一章要把可复用 AI 操作抽象成 Skill 技能包。Skill 以 Markdown 文件保存，启动时只暴露名称和描述，真正需要时再加载完整 SOP 和工具约束，让 MewCode 既能保持上下文轻量，又能按需执行复杂工作流。

## 目标用户
- 想把常用 AI 操作沉淀成可编辑 Markdown 的 MewCode 用户。
- 想在项目内共享提交、审查、测试等标准工作流的团队。
- 想通过配置扩展 Agent 行为，而不是修改 MewCode 源码的开发者。
- 想学习两阶段 Prompt 加载、工具白名单和 Skill 执行模式的实现者。

## 能力清单
- MewCode 可以解析带 YAML frontmatter 的 Skill Markdown 文件。
- MewCode 可以加载单文件 Skill 和目录型 Skill。
- MewCode 可以按项目级、用户级、内置级三层路径扫描 Skill。
- 同名 Skill 会按高优先级覆盖低优先级版本。
- 启动时只把 Skill 名称和一句描述注入上下文。
- Agent 可以通过内置工具列出、加载和激活 Skill。
- 激活后的 Skill 完整指令会在后续轮次持续注入上下文。
- 每个可见 Skill 可以自动注册为同名 slash command。
- 显式 slash Skill 调用默认只作用于当前一轮，不会自动永久激活。
- Skill 可以声明允许使用的工具集合。
- Skill 工具白名单会同时限制 Provider 可见工具和执行侧工具调用。
- 系统级 Skill 工具不受普通白名单限制，保证 Skill 可以嵌套加载。
- Skill 可以以 inline 模式在当前会话中执行。
- Skill 可以以 fork 模式在临时会话中执行，再把摘要回填主会话。
- 目录型 Skill 可以携带 references 和 tool metadata。
- MewCode 内置 commit、review、test 三个样板 Skill。
- 用户可以通过 `/skill` 管理 Skill 列表、详情和热加载。

## 非功能要求
- Skill 解析和加载必须可测试，不依赖真实 LLM。
- 单个坏 Skill 不能阻断其他 Skill 加载。
- 未知工具依赖要给出可观测错误，避免运行时才暴露危险行为。
- Skill 摘要和完整指令都应走 messages overlay，不污染 system prompt cache。
- Tool whitelist 必须在模型可见工具和工具执行两侧同时生效。
- Fork 模式只能隔离会话历史，不能绕过权限系统、MCP 管理或工具沙箱。
- 热加载后 slash command、Skill 摘要和可用 Skill 列表必须保持一致。
- Skill 文件读取不能执行任意本地脚本。

## 设计骨架
1. Skill 定义层
   - 定义 Skill 元信息、执行模式、历史注入策略、工具约束和来源信息。
   - 支持 Markdown body 作为完整 SOP。

2. Skill 解析层
   - 分离 YAML frontmatter 和 Markdown body。
   - 校验必填字段、枚举字段和工具白名单。
   - 支持单文件和目录型 Skill。

3. Skill 加载层
   - 扫描项目级、用户级和内置级目录。
   - 处理同名覆盖、坏文件跳过和热加载。
   - 维护可见 Skill 列表和加载警告。

4. Skill 工具层
   - 提供列出 Skill、加载完整 Skill、激活 Skill 的系统工具。
   - 把完整 SOP、references 摘要和工具约束以结构化结果返回给 Agent。

5. Prompt Overlay 层
   - 启动时注入 Skill 摘要列表。
   - Skill 激活后注入完整指令。
   - 一次性 slash Skill 调用只在当前轮注入完整指令。

6. 工具约束层
   - 根据 active Skill 或一次性 Skill 缩窄 Provider 工具列表。
   - 在工具执行前再次检查白名单。
   - 为系统工具和 lazy MCP 激活保留豁免通道。

7. Slash Command 接入层
   - 自动把可见 Skill 注册成 slash command。
   - 提供 `/skill list`、`/skill info` 和 `/skill reload`。
   - 保持第十章命令框架的本地分发边界。

8. 执行模式层
   - Inline 模式复用当前会话。
   - Fork 模式创建临时会话，按 Skill 声明注入历史，并把摘要写回主会话。

## Out of Scope
- 不做 Skill 市场和分发。
- 不做 Skill 版本管理。
- 不执行目录型 Skill 中的任意本地脚本工具。
- 不做脚本工具沙箱。
- 不做命令级权限控制。
- 不做动态 prompt 生成 UI。
- 不做 Skill 远程下载和签名校验。

## 完成定义
当 MewCode 可以扫描三层 Skill 目录，加载内置 commit、review、test，启动时只注入 Skill 摘要，Agent 能通过 Skill 工具按需加载并激活完整 SOP，slash command 能触发同名 Skill，工具白名单能同时限制模型可见工具和执行侧调用，`/skill` 管理命令可用，并且 inline、fork 两种执行模式都有测试覆盖时，本章达到核心完成标准。
