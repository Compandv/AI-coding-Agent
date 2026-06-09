from __future__ import annotations

# Single tool result offload threshold, measured in UTF-8 bytes.
SINGLE_RESULT_LIMIT = 50000

# Aggregate tool result offload threshold for one request turn, in UTF-8 bytes.
MESSAGE_AGGREGATE_LIMIT = 200000

# Reserved token budget for the compaction model response.
SUMMARY_RESERVE = 20000

# Automatic compaction safety margin for estimate drift and current-turn growth.
AUTO_SAFETY_MARGIN = 13000

# Manual and emergency compaction safety margin.
MANUAL_SAFETY_MARGIN = 3000

# Number of recently read file snapshots rendered in recovery context.
RECOVERY_FILE_LIMIT = 5

# Per-file snapshot budget in approximate tokens.
RECOVERY_TOKENS_PER_FILE = 5000

# Minimum recent raw context tokens to keep after LLM summary.
RECENT_KEEP_TOKENS = 10000

# Minimum recent raw message count to keep after LLM summary.
RECENT_KEEP_MESSAGES = 5

# Consecutive automatic compaction failures before auto compaction is disabled.
MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES = 3

# Direct retry limit when the summary request itself is too long.
PTL_RETRY_LIMIT = 3

# Percentage of old message groups dropped after direct retries are exhausted.
PTL_DROP_PERCENTAGE = 0.2

# Approximate UTF-8 character bytes per token.
ESTIMATE_CHARS_PER_TOKEN = 3.5

# Preview byte budget for offloaded tool results.
PREVIEW_HEAD_BYTES = 2048
PREVIEW_TAIL_BYTES = 2048

# Preview line budget for offloaded tool results.
PREVIEW_HEAD_LINES = 20
PREVIEW_TAIL_LINES = 20

# Target size for each LLM summary chunk.
SUMMARY_CHUNK_TARGET_TOKENS = 12000
SUMMARY_CHUNK_MAX_TOKENS = 18000

# Maximum user supplied compact focus length.
COMPACT_FOCUS_MAX_CHARS = 1200
