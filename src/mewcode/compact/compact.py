from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TriggerKind(Enum):
    AUTO = "auto"
    MANUAL = "manual"
    EMERGENCY = "emergency"


@dataclass(frozen=True)
class ManageOutput:
    before_tokens: int
    after_tokens: int
    compacted: bool = False
