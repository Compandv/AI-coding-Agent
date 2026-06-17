---
name: test
description: Select and run focused verification for the current change.
allowedTools: [Bash, ReadFile, Grep, Glob]
mode: inline
history: recent
---
Follow this testing SOP.

1. Identify the smallest meaningful verification for the current task.
2. Prefer targeted tests before broad test suites.
3. Run the verification command and inspect failures.
4. If tests fail, summarize the failure and likely next fix.
5. If tests pass, report exactly what was run.

User arguments: $ARGUMENTS
