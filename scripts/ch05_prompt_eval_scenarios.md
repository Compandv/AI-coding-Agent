# Chapter 5 Prompt Evaluation Scenarios

Use these scenarios for manual comparison after changing prompt modules, tool descriptions, reminder injection, or cache policy. They are qualitative checks, not an automated score.

## Scenario 1: Find Project Entry
- Input: `帮我找项目入口并说明原因`
- Expected tool behavior: Use `Glob` or `Grep` to locate likely entry files, then `ReadFile` for the most relevant candidates.
- Observe: The final answer should cite concrete files and explain why they are entry points.

## Scenario 2: Read Before Edit
- Input: `把 src/mewcode/cli.py 里启动 Agent 的地方改得更清晰一点`
- Expected tool behavior: Use `ReadFile` before `EditFile`; avoid full-file overwrite unless there is a clear reason.
- Observe: The change should be focused, and the response should mention verification or why it was not run.

## Scenario 3: Plan Mode Clarifies Without Saving
- Input: `/plan 我想做一个电商系统`
- Expected tool behavior: Use `AskUserQuestion` for broad requirements; read-only tools are allowed when project context matters; do not call `WritePlanFile` unless the user explicitly asks to save a plan file.
- Observe: The UI should ask useful questions and the final plan should appear in chat by default.

## Scenario 4: Prefer Dedicated Tools Over Bash Search
- Input: `这个项目里哪里处理工具调用显示状态？`
- Expected tool behavior: Prefer `Grep`, `Glob`, and `ReadFile` over `Bash` for normal code search.
- Observe: The answer should identify relevant files and avoid shell search commands unless necessary.

## Scenario 5: Cache Usage Observation
- Input: Send two similar normal-mode code-reading requests in the same project after the stable prompt and tool definitions are unchanged.
- Expected tool behavior: Tool choices may vary by task, but the stable `system` and `tools` content should remain unchanged between requests.
- Observe: Provider debug usage should show cached token fields when supported and when the provider/model/token threshold permits it; otherwise it should clearly show zero or unsupported cache usage.
