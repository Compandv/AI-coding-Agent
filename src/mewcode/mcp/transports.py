from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

import httpx

from .jsonrpc import decode_message, encode_message


class TransportError(Exception):
    """Raised when an MCP transport cannot send or receive messages."""


class MCPTransport(ABC):
    @abstractmethod
    def send(self, message: dict[str, Any]) -> None:
        """Send one JSON-RPC message."""

    @abstractmethod
    def receive(self, timeout_seconds: float | None = None) -> dict[str, Any]:
        """Receive one JSON-RPC message."""

    @abstractmethod
    def close(self) -> None:
        """Close any resources owned by the transport."""


class StdioTransport(MCPTransport):
    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.cwd = cwd
        self.process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[dict[str, Any] | Exception] = queue.Queue()
        self._reader: threading.Thread | None = None

    def start(self) -> None:
        if self.process is not None:
            return
        executable = resolve_stdio_command(self.command, self._child_env())
        command = [executable, *self.args]
        try:
            self.process = subprocess.Popen(
                command,
                cwd=self.cwd,
                env=self._child_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            raise TransportError(f"Failed to start MCP stdio server {self.command}: {exc}") from exc
        self._reader = threading.Thread(target=self._read_stdout, name=f"mcp-stdio-{self.command}", daemon=True)
        self._reader.start()

    def send(self, message: dict[str, Any]) -> None:
        self.start()
        assert self.process is not None
        if self.process.stdin is None:
            raise TransportError("MCP stdio server stdin is not available.")
        try:
            self.process.stdin.write(encode_message(message) + "\n")
            self.process.stdin.flush()
        except OSError as exc:
            raise TransportError(f"Failed to write MCP stdio message: {exc}") from exc

    def receive(self, timeout_seconds: float | None = None) -> dict[str, Any]:
        try:
            item = self._responses.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise TransportError("Timed out waiting for MCP stdio response.") from exc
        if isinstance(item, Exception):
            raise TransportError(str(item)) from item
        return item

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    def _read_stdout(self) -> None:
        assert self.process is not None
        stdout = self.process.stdout
        if stdout is None:
            self._responses.put(TransportError("MCP stdio server stdout is not available."))
            return
        try:
            for line in stdout:
                stripped = line.strip()
                if not stripped:
                    continue
                self._responses.put(decode_message(stripped))
        except Exception as exc:  # pragma: no cover - defensive background thread boundary
            self._responses.put(exc)

    def _child_env(self) -> dict[str, str]:
        path = os.environ.get("PATH") or os.environ.get("Path") or ""
        child_env = {"PATH": path}
        if sys.platform == "win32":
            for name in ("PATHEXT", "SystemRoot", "COMSPEC", "APPDATA", "TEMP", "TMP"):
                value = os.environ.get(name)
                if value:
                    child_env[name] = value
        child_env.update(self.env)
        return child_env


def resolve_stdio_command(command: str, env: Mapping[str, str] | None = None) -> str:
    path = None
    if env is not None:
        path = env.get("PATH") or env.get("Path")
    resolved = shutil.which(command, path=path)
    return resolved or command


class HTTPTransport(MCPTransport):
    def __init__(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = url
        self.headers = dict(headers or {})
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self._owns_client = client is None

    def send(self, message: dict[str, Any]) -> None:
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            **self.headers,
        }
        try:
            response = self.client.post(self.url, headers=headers, content=encode_message(message))
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TransportError(f"MCP HTTP request failed: {exc}") from exc
        content_type = response.headers.get("content-type", "").lower()
        if "text/event-stream" in content_type:
            raise TransportError("MCP HTTP SSE responses are not supported in this chapter.")
        if not response.content:
            return
        if "json" not in content_type and content_type:
            raise TransportError(f"MCP HTTP response was not JSON: {content_type}")
        self._responses.put(decode_message(response.text))

    def receive(self, timeout_seconds: float | None = None) -> dict[str, Any]:
        try:
            return self._responses.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise TransportError("Timed out waiting for MCP HTTP response.") from exc

    def close(self) -> None:
        if self._owns_client:
            self.client.close()
