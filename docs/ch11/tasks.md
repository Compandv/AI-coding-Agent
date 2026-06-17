# MewCode 第十一章任务拆解：Skill 技能包系统

## 任务 1：梳理现有命令、Agent、工具和 Prompt 注入入口
- 目标：确认 Slash Command 注册、Agent Loop 工具列表生成、工具执行、MCP lazy 工具和 overlay messages 的接入点。
- 影响文件：`src/mewcode/commands/`、`src/mewcode/agent.py`、`src/mewcode/repl.py`、`src/mewcode/prompts.py`、`src/mewcode/tools/`
- 依赖任务：无
- 参考资料定位：`docs/ch11/spec.md` 的「设计骨架」

## 任务 2：实现 Skill 数据结构与 frontmatter 解析
- 目标：解析 YAML frontmatter 和 Markdown body，校验 Skill 名称、描述、工具白名单、执行模式和历史策略。
- 影响文件：`src/mewcode/skills/`、`tests/test_skills.py`
- 依赖任务：任务 1
- 参考资料定位：`docs/ch11/spec.md` 的「Skill 定义层」「Skill 解析层」

## 任务 3：实现单文件和目录型 Skill 加载
- 目标：支持 `<name>.md` 和 `<name>/SKILL.md`，读取目录型 Skill 的 references 和 tool metadata。
- 影响文件：`src/mewcode/skills/`、`tests/test_skills.py`
- 依赖任务：任务 2
- 参考资料定位：`docs/ch11/spec.md` 的「Skill 解析层」

## 任务 4：实现三层 Skill 搜索与覆盖策略
- 目标：扫描项目 `.mewcode/skills/`、用户 `~/.mewcode/skills/`、内置 `src/mewcode/skills/builtin/`，同名 Skill 按优先级覆盖。
- 影响文件：`src/mewcode/skills/`、`tests/test_skills.py`
- 依赖任务：任务 3
- 参考资料定位：`docs/ch11/spec.md` 的「Skill 加载层」

## 任务 5：实现 Skill 依赖校验与热加载
- 目标：校验 allowedTools 中的内置工具和 MCP server 依赖，支持单个坏 Skill 跳过和 `/skill reload` 重新扫描。
- 影响文件：`src/mewcode/skills/`、`tests/test_skills.py`
- 依赖任务：任务 4
- 参考资料定位：`docs/ch11/spec.md` 的「工具约束层」

## 任务 6：实现 Skill 系统工具
- 目标：新增 `ListSkills`、`LoadSkill`、`ActivateSkill`，让 Agent 能发现、加载和激活完整 Skill 指令。
- 影响文件：`src/mewcode/skills/`、`src/mewcode/tools/registry.py`、`tests/test_skills.py`
- 依赖任务：任务 5
- 参考资料定位：`docs/ch11/spec.md` 的「Skill 工具层」

## 任务 7：实现 Prompt Overlay 与 activeSkills 生命周期
- 目标：启动时注入 Skill 摘要，激活后注入完整 SOP，`/clear` 清空已激活 Skill。
- 影响文件：`src/mewcode/agent.py`、`src/mewcode/repl.py`、`src/mewcode/skills/`、`tests/test_agent.py`、`tests/test_repl.py`
- 依赖任务：任务 6
- 参考资料定位：`docs/ch11/spec.md` 的「Prompt Overlay 层」

## 任务 8：接入工具白名单过滤
- 目标：按 active Skill 或一次性 Skill 缩窄 Provider 可见工具，并在执行侧阻止白名单外工具调用。
- 影响文件：`src/mewcode/agent.py`、`src/mewcode/skills/`、`tests/test_agent.py`
- 依赖任务：任务 7
- 参考资料定位：`docs/ch11/spec.md` 的「工具约束层」

## 任务 9：实现 inline 与 fork Skill 执行
- 目标：显式 slash Skill 调用可在当前会话执行或临时会话执行，fork 模式只把摘要回填主会话。
- 影响文件：`src/mewcode/agent.py`、`src/mewcode/session.py`、`tests/test_agent.py`
- 依赖任务：任务 8
- 参考资料定位：`docs/ch11/spec.md` 的「执行模式层」

## 任务 10：接入 Slash Command 框架
- 目标：自动注册可见 Skill 命令，新增 `/skill list`、`/skill info <name>`、`/skill reload`，并让 `/help` 和 Tab 补全展示 Skill。
- 影响文件：`src/mewcode/commands/`、`src/mewcode/repl.py`、`tests/test_commands.py`、`tests/test_repl.py`
- 依赖任务：任务 6、任务 9
- 参考资料定位：`docs/ch11/spec.md` 的「Slash Command 接入层」

## 任务 11：接入主流程
- 目标：CLI 启动时创建 SkillManager，加载内置和外部 Skill，注册 Skill 工具，传入 Agent 与 REPL。
- 影响文件：`src/mewcode/cli.py`、`src/mewcode/agent.py`、`src/mewcode/repl.py`、`tests/test_cli.py`
- 依赖任务：任务 1 至任务 10
- 参考资料定位：`docs/ch11/spec.md` 的「完成定义」

## 任务 12：端到端验证
- 目标：验证内置 Skill、项目级覆盖、slash 调用、Agent 按需加载、activeSkills、工具白名单、inline/fork 模式和全量测试。
- 影响文件：`tests/`、`docs/ch11/checklist.md`
- 依赖任务：任务 11
- 参考资料定位：`docs/ch11/checklist.md` 的「端到端验收」
