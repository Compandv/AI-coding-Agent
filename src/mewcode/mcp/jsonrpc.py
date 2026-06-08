from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


JSONRPC_VERSION = "2.0"


class JSONRPCError(Exception):
    """Raised when a JSON-RPC message is malformed or contains an error response."""


@dataclass(frozen=True)
class JSONRPCErrorInfo:
    code: int
    message: str
    data: Any = None


def make_request(request_id: int | str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def make_notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def make_success_response(request_id: int | str, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def make_error_response(request_id: int | str | None, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}


def encode_message(message: dict[str, Any]) -> str:
    validate_message(message)
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def decode_message(raw: str | bytes) -> dict[str, Any]:
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JSONRPCError(f"Invalid JSON-RPC JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise JSONRPCError("JSON-RPC message must be an object.")
    validate_message(data)
    return data


def validate_message(message: dict[str, Any]) -> None:
    if message.get("jsonrpc") != JSONRPC_VERSION:
        raise JSONRPCError("JSON-RPC message must contain jsonrpc='2.0'.")
    has_method = "method" in message
    has_result = "result" in message
    has_error = "error" in message
    if has_method:
        method = message.get("method")
        if not isinstance(method, str) or not method:
            raise JSONRPCError("JSON-RPC request or notification must contain a method.")
        return
    if "id" not in message:
        raise JSONRPCError("JSON-RPC response must contain an id.")
    if has_result == has_error:
        raise JSONRPCError("JSON-RPC response must contain exactly one of result or error.")
    if has_error:
        error = message.get("error")
        if not isinstance(error, dict):
            raise JSONRPCError("JSON-RPC error response must contain an error object.")
        if not isinstance(error.get("code"), int) or not isinstance(error.get("message"), str):
            raise JSONRPCError("JSON-RPC error object must contain integer code and string message.")


def response_id(message: dict[str, Any]) -> int | str | None:
    if "method" in message:
        return None
    return message.get("id")


def response_error(message: dict[str, Any]) -> JSONRPCErrorInfo | None:
    error = message.get("error")
    if not isinstance(error, dict):
        return None
    return JSONRPCErrorInfo(
        code=int(error.get("code")),
        message=str(error.get("message")),
        data=error.get("data"),
    )
