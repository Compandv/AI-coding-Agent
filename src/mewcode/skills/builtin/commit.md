---
name: commit
description: Inspect the current changes, verify intent, and create a concise git commit.
allowedTools: [Bash, ReadFile, Grep, Glob]
mode: inline
history: recent
---
Follow this commit SOP.

1. Inspect the current Git working tree before deciding anything.
2. Read only the files needed to understand the change.
3. Summarize the change and any risk briefly.
4. If it is appropriate to commit, create one focused commit with a concise message.
5. If the working tree contains unrelated changes, do not include them silently.

User arguments: $ARGUMENTS
