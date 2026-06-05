from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from mewcode.config import MewCodeConfig
from mewcode.session import Message

from .base import ChatProvider
from .errors import ProviderError


class SSEClientMixin:
    def _iter_sse_json(self, response: httpx.Response) -> Iterator[dict[str, Any]]:
        event_data: list[str] = []
        try:
            for line in response.iter_lines():
                if line == "":
                    if event_data:
                        data = "\n".join(event_data)
                        event_data = []
                        if data == "[DONE]":
                            return
                        try:
                            yield json.loads(data)
                        except json.JSONDecodeError as exc:
                            raise ProviderError(f"Invalid SSE JSON event: {exc}") from exc
                    continue

                if line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    event_data.append(line.removeprefix("data:").strip())

            if event_data:
                data = "\n".join(event_data)
                if data != "[DONE]":
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(f"Invalid SSE JSON event: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Streaming response failed: {exc}") from exc
