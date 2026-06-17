---
name: review
description: Review the current Git working tree with findings first and concrete file references.
allowedTools: [Bash, ReadFile, Grep, Glob]
mode: fork
history: recent
---
Use a code-review stance.

1. Inspect the current Git diff and relevant files.
2. Prioritize bugs, regressions, safety issues, and missing tests.
3. Report findings first, ordered by severity.
4. Include file and line references when possible.
5. If there are no findings, say that clearly and mention residual risk or test gaps.
6. Keep summary secondary.

Review focus: $ARGUMENTS
