# MewCode 第十一章验收清单：Skill 技能包系统

## Skill 文件验收
- [ ] 可以解析以 `---` 包裹的 YAML frontmatter。
- [ ] frontmatter 中缺少 `name` 会跳过该 Skill 并记录警告。
- [ ] frontmatter 中缺少 `description` 会跳过该 Skill 并记录警告。
- [ ] `mode` 只接受 `inline` 或 `fork`。
- [ ] `history` 只接受 `none`、`recent` 或 `full`。
- [ ] `allowedTools` 必须是字符串列表。
- [ ] Markdown body 会作为完整 SOP 保存。
- [ ] Skill body 中的 `$ARGUMENTS` 可以被显式调用参数替换。

## 加载路径验收
- [ ] 内置 Skill 路径为 `src/mewcode/skills/builtin/`。
- [ ] 用户级 Skill 路径为 `~/.mewcode/skills/`。
- [ ] 项目级 Skill 路径为 `.mewcode/skills/`。
- [ ] 搜索优先级为项目级 > 用户级 > 内置级。
- [ ] 同名 Skill 项目级版本会覆盖用户级和内置级版本。
- [ ] 同名 Skill 用户级版本会覆盖内置级版本。
- [ ] 单文件 Skill 支持 `<name>.md`。
- [ ] 目录型 Skill 支持 `<name>/SKILL.md`。
- [ ] 目录型 Skill 可以读取 `references/` 下的 Markdown 或文本资料。
- [ ] 目录型 Skill 可以解析 `tool.json` 元数据。
- [ ] 单个坏 Skill 不影响其他 Skill 加载。

## 工具依赖验收
- [ ] `allowedTools` 中的内置工具必须存在于 ToolRegistry。
- [ ] `allowedTools` 中的 `server__tool` 在对应 MCP server 已配置时通过校验。
- [ ] `allowedTools` 中的 `server__*` 在对应 MCP server 已配置时通过校验。
- [ ] 未配置 MCP server 的 `server__tool` 会产生可观测加载错误。
- [ ] 未知非 MCP 工具会产生可观测加载错误。
- [ ] 系统工具 `ListSkills`、`LoadSkill`、`ActivateSkill` 永远不受普通 Skill 白名单限制。
- [ ] 系统工具 `ListMCPServers`、`ActivateMCPServer` 永远不受普通 Skill 白名单限制。

## Skill 工具验收
- [ ] `ListSkills` 返回可用 Skill 名称、描述、模式和是否已激活。
- [ ] `LoadSkill` 按名称返回完整 SOP、元信息、references 摘要和 allowedTools。
- [ ] `LoadSkill` 找不到名称时返回失败结果。
- [ ] `ActivateSkill` 会把 Skill 加入 activeSkills。
- [ ] 重复激活同一个 Skill 不会重复注入。
- [ ] 多个 activeSkills 按激活顺序注入。

## Prompt 注入验收
- [ ] 启动后 prompt overlay 只包含 Skill 摘要，不包含完整 SOP。
- [ ] 调用 `LoadSkill` 后工具结果包含完整 SOP。
- [ ] 调用 `ActivateSkill` 后下一轮 prompt overlay 包含完整 SOP。
- [ ] 显式 `/commit xxx` 只在当前轮注入 commit 完整 SOP。
- [ ] Skill 摘要和完整 SOP 都进入 messages overlay。
- [ ] Skill 摘要和完整 SOP 不进入 system prompt。

## 工具白名单验收
- [ ] 没有 active Skill 时 Provider 可以看到完整工具列表。
- [ ] 有 active Skill 时 Provider 只看到 `allowedTools` 和系统工具。
- [ ] 一次性 slash Skill 调用时 Provider 只看到该 Skill 的 `allowedTools` 和系统工具。
- [ ] 执行侧会拒绝白名单外工具调用。
- [ ] 白名单外工具拒绝结果会作为结构化 tool result 回填给模型。
- [ ] MCP wildcard `server__*` 可以匹配已激活的 `server__tool`。

## Slash Command 验收
- [ ] `/skill list` 可以列出当前可见 Skill。
- [ ] `/skill info commit` 可以显示 commit Skill 的描述、模式、历史策略和 allowedTools。
- [ ] `/skill reload` 会重新扫描 Skill 并刷新 slash command。
- [ ] `/help` 会显示可见 Skill 生成的 slash command。
- [ ] Tab 补全可以补全 `/commit`。
- [ ] 未知 Skill slash command 仍然返回第十章未知命令提示。
- [ ] `/clear` 会清空 activeSkills。

## 执行模式验收
- [ ] inline Skill 在当前 ChatSession 中执行。
- [ ] inline Skill 的最终回答留在主历史里。
- [ ] fork Skill 创建临时 ChatSession。
- [ ] fork Skill 的主历史只保留用户请求和回流摘要。
- [ ] `history: none` 不向 fork 会话注入旧历史。
- [ ] `history: recent` 只向 fork 会话注入近期历史。
- [ ] `history: full` 向 fork 会话注入完整历史。
- [ ] fork Skill 使用同一 Provider、ToolRegistry、PermissionChecker 和 ToolContext。

## 内置 Skill 验收
- [ ] 内置 `commit` Skill 可见。
- [ ] 内置 `review` Skill 可见。
- [ ] 内置 `test` Skill 可见。
- [ ] `/commit message` 会触发 commit Skill。
- [ ] `/review focus` 会触发 review Skill，而不是旧的硬编码 review prompt。
- [ ] `/test pytest` 会触发 test Skill。

## 端到端验收
- [ ] 创建项目级 `commit.md` 后，`/skill info commit` 显示项目级版本。
- [ ] 用户输入“帮我提交一下”时，Agent 可以先调用 `LoadSkill` 或 `ActivateSkill` 再按 commit SOP 工作。
- [ ] 激活 review Skill 后，后续普通对话的工具列表被 review Skill 白名单收窄。
- [ ] 执行 `/clear` 后，activeSkills 为空，工具列表恢复正常。
- [ ] `.\.venv\Scripts\python.exe -m pytest -q` 可以通过。
